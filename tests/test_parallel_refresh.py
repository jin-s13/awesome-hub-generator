"""Tests for the parallel interpretation refresh helper."""

from scripts.refresh_interpretations_parallel import (
    apply_updates,
    english_pending,
    requested_chinese_fields,
)


def test_english_pending_includes_missing_tldr_or_high_score_analysis():
    assert english_pending({"title": "A", "abstract": "B"})
    assert english_pending(
        {
            "title": "A",
            "abstract": "B",
            "tldr": "Short.",
            "reasoning": "Because.",
            "score": {"total": 35},
        }
    )
    assert not english_pending(
        {
            "title": "A",
            "abstract": "B",
            "tldr": "Short.",
            "reasoning": "Because.",
            "score": {"total": 35},
            "analysis": {"methodology": "Method."},
        }
    )


def test_requested_chinese_fields_uses_existing_english_outputs():
    paper = {
        "title": "A",
        "abstract": "B",
        "title_cn": "甲",
        "abstract_cn": "乙",
        "tldr": "Short.",
        "analysis": {"methodology": "Method."},
    }

    assert requested_chinese_fields(paper) == ["tldr_cn", "analysis_cn"]


def test_apply_updates_merges_score_and_top_level_fields():
    paper = {"title": "A", "score": {"author_bonus": 1}}
    updates = {
        "tldr": "Short.",
        "score": {"total": 9, "keyword_scores": {"world model": 9}},
    }

    apply_updates(paper, updates)

    assert paper["tldr"] == "Short."
    assert paper["score"]["author_bonus"] == 1
    assert paper["score"]["total"] == 9
    assert paper["score"]["keyword_scores"] == {"world model": 9}
