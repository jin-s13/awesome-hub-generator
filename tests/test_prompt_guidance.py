"""Tests for research prompt guidance borrowed from Feynman-style workflows."""

from types import SimpleNamespace


def test_sync_classification_prompt_rejects_adjacent_but_indirect_work(monkeypatch):
    from scripts import sync

    seen = {}

    class FakeCache:
        def get_or_call_llm(self, **kwargs):
            seen["prompt"] = kwargs["messages"][0]["content"]
            return SimpleNamespace(text='{"paper_type":["method"],"tags":["world model"],"relevant":false}')

    monkeypatch.setattr(sync, "get_default_cache", lambda: FakeCache())

    sync.classify_paper(
        "Generic Video Generator",
        "This paper mentions world models but contributes a generic video generator.",
        ["cs.CV"],
        research_context="world model hub",
        relevance_criteria={
            "include": ["world models for prediction, simulation, planning, or control"],
            "exclude": ["generic video generation without predictive dynamics"],
        },
    )

    prompt = seen["prompt"]
    assert "directly relevant" in prompt
    assert "core contribution" in prompt
    assert "Adjacent terminology alone is not enough" in prompt
    assert "mark relevant=false" in prompt


def test_relevance_filter_prompt_prioritizes_core_contribution(monkeypatch):
    from scripts import relevance_filter

    seen = {}

    class FakeCache:
        def get_or_call_llm(self, **kwargs):
            seen["prompt"] = kwargs["messages"][0]["content"]
            return SimpleNamespace(text='{"relevant": false, "reason": "Only adjacent terminology."}')

    monkeypatch.setattr(relevance_filter, "API_KEY", "test-key")
    monkeypatch.setattr(relevance_filter, "get_default_cache", lambda: FakeCache())

    result = relevance_filter._llm_check_relevance(
        "Generic Video Generator",
        "This paper mentions world models but contributes a generic video generator.",
        "world model hub",
        {
            "include": ["world models for prediction, simulation, planning, or control"],
            "exclude": ["generic video generation without predictive dynamics"],
        },
    )

    prompt = seen["prompt"]
    assert result is False
    assert "CORE CONTRIBUTION" in prompt
    assert "Adjacent terminology alone is not enough" in prompt
    assert "mark relevant=false" in prompt
