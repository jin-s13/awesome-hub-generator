"""Tests for researcher_adapter.py"""

import json
from datetime import datetime
from unittest.mock import MagicMock

from scripts.researcher_adapter import ResearcherAdapter, _slugify, _infer_venue


class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"
    def test_special_chars(self):
        assert _slugify("Pi0: A VLA Flow Model!") == "pi0-a-vla-flow-model"
    def test_truncation(self):
        assert len(_slugify("a" * 100)) <= 80


class TestInferVenue:
    def test_empty(self):
        assert _infer_venue([]) == "arXiv"


class TestResearcherAdapterConfig:
    def test_sync_config_writes_files(self, sample_awesome_config, monkeypatch, tmp_path):
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
        assert config_dir.joinpath("config.json").exists()
        assert researcher_dir.joinpath(".env").exists()


class TestResearcherAdapterConvert:
    def _make_mock_paper(self, data: dict):
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
        scored_list = sample_run_result["scored_papers_by_source"]["arxiv"]
        mock_result = MagicMock()
        mock_result.scored_papers_by_source = {
            "arxiv": [
                {"paper_metadata": self._make_mock_paper(scored_list[0]), "score_response": self._make_mock_score(scored_list[0])},
                {"paper_metadata": self._make_mock_paper(scored_list[1]), "score_response": self._make_mock_score(scored_list[1])},
            ]
        }
        mock_result.analyses_by_source = sample_run_result["analyses_by_source"]
        papers = ResearcherAdapter({}).convert_to_papers_yaml(mock_result)
        assert len(papers) == 2
        assert papers[0]["score"]["total"] == 85.5
    def test_convert_empty_result(self):
        mock_result = MagicMock()
        mock_result.scored_papers_by_source = {}
        assert ResearcherAdapter({}).convert_to_papers_yaml(mock_result) == []


class TestResearcherAdapterDeduplicate:
    def test_deduplicate_by_title(self):
        existing = [{"id": "p1", "title": "Existing Paper", "links": {"paper": "http://url1.com"}}]
        new = [{"id": "p2", "title": "existing paper", "links": {"paper": "http://url2.com"}}]
        merged, added = ResearcherAdapter.deduplicate(existing, new)
        assert added == 0
    def test_sort_by_year_then_score(self):
        new = [
            {"id": "p1", "title": "A", "year": "2023", "score": {"total": 50.0}, "links": {"paper": "http://a.com"}},
            {"id": "p2", "title": "B", "year": "2025", "score": {"total": 80.0}, "links": {"paper": "http://b.com"}},
            {"id": "p3", "title": "C", "year": "2025", "score": {"total": 90.0}, "links": {"paper": "http://c.com"}},
        ]
        merged, added = ResearcherAdapter.deduplicate([], new)
        assert merged[0]["id"] == "p3"
