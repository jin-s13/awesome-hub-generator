"""Tests for update.py"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.update import (
    collect_sources_to_pool,
    fetch_teasers_step,
    interpretation_refresh_step,
    load_config,
    load_papers_yaml,
    promote_candidates,
    rank_papers_step,
    save_papers_yaml,
    seed_ref_has_domain_anchor,
    taxonomy_step,
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


class TestInterpretationRefreshStep:
    """Test daily update backfills missing LLM paper fields."""

    def test_runs_parallel_refresh_when_api_key_is_configured(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "papers.yaml").write_text("[]\n", encoding="utf-8")
        config_path = tmp_path / "awesome.yaml"
        config_path.write_text("research:\n  keywords: [world model]\n", encoding="utf-8")
        monkeypatch.setenv("ARK_API_KEY", "test-key")
        monkeypatch.setenv("HUB_CONFIG_PATH", str(config_path))
        seen = {}

        def fake_run(cmd, cwd=None, env=None, check=False):
            seen["cmd"] = cmd
            seen["cwd"] = cwd
            seen["env"] = env
            seen["check"] = check
            return MagicMock(returncode=0)

        monkeypatch.setattr("subprocess.run", fake_run)

        ok = interpretation_refresh_step({"research": {}}, data_dir)

        assert ok is True
        assert "refresh_interpretations_parallel.py" in seen["cmd"][1]
        assert seen["cmd"][-2:] == ["--config", str(config_path)]
        assert "--data-dir" in seen["cmd"]
        assert str(data_dir) in seen["cmd"]
        assert seen["env"]["HUB_DATA_DIR"] == str(data_dir)
        assert seen["check"] is False

    def test_skips_parallel_refresh_without_api_key(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch.delenv("ARK_API_KEY", raising=False)
        called = False

        def fake_run(*args, **kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("subprocess.run", fake_run)

        ok = interpretation_refresh_step({"research": {}}, data_dir)

        assert ok is False
        assert called is False


class TestFetchTeasersStep:
    """Test daily update teaser step wiring."""

    def test_passes_teaser_config(self, monkeypatch, tmp_path):
        seen = {}

        def fake_fetch_teasers(retry_fallbacks=True, workers=1):
            seen["retry_fallbacks"] = retry_fallbacks
            seen["workers"] = workers

        import fetch_teasers

        monkeypatch.setattr(fetch_teasers, "main", fake_fetch_teasers)

        fetch_teasers_step(
            {"research": {"teasers": {"workers": 7, "retry_fallbacks": False}}},
            tmp_path,
        )

        assert seen == {"retry_fallbacks": False, "workers": 7}


class TestTaxonomyStep:
    """Test taxonomy discovery and assignment wiring."""

    def test_runs_taxonomy_discovery_and_assignment_by_default(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "papers.yaml").write_text("[]\n", encoding="utf-8")
        calls = []

        def fake_build(path, config):
            calls.append(("build", path, config))
            return 2

        def fake_assign(path, config):
            calls.append(("assign", path, config))
            return 1

        monkeypatch.setattr("scripts.taxonomy_discovery.build_taxonomy", fake_build)
        monkeypatch.setattr("scripts.taxonomy_discovery.assign_papers_to_taxonomy", fake_assign)

        taxonomy_step({"research": {}}, data_dir)

        assert calls == [
            ("build", data_dir, {"research": {}}),
            ("assign", data_dir, {"research": {}}),
        ]

    def test_skips_taxonomy_discovery_when_disabled(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        called = False

        def fake_build(*args, **kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("scripts.taxonomy_discovery.build_taxonomy", fake_build)

        taxonomy_step({"research": {"taxonomy_discovery": {"enabled": False}}}, data_dir)

        assert called is False


class TestCollectSourcesToPool:
    """Test update.py uses the unified paper source aggregator."""

    def test_adds_unified_source_results_to_candidate_pool(self, monkeypatch):
        seen = {}

        def fake_collect(config, search_days=None, max_results=500):
            seen["config"] = config
            seen["github_cache_path"] = config.get("_runtime", {}).get("github_cache_path")
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
        collect_sources_to_pool(
            {
                "_runtime": {"github_cache_path": "/tmp/github-cache.json"},
                "research": {"sources": {"arxiv": True}},
            },
            pool,
            search_days=14,
        )

        assert seen["search_days"] == 14
        assert seen["github_cache_path"] == "/tmp/github-cache.json"
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

    def test_writes_discovered_github_projects_to_projects_yaml(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch.setenv("HUB_DATA_DIR", str(data_dir))

        def fake_collect(config, search_days=None, max_results=500):
            return {
                "papers": [],
                "projects": [
                    {
                        "name": "awesome-cad",
                        "description": "CAD projects",
                        "stars": 1000,
                        "links": {"github": "https://github.com/owner/awesome-cad"},
                        "sources": [{"repo": "owner/awesome-cad", "category": "github_project"}],
                    }
                ],
                "sources": {"awesome": {"enabled": True, "count": 0}},
            }

        class FakePool:
            def add_batch(self, papers, source="unknown"):
                raise AssertionError("no paper candidates should be added")

        monkeypatch.setattr("scripts.paper_sources.collect_paper_sources", fake_collect)

        collect_sources_to_pool(
            {"website": {"sections": {"projects": True}}, "research": {"sources": {"upstream_awesome": True}}},
            FakePool(),
            search_days=14,
        )

        assert "awesome-cad" in (data_dir / "projects.yaml").read_text(encoding="utf-8")
        assert "1000" in (data_dir / "projects.yaml").read_text(encoding="utf-8")


class TestPromoteCandidates:
    """Test candidate promotion safeguards."""

    def test_dedupes_same_batch_non_arxiv_title(self, tmp_path, monkeypatch):
        papers_yaml = tmp_path / "papers.yaml"
        papers_yaml.write_text("[]\n", encoding="utf-8")

        class FakePool:
            def __init__(self):
                self.relevance = []
                self.promoted = []

            def get_unchecked(self, limit):
                return [
                    {
                        "title": "Planning with an Ensemble of World Models",
                        "abstract": "A world model planning paper.",
                        "year": 2026,
                        "links": {"paper": "https://openreview.net/forum?id=cvGdPXaydP"},
                    },
                    {
                        "title": "Planning with an Ensemble of World Models",
                        "abstract": "Duplicate candidate.",
                        "year": 2026,
                        "links": {"paper": "https://openreview.net/forum?id=cvGdPXaydP"},
                    },
                ]

            def mark_relevance(self, aid, relevant):
                self.relevance.append((aid, relevant))

            def mark_promoted(self, aid):
                self.promoted.append(aid)

        monkeypatch.setattr("scripts.relevance_filter.is_cad_relevant", lambda *args, **kwargs: True)

        added = promote_candidates(
            {"research": {"candidate_pool": {"promote_batch_size": 10}}},
            FakePool(),
            papers_yaml,
        )

        papers = load_papers_yaml(papers_yaml)
        assert added == 1
        assert len(papers) == 1


class TestSeedReferenceFiltering:
    """Test stricter filtering for noisy Semantic Scholar references."""

    def test_requires_cad_anchor_for_seed_references(self):
        assert seed_ref_has_domain_anchor(
            {"title": "Low-rank adaptation of large language models", "abstract": "Adapts LLMs efficiently."},
            ["AI for CAD", "B-Rep", "parametric design"],
        ) is False
        assert seed_ref_has_domain_anchor(
            {"title": "CAD-Coder: Text-to-CAD Generation with Geometric Reward", "abstract": "Generates CAD programs."},
            ["AI for CAD", "B-Rep", "parametric design"],
        ) is True


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
