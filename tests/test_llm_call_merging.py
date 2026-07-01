"""Tests for reducing duplicate LLM calls in paper enrichment flows."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
RESEARCHER_SRC = ROOT / "arxiv-daily-researcher" / "src"
if str(RESEARCHER_SRC) not in sys.path:
    sys.path.insert(0, str(RESEARCHER_SRC))


def test_researcher_scoring_returns_abstract_translation(monkeypatch):
    from agents.analysis_agent import AnalysisAgent

    agent = AnalysisAgent.__new__(AnalysisAgent)
    calls = {"cheap": 0}

    def fake_call(prompt: str) -> str:
        calls["cheap"] += 1
        return json.dumps(
            {
                "keyword_scores": {"CAD": 8},
                "expert_authors_found": [],
                "reasoning": "Relevant to CAD generation.",
                "tldr": "Generates CAD models from text.",
                "abstract_cn": "本文从文本生成 CAD 模型。",
                "extracted_keywords": ["CAD", "text-to-CAD"],
            }
        )

    monkeypatch.setattr(agent, "_call_cheap_llm", fake_call)

    result = agent.score_paper_with_keywords(
        title="Text-to-CAD",
        authors="A. Researcher",
        abstract="We generate CAD models from text.",
        keywords_dict={"CAD": 1.0},
    )

    assert calls["cheap"] == 1
    assert result.abstract_cn == "本文从文本生成 CAD 模型。"


def test_researcher_cheap_llm_falls_back_when_json_mode_is_unsupported(monkeypatch):
    import config
    from agents.analysis_agent import AnalysisAgent

    monkeypatch.setattr(config.settings, "RETRY_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(config.settings, "RETRY_MIN_WAIT", 0)
    monkeypatch.setattr(config.settings, "RETRY_MAX_WAIT", 0)
    monkeypatch.setattr(config.settings, "TOKEN_TRACKING_ENABLED", False)

    agent = AnalysisAgent.__new__(AnalysisAgent)
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "response_format" in kwargs:
                raise RuntimeError("response_format.type json_object is not supported by this model")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
                usage=None,
            )

    agent.cheap_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    result = agent._call_cheap_llm("Return JSON")

    assert result == '{"ok": true}'
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


def test_combined_chinese_generation_uses_one_llm_call(monkeypatch):
    monkeypatch.delenv("SMART_MODEL_NAME", raising=False)
    from scripts import generate_interpretations as gi

    calls = {"llm": 0}

    def fake_llm_chat(*args, **kwargs):
        calls["llm"] += 1
        return json.dumps(
            {
                "title_cn": "文本到 CAD",
                "abstract_cn": "本文从文本生成 CAD 模型。",
                "tldr_cn": "从文本生成 CAD 模型。",
                "analysis_cn": {
                    "innovations": ["联合建模"],
                    "methodology": "使用生成模型。",
                    "key_results": "提升 CAD 生成质量。",
                    "limitations": ["数据有限"],
                    "tech_stack": ["Transformer"],
                },
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(gi, "_llm_chat", fake_llm_chat)

    result = gi.generate_chinese_fields(
        title="Text-to-CAD",
        abstract="We generate CAD models from text.",
        tldr_en="Generates CAD models from text.",
        analysis={
            "innovations": ["Joint modeling"],
            "methodology": "Uses a generative model.",
            "key_results": "Improves CAD generation quality.",
            "limitations": ["Limited data"],
            "tech_stack": ["Transformer"],
        },
    )

    assert calls["llm"] == 1
    assert result["title_cn"] == "文本到 CAD"
    assert result["tldr_cn"] == "从文本生成 CAD 模型。"
    assert result["analysis_cn"]["limitations"] == ["数据有限"]


def test_llm_call_once_passes_configured_timeout(monkeypatch):
    from scripts import generate_interpretations as gi
    from scripts.llm_cache import LLMCallResult

    seen = {}

    def fake_call_openai_responses(**kwargs):
        seen.update(kwargs)
        return LLMCallResult.from_text("ok")

    monkeypatch.setattr(gi, "API_KEY", "test-key")
    monkeypatch.setattr(gi, "call_openai_responses", fake_call_openai_responses)

    result = gi._llm_call_once(
        [{"role": "user", "content": "Hi"}],
        "test-model",
        128,
        timeout=240,
    )

    assert result.text == "ok"
    assert seen["timeout"] == 240
    assert seen["model"] == "test-model"


def test_paper_needs_chinese_fields_when_only_tldr_or_analysis_is_missing():
    from scripts import generate_interpretations as gi

    paper = {
        "title": "World Model Benchmark",
        "abstract": "A benchmark for world models.",
        "title_cn": "世界模型基准",
        "abstract_cn": "一个世界模型基准。",
        "tldr": "Benchmarks world models.",
        "analysis": {"methodology": "Evaluates models."},
    }

    assert gi.paper_needs_chinese_fields(paper)


def test_deep_analysis_prompt_uses_researcher_style_extraction(monkeypatch):
    from scripts import generate_interpretations as gi

    seen = {}

    def fake_llm_chat(messages, *args, **kwargs):
        seen["prompt"] = messages[0]["content"]
        return json.dumps(
            {
                "innovations": ["Builds a trace-based world model"],
                "methodology": "Trains on extracted interaction traces.",
                "key_results": "Improves long-horizon prediction.",
                "limitations": ["Trace extraction can miss fine-grained dynamics."],
            }
        )

    monkeypatch.setattr(gi, "_llm_chat", fake_llm_chat)

    result = gi.generate_deep_analysis(
        "Trace World Model",
        "We train a world model on interaction traces and evaluate planning.",
    )

    prompt = seen["prompt"]
    assert result["innovations"] == ["Builds a trace-based world model"]
    assert "main claims" in prompt
    assert "supporting evidence" in prompt
    assert "methodology details" in prompt
    assert "experimental results" in prompt
    assert "stated limitations" in prompt
    assert "Do not invent" in prompt


def test_tldr_reasoning_prompt_asks_for_evidence_bound_scoring(monkeypatch):
    from scripts import generate_interpretations as gi

    seen = {}

    def fake_llm_chat(messages, *args, **kwargs):
        seen["prompt"] = messages[0]["content"]
        return json.dumps(
            {
                "tldr": "Learns trace-based world models for planning.",
                "reasoning": "Strong method evidence but limited code signals.",
                "has_real_world": True,
                "keyword_scores": {"world model": 9},
            }
        )

    monkeypatch.setattr(gi, "_llm_chat", fake_llm_chat)

    result = gi.generate_tldr_and_reasoning(
        "Trace World Model",
        "We train a world model on interaction traces and evaluate planning.",
        ["world model"],
    )

    prompt = seen["prompt"]
    assert result["keyword_scores"]["world model"] == 9
    assert "core claims" in prompt
    assert "supporting evidence" in prompt
    assert "methodology" in prompt
    assert "limitations" in prompt
    assert "Score only what is supported" in prompt
