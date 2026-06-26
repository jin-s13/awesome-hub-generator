"""Tests for taxonomy-driven literature survey generation."""

from pathlib import Path

import yaml

from scripts.literature_survey import build_literature_surveys


def test_build_literature_surveys_groups_taxonomy_and_score_components(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.joinpath("papers.yaml").write_text(
        yaml.dump(
            [
                {
                    "id": "method-1",
                    "title": "A Strong World Model Method",
                    "year": 2026,
                    "paper_type": ["method"],
                    "tags": ["world model", "video"],
                    "analysis": {
                        "innovations": ["Introduces trace-conditioned world modeling for robot policies"],
                        "methodology": "Uses trace prediction as a compact representation for planning.",
                        "key_results": "Improves trajectory prediction over video-token baselines.",
                        "limitations": ["Depends on reliable trace extraction"],
                    },
                    "analysis_cn": {
                        "innovations": ["提出用于机器人策略的轨迹条件世界建模"],
                        "methodology": "使用轨迹预测作为规划的紧凑表示。",
                        "key_results": "相比视频 token 基线提升了轨迹预测效果。",
                        "limitations": ["依赖可靠的轨迹提取"],
                    },
                    "score": {
                        "read_first_score": 91,
                        "components": {
                            "topical_relevance": {"value": 95},
                            "reproducibility": {"value": 70},
                        },
                    },
                },
                {
                    "id": "benchmark-1",
                    "title": "WorldBench",
                    "year": 2025,
                    "paper_type": ["benchmark"],
                    "tags": ["benchmark", "dataset"],
                    "score": {
                        "read_first_score": 83,
                        "components": {
                            "topical_relevance": {"value": 88},
                            "reproducibility": {"value": 90},
                        },
                    },
                },
                {
                    "id": "method-2",
                    "title": "A Lower Ranked Method",
                    "year": 2024,
                    "paper_type": ["method"],
                    "tags": ["world model"],
                    "analysis": {
                        "innovations": ["Adds latent dynamics ablations for planning"],
                        "methodology": "Compares latent dynamics variants under the same planner.",
                        "key_results": "Shows planning quality is sensitive to dynamics representation.",
                        "limitations": ["Small benchmark coverage"],
                    },
                    "score": {"read_first_score": 55},
                },
            ],
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    count = build_literature_surveys(
        data_dir,
        {
            "research": {
                "taxonomy": {
                    "paper_types": [
                        {"label": "method", "description": "New methods and algorithms"},
                        {"label": "benchmark", "description": "Datasets and evaluation protocols"},
                    ]
                }
            }
        },
        generated_at="2026-06-26T00:00:00Z",
        use_llm=False,
    )

    surveys = yaml.safe_load((data_dir / "surveys.yaml").read_text(encoding="utf-8"))

    assert count == 2
    assert surveys["schema_version"] == "awesome-hub.surveys.v1"
    assert [topic["id"] for topic in surveys["topics"]] == ["method", "benchmark"]
    assert surveys["topics"][0]["paper_count"] == 2
    assert surveys["topics"][0]["top_papers"][0]["id"] == "method-1"
    assert surveys["topics"][0]["component_averages"]["topical_relevance"] == 95
    assert surveys["topics"][0]["related_work_outline"][0].startswith("Mainstream direction:")
    assert "trace-conditioned world modeling" in surveys["topics"][0]["related_work_outline"][0]
    assert surveys["topics"][0]["related_work_outline"][1].startswith("Shared research pattern:")
    assert "Improves trajectory prediction" in surveys["topics"][0]["related_work_outline"][1]
    assert surveys["topics"][0]["related_work_outline"][2].startswith("Key differences:")
    assert surveys["topics"][0]["related_work_outline"][3].startswith("Trend evolution:")
    assert surveys["topics"][0]["related_work_outline"][4].startswith("Open questions:")
    assert "Depends on reliable trace extraction" in surveys["topics"][0]["related_work_outline"][4]
    assert surveys["topics"][0]["label_zh"] == "方法"
    assert "新方法和算法" in surveys["topics"][0]["description_zh"]
    assert surveys["topics"][0]["related_work_outline_zh"][0].startswith("主流方向：")
    assert "轨迹条件世界建模" in surveys["topics"][0]["related_work_outline_zh"][0]
    assert surveys["topics"][0]["related_work_outline_zh"][1].startswith("研究共性：")
    assert "相比视频 token 基线提升了轨迹预测效果" in surveys["topics"][0]["related_work_outline_zh"][1]
    assert surveys["topics"][1]["top_tags"] == ["benchmark", "dataset"]
    assert surveys["topics"][1]["label_zh"] == "基准"
