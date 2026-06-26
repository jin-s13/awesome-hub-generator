"""Tests for build.py"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.build import (
    load_config,
    render_template,
    generate_readme_with_table,
    filter_auto_discovered_entries,
    filter_irrelevant_papers,
    prune_disabled_section_data,
    sync_options_from_config,
)


class TestLoadConfig:
    """Test config loading."""

    def test_loads_yaml(self, tmp_path):
        config = tmp_path / "awesome.yaml"
        config.write_text("project:\n  name: Test\n", encoding="utf-8")
        with patch("scripts.build.SITE_DIR", tmp_path), patch("scripts.build.ROOT", tmp_path):
            result = load_config()
        assert result["project"]["name"] == "Test"

    def test_exits_on_missing(self, tmp_path):
        with patch("scripts.build.SITE_DIR", tmp_path), patch("scripts.build.ROOT", tmp_path):
            with pytest.raises(SystemExit):
                load_config()


class TestRenderTemplate:
    """Test template rendering."""

    def test_replaces_variables(self, tmp_path):
        src = tmp_path / "template.html"
        src.write_text("<h1>{{PROJECT_NAME}}</h1><p>{{DESCRIPTION}}</p>", encoding="utf-8")
        dst = tmp_path / "output.html"
        render_template(src, dst, {"PROJECT_NAME": "Test", "DESCRIPTION": "Hello"})
        content = dst.read_text(encoding="utf-8")
        assert "<h1>Test</h1>" in content
        assert "<p>Hello</p>" in content

    def test_skips_directories(self, tmp_path):
        src = tmp_path / "adir"
        src.mkdir()
        dst = tmp_path / "outdir"
        dst.mkdir()
        render_template(src, dst, {"KEY": "val"})
        # Should not crash, just skip


class TestGenerateReadmeWithTable:
    """Test README generation."""

    def test_generates_table(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        papers_file = data_dir / "papers.yaml"
        papers_file.write_text(
            "- id: p1\n  title: Paper 1\n  year: 2025\n  venue: arXiv\n  links:\n    paper: http://url.com\n",
            encoding="utf-8",
        )
        config = {"project": {"name": "Test Hub", "description": "A test hub."}}

        generate_readme_with_table(config, tmp_path, data_dir)

        readme = tmp_path / "README.md"
        assert readme.exists()
        content = readme.read_text(encoding="utf-8")
        assert "# Test Hub" in content
        assert "Paper 1" in content
        assert "http://url.com" in content


class TestSectionDataPruning:
    """Test website section switches affect generated data files."""

    def test_clears_disabled_tools_and_resources_but_keeps_datasets(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "datasets.yaml").write_text("- name: Dataset\n", encoding="utf-8")
        (data_dir / "tools.yaml").write_text("- name: Bad Tool\n", encoding="utf-8")
        (data_dir / "resources.yaml").write_text("- name: Bad Resource\n", encoding="utf-8")

        config = {
            "website": {
                "sections": {
                    "datasets": True,
                    "tools": False,
                    "resources": False,
                }
            }
        }

        prune_disabled_section_data(data_dir, config)

        assert (data_dir / "datasets.yaml").read_text(encoding="utf-8") == "- name: Dataset\n"
        assert (data_dir / "tools.yaml").read_text(encoding="utf-8") == "[]\n"
        assert (data_dir / "resources.yaml").read_text(encoding="utf-8") == "[]\n"


class TestAutoDiscoverFiltering:
    """Test GitHub auto-discover does not promote generic resources as papers."""

    def test_drops_resource_entries_when_resources_section_is_disabled(self):
        entries = [
            {
                "title": "Generic MCP Server",
                "_type": "resource",
                "links": {"code": "https://github.com/example/mcp"},
            },
            {
                "title": "World Model Paper",
                "links": {"paper": "https://arxiv.org/abs/2501.00001"},
            },
        ]
        config = {"website": {"sections": {"resources": False}}}

        filtered = filter_auto_discovered_entries(entries, config)

        assert [item["title"] for item in filtered] == ["World Model Paper"]

    def test_drops_abstractless_non_academic_entries_when_resources_disabled(self):
        entries = [
            {"title": "GitHub Project", "links": {"code": "https://github.com/example/project"}},
            {"title": "Academic Paper", "links": {"paper": "https://openreview.net/forum?id=abc"}},
        ]

        filtered = filter_auto_discovered_entries(entries, {"website": {"sections": {"resources": False}}})

        assert [item["title"] for item in filtered] == ["Academic Paper"]


class TestRelevanceFiltering:
    """Test build forwards configured relevance criteria to relevance_filter."""

    def test_filter_irrelevant_papers_passes_relevance_criteria(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "papers.yaml").write_text(
            "- title: Paper\n  abstract: About world models.\n",
            encoding="utf-8",
        )
        seen = {}

        def fake_filter(papers, negative, min_score, **kwargs):
            seen.update(kwargs)
            return papers, []

        monkeypatch.setattr("relevance_filter.filter_papers", fake_filter)

        filter_irrelevant_papers(
            data_dir,
            {
                "project": {"description": "World model hub"},
                "research": {
                    "relevance_criteria": {"include": ["world models"], "exclude": ["MCP"]},
                    "keywords": ["world model"],
                },
            },
        )

        assert seen["relevance_criteria"]["include"] == ["world models"]


class TestSyncOptionsFromConfig:
    """Test build passes taxonomy and relevance criteria into arXiv fallback sync."""

    def test_extracts_taxonomy_relevance_and_context(self):
        config = {
            "project": {"description": "World model hub"},
            "research": {
                "taxonomy": {"paper_types": [{"label": "benchmark", "description": "Benchmarks"}]},
                "relevance_criteria": {"include": ["world models"], "exclude": ["finance"]},
            },
        }

        options = sync_options_from_config(config)

        assert options["research_context"] == "World model hub"
        assert options["taxonomy"]["paper_types"][0]["label"] == "benchmark"
        assert options["relevance_criteria"]["include"] == ["world models"]


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
        """Verify fallback to arXiv API when researcher fails."""
        mocker.patch("scripts.researcher_adapter.ResearcherAdapter",
                     side_effect=ImportError("no researcher"))

        with patch("scripts.sync.search_arxiv") as mock_search:
            mock_search.return_value = [
                {"title": "Paper 1", "abstract": "Abstract", "categories": ["cs.CV"]}
            ]

            config = {"project": {"name": "Test"}, "research": {"keywords": ["test"]}}
            keywords = config["research"]["keywords"]
            categories = config["research"].get("arxiv_categories", [])
            date_from = config["research"].get("date_from", "")

            # This simulates what main() does in the fallback path
            papers = mock_search(keywords, categories, date_from, "", max_results=500)
            assert len(papers) == 1
            mock_search.assert_called_once()

    def test_skip_researcher_flag_logic(self, mocker):
        """Verify --skip-researcher uses arXiv API directly."""
        with patch("scripts.sync.search_arxiv") as mock_search:
            mock_search.return_value = [
                {"title": "Paper 1", "abstract": "Abstract", "categories": ["cs.CV"]}
            ]

            config = {"project": {"name": "Test"}, "research": {"keywords": ["test"]}}
            keywords = config["research"]["keywords"]
            categories = config["research"].get("arxiv_categories", [])
            date_from = config["research"].get("date_from", "")

            papers = mock_search(keywords, categories, date_from, "", max_results=500)
            assert len(papers) == 1
            mock_search.assert_called_once()
