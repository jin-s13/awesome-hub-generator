import time


def test_sync_papers_classifies_with_configured_workers(tmp_path, monkeypatch):
    from scripts import sync

    calls = []

    def fake_classify(title, abstract, categories, research_context="", taxonomy=None, relevance_criteria=None):
        calls.append(title)
        time.sleep(0.05)
        return {"paper_type": ["method"], "tags": [title], "relevant": True}

    monkeypatch.setattr(sync, "classify_paper", fake_classify)
    output = tmp_path / "papers.yaml"
    output.write_text("[]\n", encoding="utf-8")
    papers = [
        {"title": f"Paper {idx}", "abstract": "Abstract", "links": {"paper": f"https://arxiv.org/abs/2601.0000{idx}"}}
        for idx in range(4)
    ]

    start = time.perf_counter()
    added = sync.sync_papers(
        papers,
        output,
        skip_llm=False,
        research_context="test hub",
        relevance_criteria={"include": ["test"]},
        llm_workers=4,
    )
    elapsed = time.perf_counter() - start

    assert added == 4
    assert sorted(calls) == [f"Paper {idx}" for idx in range(4)]
    assert elapsed < 0.18


def test_filter_papers_checks_relevance_with_configured_workers(monkeypatch):
    from scripts import relevance_filter

    calls = []

    def fake_check(paper, *args, **kwargs):
        calls.append(paper["title"])
        time.sleep(0.05)
        return True

    monkeypatch.setattr(relevance_filter, "is_cad_relevant", fake_check)
    papers = [{"title": f"Paper {idx}", "abstract": "Abstract"} for idx in range(4)]

    start = time.perf_counter()
    relevant, removed = relevance_filter.filter_papers(
        papers,
        research_context="test hub",
        relevance_criteria={"include": ["test"]},
        use_llm=True,
        llm_workers=4,
    )
    elapsed = time.perf_counter() - start

    assert len(relevant) == 4
    assert removed == []
    assert sorted(calls) == [f"Paper {idx}" for idx in range(4)]
    assert elapsed < 0.18


def test_sync_papers_filters_negative_keywords_with_configured_workers(tmp_path, monkeypatch):
    from scripts import sync

    monkeypatch.setenv("ARK_API_KEY", "test-key")
    calls = []

    def fake_negative(title, abstract, negative_keywords):
        calls.append(title)
        time.sleep(0.05)
        return False

    monkeypatch.setattr("scripts.relevance_filter._llm_filter_negative", fake_negative)
    output = tmp_path / "papers.yaml"
    output.write_text("[]\n", encoding="utf-8")
    papers = [
        {"title": f"Paper {idx}", "abstract": "Abstract", "links": {"paper": f"https://arxiv.org/abs/2602.0000{idx}"}}
        for idx in range(4)
    ]

    start = time.perf_counter()
    added = sync.sync_papers(
        papers,
        output,
        skip_llm=True,
        negative_keywords=["unrelated"],
        llm_workers=4,
    )
    elapsed = time.perf_counter() - start

    assert added == 4
    assert sorted(calls) == [f"Paper {idx}" for idx in range(4)]
    assert elapsed < 0.18


def test_relevance_filter_trusts_prior_llm_relevant_true(monkeypatch):
    from scripts import relevance_filter

    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM relevance should not run for prior relevant=true")

    monkeypatch.setattr(relevance_filter, "_llm_check_relevance", fail_if_called)

    assert relevance_filter.is_cad_relevant(
        {"title": "Paper", "abstract": "Abstract", "relevant": True},
        research_context="test hub",
        relevance_criteria={"include": ["test"]},
    )


def test_literature_surveys_synthesizes_topics_with_configured_workers(tmp_path, monkeypatch):
    from scripts import literature_survey

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "papers.yaml").write_text(
        """
- id: p1
  title: "Paper One"
  abstract: "alpha topic"
  tags: [alpha]
  taxonomy:
    primary: alpha
- id: p2
  title: "Paper Two"
  abstract: "beta topic"
  tags: [beta]
  taxonomy:
    primary: beta
""",
        encoding="utf-8",
    )
    (data_dir / "taxonomy.yaml").write_text(
        """
nodes:
  - id: alpha
    label: Alpha
    keywords: [alpha]
  - id: beta
    label: Beta
    keywords: [beta]
""",
        encoding="utf-8",
    )
    calls = []

    def fake_synthesis(topic, papers, tags):
        calls.append(topic["id"])
        time.sleep(0.05)
        return {
            "outline": [
                "Mainstream direction: x",
                "Shared research pattern: x",
                "Key differences: x",
                "Trend evolution: x",
                "Open questions: x",
            ],
            "outline_zh": [
                "主流方向：x",
                "研究共性：x",
                "关键差异：x",
                "趋势演进：x",
                "开放问题：x",
            ],
        }

    monkeypatch.setattr(literature_survey, "_llm_topic_synthesis", fake_synthesis)

    start = time.perf_counter()
    topics = literature_survey.build_literature_surveys(data_dir, {}, use_llm=True, llm_workers=2)
    elapsed = time.perf_counter() - start

    assert topics == 2
    assert sorted(calls) == ["alpha", "beta"]
    assert elapsed < 0.16
