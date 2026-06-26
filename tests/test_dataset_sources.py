"""Tests for dataset discovery and derivation."""

from pathlib import Path

import yaml

from scripts.dataset_sources import (
    associate_datasets_with_papers,
    fetch_hf_datasets,
    merge_dataset_entries,
    sync_datasets,
)


def test_fetch_hf_datasets_maps_search_results(monkeypatch):
    calls = []

    def fake_get_json(url):
        calls.append(url)
        return [
            {
                "id": "world-model-lab/worldbench",
                "description": "Benchmark data for world model evaluation.",
                "downloads": 1234,
                "likes": 42,
                "tags": ["world-model", "benchmark"],
                "lastModified": "2026-01-02T00:00:00.000Z",
                "cardData": {
                    "paper": "https://arxiv.org/abs/2601.00001",
                    "license": "mit",
                },
            }
        ]

    monkeypatch.setattr("scripts.dataset_sources._http_get_json", fake_get_json)

    datasets = fetch_hf_datasets(
        {
            "research": {
                "keywords": ["world model"],
                "datasets": {"huggingface_limit_per_keyword": 5},
            },
            "website": {"sections": {"datasets": True}},
        }
    )

    assert "search=world+model" in calls[0]
    assert datasets == [
        {
            "id": "hf-world-model-lab-worldbench",
            "name": "world-model-lab/worldbench",
            "year": 2026,
            "description": "Benchmark data for world model evaluation.",
            "tags": ["world-model", "benchmark"],
            "links": {
                "huggingface": "https://huggingface.co/datasets/world-model-lab/worldbench",
                "paper": "https://arxiv.org/abs/2601.00001",
            },
            "sources": [{"repo": "huggingface-datasets", "category": "dataset"}],
            "notes": "downloads=1234, likes=42, license=mit",
        }
    ]


def test_sync_datasets_derives_benchmark_and_dataset_mention_papers(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "papers.yaml").write_text(
        """
- id: bench-1
  title: "WorldBench: A Benchmark for World Models"
  abstract: "We introduce a benchmark for world model evaluation."
  year: 2026
  paper_type: [benchmark]
  tags: [benchmark, world model]
  links:
    paper: https://arxiv.org/abs/2601.00001
- id: dataset-1
  title: "A Large Dataset for Interactive World Models"
  abstract: "This dataset contains video action trajectories."
  year: 2025
  paper_type: [method]
  tags: [world model]
  links:
    paper: https://arxiv.org/abs/2501.00001
- id: method-2
  title: "AdaptiveLoad: Faster World Model Training"
  abstract: "We improve throughput when training on large video datasets and benchmark against baselines."
  year: 2026
  paper_type: [method]
  tags: [world model, data loading]
  links:
    paper: https://arxiv.org/abs/2602.00001
""",
        encoding="utf-8",
    )
    (data_dir / "datasets.yaml").write_text("[]\n", encoding="utf-8")

    result = sync_datasets(
        data_dir,
        {
            "research": {"datasets": {"huggingface": False}},
            "website": {"sections": {"datasets": True}},
        },
    )

    datasets = yaml.safe_load((data_dir / "datasets.yaml").read_text(encoding="utf-8")) or []
    assert result["derived_from_papers"] == 2
    assert [item["name"] for item in datasets] == [
        "WorldBench",
        "A Large Dataset for Interactive World Models",
    ]
    assert "category" not in datasets[0]
    assert "type" not in datasets[0]
    assert datasets[0]["links"]["paper"] == "https://arxiv.org/abs/2601.00001"


def test_associate_datasets_with_papers_adds_related_papers():
    datasets = [
        {
            "name": "world-model-lab/worldbench",
            "links": {"huggingface": "https://huggingface.co/datasets/world-model-lab/worldbench"},
            "sources": [{"repo": "huggingface-datasets"}],
        }
    ]
    papers = [
        {
            "id": "paper-1",
            "title": "WorldBench: A Benchmark for World Models",
            "abstract": "We evaluate on the WorldBench dataset.",
            "links": {"paper": "https://arxiv.org/abs/2601.00001"},
        }
    ]

    associated = associate_datasets_with_papers(datasets, papers)

    assert associated[0]["links"]["paper"] == "https://arxiv.org/abs/2601.00001"
    assert associated[0]["related_papers"] == [
        {
            "id": "paper-1",
            "title": "WorldBench: A Benchmark for World Models",
            "url": "https://arxiv.org/abs/2601.00001",
        }
    ]


def test_merge_dataset_entries_preserves_manual_entry_and_dedupes_hf_url():
    existing = [
        {
            "name": "Manual WorldBench",
            "links": {"huggingface": "https://huggingface.co/datasets/world-model-lab/worldbench"},
            "description": "Curated by hand.",
        }
    ]
    incoming = [
        {
            "name": "world-model-lab/worldbench",
            "links": {"huggingface": "https://huggingface.co/datasets/world-model-lab/worldbench"},
            "description": "Fetched from HF.",
        }
    ]

    merged, added = merge_dataset_entries(existing, incoming)

    assert added == 0
    assert merged == existing
