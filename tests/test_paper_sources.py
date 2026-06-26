"""Tests for unified paper source aggregation."""

from scripts.paper_sources import collect_paper_sources


def test_collect_paper_sources_merges_enabled_sources_and_dedupes(monkeypatch):
    calls = []

    def fake_arxiv(config, search_days=None, max_results=500):
        calls.append("arxiv")
        return [
            {
                "id": "arxiv-paper",
                "arxiv_id": "2601.00001",
                "title": "Unified Paper Search",
                "links": {"paper": "https://arxiv.org/abs/2601.00001"},
                "sources": [{"repo": "arxiv", "category": "paper"}],
            }
        ]

    def fake_hf(config, search_days=None):
        calls.append("huggingface")
        return [
            {
                "id": "hf-paper",
                "title": "Unified Paper Search",
                "links": {"paper": "https://arxiv.org/abs/2601.00001"},
                "sources": [{"repo": "huggingface-daily", "category": "paper"}],
                "score": {"upvotes": 17},
            }
        ]

    def fake_awesome(config):
        calls.append("awesome")
        return [
            {
                "id": "awesome-paper",
                "title": "A Curated Awesome Paper",
                "links": {"paper": "https://example.com/paper"},
                "sources": [{"repo": "owner/awesome-list", "category": "paper"}],
            }
        ]

    def fail_alphaxiv(config, query=None):
        raise AssertionError("AlphaXiv should be disabled unless explicitly enabled")

    monkeypatch.setattr("scripts.paper_sources.fetch_arxiv_source", fake_arxiv)
    monkeypatch.setattr("scripts.paper_sources.fetch_huggingface_source", fake_hf)
    monkeypatch.setattr("scripts.paper_sources.fetch_awesome_source", fake_awesome)
    monkeypatch.setattr("scripts.paper_sources.fetch_alphaxiv_source", fail_alphaxiv)

    result = collect_paper_sources(
        {
            "research": {
                "keywords": ["paper search"],
                "sources": {
                    "arxiv": True,
                    "huggingface_daily": True,
                    "upstream_awesome": True,
                    "alphaxiv": False,
                },
            }
        },
        search_days=7,
    )

    assert calls == ["arxiv", "huggingface", "awesome"]
    assert len(result["papers"]) == 2
    merged = result["papers"][0]
    assert merged["arxiv_id"] == "2601.00001"
    assert [source["repo"] for source in merged["sources"]] == ["arxiv", "huggingface-daily"]
    assert merged["score"]["upvotes"] == 17
    assert result["sources"]["arxiv"]["count"] == 1
    assert result["sources"]["huggingface"]["count"] == 1
    assert result["sources"]["awesome"]["count"] == 1
    assert result["sources"]["alphaxiv"]["enabled"] is False


def test_collect_paper_sources_records_nonfatal_source_errors(monkeypatch):
    def broken_arxiv(config, search_days=None, max_results=500):
        raise RuntimeError("temporary arxiv outage")

    def fake_hf(config, search_days=None):
        return [{"id": "hf-only", "title": "HF Paper", "links": {"paper": "https://arxiv.org/abs/2602.00001"}}]

    monkeypatch.setattr("scripts.paper_sources.fetch_arxiv_source", broken_arxiv)
    monkeypatch.setattr("scripts.paper_sources.fetch_huggingface_source", fake_hf)
    monkeypatch.setattr("scripts.paper_sources.fetch_awesome_source", lambda config: [])
    monkeypatch.setattr("scripts.paper_sources.fetch_alphaxiv_source", lambda config, query=None: [])

    result = collect_paper_sources(
        {
            "research": {
                "sources": {
                    "arxiv": True,
                    "huggingface_daily": True,
                    "upstream_awesome": False,
                    "alphaxiv": False,
                }
            }
        }
    )

    assert len(result["papers"]) == 1
    assert result["sources"]["arxiv"]["count"] == 0
    assert "temporary arxiv outage" in result["sources"]["arxiv"]["error"]
