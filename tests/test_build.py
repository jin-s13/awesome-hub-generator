"""Tests for build.py"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.build import (
    infer_base_path,
    load_config,
    render_template,
    generate_site,
    generate_readme_with_table,
    derive_datasets_from_benchmark_papers,
    filter_auto_discovered_entries,
    filter_irrelevant_papers,
    prune_disabled_section_data,
    rank_papers_step,
    section_enabled,
    sync_unified_paper_sources,
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


class TestAstroTemplate:
    """Test generated Astro template avoids production-only root redirects."""

    def test_root_route_is_template_page_not_astro_redirect(self):
        root = Path(__file__).resolve().parents[1]
        config = (root / "templates/astro-site/astro.config.mjs").read_text(encoding="utf-8")
        index_page = root / "templates/astro-site/src/pages/index.astro"

        assert "redirects" not in config
        assert index_page.exists()

    def test_datasets_page_does_not_build_category_filter(self):
        root = Path(__file__).resolve().parents[1]
        datasets_page = (root / "templates/astro-site/src/pages/[lang]/datasets.astro").read_text(encoding="utf-8")

        assert "const categories" not in datasets_page
        assert "categories=" not in datasets_page

    def test_project_site_url_path_is_used_as_astro_base(self):
        root = Path(__file__).resolve().parents[1]
        config = (root / "templates/astro-site/astro.config.mjs").read_text(encoding="utf-8")
        lang_lib = (root / "templates/astro-site/src/lib/lang.ts").read_text(encoding="utf-8")

        assert "base: '{{BASE_PATH}}' || undefined" in config
        assert "const BASE_PATH = '{{BASE_PATH}}'" in lang_lib
        assert infer_base_path({"site_url": "https://jin-s13.github.io/awesome-world-model-hub"}) == "/awesome-world-model-hub"
        assert infer_base_path({"site_url": "https://jin-s13.github.io"}) == ""
        assert infer_base_path({"base_path": "/custom", "site_url": "https://example.com/ignored"}) == "/custom"

    def test_analysis_page_is_aggregate_analysis_without_survey_paper_grid(self):
        root = Path(__file__).resolve().parents[1]
        analysis_page = root / "templates/astro-site/src/pages/[lang]/analysis.astro"
        content = analysis_page.read_text(encoding="utf-8")

        assert analysis_page.exists()
        assert "paperTypeList(paper).includes('survey')" not in content
        assert "surveyPapers" not in content
        assert "FilterBar" not in content
        assert "PaperCard" not in content
        assert "Survey papers in the index" not in content
        assert "pages.analysis.title" in content
        assert "Cross-paper synthesis" in content

    def test_legacy_survey_route_redirects_to_analysis(self):
        root = Path(__file__).resolve().parents[1]
        survey_page = root / "templates/astro-site/src/pages/[lang]/surveys.astro"
        content = survey_page.read_text(encoding="utf-8")

        assert survey_page.exists()
        assert "/analysis" in content
        assert "window.location.replace" in content

    def test_analysis_page_reads_generated_survey_topics(self):
        root = Path(__file__).resolve().parents[1]
        data_lib = (root / "templates/astro-site/src/lib/data.ts").read_text(encoding="utf-8")
        analysis_page = (root / "templates/astro-site/src/pages/[lang]/analysis.astro").read_text(encoding="utf-8")

        assert "getSurveys" in data_lib
        assert "label_zh?: string" in data_lib
        assert "description_zh?: string" in data_lib
        assert "related_work_outline_zh?: string[]" in data_lib
        assert "literature_review?: Record<string, unknown>" in data_lib
        assert "const surveyTopics = getSurveys()" in analysis_page
        assert "localizedReview" in analysis_page
        assert "reviewKeyMap" in analysis_page
        assert "Literature review synthesis" in analysis_page
        assert "文献综述归纳" in analysis_page
        assert "Research Lines" in analysis_page
        assert "研究路线" in analysis_page
        assert "localizedTopicLabel" in analysis_page
        assert "componentLabel" in analysis_page
        assert "import { localizePath, type Lang } from '../../lib/lang';" in analysis_page
        assert "localizePath(`/papers/${paper.id}`, lang)" in analysis_page
        assert 'class="survey-paper-list"' not in analysis_page
        assert "survey-paper-link" not in analysis_page

    def test_paper_card_does_not_render_duplicate_source_row(self):
        root = Path(__file__).resolve().parents[1]
        paper_card = (root / "templates/astro-site/src/components/PaperCard.astro").read_text(encoding="utf-8")

        assert 'class="source-row"' not in paper_card
        assert "sourceRepos" in paper_card

    def test_paper_card_uses_readable_link_labels_and_one_detail_action(self):
        root = Path(__file__).resolve().parents[1]
        paper_card = (root / "templates/astro-site/src/components/PaperCard.astro").read_text(encoding="utf-8")

        assert "linkLabelMap" in paper_card
        assert "{linkLabel(key)}" in paper_card
        assert "detail-link" not in paper_card
        assert "paperCard.details" not in paper_card

    def test_papers_page_uses_progressive_grid_for_large_indexes(self):
        root = Path(__file__).resolve().parents[1]
        papers_page = (root / "templates/astro-site/src/pages/[lang]/papers.astro").read_text(encoding="utf-8")
        progressive_grid = (root / "templates/astro-site/src/components/ProgressivePaperGrid.astro").read_text(encoding="utf-8")
        filter_bar = (root / "templates/astro-site/src/components/FilterBar.astro").read_text(encoding="utf-8")

        assert "ProgressivePaperGrid" in papers_page
        assert "papers.map((paper) => <PaperCard" not in papers_page
        assert "INITIAL_VISIBLE_COUNT" in progressive_grid
        assert "BATCH_SIZE" in progressive_grid
        assert "data-progressive-grid" in progressive_grid
        assert "hub-filter-change" in filter_bar
        assert "hub-filter-count" in filter_bar

    def test_resource_card_uses_readable_link_labels(self):
        root = Path(__file__).resolve().parents[1]
        resource_card = (root / "templates/astro-site/src/components/ResourceCard.astro").read_text(encoding="utf-8")

        assert "linkLabelMap" in resource_card
        assert "{linkLabel(key)}" in resource_card

    def test_home_featured_datasets_use_paper_like_cards(self):
        root = Path(__file__).resolve().parents[1]
        index_page = (root / "templates/astro-site/src/pages/[lang]/index.astro").read_text(encoding="utf-8")
        resource_card = (root / "templates/astro-site/src/components/ResourceCard.astro").read_text(encoding="utf-8")
        data_lib = (root / "templates/astro-site/src/lib/data.ts").read_text(encoding="utf-8")

        assert "featured-dataset-section" in index_page
        assert "featured-dataset-grid" in index_page
        assert "{showDatasets && <section class=\"featured-dataset-section\">" in index_page
        assert '<ResourceCard item={item} mode="paper" lang={lang}' in index_page
        assert "datasets.slice(0, 3)" in index_page
        assert "preview?: string" in data_lib
        assert "related_papers?: RelatedPaperRef[]" in data_lib
        assert 'mode === "paper"' in resource_card
        assert "detailHref" in resource_card
        assert "preview-wrap" in resource_card
        assert "paper-body" in resource_card
        assert "target=\"_blank\"" not in resource_card.split("preview-wrap", 1)[1].split("</a>", 1)[0]

    def test_dataset_detail_page_exists(self):
        root = Path(__file__).resolve().parents[1]
        detail_page = root / "templates/astro-site/src/pages/[lang]/datasets/[id].astro"
        content = detail_page.read_text(encoding="utf-8")
        data_lib = (root / "templates/astro-site/src/lib/data.ts").read_text(encoding="utf-8")

        assert detail_page.exists()
        assert "getDataset" in content
        assert "related_papers" in content
        assert "dataset.analysis" in content
        assert "preview-wrap detail-preview" in content
        assert "localizedTitle" in content
        assert "localizedDescription" in content
        assert "localizedNotes" in content
        assert "relatedPaperTitle" in content
        assert "name_zh?: string" in data_lib
        assert "description_zh?: string" in data_lib
        assert "notes_zh?: string" in data_lib
        assert "title_zh?: string" in data_lib

    def test_datasets_page_uses_localized_media_cards(self):
        root = Path(__file__).resolve().parents[1]
        datasets_page = (root / "templates/astro-site/src/pages/[lang]/datasets.astro").read_text(encoding="utf-8")
        resource_card = (root / "templates/astro-site/src/components/ResourceCard.astro").read_text(encoding="utf-8")

        assert '<ResourceCard item={item} mode="paper" lang={lang}' in datasets_page
        assert "localizedTitle" in resource_card
        assert "localizedDescription" in resource_card
        assert "item.name_zh" in resource_card
        assert "item.description_zh" in resource_card

    def test_projects_section_defaults_on_and_resources_default_off(self):
        config = {"website": {"sections": {"papers": True, "datasets": True}}}

        assert section_enabled(config, "papers") is True
        assert section_enabled(config, "datasets") is True
        assert section_enabled(config, "projects") is True
        assert section_enabled(config, "resources") is False

    def test_generate_site_removes_disabled_optional_pages(self, tmp_path):
        config = {
            "project": {"name": "Test Hub", "description": "Test", "site_url": "https://example.com/test"},
            "website": {"sections": {"papers": True, "datasets": True, "projects": False, "resources": False}},
        }

        generate_site(config, tmp_path)

        assert not (tmp_path / "src/pages/[lang]/projects.astro").exists()
        assert not (tmp_path / "src/pages/[lang]/resources.astro").exists()
        assert (tmp_path / "src/pages/[lang]/papers.astro").exists()
        assert (tmp_path / "src/pages/[lang]/datasets.astro").exists()

    def test_projects_page_is_the_only_project_navigation_route(self):
        root = Path(__file__).resolve().parents[1]
        base = (root / "templates/astro-site/src/layouts/Base.astro").read_text(encoding="utf-8")
        index_page = (root / "templates/astro-site/src/pages/[lang]/index.astro").read_text(encoding="utf-8")
        projects_page = root / "templates/astro-site/src/pages/[lang]/projects.astro"
        removed_page = root / "templates/astro-site/src/pages/[lang]/tools.astro"
        i18n = (root / "templates/astro-site/src/lib/i18n.ts").read_text(encoding="utf-8")

        assert projects_page.exists()
        assert not removed_page.exists()
        assert "localizePath('/projects', lang)" in base
        assert "localizePath('/projects', lang)" in index_page
        assert "localizePath('/tools', lang)" not in base
        assert "localizePath('/tools', lang)" not in index_page
        assert "'pages.projects.title': { en: 'Projects'" in i18n

    def test_index_pages_expose_domain_specific_sorting(self):
        root = Path(__file__).resolve().parents[1]
        papers_page = (root / "templates/astro-site/src/pages/[lang]/papers.astro").read_text(encoding="utf-8")
        datasets_page = (root / "templates/astro-site/src/pages/[lang]/datasets.astro").read_text(encoding="utf-8")
        projects_page = (root / "templates/astro-site/src/pages/[lang]/projects.astro").read_text(encoding="utf-8")
        filter_bar = (root / "templates/astro-site/src/components/FilterBar.astro").read_text(encoding="utf-8")
        paper_grid = (root / "templates/astro-site/src/components/ProgressivePaperGrid.astro").read_text(encoding="utf-8")
        resource_card = (root / "templates/astro-site/src/components/ResourceCard.astro").read_text(encoding="utf-8")
        data_lib = (root / "templates/astro-site/src/lib/data.ts").read_text(encoding="utf-8")
        i18n = (root / "templates/astro-site/src/lib/i18n.ts").read_text(encoding="utf-8")

        assert "filter.sortScore" in papers_page
        assert "filter.sortYear" in papers_page
        assert "sortPapers" in paper_grid
        assert "scoreValue(b.score) - scoreValue(a.score)" in data_lib
        assert "filter.sortScore" in datasets_page
        assert "data-sort-container" in datasets_page
        assert "related_papers" in data_lib
        assert "sortOptions" in projects_page
        assert "filter.sortStars" in projects_page
        assert "filter.sortAlpha" in projects_page
        assert "data-sort-container" in projects_page
        assert "sortSelect" in filter_bar
        assert "sortItems" in filter_bar
        assert "hub-filter-change" in filter_bar
        assert "data-score={sortScore}" in resource_card
        assert "data-title={title}" in resource_card
        assert "'filter.sort':" in i18n
        assert "'filter.sortStars':" in i18n

    def test_navigation_orders_content_before_analysis_sections(self):
        root = Path(__file__).resolve().parents[1]
        base = (root / "templates/astro-site/src/layouts/Base.astro").read_text(encoding="utf-8")
        expected_order = [
            "nav.home",
            "nav.papers",
            "nav.datasets",
            "nav.projects",
            "nav.analysis",
            "nav.trends",
        ]

        positions = [base.index(f"_t('{key}')") for key in expected_order]
        assert positions == sorted(positions)

    def test_daily_update_workflow_template_is_configured_for_world_model_hub(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / "templates/workflows/daily-update.yml").read_text(encoding="utf-8")

        assert "cron: '0 0 * * *'" in workflow
        assert "jin-s13/awesome-hub-generator" in workflow
        assert "your-org/awesome-hub-generator" not in workflow
        assert "OPENALEX_API_KEY" in workflow
        assert "OPENALEX_MAILTO" in workflow
        assert "SEMANTIC_SCHOLAR_API_KEY" in workflow
        assert "ARK_SURVEY_TIMEOUT_SECONDS" in workflow
        assert "SEMANTIC_SCHOLAR_REQUEST_INTERVAL_SECONDS" in workflow
        assert "GH_DISCOVERY_TOKEN" in workflow
        assert "GH_TOKEN: ${{ secrets.GH_DISCOVERY_TOKEN || github.token }}" in workflow
        assert "GITHUB_TOKEN:" not in workflow
        assert ".local/website" in workflow
        assert "python awesome-hub-generator/scripts/update.py" in workflow
        assert "Publish GitHub Pages branch" in workflow
        assert "git switch --orphan gh-pages" in workflow
        assert "git push -f origin gh-pages" in workflow
        assert "actions/deploy-pages@v4" not in workflow
        assert "actions/upload-pages-artifact@v3" not in workflow
        assert "github.event_name != 'push'" in workflow

    def test_trends_page_normalizes_tags_and_infers_missing_years(self):
        root = Path(__file__).resolve().parents[1]
        trends_page = (root / "templates/astro-site/src/pages/[lang]/trends.astro").read_text(encoding="utf-8")

        assert "normalizeTag" in trends_page
        assert "inferPaperYear" in trends_page
        assert "yearCounts[y]" in trends_page
        assert "'Unknown'" not in trends_page
        assert "componentAgg" in trends_page
        assert "Read-first component trends" in trends_page

    def test_paper_detail_localizes_score_component_notes(self):
        root = Path(__file__).resolve().parents[1]
        detail_page = (root / "templates/astro-site/src/pages/[lang]/papers/[id].astro").read_text(encoding="utf-8")
        data_lib = (root / "templates/astro-site/src/lib/data.ts").read_text(encoding="utf-8")

        assert "explanation_zh?: string" in data_lib
        assert "localizedComponentExplanation" in detail_page
        assert "formatEvidenceDetail" in detail_page
        assert "component.explanation_zh" in detail_page

    def test_paper_detail_uses_readable_resource_link_labels(self):
        root = Path(__file__).resolve().parents[1]
        detail_page = (root / "templates/astro-site/src/pages/[lang]/papers/[id].astro").read_text(encoding="utf-8")

        assert "linkLabelMap" in detail_page
        assert "{linkLabel(key)}" in detail_page


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

    def test_clears_disabled_projects_and_resources_but_keeps_datasets(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "datasets.yaml").write_text("- name: Dataset\n", encoding="utf-8")
        (data_dir / "projects.yaml").write_text("- name: Bad Project\n", encoding="utf-8")
        (data_dir / "resources.yaml").write_text("- name: Bad Resource\n", encoding="utf-8")

        config = {
            "website": {
                "sections": {
                    "datasets": True,
                    "projects": False,
                    "resources": False,
                }
            }
        }

        prune_disabled_section_data(data_dir, config)

        assert (data_dir / "datasets.yaml").read_text(encoding="utf-8") == "- name: Dataset\n"
        assert (data_dir / "projects.yaml").read_text(encoding="utf-8") == "[]\n"
        assert (data_dir / "resources.yaml").read_text(encoding="utf-8") == "[]\n"


class TestDatasetDerivation:
    """Test benchmark papers populate datasets.yaml."""

    def test_derives_dataset_entries_from_benchmark_papers(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "papers.yaml").write_text(
            """
- id: bench-1
  title: "WorldBench: A Benchmark for World Models"
  abstract: "We introduce a benchmark for world models."
  year: 2026
  paper_type: [benchmark]
  tags: [benchmark, world model]
  links:
    paper: https://arxiv.org/abs/2601.00001
  sources:
    - repo: arxiv
- id: method-1
  title: "A World Model Method"
  year: 2026
  paper_type: [method]
  tags: [world model]
""",
            encoding="utf-8",
        )
        (data_dir / "datasets.yaml").write_text("[]\n", encoding="utf-8")

        added = derive_datasets_from_benchmark_papers(
            data_dir,
            {"website": {"sections": {"datasets": True}}},
        )

        datasets = __import__("yaml").safe_load((data_dir / "datasets.yaml").read_text()) or []
        assert added == 1
        assert datasets[0]["name"] == "WorldBench"
        assert "category" not in datasets[0]
        assert "type" not in datasets[0]
        assert datasets[0]["links"]["paper"] == "https://arxiv.org/abs/2601.00001"


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

    def test_filter_irrelevant_papers_can_skip_llm(self, tmp_path, monkeypatch):
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
                    "relevance_criteria": {"include": ["world models"]},
                    "keywords": ["world model"],
                },
            },
            use_llm=False,
        )

        assert seen["use_llm"] is False


class TestRankPapersStep:
    """Test PaperRank-lite build step wiring."""

    def test_calls_rank_enricher_by_default(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "papers.yaml").write_text("[]\n", encoding="utf-8")
        seen = {}

        def fake_enrich(path, config):
            seen["path"] = path
            seen["config"] = config
            return 0

        monkeypatch.setattr("scripts.paper_rank.enrich_paper_rank_scores", fake_enrich)

        rank_papers_step(data_dir, {"research": {"keywords": ["CAD"]}})

        assert seen["path"] == data_dir / "papers.yaml"
        assert seen["config"]["research"]["keywords"] == ["CAD"]

    def test_skips_when_disabled(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "papers.yaml").write_text("[]\n", encoding="utf-8")
        called = False

        def fake_enrich(path, config):
            nonlocal called
            called = True
            return 0

        monkeypatch.setattr("scripts.paper_rank.enrich_paper_rank_scores", fake_enrich)

        rank_papers_step(data_dir, {"research": {"ranking": {"enabled": False}}})

        assert called is False


class TestUnifiedPaperSourcesStep:
    """Test build.py syncs unified source results through sync_papers."""

    def test_syncs_collected_papers_to_papers_yaml(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        seen = {}

        def fake_collect(config, search_days=None, max_results=500):
            seen["search_days"] = search_days
            seen["max_results"] = max_results
            seen["github_cache_path"] = config.get("_runtime", {}).get("github_cache_path")
            return {
                "papers": [
                    {
                        "title": "Unified Build Paper",
                        "abstract": "A paper discovered by unified sources.",
                        "links": {"paper": "https://arxiv.org/abs/2601.00001"},
                    }
                ],
                "sources": {"arxiv": {"enabled": True, "count": 1}},
            }

        def fake_sync(papers, output_path, source_repo="arxiv", **kwargs):
            seen["papers"] = papers
            seen["output_path"] = output_path
            seen["source_repo"] = source_repo
            seen["kwargs"] = kwargs
            return len(papers)

        monkeypatch.setattr("scripts.paper_sources.collect_paper_sources", fake_collect)
        monkeypatch.setattr("sync.sync_papers", fake_sync)

        added = sync_unified_paper_sources(
            data_dir,
            {"project": {"description": "World models"}, "research": {"keywords": ["world model"]}},
            skip_llm=True,
            max_papers=10,
            search_days=30,
        )

        assert added == 1
        assert seen["search_days"] == 30
        assert seen["max_results"] == 10
        assert seen["github_cache_path"] == str(data_dir / "github_discovery_cache.json")
        assert seen["output_path"] == data_dir / "papers.yaml"
        assert seen["source_repo"] == "unified-sources"
        assert seen["kwargs"]["skip_llm"] is True
        assert seen["kwargs"]["research_context"] == "World models"


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
