"""Tests for researcher_adapter.py"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.researcher_adapter import ResearcherAdapter, _slugify, _infer_venue


class TestSlugify:
    """Test the _slugify helper."""

    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Pi0: A VLA Flow Model!") == "pi0-a-vla-flow-model"

    def test_truncation(self):
        long = "a" * 100
        assert len(_slugify(long)) <= 80

    def test_unicode(self):
        slug = _slugify("扩散模型研究")
        assert isinstance(slug, str)
        assert slug  # non-empty


class TestInferVenue:
    """Test the _infer_venue helper."""

    def test_empty(self):
        assert _infer_venue([]) == "arXiv"

    def test_with_categories(self):
        assert _infer_venue(["cs.CV", "cs.LG"]) == "arXiv"


class TestResearcherAdapterConfig:
    """Test configuration sync."""

    def test_sync_config_writes_files(self, sample_awesome_config, monkeypatch, tmp_path):
        """Verify sync_config writes both config.json and .env."""
        # Redirect paths to temp
        researcher_dir = tmp_path / "arxiv-daily-researcher"
        researcher_dir.mkdir()
        config_dir = researcher_dir / "configs"
        config_dir.mkdir()

        import scripts.researcher_adapter as ra
        monkeypatch.setattr(ra, "RESEARCHER_DIR", researcher_dir)
        monkeypatch.setattr(ra, "RESEARCHER_CONFIG_PATH", config_dir / "config.json")
        monkeypatch.setattr(ra, "RESEARCHER_ENV_PATH", researcher_dir / ".env")

        adapter = ResearcherAdapter(sample_awesome_config)
        adapter.sync_config()

        # Check config.json
        config_path = config_dir / "config.json"
        assert config_path.exists()
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["search_settings"]["search_days"] == 3
        assert "CAD" in data["keywords"]["primary_keywords"]["keywords"]

        # Check .env
        env_path = researcher_dir / ".env"
        assert env_path.exists()
        content = env_path.read_text(encoding="utf-8")
        assert "NOTIFICATIONS_ENABLED=false" in content


class TestResearcherAdapterConvert:
    """Test converting RunResult to papers.yaml format."""

    def _make_mock_paper(self, data: dict):
        """Create a mock paper_metadata object with proper attributes."""
        pm = data["paper_metadata"]
        meta = MagicMock()
        meta.paper_id = pm["paper_id"]
        meta.title = pm["title"]
        meta.authors = pm["authors"]
        meta.abstract = pm["abstract"]
        meta.published_date = datetime.strptime(pm["published_date"], "%Y-%m-%d")
        meta.url = pm["url"]
        meta.pdf_url = pm["pdf_url"]
        meta.categories = pm["categories"]
        meta.source = pm["source"]
        return meta

    def _make_mock_score(self, data: dict):
        """Create a mock score_response object with proper attributes."""
        sr = data["score_response"]
        score = MagicMock()
        score.total_score = sr["total_score"]
        score.keyword_scores = sr["keyword_scores"]
        score.author_bonus = sr["author_bonus"]
        score.passing_score = sr["passing_score"]
        score.is_qualified = sr["is_qualified"]
        score.tldr = sr["tldr"]
        score.reasoning = sr["reasoning"]
        score.extracted_keywords = sr["extracted_keywords"]
        return score

    def test_convert_basic(self, sample_run_result):
        """Verify basic conversion of scored papers."""
        # Build proper mock objects instead of raw dicts
        scored_list = sample_run_result["scored_papers_by_source"]["arxiv"]
        mock_result = MagicMock()
        mock_result.scored_papers_by_source = {
            "arxiv": [
                {
                    "paper_metadata": self._make_mock_paper(scored_list[0]),
                    "score_response": self._make_mock_score(scored_list[0]),
                },
                {
                    "paper_metadata": self._make_mock_paper(scored_list[1]),
                    "score_response": self._make_mock_score(scored_list[1]),
                },
            ]
        }
        mock_result.analyses_by_source = sample_run_result["analyses_by_source"]

        adapter = ResearcherAdapter({})
        papers = adapter.convert_to_papers_yaml(mock_result)

        assert len(papers) == 2

        # First paper
        p1 = papers[0]
        assert "pi0" in p1["id"]
        assert p1["title"] == "Pi0: A Vision-Language-Action Flow Model"
        assert p1["year"] == "2025"
        assert p1["links"]["paper"] == "https://arxiv.org/abs/2504.12345"
        assert p1["links"]["pdf"] == "https://arxiv.org/pdf/2504.12345.pdf"

        # Score fields
        assert p1["score"]["total"] == 85.5
        assert p1["score"]["keyword_scores"]["world model"] == 9.0
        assert p1["score"]["passing_score"] == 20.0
        assert p1["score"]["is_qualified"] is True
        assert p1["tldr"] == "提出了一种基于流匹配的 VLA 基础模型。"
        assert p1["reasoning"] == "论文核心方法涉及流匹配，面向具身 AI。"
        assert p1["tags"] == ["VLA", "Flow Matching", "Robot Foundation Model"]

        # Deep analysis
        assert "analysis" in p1
        assert p1["analysis"]["innovations"] == ["首次将流匹配应用于 VLA 基础模型"]
        assert p1["analysis"]["limitations"] == ["仅在仿真环境中验证"]

        # Second paper (no analysis)
        p2 = papers[1]
        assert "diffusion" in p2["id"]
        assert p2["score"]["total"] == 72.0
        assert "analysis" not in p2

    def test_convert_empty_result(self):
        """Handle empty RunResult gracefully."""
        mock_result = MagicMock()
        mock_result.scored_papers_by_source = {}

        adapter = ResearcherAdapter({})
        papers = adapter.convert_to_papers_yaml(mock_result)
        assert papers == []

    def test_convert_no_analyses(self, sample_run_result):
        """Handle RunResult without analyses."""
        mock_result = MagicMock()
        mock_result.scored_papers_by_source = sample_run_result["scored_papers_by_source"]
        mock_result.analyses_by_source = {}

        adapter = ResearcherAdapter({})
        papers = adapter.convert_to_papers_yaml(mock_result)

        assert len(papers) == 2
        # No analysis attached
        assert "analysis" not in papers[0]

    def test_convert_missing_fields(self):
        """Handle papers with missing metadata gracefully."""
        meta = MagicMock()
        meta.paper_id = "test.123"
        meta.title = "Test Paper"
        meta.authors = ["Author"]
        meta.abstract = "Abstract"
        meta.published_date = datetime(2025, 6, 1)
        meta.url = "https://arxiv.org/abs/test.123"
        meta.pdf_url = ""
        meta.categories = ["cs.LG"]
        meta.source = "arxiv"

        score = MagicMock()
        score.total_score = 50.0
        score.keyword_scores = {"test": 5.0}
        score.author_bonus = 0.0
        score.passing_score = 10.0
        score.is_qualified = True
        score.tldr = "Test TLDR"
        score.reasoning = "Test reasoning"
        score.extracted_keywords = ["test"]

        mock_result = MagicMock()
        mock_result.scored_papers_by_source = {
            "arxiv": [
                {
                    "paper_metadata": meta,
                    "score_response": score,
                }
            ]
        }
        mock_result.analyses_by_source = {}

        adapter = ResearcherAdapter({})
        papers = adapter.convert_to_papers_yaml(mock_result)

        assert len(papers) == 1
        assert papers[0]["title"] == "Test Paper"
        assert papers[0]["score"]["total"] == 50.0


class TestResearcherAdapterDeduplicate:
    """Test deduplication logic."""

    def test_deduplicate_by_title(self):
        """Deduplicate papers with same title (case-insensitive)."""
        existing = [
            {"id": "paper-1", "title": "Existing Paper", "links": {"paper": "http://url1.com"}},
        ]
        new = [
            {"id": "paper-2", "title": "existing paper", "links": {"paper": "http://url2.com"}},
            {"id": "paper-3", "title": "New Paper", "links": {"paper": "http://url3.com"}},
        ]

        merged, added = ResearcherAdapter.deduplicate(existing, new)
        assert added == 1
        assert len(merged) == 2

    def test_deduplicate_by_id(self):
        """Deduplicate papers with same id."""
        existing = [
            {"id": "same-id", "title": "Paper A", "links": {"paper": "http://url1.com"}},
        ]
        new = [
            {"id": "same-id", "title": "Paper B", "links": {"paper": "http://url2.com"}},
        ]

        merged, added = ResearcherAdapter.deduplicate(existing, new)
        assert added == 0
        assert len(merged) == 1

    def test_deduplicate_by_url(self):
        """Deduplicate papers with same paper URL."""
        existing = [
            {"id": "paper-1", "title": "Paper A", "links": {"paper": "http://same-url.com"}},
        ]
        new = [
            {"id": "paper-2", "title": "Paper B", "links": {"paper": "http://same-url.com"}},
        ]

        merged, added = ResearcherAdapter.deduplicate(existing, new)
        assert added == 0
        assert len(merged) == 1

    def test_deduplicate_all_new(self):
        """All new papers should be added."""
        existing = [
            {"id": "p1", "title": "Paper 1", "links": {"paper": "http://url1.com"}},
        ]
        new = [
            {"id": "p2", "title": "Paper 2", "links": {"paper": "http://url2.com"}},
            {"id": "p3", "title": "Paper 3", "links": {"paper": "http://url3.com"}},
        ]

        merged, added = ResearcherAdapter.deduplicate(existing, new)
        assert added == 2
        assert len(merged) == 3

    def test_sort_by_year_then_score(self):
        """Verify sorting: newest year first, then by score descending."""
        existing = []
        new = [
            {"id": "p1", "title": "Paper A", "year": "2023", "score": {"total": 50.0}, "links": {"paper": "http://a.com"}},
            {"id": "p2", "title": "Paper B", "year": "2025", "score": {"total": 80.0}, "links": {"paper": "http://b.com"}},
            {"id": "p3", "title": "Paper C", "year": "2025", "score": {"total": 90.0}, "links": {"paper": "http://c.com"}},
            {"id": "p4", "title": "Paper D", "year": "2024", "score": {"total": 70.0}, "links": {"paper": "http://d.com"}},
        ]

        merged, added = ResearcherAdapter.deduplicate(existing, new)
        assert added == 4

        # Order: 2025 score 90, 2025 score 80, 2024, 2023
        assert merged[0]["id"] == "p3"
        assert merged[1]["id"] == "p2"
        assert merged[2]["id"] == "p4"
        assert merged[3]["id"] == "p1"
