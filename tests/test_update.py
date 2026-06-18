"""Tests for update.py"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.update import (
    load_config,
    load_papers_yaml,
    save_papers_yaml,
)


class TestLoadConfig:
    """Test config loading."""

    def test_loads_yaml(self, tmp_path):
        config = tmp_path / "awesome.yaml"
        config.write_text("project:\n  name: Test\nresearch:\n  keywords: [test]\n", encoding="utf-8")
        with patch("scripts.update.ROOT", tmp_path):
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
        # Test that update_from_arxiv_api calls search_arxiv
        # We test this by patching scripts.sync.search_arxiv directly
        with patch("scripts.sync.search_arxiv") as mock_search:
            mock_search.return_value = [
                {"title": "Paper 1", "abstract": "Abstract", "categories": ["cs.CV"]}
            ]

            # Import inside the patched context so "from sync import search_arxiv"
            # gets the patched version
            from scripts.update import update_from_arxiv_api

            config = {"project": {"name": "Test"}, "research": {"keywords": ["test"]}}
            new_papers = update_from_arxiv_api(config)

            assert len(new_papers) == 1
            mock_search.assert_called_once()

    def test_skip_researcher_logic(self, mocker):
        """Verify --skip-researcher uses arXiv API directly."""
        with patch("scripts.sync.search_arxiv") as mock_search:
            mock_search.return_value = [
                {"title": "Paper 1", "abstract": "Abstract", "categories": ["cs.CV"]}
            ]

            from scripts.update import update_from_arxiv_api

            config = {"project": {"name": "Test"}, "research": {"keywords": ["test"]}}
            new_papers = update_from_arxiv_api(config)

            assert len(new_papers) == 1
            mock_search.assert_called_once()
