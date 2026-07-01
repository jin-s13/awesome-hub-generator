from pathlib import Path

import yaml

from scripts.literature_survey import build_literature_surveys
from scripts.taxonomy_discovery import assign_papers_to_taxonomy, build_taxonomy


def test_build_taxonomy_uses_configured_nodes_and_source_headings(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.joinpath("papers.yaml").write_text(
        yaml.dump(
            [
                {
                    "id": "memory-agent",
                    "title": "A Memory System for Self-Improving Agents",
                    "abstract": "The agent improves by storing reusable memories and skills.",
                    "tags": ["memory", "skill library"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    count = build_taxonomy(
        data_dir,
        {
            "research": {
                "taxonomy_discovery": {
                    "enabled": True,
                    "nodes": [
                        {
                            "id": "agent_optimization",
                            "label": "Agent Optimization",
                            "children": [{"id": "single_agent_optimization", "label": "Single-Agent Optimization"}],
                        }
                    ],
                    "source_headings": [
                        "Memory Systems",
                        "Agent Safety and Guardrails",
                    ],
                }
            }
        },
        generated_at="2026-06-30T00:00:00Z",
        use_llm=False,
    )

    taxonomy = yaml.safe_load((data_dir / "taxonomy.yaml").read_text(encoding="utf-8"))

    assert count == 4
    assert taxonomy["schema_version"] == "awesome-hub.taxonomy.v1"
    assert taxonomy["nodes"][0]["id"] == "agent_optimization"
    assert taxonomy["nodes"][0]["children"][0]["id"] == "single_agent_optimization"
    assert [node["id"] for node in taxonomy["nodes"][1:]] == ["memory_systems", "agent_safety_and_guardrails"]


def test_assign_papers_to_taxonomy_writes_primary_secondary_and_evidence(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.joinpath("taxonomy.yaml").write_text(
        yaml.dump(
            {
                "schema_version": "awesome-hub.taxonomy.v1",
                "nodes": [
                    {
                        "id": "agent_optimization",
                        "label": "Agent Optimization",
                        "children": [
                            {
                                "id": "single_agent_optimization",
                                "label": "Single-Agent Optimization",
                                "description": "self-improving single agent behavior",
                                "keywords": ["self-improving", "single agent"],
                            }
                        ],
                    },
                    {
                        "id": "infrastructure_protocols",
                        "label": "Infrastructure and Protocols",
                        "children": [
                            {
                                "id": "memory_systems",
                                "label": "Memory Systems",
                                "description": "agent memory and skill libraries",
                                "keywords": ["memory", "skill library"],
                            }
                        ],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    data_dir.joinpath("papers.yaml").write_text(
        yaml.dump(
            [
                {
                    "id": "memory-agent",
                    "title": "A Memory System for Self-Improving Agents",
                    "abstract": "The agent improves by storing reusable memories in a skill library.",
                    "tags": ["memory", "skill library"],
                    "paper_type": ["method"],
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    updated = assign_papers_to_taxonomy(data_dir, {}, use_llm=False)
    papers = yaml.safe_load((data_dir / "papers.yaml").read_text(encoding="utf-8"))
    mapping = yaml.safe_load((data_dir / "paper_taxonomy.yaml").read_text(encoding="utf-8"))

    assert updated == 1
    assert papers[0]["taxonomy"]["primary"] == "infrastructure_protocols.memory_systems"
    assert "agent_optimization.single_agent_optimization" in papers[0]["taxonomy"]["secondary"]
    assert papers[0]["taxonomy"]["confidence"] > 0
    assert "memory" in papers[0]["taxonomy"]["evidence"].lower()
    assert mapping["assignments"][0]["paper_id"] == "memory-agent"


def test_literature_surveys_group_by_taxonomy_assignment(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.joinpath("taxonomy.yaml").write_text(
        yaml.dump(
            {
                "schema_version": "awesome-hub.taxonomy.v1",
                "nodes": [
                    {"id": "memory_systems", "label": "Memory Systems", "description": "Agent memory"},
                    {"id": "tool_use", "label": "Tool Use", "description": "Tool learning"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    data_dir.joinpath("papers.yaml").write_text(
        yaml.dump(
            [
                {
                    "id": "memory-agent",
                    "title": "A Memory System for Agents",
                    "year": 2026,
                    "paper_type": ["method"],
                    "tags": ["memory"],
                    "taxonomy": {"primary": "memory_systems", "secondary": [], "confidence": 0.8},
                    "score": {"read_first_score": 90},
                },
                {
                    "id": "tool-agent",
                    "title": "Tool Learning for Agents",
                    "year": 2026,
                    "paper_type": ["method"],
                    "tags": ["tool"],
                    "taxonomy": {"primary": "tool_use", "secondary": [], "confidence": 0.8},
                    "score": {"read_first_score": 80},
                },
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    count = build_literature_surveys(data_dir, {"research": {}}, generated_at="2026-06-30T00:00:00Z", use_llm=False)
    surveys = yaml.safe_load((data_dir / "surveys.yaml").read_text(encoding="utf-8"))

    assert count == 2
    assert [topic["id"] for topic in surveys["topics"]] == ["memory_systems", "tool_use"]
    assert surveys["topics"][0]["top_papers"][0]["id"] == "memory-agent"


def test_literature_surveys_raise_when_llm_synthesis_fails(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_dir.joinpath("papers.yaml").write_text(
        yaml.dump(
            [
                {
                    "id": "method-1",
                    "title": "Self Improving Agent",
                    "year": 2026,
                    "paper_type": ["method"],
                    "tags": ["agent"],
                    "score": {"read_first_score": 90},
                }
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("scripts.literature_survey._llm_topic_synthesis", lambda topic, papers, tags: None)

    import pytest

    with pytest.raises(RuntimeError, match="LLM topic synthesis failed"):
        build_literature_surveys(
            data_dir,
            {"research": {"taxonomy": {"paper_types": [{"label": "method", "description": "Methods"}]}}},
            generated_at="2026-06-30T00:00:00Z",
            use_llm=True,
        )
