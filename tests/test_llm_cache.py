"""Tests for llm_cache.py."""

from scripts.llm_cache import (
    LLMCallResult,
    LLMCache,
    paper_identity_from,
    stable_hash,
)


def test_paper_identity_prefers_arxiv_id():
    assert paper_identity_from(arxiv_id="2401.12345", title="A Paper") == "arxiv:2401.12345"


def test_stable_hash_is_deterministic_for_dicts():
    assert stable_hash({"b": 2, "a": 1}) == stable_hash({"a": 1, "b": 2})


def test_get_or_call_llm_caches_and_records_hits(tmp_path):
    cache = LLMCache(tmp_path / "llm.db")
    calls = {"n": 0}
    messages = [{"role": "user", "content": "hello"}]

    def call_func():
        calls["n"] += 1
        return LLMCallResult("response", prompt_tokens=3, completion_tokens=2, total_tokens=5)

    first = cache.get_or_call_llm(
        task_type="relevance_check",
        model="test-model",
        prompt_version="v1",
        paper_identity="arxiv:2401.12345",
        abstract="abstract",
        criteria={"kw": ["cad"]},
        messages=messages,
        call_func=call_func,
    )
    second = cache.get_or_call_llm(
        task_type="relevance_check",
        model="test-model",
        prompt_version="v1",
        paper_identity="arxiv:2401.12345",
        abstract="abstract",
        criteria={"kw": ["cad"]},
        messages=messages,
        call_func=call_func,
    )

    assert first.text == "response"
    assert second.text == "response"
    assert calls["n"] == 1

    stats = cache.stats()
    item = stats["calls_by_task"]["relevance_check"]
    assert item["calls"] == 2
    assert item["cache_hits"] == 1
    assert item["total_tokens"] == 5


def test_legacy_prompt_api_round_trips(tmp_path):
    cache = LLMCache(tmp_path / "llm.db")
    cache.put("prompt", {"ok": True}, "legacy_task")
    assert cache.get("prompt", "legacy_task") == {"ok": True}
