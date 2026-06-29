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
    review = surveys["topics"][0]["literature_review"]
    review_zh = surveys["topics"][0]["literature_review_zh"]
    assert review["scope_methodology"]
    assert review["line_of_work_matrix"]
    assert review["consensus"]
    assert review["disagreements"]
    assert surveys["topics"][0]["literature_review"]["timeline"]
    assert surveys["topics"][0]["literature_review"]["references"][0]["id"] == "method-1"
    assert review_zh["研究路线矩阵"]
    assert review_zh["共识"]
    assert "trace prediction" not in " ".join(review["consensus"])
    assert "world model, video" not in " ".join(review["disagreements"])
    assert any(item["路线"] == "方法表示与目标设计" for item in review_zh["研究路线矩阵"])
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


def test_literature_review_synthesizes_lines_of_work_instead_of_tags(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.joinpath("papers.yaml").write_text(
        yaml.dump(
            [
                {
                    "id": "robot-latent",
                    "title": "Latent Action World Models for Robot Planning",
                    "year": 2026,
                    "paper_type": ["method"],
                    "tags": ["RO", "world model", "CV"],
                    "analysis": {
                        "innovations": ["Learns compact latent states for action-conditioned robot planning"],
                        "methodology": "Predicts latent states under candidate actions and uses them inside a planner.",
                        "key_results": "Planning success improves on manipulation tasks against video-token baselines.",
                        "limitations": ["Only tested on one manipulation benchmark"],
                    },
                    "analysis_cn": {
                        "innovations": ["学习用于动作条件机器人规划的紧凑潜状态"],
                        "methodology": "在候选动作下预测潜状态，并把预测结果接入规划器。",
                        "key_results": "在操作任务中相对视频 token 基线提升规划成功率。",
                        "limitations": ["只在一个操作基准上测试"],
                    },
                    "score": {"read_first_score": 90},
                },
                {
                    "id": "driving-control",
                    "title": "Closed-Loop Driving World Model",
                    "year": 2026,
                    "paper_type": ["method"],
                    "tags": ["AI", "world models", "autonomous driving"],
                    "analysis": {
                        "innovations": ["Uses action-conditioned generation for closed-loop driving simulation"],
                        "methodology": "Rolls out controllable future scenes from ego actions and simulator state.",
                        "key_results": "Improves closed-loop robustness in driving simulation.",
                        "limitations": ["Limited evidence outside the driving simulator"],
                    },
                    "analysis_cn": {
                        "innovations": ["面向闭环驾驶仿真使用动作条件生成"],
                        "methodology": "基于自车动作和仿真状态滚动生成可控未来场景。",
                        "key_results": "提升驾驶仿真中的闭环鲁棒性。",
                        "limitations": ["驾驶仿真之外的证据有限"],
                    },
                    "score": {"read_first_score": 86},
                },
                {
                    "id": "eval-suite",
                    "title": "World Model Evaluation Suite",
                    "year": 2026,
                    "paper_type": ["method"],
                    "tags": ["benchmark", "world model"],
                    "analysis": {
                        "innovations": ["Defines stress tests for prediction, controllability, and decision utility"],
                        "methodology": "Builds benchmark tasks with baselines, metrics, and failure cases.",
                        "key_results": "Shows pixel fidelity and decision utility can disagree.",
                        "limitations": ["Benchmark coverage is still narrow"],
                    },
                    "analysis_cn": {
                        "innovations": ["定义预测、可控性和决策效用压力测试"],
                        "methodology": "构建包含基线、指标和失败案例的基准任务。",
                        "key_results": "显示像素保真度和决策效用可能不一致。",
                        "limitations": ["基准覆盖仍然较窄"],
                    },
                    "score": {"read_first_score": 82},
                },
            ],
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    build_literature_surveys(
        data_dir,
        {"research": {"taxonomy": {"paper_types": [{"label": "method", "description": "New methods and algorithms"}]}}},
        generated_at="2026-06-26T00:00:00Z",
        use_llm=False,
    )

    topic = yaml.safe_load((data_dir / "surveys.yaml").read_text(encoding="utf-8"))["topics"][0]
    review = topic["literature_review"]
    review_zh = topic["literature_review_zh"]

    assert {item["line"] for item in review["line_of_work_matrix"]} >= {
        "Method representation and objective design",
        "Planning and action-interface methods",
        "Method evidence and ablation protocol",
    }
    assert "RO" not in " ".join(review["disagreements"])
    assert "CV" not in " ".join(review["disagreements"])
    assert "tag" not in " ".join(review["disagreements"]).lower()
    assert "RO, world model, CV" not in " ".join(review["disagreements"])
    assert "Latent Action World Models for Robot Planning" not in " ".join(review["consensus"])
    assert "研究路线" in "".join(review_zh.keys())
    assert "标签" not in " ".join(review_zh["分歧"])


def test_literature_review_uses_topic_specific_research_lines(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.joinpath("papers.yaml").write_text(
        yaml.dump(
            [
                {
                    "id": "method-repr",
                    "title": "Latent Objective Design for World Models",
                    "year": 2026,
                    "paper_type": ["method"],
                    "tags": ["world model", "latent"],
                    "analysis": {
                        "innovations": ["Introduces a latent training objective for compact predictive state learning"],
                        "methodology": "Compares representation objectives and ablations under a shared planner.",
                        "key_results": "Representation choice changes downstream planning success.",
                        "limitations": ["Limited evidence beyond the chosen objective family"],
                    },
                    "analysis_cn": {
                        "innovations": ["提出用于紧凑预测状态学习的潜变量训练目标"],
                        "methodology": "在共享规划器下比较表示目标和消融。",
                        "key_results": "表示选择会改变下游规划成功率。",
                        "limitations": ["所选目标族之外的证据有限"],
                    },
                    "score": {"read_first_score": 90},
                },
                {
                    "id": "application-robot",
                    "title": "World Models for Robot Manipulation",
                    "year": 2026,
                    "paper_type": ["application"],
                    "tags": ["robotics", "manipulation", "world model"],
                    "analysis": {
                        "innovations": ["Adapts world models to robotic manipulation tasks with contact-rich dynamics"],
                        "methodology": "Evaluates policies on manipulation tasks with object interaction and domain shifts.",
                        "key_results": "Robot task success improves in manipulation scenarios.",
                        "limitations": ["Transfer across robot embodiments remains unclear"],
                    },
                    "analysis_cn": {
                        "innovations": ["把世界模型适配到具有接触动力学的机器人操作任务"],
                        "methodology": "在包含物体交互和领域变化的操作任务上评测策略。",
                        "key_results": "机器人操作场景中的任务成功率提升。",
                        "limitations": ["跨机器人本体迁移仍不清楚"],
                    },
                    "score": {"read_first_score": 88},
                },
                {
                    "id": "system-stack",
                    "title": "Open-Source Real-Time World Model System",
                    "year": 2026,
                    "paper_type": ["system"],
                    "tags": ["system", "open-source", "real-time"],
                    "analysis": {
                        "innovations": ["Builds an open-source real-time world model stack"],
                        "methodology": "Integrates data ingestion, training, inference, and deployment into a runnable pipeline.",
                        "key_results": "The system supports reproducible end-to-end experiments.",
                        "limitations": ["External deployment validation is limited"],
                    },
                    "analysis_cn": {
                        "innovations": ["构建开源实时世界模型系统栈"],
                        "methodology": "把数据接入、训练、推理和部署集成为可运行流水线。",
                        "key_results": "系统支持可复现的端到端实验。",
                        "limitations": ["外部部署验证有限"],
                    },
                    "score": {"read_first_score": 86},
                },
            ],
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    build_literature_surveys(
        data_dir,
        {
            "research": {
                "taxonomy": {
                    "paper_types": [
                        {"label": "method", "description": "New methods and algorithms"},
                        {"label": "application", "description": "Domain applications"},
                        {"label": "system", "description": "Runnable systems and infrastructure"},
                    ]
                }
            }
        },
        generated_at="2026-06-26T00:00:00Z",
        use_llm=False,
    )

    topics = {topic["id"]: topic for topic in yaml.safe_load((data_dir / "surveys.yaml").read_text(encoding="utf-8"))["topics"]}

    method_lines = {item["line"] for item in topics["method"]["literature_review"]["line_of_work_matrix"]}
    application_lines = {item["line"] for item in topics["application"]["literature_review"]["line_of_work_matrix"]}
    system_lines = {item["line"] for item in topics["system"]["literature_review"]["line_of_work_matrix"]}

    assert "Method representation and objective design" in method_lines
    assert "Embodied and domain task transfer" in application_lines
    assert "Runnable pipelines and deployment stacks" in system_lines
    assert method_lines != application_lines
    assert method_lines != system_lines
    assert application_lines != system_lines
    assert topics["method"]["literature_review"]["consensus"] != topics["application"]["literature_review"]["consensus"]
    assert topics["application"]["literature_review_zh"]["研究路线矩阵"][0]["路线"] == "具身与领域任务迁移"
    assert topics["system"]["literature_review_zh"]["研究路线矩阵"][0]["路线"] == "可运行流水线与部署栈"
