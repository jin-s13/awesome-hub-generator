"""Tests for read-first deep research queue generation."""

from pathlib import Path

import yaml

from scripts.deep_research_queue import build_deep_research_queue


def test_build_deep_research_queue_writes_manifest_and_report(tmp_path: Path):
    data_dir = tmp_path / "data"
    resource_dir = tmp_path / "resource"
    data_dir.mkdir()
    data_dir.joinpath("papers.yaml").write_text(
        yaml.dump(
            [
                {
                    "id": "paper-high",
                    "title": "High Priority Paper",
                    "year": 2026,
                    "links": {"paper": "https://arxiv.org/abs/2601.00001"},
                    "score": {
                        "total": 30,
                        "read_first_score": 88.5,
                        "components": {
                            "topical_relevance": {"value": 95, "explanation": "strong topic fit"},
                            "reproducibility": {"value": 80, "explanation": "code available"},
                        },
                    },
                },
                {
                    "id": "paper-low",
                    "title": "Low Priority Paper",
                    "year": 2024,
                    "links": {"paper": "https://arxiv.org/abs/2401.00001"},
                    "score": {"read_first_score": 42},
                },
            ],
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    count = build_deep_research_queue(
        data_dir,
        {
            "research": {
                "deep_research": {
                    "enabled": True,
                    "min_read_first_score": 75,
                    "max_papers_per_run": 1,
                }
            }
        },
        resource_dir=resource_dir,
        generated_at="2026-06-26T00:00:00Z",
    )

    manifest = yaml.safe_load((data_dir / "research_runs.yaml").read_text(encoding="utf-8"))
    papers = yaml.safe_load((data_dir / "papers.yaml").read_text(encoding="utf-8"))
    report = resource_dir / "paper-high" / "research.md"

    assert count == 1
    assert manifest["schema_version"] == "awesome-hub.researchRuns.v1"
    assert manifest["runs"][0]["workflow"] == "deep_research"
    assert manifest["runs"][0]["status"] == "planned"
    assert manifest["runs"][0]["papers"][0]["id"] == "paper-high"
    assert manifest["runs"][0]["papers"][0]["verification"]["state"] == "not_checked"
    assert manifest["runs"][0]["artifacts"][0]["path"] == "resource/paper-high/research.md"
    assert manifest["runs"][0]["papers"][0]["critique"]["concerns"]
    assert manifest["runs"][0]["papers"][0]["next_actions"]
    assert report.exists()
    report_text = report.read_text(encoding="utf-8")
    assert "High Priority Paper" in report_text
    assert "## Critique" in report_text
    assert "## Next Research Actions" in report_text
    assert "## Claim Extraction" in report_text
    assert "## Evidence and Verification" in report_text
    assert "datasets, baselines, metrics" in report_text
    assert "source locations" in report_text
    assert papers[0]["deep_research"]["status"] == "planned"
    assert "deep_research" not in papers[1]


def test_build_deep_research_queue_respects_disabled_config(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.joinpath("papers.yaml").write_text("[]\n", encoding="utf-8")

    count = build_deep_research_queue(
        data_dir,
        {"research": {"deep_research": {"enabled": False}}},
        generated_at="2026-06-26T00:00:00Z",
    )

    assert count == 0
    assert not (data_dir / "research_runs.yaml").exists()
