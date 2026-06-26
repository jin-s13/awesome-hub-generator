from pathlib import Path

import yaml

from scripts.paper_rank import enrich_paper_rank_scores, rank_signal_components


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
