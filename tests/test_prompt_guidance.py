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


def test_relevance_filter_offline_fallback_rejects_adjacent_agent_memory_work(monkeypatch):
    from scripts import relevance_filter

    monkeypatch.setattr(relevance_filter, "API_KEY", "")

    result = relevance_filter.is_cad_relevant(
        {
            "title": "Zep: A Temporal Knowledge Graph Architecture for Agent Memory",
            "abstract": (
                "We introduce Zep, a memory layer service for AI agents. "
                "It improves long-term context maintenance and retrieval over "
                "ongoing conversations and business data."
            ),
            "tags": ["agent memory", "knowledge graph", "retrieval"],
        },
        research_context="agent skill evolution hub",
        relevance_criteria={
            "include": [
                "Agent skill learning, acquisition, or discovery",
                "Skill libraries, skill composition, or skill reuse",
                "Agent memory systems that enable skill accumulation",
            ],
            "exclude": [
                "Agent memory, RAG, or retrieval systems without skill accumulation or evolution",
            ],
        },
        domain_keywords=["agent skill learning", "skill evolution", "agent"],
    )

    assert result is False


def test_relevance_filter_offline_fallback_keeps_direct_skill_evolution_work(monkeypatch):
    from scripts import relevance_filter

    monkeypatch.setattr(relevance_filter, "API_KEY", "")

    result = relevance_filter.is_cad_relevant(
        {
            "title": "EvoAgent: Self-Evolving Agents with Skill Libraries",
            "abstract": (
                "We propose a self-evolving agent that accumulates reusable skills "
                "in a skill library, composes them for new tasks, and improves via "
                "automatic task generation."
            ),
            "tags": ["self-evolving agent", "skill library", "skill composition"],
        },
        research_context="agent skill evolution hub",
        relevance_criteria={
            "include": [
                "Agent skill learning, acquisition, or discovery",
                "Skill libraries, skill composition, or skill reuse",
                "Self-improving or self-evolving AI agents",
                "Curriculum learning or automatic task generation for agent training",
            ],
            "exclude": [
                "General LLM training, pretraining, or fine-tuning without skill/agent focus",
            ],
        },
        domain_keywords=["agent skill learning", "skill evolution", "agent"],
    )

    assert result is True


def test_relevance_filter_offline_fallback_keeps_agent_self_evolution_work(monkeypatch):
    from scripts import relevance_filter

    monkeypatch.setattr(relevance_filter, "API_KEY", "")

    result = relevance_filter.is_cad_relevant(
        {
            "title": "EvoScientist: Towards Multi-Agent Evolving AI Scientists",
            "abstract": (
                "We propose an evolving multi-agent AI scientist framework with "
                "persistent memory and self-evolution. The system continuously "
                "improves research strategies through multi-agent evolution."
            ),
            "tags": ["multi-agent systems", "self-evolution", "LLM-based agents"],
        },
        research_context="agent skill evolution hub",
        relevance_criteria={
            "include": [
                "Self-improving or self-evolving AI agents",
                "Agent self-play, self-training, or self-correction for skill improvement",
            ],
            "exclude": [
                "General LLM training, pretraining, or fine-tuning without skill/agent focus",
            ],
        },
        domain_keywords=["agent skill learning", "skill evolution", "agent"],
    )

    assert result is True


def test_relevance_filter_offline_fallback_is_driven_by_configured_domain(monkeypatch):
    from scripts import relevance_filter

    monkeypatch.setattr(relevance_filter, "API_KEY", "")

    result = relevance_filter.is_cad_relevant(
        {
            "title": "Large Language Models as Tool Makers",
            "abstract": (
                "This paper proposes a closed-loop framework where language models "
                "create reusable tools for solving reasoning tasks."
            ),
            "tags": ["tool making", "LLM", "reasoning"],
        },
        research_context="AI mathematics proof hub",
        relevance_criteria={
            "include": [
                "AI systems for theorem proving, formal proof generation, or proof assistants",
                "Neural-symbolic methods for mathematical proof search",
            ],
            "exclude": [
                "General LLM reasoning or tool-use papers without formal mathematics proof contribution",
            ],
        },
        domain_keywords=["theorem proving", "formal proof generation", "proof assistant"],
    )

    assert result is False


def test_relevance_filter_offline_fallback_keeps_configured_math_proof_work(monkeypatch):
    from scripts import relevance_filter

    monkeypatch.setattr(relevance_filter, "API_KEY", "")

    result = relevance_filter.is_cad_relevant(
        {
            "title": "Neural Theorem Proving with Lean Proof Assistants",
            "abstract": (
                "We introduce a neural-symbolic method for theorem proving that "
                "generates formal proofs in the Lean proof assistant."
            ),
            "tags": ["theorem proving", "formal proof generation", "proof assistant"],
        },
        research_context="AI mathematics proof hub",
        relevance_criteria={
            "include": [
                "AI systems for theorem proving, formal proof generation, or proof assistants",
                "Neural-symbolic methods for mathematical proof search",
            ],
            "exclude": [
                "General LLM reasoning or tool-use papers without formal mathematics proof contribution",
            ],
        },
        domain_keywords=["theorem proving", "formal proof generation", "proof assistant"],
    )

    assert result is True


def test_sync_classification_fallback_leaves_relevance_unknown_when_llm_unavailable(monkeypatch):
    from scripts import sync

    class FakeCache:
        def get_or_call_llm(self, **kwargs):
            return SimpleNamespace(text="")

    monkeypatch.setattr(sync, "get_default_cache", lambda: FakeCache())

    result = sync.classify_paper(
        "GLM-5: from Vibe Coding to Agentic Engineering",
        (
            "We present GLM-5, a next-generation foundation model with agentic, "
            "reasoning, and coding capabilities. It improves benchmarks through "
            "asynchronous reinforcement learning."
        ),
        ["cs.AI"],
        research_context="agent skill evolution hub",
        relevance_criteria={
            "include": [
                "Agent skill learning, acquisition, or discovery",
                "Skill libraries, skill composition, or skill reuse",
                "Self-improving or self-evolving AI agents",
            ],
            "exclude": [
                "General LLM training, pretraining, or fine-tuning without skill/agent focus",
                "Agentic coding benchmarks without skill accumulation or evolution",
            ],
        },
    )

    assert "relevant" not in result


def test_relevance_filter_empty_llm_response_is_unknown(monkeypatch):
    from scripts import relevance_filter

    class FakeCache:
        def get_or_call_llm(self, **kwargs):
            return SimpleNamespace(text="")

    monkeypatch.setattr(relevance_filter, "API_KEY", "test-key")
    monkeypatch.setattr(relevance_filter, "get_default_cache", lambda: FakeCache())

    result = relevance_filter._llm_check_relevance(
        "GLM-5: from Vibe Coding to Agentic Engineering",
        "A foundation model paper with agentic coding benchmarks.",
        "agent skill evolution hub",
        {
            "include": ["Agent skill learning, acquisition, or discovery"],
            "exclude": ["General LLM training without skill/agent focus"],
        },
    )

    assert result is None
