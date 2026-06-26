"""Tests for reclassifying existing papers with the configured taxonomy."""

from scripts.reclassify_paper_types import reclassify_papers


def test_reclassify_papers_updates_paper_type_tags_and_dimensions():
    papers = [
        {
            "id": "p1",
            "title": "World Model Benchmark",
            "abstract": "A benchmark for video world models.",
            "tags": ["old"],
            "paper_type": ["method"],
        }
    ]
    research = {
        "taxonomy": {
            "paper_types": [{"label": "benchmark", "description": "Benchmark papers"}],
            "dimensions": [{"name": "tasks", "description": "tasks"}],
        },
        "relevance_criteria": {"include": ["world models"], "exclude": []},
    }

    calls = []

    def fake_classify(title, abstract, categories, research_context, taxonomy, relevance_criteria):
        calls.append((title, research_context, taxonomy, relevance_criteria))
        return {
            "paper_type": ["benchmark"],
            "tags": ["world-model", "evaluation"],
            "tasks": ["video prediction"],
            "relevant": True,
        }

    updated, rejected = reclassify_papers(
        papers,
        research,
        project_description="World model hub",
        classify_func=fake_classify,
    )

    assert updated == 1
    assert rejected == 0
    assert papers[0]["paper_type"] == ["benchmark"]
    assert papers[0]["tags"] == ["world-model", "evaluation"]
    assert papers[0]["tasks"] == ["video prediction"]
    assert "category" not in papers[0]
    assert calls[0][1] == "World model hub"
