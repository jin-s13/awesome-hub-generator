from pathlib import Path
from urllib.error import HTTPError

import yaml

from scripts.paper_rank import enrich_paper_rank_scores, fetch_openalex_metadata_for_papers, rank_signal_components


def test_rank_signal_components_builds_explainable_scores():
    paper = {
        "title": "Text-to-CAD generation with parametric B-Rep programs",
        "abstract": (
            "We evaluate a CAD generation method with baselines, ablations, "
            "benchmark datasets, and released GitHub code."
        ),
        "tags": ["CAD generation", "B-Rep"],
        "links": {
            "paper": "https://arxiv.org/abs/2401.12345",
            "pdf": "https://arxiv.org/pdf/2401.12345",
            "code": "https://github.com/example/text-to-cad",
        },
        "score": {
            "total": 42.0,
            "keyword_scores": {"CAD": 9, "B-Rep": 8, "text-to-CAD": 10},
        },
        "analysis": {
            "methodology": "Uses a transformer decoder and evaluates against baselines.",
            "key_results": "Improves reconstruction accuracy on benchmark datasets.",
            "limitations": ["Does not handle complex assemblies."],
        },
        "year": 2024,
    }
    config = {
        "research": {
            "keywords": ["CAD", "B-Rep", "text-to-CAD"],
            "ranking": {
                "weights": {
                    "topical_relevance": 0.5,
                    "methodology_quality": 0.25,
                    "reproducibility": 0.25,
                }
            },
        }
    }

    components, applied_weights, read_first = rank_signal_components(
        paper,
        config,
        now_year=2026,
    )

    assert set(components) >= {
        "topical_relevance",
        "methodology_quality",
        "reproducibility",
    }
    assert components["topical_relevance"]["available"] is True
    assert components["reproducibility"]["value"] >= 80
    assert components["methodology_quality"]["value"] >= 70
    assert round(sum(applied_weights.values()), 6) == 1
    assert 0 <= read_first <= 100


def test_rank_signal_components_includes_chinese_explanations():
    paper = {
        "title": "3D interaction trace world model",
        "abstract": "Experiments compare baselines and report results.",
        "year": 2026,
        "tags": ["world model"],
        "links": {"paper": "https://arxiv.org/abs/2606.13769"},
        "score": {"keyword_scores": {"world model": 9}},
    }
    config = {"research": {"keywords": ["world model"]}}

    components, _, _ = rank_signal_components(paper, config, now_year=2026)

    for component in components.values():
        assert component["explanation_zh"]
        assert component["explanation_zh"] != component["explanation"]


def test_enrich_paper_rank_scores_preserves_existing_total_and_writes_yaml(tmp_path: Path):
    papers_path = tmp_path / "papers.yaml"
    papers = [
        {
            "id": "paper-a",
            "title": "CAD generation with code",
            "abstract": "We evaluate baselines and release code.",
            "year": 2024,
            "tags": ["CAD"],
            "links": {"paper": "https://arxiv.org/abs/2401.12345", "code": "https://github.com/example/repo"},
            "score": {"total": 31.5, "keyword_scores": {"CAD": 8}},
        },
        {
            "id": "paper-b",
            "title": "Unscored geometric modeling survey",
            "abstract": "A survey of geometric modeling.",
            "year": 2021,
            "tags": ["geometric modeling"],
            "links": {"paper": "https://example.com/paper"},
        },
    ]
    papers_path.write_text(yaml.dump(papers, allow_unicode=True, sort_keys=False), encoding="utf-8")

    updated = enrich_paper_rank_scores(
        papers_path,
        {"research": {"keywords": ["CAD", "geometric modeling"]}},
        now_year=2026,
    )

    saved = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    assert updated == 2
    assert saved[0]["score"]["total"] == 31.5
    assert "read_first_score" in saved[0]["score"]
    assert "components" in saved[0]["score"]
    assert saved[0]["score"]["ranking_profile"] == "paper_rank_lite_v1"
    assert saved[1]["score"]["read_first_score"] >= 0


def test_enrich_paper_rank_scores_adds_citation_graph_sensitivity_and_field_roles(tmp_path: Path):
    papers_path = tmp_path / "papers.yaml"
    papers = [
        {
            "id": "foundation",
            "title": "Foundation World Model",
            "abstract": "A benchmarked world model with baselines and ablations.",
            "year": 2022,
            "tags": ["world model", "benchmark"],
            "links": {"paper": "https://example.com/foundation", "code": "https://github.com/example/foundation"},
            "openalex": {
                "id": "https://openalex.org/W1",
                "cited_by_count": 180,
                "citation_normalized_percentile": 0.92,
                "referenced_works": [],
            },
            "score": {"keyword_scores": {"world model": 9}},
        },
        {
            "id": "bridge",
            "title": "Bridge World Model",
            "abstract": "Connects robot world models with video world models and reports metrics.",
            "year": 2025,
            "tags": ["world model", "robotics", "video"],
            "links": {"paper": "https://example.com/bridge"},
            "openalex": {
                "id": "https://openalex.org/W2",
                "cited_by_count": 42,
                "referenced_works": ["https://openalex.org/W1"],
            },
            "score": {"keyword_scores": {"world model": 8}},
        },
        {
            "id": "frontier",
            "title": "Frontier Action World Model",
            "abstract": "Recent action-conditioned world model with released code and evaluation.",
            "full_text": "The experiments include ablation, baseline comparison, metrics, limitations, and compute resources.",
            "year": 2026,
            "tags": ["world model", "action"],
            "links": {"paper": "https://example.com/frontier", "code": "https://github.com/example/frontier"},
            "openalex": {
                "id": "https://openalex.org/W3",
                "cited_by_count": 18,
                "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"],
            },
            "score": {"keyword_scores": {"world model": 10}},
        },
    ]
    papers_path.write_text(yaml.dump(papers, allow_unicode=True, sort_keys=False), encoding="utf-8")

    updated = enrich_paper_rank_scores(
        papers_path,
        {"research": {"keywords": ["world model"], "ranking": {"citation_graph": {"enabled": True}}}},
        now_year=2026,
    )

    saved = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    by_id = {paper["id"]: paper for paper in saved}
    assert updated == 3
    assert "citation_impact" in by_id["foundation"]["score"]["components"]
    assert by_id["foundation"]["score"]["components"]["citation_impact"]["value"] >= 90
    assert by_id["foundation"]["score"]["components"]["graph_prestige"]["available"] is True
    assert by_id["frontier"]["score"]["components"]["citation_velocity"]["available"] is True
    assert by_id["frontier"]["score"]["rank_sensitivity"]["rank_range"] >= 0
    assert by_id["frontier"]["score"]["rank_sensitivity"]["profiles"]
    assert "frontier" in by_id["frontier"]["score"]["field_roles"]
    assert "foundation" in by_id["foundation"]["score"]["field_roles"]
    assert any(
        evidence.get("span", {}).get("source") == "full_text"
        for evidence in by_id["frontier"]["score"]["components"]["methodology_quality"]["evidence"]
    )


def test_enrich_paper_rank_scores_can_fetch_openalex_metadata(tmp_path: Path, monkeypatch):
    papers_path = tmp_path / "papers.yaml"
    papers_path.write_text(
        yaml.dump(
            [
                {
                    "id": "paper-a",
                    "title": "Fetched Citation Paper",
                    "abstract": "A world model paper with experiments.",
                    "year": 2026,
                    "tags": ["world model"],
                    "links": {"paper": "https://arxiv.org/abs/2601.00001"},
                    "score": {"keyword_scores": {"world model": 9}},
                }
            ],
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    def fake_fetcher(papers, _config):
        assert papers[0]["title"] == "Fetched Citation Paper"
        return {
            "paper-a": {
                "id": "https://openalex.org/WFETCH",
                "cited_by_count": 12,
                "referenced_works": [],
                "citation_normalized_percentile": 0.7,
            }
        }

    monkeypatch.setattr("scripts.paper_rank.fetch_openalex_metadata_for_papers", fake_fetcher)

    enrich_paper_rank_scores(
        papers_path,
        {
            "research": {
                "keywords": ["world model"],
                "ranking": {"citation_graph": {"enabled": True, "fetch_openalex": True}},
            }
        },
        now_year=2026,
    )

    saved = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    assert saved[0]["openalex"]["id"] == "https://openalex.org/WFETCH"
    assert saved[0]["score"]["components"]["citation_impact"]["available"] is True


def test_fetch_openalex_metadata_sends_api_key_as_query_param(monkeypatch):
    captured_requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'{"results":[{"id":"https://openalex.org/W1",'
                b'"title":"A World Model Paper",'
                b'"cited_by_count":5,"referenced_works":[]}]}'
            )

    def fake_urlopen(request, timeout):
        captured_requests.append(request)
        return FakeResponse()

    monkeypatch.setattr("scripts.paper_rank.urllib.request.urlopen", fake_urlopen)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)

    results = fetch_openalex_metadata_for_papers(
        [{"id": "paper-a", "title": "A World Model Paper"}],
        {
            "research": {
                "ranking": {
                    "citation_graph": {
                        "api_key": "test-key",
                        "mailto": "reader@example.com",
                    }
                }
            }
        },
    )

    assert results["paper-a"]["id"] == "https://openalex.org/W1"
    assert "api_key=test-key" in captured_requests[0].full_url
    assert "mailto=reader%40example.com" in captured_requests[0].full_url
    assert "Authorization" not in dict(captured_requests[0].header_items())


def test_fetch_openalex_metadata_uses_mailto_env(monkeypatch):
    captured_requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'{"results":[{"id":"https://openalex.org/W1",'
                b'"title":"A World Model Paper",'
                b'"cited_by_count":5,"referenced_works":[]}]}'
            )

    def fake_urlopen(request, timeout):
        captured_requests.append(request)
        return FakeResponse()

    monkeypatch.setattr("scripts.paper_rank.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("OPENALEX_MAILTO", "reader@example.com")

    results = fetch_openalex_metadata_for_papers(
        [{"id": "paper-a", "title": "A World Model Paper"}],
        {"research": {"ranking": {"citation_graph": {}}}},
    )

    assert results["paper-a"]["id"] == "https://openalex.org/W1"
    assert "mailto=reader%40example.com" in captured_requests[0].full_url


def test_fetch_openalex_metadata_uses_arxiv_landing_page_without_version(monkeypatch):
    captured_requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'{"results":[{"id":"https://openalex.org/WARXIV",'
                b'"title":"Agentic World Modeling: Foundations, Capabilities, Laws, and Beyond",'
                b'"cited_by_count":3,"referenced_works":[]}]}'
            )

    def fake_urlopen(request, timeout):
        captured_requests.append(request)
        return FakeResponse()

    monkeypatch.setattr("scripts.paper_rank.urllib.request.urlopen", fake_urlopen)

    results = fetch_openalex_metadata_for_papers(
        [
            {
                "id": "agentic",
                "title": "Agentic World Modeling: Foundations, Capabilities, Laws, and Beyond",
                "links": {"paper": "https://arxiv.org/abs/2604.22748v3"},
            }
        ],
        {"research": {"ranking": {"citation_graph": {"workers": 1}}}},
    )

    assert results["agentic"]["id"] == "https://openalex.org/WARXIV"
    assert "filter=locations.landing_page_url" in captured_requests[0].full_url
    assert "2604.22748v3" not in captured_requests[0].full_url
    assert "2604.22748" in captured_requests[0].full_url


def test_fetch_openalex_metadata_rejects_title_mismatch(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'{"results":[{"id":"https://openalex.org/WWRONG",'
                b'"title":"Not All Points Are Equal: Uncertainty-Aware 4D LiDAR Scene Synthesis",'
                b'"cited_by_count":99,"referenced_works":[]}]}'
            )

    monkeypatch.setattr("scripts.paper_rank.urllib.request.urlopen", lambda request, timeout: FakeResponse())

    results = fetch_openalex_metadata_for_papers(
        [
            {
                "id": "agentic",
                "title": "Agentic World Modeling: Foundations, Capabilities, Laws, and Beyond",
                "links": {"paper": "https://arxiv.org/abs/2604.22748v3"},
            }
        ],
        {"research": {"ranking": {"citation_graph": {"workers": 1}}}},
    )

    assert results == {}


def test_fetch_openalex_metadata_stops_on_rate_limit(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        raise HTTPError("", 429, "Too Many Requests", None, None)

    monkeypatch.setattr("scripts.paper_rank.urllib.request.urlopen", fake_urlopen)

    results = fetch_openalex_metadata_for_papers(
        [
            {"id": "paper-a", "title": "A World Model Paper"},
            {"id": "paper-b", "title": "Another World Model Paper"},
        ],
        {"research": {"ranking": {"citation_graph": {"workers": 10, "timeout": 1}}}},
    )

    assert results == {}
    assert len(calls) == 1
