"""Tests for unified paper source aggregation."""

from scripts.paper_sources import collect_paper_sources


def test_markdown_list_parser_handles_awesome_badge_links():
    from scripts.ingest_source import MarkdownListParser

    readme = (
        "- [**UniFuture**] UniFuture: A 4D Driving World Model for Future Generation and Perception. "
        "**`ICRA 26`** [[Paper](https://arxiv.org/abs/2503.13587)] "
        "[[Code](https://github.com/dk-liang/UniFuture)] "
        "[[Project](https://dk-liang.github.io/UniFuture/)]"
    )

    papers = MarkdownListParser.parse(readme, "LMD0311/Awesome-World-Model")

    assert len(papers) == 1
    assert papers[0]["title"] == "UniFuture: A 4D Driving World Model for Future Generation and Perception"
    assert papers[0]["year"] == 2026
    assert papers[0]["venue"] == "ICRA 26"
    assert papers[0]["links"]["paper"] == "https://arxiv.org/abs/2503.13587"
    assert papers[0]["links"]["code"] == "https://github.com/dk-liang/UniFuture"
    assert papers[0]["links"]["project"] == "https://dk-liang.github.io/UniFuture/"


def test_markdown_list_parser_uses_arxiv_url_year_when_venue_has_typo():
    from scripts.ingest_source import MarkdownListParser

    readme = (
        "- **PerceptUI**: PerceptUI: LLM Agents as Human-Aligned Synthetic Users for UI/UX Evaluation. "
        "**`arXiv 05.6`** [[Paper](https://arxiv.org/abs/2606.05697)]"
    )

    papers = MarkdownListParser.parse(readme, "LMD0311/Awesome-World-Model")

    assert papers[0]["year"] == 2026


def test_markdown_table_parser_preserves_upstream_metadata():
    from scripts.ingest_source import MarkdownTableParser

    readme = """
| Model | Paper | Authors | Venue | Website | GitHub | Teaser |
| --- | --- | --- | --- | --- | --- | --- |
| AutoResearch | [AI for Auto-Research](https://arxiv.org/abs/2605.18661) | Ada Lovelace, Alan Turing | arXiv 2026 | [Project](https://worldbench.github.io/awesome-ai-auto-research/) | [Code](https://github.com/worldbench/awesome-ai-auto-research) | ![teaser](https://example.com/teaser.png) |
"""

    papers = MarkdownTableParser.parse(readme, "worldbench/awesome-ai-auto-research")

    assert len(papers) == 1
    assert papers[0]["title"] == "AI for Auto-Research"
    assert papers[0]["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert papers[0]["venue"] == "arXiv 2026"
    assert papers[0]["links"]["paper"] == "https://arxiv.org/abs/2605.18661"
    assert papers[0]["links"]["project"] == "https://worldbench.github.io/awesome-ai-auto-research/"
    assert papers[0]["links"]["code"] == "https://github.com/worldbench/awesome-ai-auto-research"
    assert papers[0]["preview"] == "https://example.com/teaser.png"


def test_markdown_list_parser_preserves_inline_teaser_image():
    from scripts.ingest_source import MarkdownListParser

    readme = (
        "- [AutoResearch](https://arxiv.org/abs/2605.18661) - "
        "AI auto-research survey ![teaser](https://example.com/list-teaser.png)"
    )

    papers = MarkdownListParser.parse(readme, "worldbench/awesome-ai-auto-research")

    assert papers[0]["preview"] == "https://example.com/list-teaser.png"


def test_markdown_list_parser_handles_bold_title_badge_links():
    from scripts.ingest_source import MarkdownListParser

    readme = (
        "*   **SCIMON : Scientific Inspiration Machines Optimized for Novelty** "
        "[![arXiv](https://img.shields.io/badge/arXiv-2305.14259-B31B1B.svg)]"
        "(https://arxiv.org/pdf/2305.14259) - *Wang et al. (2023.05)*"
    )

    papers = MarkdownListParser.parse(readme, "HKUST-KnowComp/Awesome-LLM-Scientific-Discovery")

    assert len(papers) == 1
    assert papers[0]["title"] == "SCIMON : Scientific Inspiration Machines Optimized for Novelty"
    assert papers[0]["links"]["paper"] == "https://arxiv.org/pdf/2305.14259"
    assert papers[0]["preview"] == "/assets/placeholder.svg"


def test_yaml_parser_preserves_authors_preview_and_link_aliases():
    from scripts.ingest_source import YamlParser

    content = """
- title: AI for Auto-Research
  authors: Ada Lovelace and Alan Turing
  arxiv: https://arxiv.org/abs/2605.18661
  github: https://github.com/worldbench/awesome-ai-auto-research
  website: https://worldbench.github.io/awesome-ai-auto-research/
  teaser: https://example.com/yaml-teaser.png
  venue: arXiv
"""

    papers = YamlParser.parse(content, "worldbench/awesome-ai-auto-research")

    assert papers[0]["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert papers[0]["links"]["paper"] == "https://arxiv.org/abs/2605.18661"
    assert papers[0]["links"]["code"] == "https://github.com/worldbench/awesome-ai-auto-research"
    assert papers[0]["links"]["project"] == "https://worldbench.github.io/awesome-ai-auto-research/"
    assert papers[0]["preview"] == "https://example.com/yaml-teaser.png"


def test_sync_papers_preserves_upstream_awesome_metadata(tmp_path):
    from scripts.sync import load_yaml, sync_papers

    output = tmp_path / "papers.yaml"
    added = sync_papers(
        [
            {
                "title": "UniFuture: A 4D Driving World Model for Future Generation and Perception",
                "abstract": "",
                "year": 2026,
                "venue": "ICRA 26",
                "links": {"paper": "https://arxiv.org/abs/2503.13587"},
                "preview": "https://example.com/upstream-teaser.png",
                "sources": [{"repo": "LMD0311/Awesome-World-Model", "category": "Others"}],
            }
        ],
        output,
        source_repo="unified-sources",
        skip_llm=True,
    )

    papers = load_yaml(output)

    assert added == 1
    assert papers[0]["venue"] == "ICRA 26"
    assert papers[0]["preview"] == "https://example.com/upstream-teaser.png"
    assert papers[0]["sources"][0]["repo"] == "LMD0311/Awesome-World-Model"


def test_collect_paper_sources_merges_enabled_sources_and_dedupes(monkeypatch):
    calls = []

    def fake_arxiv(config, search_days=None, max_results=500):
        calls.append("arxiv")
        return [
            {
                "id": "arxiv-paper",
                "arxiv_id": "2601.00001",
                "title": "Unified Paper Search",
                "links": {"paper": "https://arxiv.org/abs/2601.00001"},
                "sources": [{"repo": "arxiv", "category": "paper"}],
            }
        ]

    def fake_hf(config, search_days=None):
        calls.append("huggingface")
        return [
            {
                "id": "hf-paper",
                "title": "Unified Paper Search",
                "links": {"paper": "https://arxiv.org/abs/2601.00001"},
                "sources": [{"repo": "huggingface-daily", "category": "paper"}],
                "score": {"upvotes": 17},
            }
        ]

    def fake_awesome_bundle(config):
        calls.append("awesome")
        return {
            "papers": [
                {
                    "id": "awesome-paper",
                    "title": "A Curated Awesome Paper",
                    "links": {"paper": "https://example.com/paper"},
                    "sources": [{"repo": "owner/awesome-list", "category": "paper"}],
                }
            ],
            "projects": [
                {
                    "name": "awesome-list",
                    "links": {"github": "https://github.com/owner/awesome-list"},
                    "stars": 123,
                    "sources": [{"repo": "owner/awesome-list", "category": "github_project"}],
                }
            ],
        }

    def fail_alphaxiv(config, query=None):
        raise AssertionError("AlphaXiv should be disabled unless explicitly enabled")

    monkeypatch.setattr("scripts.paper_sources.fetch_arxiv_source", fake_arxiv)
    monkeypatch.setattr("scripts.paper_sources.fetch_huggingface_source", fake_hf)
    monkeypatch.setattr("scripts.paper_sources.fetch_awesome_bundle", fake_awesome_bundle)
    monkeypatch.setattr("scripts.paper_sources.fetch_alphaxiv_source", fail_alphaxiv)

    result = collect_paper_sources(
        {
            "research": {
                "keywords": ["paper search"],
                "sources": {
                    "arxiv": True,
                    "huggingface_daily": True,
                    "upstream_awesome": True,
                    "alphaxiv": False,
                },
            }
        },
        search_days=7,
    )

    assert calls == ["arxiv", "huggingface", "awesome"]
    assert len(result["papers"]) == 2
    merged = result["papers"][0]
    assert merged["arxiv_id"] == "2601.00001"
    assert [source["repo"] for source in merged["sources"]] == ["arxiv", "huggingface-daily"]
    assert merged["score"]["upvotes"] == 17
    assert result["sources"]["arxiv"]["count"] == 1
    assert result["sources"]["huggingface"]["count"] == 1
    assert result["sources"]["awesome"]["count"] == 1
    assert result["sources"]["alphaxiv"]["enabled"] is False
    assert result["projects"][0]["name"] == "awesome-list"
    assert result["projects"][0]["stars"] == 123


def test_collect_paper_sources_records_nonfatal_source_errors(monkeypatch):
    def broken_arxiv(config, search_days=None, max_results=500):
        raise RuntimeError("temporary arxiv outage")

    def fake_hf(config, search_days=None):
        return [{"id": "hf-only", "title": "HF Paper", "links": {"paper": "https://arxiv.org/abs/2602.00001"}}]

    monkeypatch.setattr("scripts.paper_sources.fetch_arxiv_source", broken_arxiv)
    monkeypatch.setattr("scripts.paper_sources.fetch_huggingface_source", fake_hf)
    monkeypatch.setattr("scripts.paper_sources.fetch_awesome_bundle", lambda config: {"papers": [], "projects": []})
    monkeypatch.setattr("scripts.paper_sources.fetch_alphaxiv_source", lambda config, query=None: [])

    result = collect_paper_sources(
        {
            "research": {
                "sources": {
                    "arxiv": True,
                    "huggingface_daily": True,
                    "upstream_awesome": False,
                    "alphaxiv": False,
                }
            }
        }
    )

    assert len(result["papers"]) == 1
    assert result["sources"]["arxiv"]["count"] == 0
    assert "temporary arxiv outage" in result["sources"]["arxiv"]["error"]


def test_fetch_awesome_source_uses_configured_repos_without_auto_discover(monkeypatch):
    from scripts.discover_sources import SourceInfo
    from scripts.paper_sources import fetch_awesome_source

    calls = []

    class FakeDiscoverer:
        def __init__(self, **kwargs):
            pass

        def source_from_repo(self, repo):
            calls.append(("source_from_repo", repo))
            return SourceInfo(
                full_name=repo,
                html_url=f"https://github.com/{repo}",
                stars=123,
                description="Curated world-model papers",
                default_branch="main",
            )

        def discover(self, keywords, min_stars=5, max_sources=10):
            calls.append(("discover", tuple(keywords)))
            raise AssertionError("auto discovery should not run for explicit upstream repos")

        def fetch_readme(self, source):
            calls.append(("fetch_readme", source.full_name))
            return "- [Dreamer: Reinforcement Learning with Latent Dynamics](https://arxiv.org/abs/1912.01603)"

        def list_repo_files(self, source):
            calls.append(("list_repo_files", source.full_name))
            return ["README.md"]

    monkeypatch.setattr("scripts.discover_sources.GitHubDiscoverer", FakeDiscoverer)

    papers = fetch_awesome_source(
        {
            "research": {
                "keywords": ["world model"],
                "sources": {"upstream_awesome": True},
                "upstream_awesome": {
                    "repos": ["curated/awesome-world-models"],
                    "auto_discover": False,
                },
            }
        }
    )

    assert [paper["title"] for paper in papers] == ["Dreamer: Reinforcement Learning with Latent Dynamics"]
    assert papers[0]["links"]["paper"] == "https://arxiv.org/abs/1912.01603"
    assert papers[0]["sources"][0]["repo"] == "curated/awesome-world-models"
    assert ("discover", ("world model",)) not in calls


def test_fetch_awesome_source_passes_runtime_cache_path(monkeypatch, tmp_path):
    from scripts.discover_sources import SourceInfo
    from scripts.paper_sources import fetch_awesome_source

    created = {}

    class FakeDiscoverer:
        def __init__(self, cache_path=None, **kwargs):
            created["cache_path"] = cache_path

        def source_from_repo(self, repo):
            return SourceInfo(repo, f"https://github.com/{repo}", 10, "", "main")

        def discover(self, keywords, min_stars=5, max_sources=10):
            return []

        def fetch_readme(self, source):
            return "- [CAD Paper](https://arxiv.org/abs/2601.00001)"

        def list_repo_files(self, source):
            return ["README.md"]

    monkeypatch.setattr("scripts.discover_sources.GitHubDiscoverer", FakeDiscoverer)
    cache_path = tmp_path / "github-cache.json"

    fetch_awesome_source(
        {
            "_runtime": {"github_cache_path": str(cache_path)},
            "research": {
                "keywords": ["CAD"],
                "sources": {"upstream_awesome": True},
                "upstream_awesome": {"repos": ["owner/awesome-cad"], "auto_discover": False},
            },
        }
    )

    assert created["cache_path"] == cache_path


def test_fetch_awesome_source_passes_github_runtime_limits(monkeypatch):
    from scripts.discover_sources import SourceInfo
    from scripts.paper_sources import fetch_awesome_source

    created = {}
    discovered = {}
    fetched_readmes = []

    class FakeDiscoverer:
        def __init__(self, **kwargs):
            created.update(kwargs)

        def source_from_repo(self, repo):
            return SourceInfo(repo, f"https://github.com/{repo}", 10, "", "main")

        def discover(self, keywords, min_stars=5, max_sources=10, query_expansion=None, max_search_terms=None):
            discovered.update(
                {
                    "keywords": keywords,
                    "min_stars": min_stars,
                    "max_sources": max_sources,
                    "query_expansion": query_expansion,
                    "max_search_terms": max_search_terms,
                }
            )
            return [
                SourceInfo("extra/awesome-one", "https://github.com/extra/awesome-one", 9, "", "main"),
                SourceInfo("extra/awesome-two", "https://github.com/extra/awesome-two", 8, "", "main"),
            ]

        def fetch_readme(self, source):
            fetched_readmes.append(source.full_name)
            return "- [CAD Paper](https://arxiv.org/abs/2601.00001)"

        def list_repo_files(self, source):
            return ["README.md"]

    monkeypatch.setattr("scripts.discover_sources.GitHubDiscoverer", FakeDiscoverer)

    fetch_awesome_source(
        {
            "research": {
                "keywords": ["CAD", "B-Rep", "CSG"],
                "sources": {"upstream_awesome": True},
                "upstream_awesome": {"repos": ["owner/awesome-cad"], "auto_discover": True},
                "auto_discover": {
                    "min_stars": 7,
                    "max_sources": 4,
                    "max_search_terms": 2,
                    "max_repos_to_fetch": 2,
                    "query_expansion": ["neural CAD"],
                    "search_interval_seconds": 0.5,
                    "core_interval_seconds": 0.1,
                    "request_timeout_seconds": 8,
                    "max_rate_limit_sleep_seconds": 30,
                },
            },
        }
    )

    assert created["search_interval_seconds"] == 0.5
    assert created["core_interval_seconds"] == 0.1
    assert created["request_timeout_seconds"] == 8
    assert created["max_rate_limit_sleep_seconds"] == 30
    assert discovered["max_search_terms"] == 2
    assert discovered["query_expansion"] == ["neural CAD"]
    assert fetched_readmes == ["owner/awesome-cad", "extra/awesome-one"]


def test_fetch_awesome_source_filters_non_paper_resource_links(monkeypatch):
    from scripts.discover_sources import SourceInfo
    from scripts.paper_sources import fetch_awesome_source

    class FakeDiscoverer:
        def __init__(self, **kwargs):
            pass

        def source_from_repo(self, repo):
            return SourceInfo(repo, f"https://github.com/{repo}", 10, "", "main")

        def fetch_readme(self, source):
            return "\n".join(
                [
                    "- [World Model Workshop](https://example.com/workshop)",
                    "- [Dreamer](https://arxiv.org/abs/1912.01603)",
                ]
            )

        def list_repo_files(self, source):
            return ["README.md"]

    monkeypatch.setattr("scripts.discover_sources.GitHubDiscoverer", FakeDiscoverer)

    papers = fetch_awesome_source(
        {
            "research": {
                "upstream_awesome": {
                    "repos": ["curated/awesome-world-models"],
                    "auto_discover": False,
                },
            }
        }
    )

    assert [paper["title"] for paper in papers] == ["Dreamer"]
