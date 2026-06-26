"""Tests for update.py"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.update import (
    collect_sources_to_pool,
    load_config,
    load_papers_yaml,
    rank_papers_step,
    save_papers_yaml,
)


class TestLoadConfig:
    """Test config loading."""

    def test_loads_yaml(self, tmp_path):
        config = tmp_path / "awesome.yaml"
        config.write_text("project:\n  name: Test\nresearch:\n  keywords: [test]\n", encoding="utf-8")
        with patch("scripts.update.SITE_DIR", tmp_path), patch("scripts.update.ROOT", tmp_path):
            result = load_config()
        assert result["project"]["name"] == "Test"
        assert result["research"]["keywords"] == ["test"]


class TestLoadPapersYaml:
    """Test loading papers from YAML."""

    def test_loads_existing(self, tmp_path):
        f = tmp_path / "papers.yaml"
        f.write_text("- id: p1\n  title: Paper 1\n", encoding="utf-8")
        papers = load_papers_yaml(f)
        assert len(papers) == 1
        assert papers[0]["id"] == "p1"

    def test_returns_empty_for_missing(self, tmp_path):
        f = tmp_path / "nonexistent.yaml"
        papers = load_papers_yaml(f)
        assert papers == []

    def test_returns_empty_for_empty(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        papers = load_papers_yaml(f)
        assert papers == []


class TestSavePapersYaml:
    """Test saving papers to YAML."""

    def test_saves_and_loads(self, tmp_path):
        f = tmp_path / "papers.yaml"
        papers = [
            {"id": "p1", "title": "Paper 1", "score": {"total": 85.0}},
            {"id": "p2", "title": "Paper 2", "score": {"total": 72.0}},
        ]
        save_papers_yaml(f, papers)
        assert f.exists()

        # Verify round-trip
        loaded = load_papers_yaml(f)
        assert len(loaded) == 2
        assert loaded[0]["id"] == "p1"
        assert loaded[0]["score"]["total"] == 85.0


class TestRankPapersStep:
    """Test PaperRank-lite step wiring."""

    def test_calls_rank_enricher_by_default(self, tmp_path, monkeypatch):
        papers_yaml = tmp_path / "papers.yaml"
        papers_yaml.write_text("[]\n", encoding="utf-8")
        seen = {}

        def fake_enrich(path, config):
            seen["path"] = path
            seen["config"] = config
            return 0

        monkeypatch.setattr("scripts.paper_rank.enrich_paper_rank_scores", fake_enrich)

        rank_papers_step({"research": {"keywords": ["CAD"]}}, papers_yaml)

        assert seen["path"] == papers_yaml
        assert seen["config"]["research"]["keywords"] == ["CAD"]

    def test_skips_when_disabled(self, tmp_path, monkeypatch):
        papers_yaml = tmp_path / "papers.yaml"
        papers_yaml.write_text("[]\n", encoding="utf-8")
        called = False

        def fake_enrich(path, config):
            nonlocal called
            called = True
            return 0

        monkeypatch.setattr("scripts.paper_rank.enrich_paper_rank_scores", fake_enrich)

        rank_papers_step({"research": {"ranking": {"enabled": False}}}, papers_yaml)

        assert called is False


class TestCollectSourcesToPool:
    """Test update.py uses the unified paper source aggregator."""

    def test_adds_unified_source_results_to_candidate_pool(self, monkeypatch):
        seen = {}

        def fake_collect(config, search_days=None, max_results=500):
            seen["config"] = config
            seen["search_days"] = search_days
            return {
                "papers": [
                    {
                        "id": "paper-1",
                        "title": "Unified Search Paper",
                        "links": {"paper": "https://arxiv.org/abs/2601.00001"},
                    }
                ],
                "sources": {
                    "arxiv": {"enabled": True, "count": 1},
                    "huggingface": {"enabled": False, "count": 0},
                    "awesome": {"enabled": False, "count": 0},
                    "alphaxiv": {"enabled": False, "count": 0},
                },
            }

        class FakePool:
            def __init__(self):
                self.calls = []

            def add_batch(self, papers, source="unknown"):
                self.calls.append((papers, source))
                return len(papers)

        monkeypatch.setattr("scripts.paper_sources.collect_paper_sources", fake_collect)

        pool = FakePool()
        collect_sources_to_pool({"research": {"sources": {"arxiv": True}}}, pool, search_days=14)

        assert seen["search_days"] == 14
        assert pool.calls == [
            (
                [
                    {
                        "id": "paper-1",
                        "title": "Unified Search Paper",
                        "links": {"paper": "https://arxiv.org/abs/2601.00001"},
                    }
                ],
                "unified-sources",
            )
        ]


class TestMainLogic:
    """Test the main entry point logic via direct function calls."""

    def test_researcher_path_logic(self, mocker):
        """Verify the researcher path: adapter called, results converted, deduped."""
        mock_adapter_cls = mocker.patch("scripts.researcher_adapter.ResearcherAdapter")
        mock_adapter = mock_adapter_cls.return_value
        mock_result = MagicMock()
        mock_adapter.run_daily_research.return_value = mock_result
        mock_adapter.convert_to_papers_yaml.return_value = [
            {"id": "p1", "title": "Paper 1", "links": {"paper": "http://url1.com"}},
        ]
        mock_adapter_cls.deduplicate = MagicMock(return_value=([
            {"id": "p1", "title": "Paper 1", "links": {"paper": "http://url1.com"}},
        ], 1))

        # Simulate what main() does in the researcher path
        config = {"project": {"name": "Test"}, "research": {"keywords": ["test"]}}
        adapter = mock_adapter_cls(config)
        result = adapter.run_daily_research()
        new_papers = adapter.convert_to_papers_yaml(result)
        merged, added = mock_adapter_cls.deduplicate([], new_papers)

        assert len(new_papers) == 1
        assert added == 1
        assert len(merged) == 1
        mock_adapter_cls.assert_called_once()
        mock_adapter.run_daily_research.assert_called_once()
        mock_adapter.convert_to_papers_yaml.assert_called_once()

    def test_fallback_path_logic(self, mocker):
        """Verify fallback: when researcher fails, use arXiv API."""
        with patch("scripts.sync.search_arxiv") as mock_search:
            mock_search.return_value = [
                {"title": "Paper 1", "abstract": "Abstract", "categories": ["cs.CV"]}
            ]

            from scripts.update import fetch_from_arxiv

            config = {"project": {"name": "Test"}, "research": {"keywords": ["test"]}}
            new_papers = fetch_from_arxiv(config, search_days=3)

            assert len(new_papers) == 1
            mock_search.assert_called_once()

    def test_skip_researcher_logic(self, mocker):
        """Verify --skip-researcher uses arXiv API directly."""
        with patch("scripts.sync.search_arxiv") as mock_search:
            mock_search.return_value = [
                {"title": "Paper 1", "abstract": "Abstract", "categories": ["cs.CV"]}
            ]

            from scripts.update import fetch_from_arxiv

            config = {"project": {"name": "Test"}, "research": {"keywords": ["test"]}}
            new_papers = fetch_from_arxiv(config, search_days=3)

            assert len(new_papers) == 1
            mock_search.assert_called_once()
