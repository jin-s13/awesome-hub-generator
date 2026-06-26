"""PaperRank-lite scoring for awesome-hub-generator.

This module adds explainable read-first signals to existing papers.yaml entries
without replacing the upstream LLM score. It is intentionally local and
deterministic: network-backed citation metadata can be layered on later.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

RANKING_PROFILE = "paper_rank_lite_v1"

DEFAULT_WEIGHTS = {
    "topical_relevance": 0.40,
    "methodology_quality": 0.25,
    "reproducibility": 0.25,
    "recency": 0.10,
}

METHODOLOGY_MARKERS = {
    "ablation",
    "analysis",
    "baseline",
    "benchmark",
    "dataset",
    "evaluation",
    "experiment",
    "metric",
    "result",
    "validation",
}

REPRODUCIBILITY_MARKERS = {
    "artifact",
    "checkpoint",
    "code",
    "dataset",
    "github",
    "open source",
    "reproduce",
    "repository",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "paper",
    "research",
    "the",
    "to",
    "using",
    "we",
    "with",
}


def _tokens(text: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in STOP_WORDS
    ]


def _text_fields(paper: Dict[str, Any]) -> str:
    analysis = paper.get("analysis") if isinstance(paper.get("analysis"), dict) else {}
    parts: List[str] = [
        str(paper.get("title") or ""),
        str(paper.get("abstract") or ""),
        " ".join(str(tag) for tag in paper.get("tags") or []),
        " ".join(str(tag) for tag in paper.get("representations") or []),
        str(analysis.get("methodology") or ""),
        str(analysis.get("key_results") or ""),
        " ".join(str(item) for item in analysis.get("innovations") or []),
        " ".join(str(item) for item in analysis.get("limitations") or []),
    ]
    return " ".join(parts)


def _round(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _signal(
    value: float,
    available: bool,
    confidence: str,
    explanation: str,
    explanation_zh: str,
    evidence: Iterable[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "value": _round(value),
        "available": bool(available),
        "confidence": confidence,
        "explanation": explanation,
        "explanation_zh": explanation_zh,
        "evidence": list(evidence),
    }


def _research_keywords(config: Dict[str, Any]) -> List[str]:
    research = config.get("research", {}) if isinstance(config, dict) else {}
    keywords = []
    for field in ("keywords", "domain_boost_keywords"):
        raw = research.get(field, [])
        if isinstance(raw, list):
            keywords.extend(str(item) for item in raw if str(item).strip())
    return keywords


def _score_topical_relevance(paper: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    score = paper.get("score") if isinstance(paper.get("score"), dict) else {}
    keyword_scores = score.get("keyword_scores") if isinstance(score.get("keyword_scores"), dict) else {}
    if keyword_scores:
        values = [float(value) for value in keyword_scores.values() if isinstance(value, (int, float))]
        if values:
            max_score = (
                config.get("research", {})
                .get("scoring", {})
                .get("max_score_per_keyword", 10)
            )
            normalized = sum(values) / max(1, len(values)) / max(1, float(max_score)) * 100
            return _signal(
                normalized,
                True,
                "high",
                "Uses existing LLM keyword relevance scores normalized to 0-100.",
                "使用现有 LLM 关键词相关性评分，并归一化到 0-100。",
                [{"source": "papers.yaml", "field": "score.keyword_scores", "detail": ",".join(keyword_scores.keys())}],
            )

    keywords = _research_keywords(config)
    keyword_tokens = set(_tokens(" ".join(keywords)))
    paper_tokens = set(_tokens(_text_fields(paper)))
    if not keyword_tokens:
        return _signal(
            0,
            False,
            "low",
            "No research keywords were configured, so topical relevance is excluded.",
            "未配置研究关键词，因此不纳入主题相关性评分。",
            [{"source": "awesome.yaml", "field": "research.keywords", "detail": "missing"}],
        )
    overlap = len(keyword_tokens & paper_tokens) / len(keyword_tokens)
    title_tokens = set(_tokens(str(paper.get("title") or "")))
    title_overlap = len(keyword_tokens & title_tokens) / len(keyword_tokens)
    value = (0.75 * overlap + 0.25 * title_overlap) * 100
    return _signal(
        value,
        True,
        "medium" if paper.get("abstract") else "low",
        "Matches configured research keywords against title, abstract, tags, and analysis text.",
        "将配置的研究关键词与标题、摘要、标签和分析文本进行匹配。",
        [{"source": "awesome.yaml", "field": "research.keywords", "detail": f"matched={len(keyword_tokens & paper_tokens)}"}],
    )


def _marker_hits(text: str, markers: Iterable[str]) -> List[str]:
    lower = text.lower()
    return sorted({marker for marker in markers if marker in lower})


def _score_methodology_quality(paper: Dict[str, Any]) -> Dict[str, Any]:
    text = _text_fields(paper)
    analysis = paper.get("analysis") if isinstance(paper.get("analysis"), dict) else {}
    hits = _marker_hits(text, METHODOLOGY_MARKERS)
    has_abstract = bool(str(paper.get("abstract") or "").strip())
    has_analysis = bool(analysis)
    has_limitations = bool(analysis.get("limitations"))
    value = min(100, len(hits) * 10 + (20 if has_abstract else 0) + (20 if has_analysis else 0) + (10 if has_limitations else 0))
    available = has_abstract or has_analysis
    return _signal(
        value,
        available,
        "medium" if available else "low",
        "Screens visible abstract and analysis fields for experiment, dataset, baseline, metric, and limitation evidence.",
        "检查可见的摘要与分析字段，寻找实验、数据集、基线、指标和局限性等方法证据。",
        [
            {"source": "papers.yaml", "field": "abstract/analysis", "detail": f"markers={','.join(hits) or 'none'}"},
        ],
    )


def _score_reproducibility(paper: Dict[str, Any]) -> Dict[str, Any]:
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    link_text = " ".join(str(value) for value in links.values())
    text = f"{_text_fields(paper)} {link_text}"
    hits = _marker_hits(text, REPRODUCIBILITY_MARKERS)
    has_pdf = any(key in links and links.get(key) for key in ("pdf", "paper"))
    has_code = any("github.com" in str(value).lower() for value in links.values()) or any(
        key in links and links.get(key) for key in ("code", "github", "repo")
    )
    has_dataset = any(key in links and links.get(key) for key in ("dataset", "data"))
    value = min(100, (30 if has_pdf else 0) + (35 if has_code else 0) + (15 if has_dataset else 0) + min(len(hits) * 8, 20))
    return _signal(
        value,
        True,
        "medium" if has_code or has_dataset else "low",
        "Screens links and visible text for paper, code, dataset, artifact, and repository signals.",
        "检查链接和可见文本中的论文、代码、数据集、工件与仓库信号。",
        [{"source": "papers.yaml", "field": "links", "detail": f"pdf={has_pdf}; code={has_code}; dataset={has_dataset}; markers={','.join(hits) or 'none'}"}],
    )


def _score_recency(paper: Dict[str, Any], now_year: int) -> Dict[str, Any]:
    try:
        year = int(paper.get("year"))
    except (TypeError, ValueError):
        return _signal(
            0,
            False,
            "low",
            "Publication year is missing, so recency is excluded.",
            "缺少发表年份，因此不纳入近期性评分。",
            [{"source": "papers.yaml", "field": "year", "detail": "missing"}],
        )
    age = max(0, now_year - year)
    value = 100 * math.exp(-age / 7)
    return _signal(
        value,
        True,
        "medium",
        "Uses a gentle age decay so recent papers surface without erasing older foundations.",
        "使用温和的时间衰减，让近期论文更容易浮现，同时保留较早基础工作的价值。",
        [{"source": "papers.yaml", "field": "year", "detail": str(year)}],
    )


def _ranking_weights(config: Dict[str, Any]) -> Dict[str, float]:
    raw = (
        config.get("research", {})
        .get("ranking", {})
        .get("weights", {})
        if isinstance(config, dict)
        else {}
    )
    if not isinstance(raw, dict) or not raw:
        return dict(DEFAULT_WEIGHTS)
    weights = {}
    for key, value in raw.items():
        if key in DEFAULT_WEIGHTS and isinstance(value, (int, float)) and value > 0:
            weights[key] = float(value)
    return weights or dict(DEFAULT_WEIGHTS)


def rank_signal_components(
    paper: Dict[str, Any],
    config: Dict[str, Any],
    *,
    now_year: Optional[int] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, float], float]:
    """Return component signals, normalized applied weights, and read-first score."""
    year = now_year or _dt.datetime.now().year
    components = {
        "topical_relevance": _score_topical_relevance(paper, config),
        "methodology_quality": _score_methodology_quality(paper),
        "reproducibility": _score_reproducibility(paper),
        "recency": _score_recency(paper, year),
    }
    weights = _ranking_weights(config)
    available_weights = {
        key: weight
        for key, weight in weights.items()
        if key in components and components[key].get("available")
    }
    denominator = sum(available_weights.values())
    if denominator <= 0:
        return components, {}, 0.0
    applied = {key: round(weight / denominator, 6) for key, weight in available_weights.items()}
    read_first = sum(components[key]["value"] * normalized for key, normalized in applied.items())
    return components, applied, _round(read_first)


def enrich_paper_rank_scores(
    papers_path: Path,
    config: Dict[str, Any],
    *,
    now_year: Optional[int] = None,
) -> int:
    """Add PaperRank-lite fields to every paper in a papers.yaml file."""
    if not papers_path.exists():
        return 0
    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8")) or []
    if not isinstance(papers, list):
        return 0

    updated = 0
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        components, applied_weights, read_first = rank_signal_components(paper, config, now_year=now_year)
        score = paper.get("score")
        if not isinstance(score, dict):
            score = {}
            paper["score"] = score
        score["read_first_score"] = read_first
        score["components"] = components
        score["applied_weights"] = applied_weights
        score["ranking_profile"] = RANKING_PROFILE
        score.setdefault("warnings", [])
        updated += 1

    papers_path.write_text(
        yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return updated
