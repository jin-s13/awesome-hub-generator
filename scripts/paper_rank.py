"""PaperRank-lite scoring for awesome-hub-generator.

This module adds explainable read-first signals to existing papers.yaml entries
without replacing the upstream LLM score. It is intentionally local and
deterministic: network-backed citation metadata can be layered on later.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

RANKING_PROFILE = "paper_rank_lite_v1"

DEFAULT_WEIGHTS = {
    "topical_relevance": 0.25,
    "citation_impact": 0.15,
    "graph_prestige": 0.15,
    "citation_velocity": 0.10,
    "methodology_quality": 0.15,
    "reproducibility": 0.15,
    "recency": 0.05,
}


class OpenAlexRateLimit(RuntimeError):
    """Raised when OpenAlex reports that the current API quota is exhausted."""

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
        str(paper.get("full_text") or paper.get("fullText") or ""),
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


def _normalize_openalex_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rstrip("/").split("/")[-1]


def _citation_info(paper: Dict[str, Any]) -> Dict[str, Any]:
    raw = paper.get("openalex") if isinstance(paper.get("openalex"), dict) else {}
    percentile = raw.get("citation_normalized_percentile", paper.get("citation_normalized_percentile"))
    if isinstance(percentile, dict):
        percentile = percentile.get("value")
    refs = raw.get("referenced_works", paper.get("referenced_works", []))
    if not isinstance(refs, list):
        refs = []
    return {
        "id": _normalize_openalex_id(raw.get("id") or paper.get("openalex_id")),
        "citation_count": int(raw.get("cited_by_count", paper.get("citation_count", 0)) or 0),
        "citation_normalized_percentile": float(percentile) if isinstance(percentile, (int, float)) else None,
        "referenced_works": [_normalize_openalex_id(ref) for ref in refs if _normalize_openalex_id(ref)],
    }


def _citation_velocity_from_info(info: Dict[str, Any], paper: Dict[str, Any], now_year: int) -> float:
    try:
        year = int(paper.get("year"))
    except (TypeError, ValueError):
        return 0.0
    return float(info.get("citation_count") or 0) / max(1, now_year - year + 1)


def _pagerank(ids: List[str], edges: List[Tuple[str, str]], iterations: int = 30, damping: float = 0.85) -> Dict[str, float]:
    if not ids:
        return {}
    ranks = {paper_id: 1.0 / len(ids) for paper_id in ids}
    outgoing: Dict[str, List[str]] = defaultdict(list)
    for source, target in edges:
        if source in ranks and target in ranks:
            outgoing[source].append(target)
    for _ in range(iterations):
        next_ranks = {paper_id: (1.0 - damping) / len(ids) for paper_id in ids}
        dangling = sum(ranks[paper_id] for paper_id in ids if not outgoing.get(paper_id))
        dangling_share = damping * dangling / len(ids)
        for paper_id in ids:
            next_ranks[paper_id] += dangling_share
        for source, targets in outgoing.items():
            share = damping * ranks[source] / max(1, len(targets))
            for target in targets:
                next_ranks[target] += share
        ranks = next_ranks
    return ranks


def _citation_graph_context(papers: List[Dict[str, Any]], now_year: int) -> Dict[str, Any]:
    infos = {id(paper): _citation_info(paper) for paper in papers}
    ids = [info["id"] for info in infos.values() if info["id"]]
    id_set = set(ids)
    edges: List[Tuple[str, str]] = []
    in_degree: Dict[str, int] = defaultdict(int)
    out_degree: Dict[str, int] = defaultdict(int)
    for info in infos.values():
        source = info["id"]
        if not source:
            continue
        for target in info["referenced_works"]:
            if target in id_set:
                edges.append((source, target))
                out_degree[source] += 1
                in_degree[target] += 1
    pagerank = _pagerank(ids, edges)
    max_pr = max(pagerank.values()) if pagerank else 0.0
    max_citation_log = max([math.log1p(info["citation_count"]) for info in infos.values()] or [0.0])
    velocities = [_citation_velocity_from_info(infos[id(paper)], paper, now_year) for paper in papers]
    max_velocity_log = max([math.log1p(value) for value in velocities] or [0.0])
    return {
        "infos": infos,
        "edges": edges,
        "pagerank": pagerank,
        "max_pagerank": max_pr,
        "max_citation_log": max_citation_log,
        "max_velocity_log": max_velocity_log,
        "in_degree": in_degree,
        "out_degree": out_degree,
    }


def _paper_lookup_key(paper: Dict[str, Any]) -> str:
    return str(paper.get("id") or paper.get("title") or "").strip()


def _arxiv_landing_page_url(value: str) -> str:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^?#/]+)", value or "", re.I)
    if not match:
        return ""
    arxiv_id = match.group(1).replace(".pdf", "")
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.I)
    return f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""


def _openalex_query_for_paper(paper: Dict[str, Any]) -> str:
    doi = str(paper.get("doi") or "").strip()
    if doi:
        return f"filter=doi:{urllib.parse.quote(doi)}"
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    paper_url = str(links.get("paper") or links.get("pdf") or "")
    arxiv_url = _arxiv_landing_page_url(paper_url)
    if arxiv_url:
        return f"filter=locations.landing_page_url:{urllib.parse.quote(arxiv_url, safe=':/')}"
    return f"search={urllib.parse.quote_plus(str(paper.get('title') or ''))}"


def _title_match_score(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _openalex_work_matches_paper(paper: Dict[str, Any], work: Dict[str, Any]) -> bool:
    expected = str(paper.get("title") or "").strip()
    actual = str(work.get("title") or work.get("display_name") or "").strip()
    if not expected or not actual:
        return True
    return _title_match_score(expected, actual) >= 0.35


def _openalex_work_to_metadata(work: Dict[str, Any]) -> Dict[str, Any]:
    percentile = work.get("citation_normalized_percentile")
    if isinstance(percentile, dict):
        percentile = percentile.get("value")
    return {
        "id": work.get("id", ""),
        "cited_by_count": int(work.get("cited_by_count") or 0),
        "citation_normalized_percentile": percentile if isinstance(percentile, (int, float)) else None,
        "referenced_works": work.get("referenced_works") if isinstance(work.get("referenced_works"), list) else [],
        "topics": [
            item.get("display_name")
            for item in (work.get("topics") or [])
            if isinstance(item, dict) and item.get("display_name")
        ],
        "concepts": [
            item.get("display_name")
            for item in (work.get("concepts") or [])
            if isinstance(item, dict) and item.get("display_name")
        ],
    }


def fetch_openalex_metadata_for_papers(papers: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Fetch OpenAlex-shaped citation metadata for papers.

    This is optional and intentionally best-effort. Build flows should keep
    working when OpenAlex is unavailable.
    """
    ranking = config.get("research", {}).get("ranking", {}) if isinstance(config, dict) else {}
    citation_graph = ranking.get("citation_graph", {}) if isinstance(ranking, dict) else {}
    timeout = int(citation_graph.get("timeout", 20)) if isinstance(citation_graph, dict) else 20
    workers = int(citation_graph.get("workers", 6)) if isinstance(citation_graph, dict) else 6
    workers = max(1, min(workers, 16))
    email = str((citation_graph.get("mailto") if isinstance(citation_graph, dict) else "") or os.environ.get("OPENALEX_MAILTO") or "").strip()
    api_key = str(citation_graph.get("api_key") or os.environ.get("OPENALEX_API_KEY") or "").strip()
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:].strip()
    headers = {"User-Agent": "awesome-hub-generator/1.0"}
    extra_params = []
    if api_key:
        extra_params.append(("api_key", api_key))
    if email:
        extra_params.append(("mailto", email))
    extra_query = f"&{urllib.parse.urlencode(extra_params)}" if extra_params else ""
    results: Dict[str, Dict[str, Any]] = {}

    def fetch_one(paper: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        if not isinstance(paper, dict) or not paper.get("title"):
            return "", None
        query = _openalex_query_for_paper(paper)
        url = f"https://api.openalex.org/works?{query}&per-page=1{extra_query}"
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise OpenAlexRateLimit("OpenAlex API quota exhausted") from exc
            return "", None
        except Exception:
            return "", None
        works = payload.get("results") if isinstance(payload, dict) else []
        if works and isinstance(works[0], dict):
            if not _openalex_work_matches_paper(paper, works[0]):
                return "", None
            key = _paper_lookup_key(paper)
            if key:
                return key, _openalex_work_to_metadata(works[0])
        return "", None

    candidates = [paper for paper in papers if isinstance(paper, dict) and paper.get("title")]
    if not candidates:
        return results
    try:
        key, metadata = fetch_one(candidates[0])
    except OpenAlexRateLimit:
        print("[paper-rank] OpenAlex API quota exhausted; skipping citation metadata fetch.", file=sys.stderr)
        return results
    if key and metadata:
        results[key] = metadata
    candidates = candidates[1:]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_one, paper) for paper in candidates]
        for future in concurrent.futures.as_completed(futures):
            try:
                key, metadata = future.result()
            except OpenAlexRateLimit:
                print("[paper-rank] OpenAlex API quota exhausted; skipping remaining citation metadata fetches.", file=sys.stderr)
                for pending in futures:
                    pending.cancel()
                break
            if key and metadata:
                results[key] = metadata
    return results


def _merge_openalex_metadata(papers: List[Dict[str, Any]], config: Dict[str, Any]) -> None:
    ranking = config.get("research", {}).get("ranking", {}) if isinstance(config, dict) else {}
    citation_graph = ranking.get("citation_graph", {}) if isinstance(ranking, dict) else {}
    should_fetch = bool(citation_graph.get("fetch_openalex")) if isinstance(citation_graph, dict) else False
    if not should_fetch:
        return
    fetched = fetch_openalex_metadata_for_papers(papers, config)
    for paper in papers:
        key = _paper_lookup_key(paper)
        if key and key in fetched:
            existing = paper.get("openalex") if isinstance(paper.get("openalex"), dict) else {}
            merged = dict(existing)
            merged.update({k: v for k, v in fetched[key].items() if v not in (None, "", [], {})})
            paper["openalex"] = merged


def _score_citation_impact(paper: Dict[str, Any], graph_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not graph_context:
        return _signal(0, False, "low", "No citation metadata was supplied, so citation impact is excluded.", "未提供引用元数据，因此不纳入引用影响力评分。", [])
    info = graph_context["infos"].get(id(paper), {})
    if not info.get("id"):
        return _signal(0, False, "low", "No OpenAlex identifier was available for this paper.", "该论文没有可用的 OpenAlex 标识符。", [])
    if isinstance(info.get("citation_normalized_percentile"), float):
        value = info["citation_normalized_percentile"] * 100
        detail = f"citation_normalized_percentile={info['citation_normalized_percentile']}"
    else:
        max_log = graph_context.get("max_citation_log") or 0
        value = (math.log1p(info.get("citation_count") or 0) / max_log * 100) if max_log else 0
        detail = f"cited_by_count={info.get('citation_count', 0)}"
    return _signal(
        value,
        True,
        "medium",
        "Uses OpenAlex-shaped citation metadata as a bibliometric attention signal, separate from paper quality.",
        "使用 OpenAlex 形态的引用元数据作为文献关注度信号，并与论文本身质量分开处理。",
        [{"source": "openalex", "field": "citation", "detail": detail}],
    )


def _score_graph_prestige(paper: Dict[str, Any], graph_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not graph_context or not graph_context.get("edges"):
        return _signal(0, False, "low", "No local citation edges were available, so graph prestige is excluded.", "没有可用的局部引用边，因此不纳入图谱声望评分。", [])
    info = graph_context["infos"].get(id(paper), {})
    paper_id = info.get("id")
    rank = graph_context["pagerank"].get(paper_id, 0.0)
    max_rank = graph_context.get("max_pagerank") or 0.0
    return _signal(
        (rank / max_rank * 100) if max_rank else 0,
        bool(paper_id),
        "medium",
        "PageRank-style prestige over the local citation graph built from available OpenAlex references.",
        "基于可用 OpenAlex 引用关系构建局部引用图，并计算 PageRank 风格的图谱声望。",
        [{"source": "openalex", "field": "referenced_works", "detail": f"local_pagerank={rank:.4f}"}],
    )


def _score_citation_velocity(paper: Dict[str, Any], graph_context: Optional[Dict[str, Any]], now_year: int) -> Dict[str, Any]:
    if not graph_context:
        return _signal(0, False, "low", "No citation metadata was supplied, so citation velocity is excluded.", "未提供引用元数据，因此不纳入引用速度评分。", [])
    info = graph_context["infos"].get(id(paper), {})
    if not info.get("id"):
        return _signal(0, False, "low", "No OpenAlex identifier was available for this paper.", "该论文没有可用的 OpenAlex 标识符。", [])
    velocity = _citation_velocity_from_info(info, paper, now_year)
    max_log = graph_context.get("max_velocity_log") or 0.0
    return _signal(
        (math.log1p(velocity) / max_log * 100) if max_log else 0,
        True,
        "medium",
        "Citation velocity estimates citations per publication-year to reduce old-paper bias.",
        "引用速度按发表年限估算年均引用，降低旧论文天然占优的偏差。",
        [{"source": "openalex", "field": "cited_by_count/year", "detail": f"velocity={velocity:.2f}"}],
    )


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


def _span_evidence(text: str, markers: Iterable[str], *, source: str, field: str, limit: int = 3) -> List[Dict[str, Any]]:
    lower = text.lower()
    spans: List[Dict[str, Any]] = []
    for marker in sorted(markers):
        index = lower.find(marker)
        if index < 0:
            continue
        start = max(0, index - 80)
        end = min(len(text), index + len(marker) + 80)
        spans.append(
            {
                "source": "papers.yaml",
                "field": field,
                "detail": marker,
                "span": {
                    "source": source,
                    "field": field,
                    "marker": marker,
                    "start": index,
                    "end": index + len(marker),
                    "text": re.sub(r"\s+", " ", text[start:end]).strip(),
                },
            }
        )
        if len(spans) >= limit:
            break
    return spans


def _score_methodology_quality(paper: Dict[str, Any]) -> Dict[str, Any]:
    text = _text_fields(paper)
    analysis = paper.get("analysis") if isinstance(paper.get("analysis"), dict) else {}
    hits = _marker_hits(text, METHODOLOGY_MARKERS)
    full_text = str(paper.get("full_text") or paper.get("fullText") or "")
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
            *_span_evidence(full_text, METHODOLOGY_MARKERS, source="full_text", field="full_text"),
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
    graph_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, float], float]:
    """Return component signals, normalized applied weights, and read-first score."""
    year = now_year or _dt.datetime.now().year
    components = {
        "topical_relevance": _score_topical_relevance(paper, config),
        "citation_impact": _score_citation_impact(paper, graph_context),
        "graph_prestige": _score_graph_prestige(paper, graph_context),
        "citation_velocity": _score_citation_velocity(paper, graph_context, year),
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


SENSITIVITY_PROFILES = {
    "balanced": DEFAULT_WEIGHTS,
    "citation_heavy": {
        "topical_relevance": 0.20,
        "citation_impact": 0.25,
        "graph_prestige": 0.25,
        "citation_velocity": 0.10,
        "methodology_quality": 0.10,
        "reproducibility": 0.05,
        "recency": 0.05,
    },
    "method_repro_heavy": {
        "topical_relevance": 0.20,
        "citation_impact": 0.05,
        "graph_prestige": 0.05,
        "citation_velocity": 0.05,
        "methodology_quality": 0.30,
        "reproducibility": 0.25,
        "recency": 0.10,
    },
    "frontier_heavy": {
        "topical_relevance": 0.20,
        "citation_impact": 0.05,
        "graph_prestige": 0.05,
        "citation_velocity": 0.25,
        "methodology_quality": 0.15,
        "reproducibility": 0.10,
        "recency": 0.20,
    },
    "topic_heavy": {
        "topical_relevance": 0.50,
        "citation_impact": 0.10,
        "graph_prestige": 0.05,
        "citation_velocity": 0.05,
        "methodology_quality": 0.15,
        "reproducibility": 0.10,
        "recency": 0.05,
    },
}


def _weighted_score(components: Dict[str, Dict[str, Any]], weights: Dict[str, float]) -> float:
    available = {key: weight for key, weight in weights.items() if components.get(key, {}).get("available")}
    denominator = sum(available.values())
    if denominator <= 0:
        return 0.0
    return _round(sum(float(components[key].get("value") or 0) * weight / denominator for key, weight in available.items()))


def _attach_rank_sensitivity(papers: List[Dict[str, Any]]) -> None:
    profile_scores: Dict[str, Dict[int, float]] = {}
    profile_ranks: Dict[str, Dict[int, int]] = {}
    for profile_id, weights in SENSITIVITY_PROFILES.items():
        scores = {
            id(paper): _weighted_score((paper.get("score") or {}).get("components", {}), weights)
            for paper in papers
            if isinstance(paper.get("score"), dict)
        }
        profile_scores[profile_id] = scores
        ranked = sorted(papers, key=lambda paper: (-scores.get(id(paper), 0), -(paper.get("year") or 0), paper.get("title") or ""))
        profile_ranks[profile_id] = {id(paper): index for index, paper in enumerate(ranked, 1)}

    for paper in papers:
        score = paper.get("score") if isinstance(paper.get("score"), dict) else {}
        ranks = {profile: rank_by_id.get(id(paper), 0) for profile, rank_by_id in profile_ranks.items()}
        rank_values = [rank for rank in ranks.values() if rank]
        if not rank_values:
            continue
        rank_range = max(rank_values) - min(rank_values)
        stability = "stable" if rank_range <= 1 else "sensitive" if rank_range <= 3 else "volatile"
        score["rank_sensitivity"] = {
            "stability": stability,
            "rank_range": rank_range,
            "profiles": {
                profile: {
                    "rank": ranks[profile],
                    "score": profile_scores[profile].get(id(paper), 0),
                }
                for profile in SENSITIVITY_PROFILES
            },
        }


def _field_roles(paper: Dict[str, Any], graph_context: Optional[Dict[str, Any]]) -> List[str]:
    score = paper.get("score") if isinstance(paper.get("score"), dict) else {}
    components = score.get("components") if isinstance(score.get("components"), dict) else {}
    roles: List[str] = []
    if components.get("citation_impact", {}).get("value", 0) >= 75 or components.get("graph_prestige", {}).get("value", 0) >= 65:
        roles.append("foundation")
    if components.get("recency", {}).get("value", 0) >= 85 or components.get("citation_velocity", {}).get("value", 0) >= 65:
        roles.append("frontier")
    info = graph_context["infos"].get(id(paper), {}) if graph_context else {}
    local_degree = 0
    if graph_context and info.get("id"):
        local_degree = graph_context["in_degree"].get(info["id"], 0) + graph_context["out_degree"].get(info["id"], 0)
    if local_degree >= 2 or len(paper.get("tags") or []) >= 3:
        roles.append("bridge")
    if components.get("methodology_quality", {}).get("value", 0) >= 70:
        roles.append("methodology_anchor")
    if components.get("reproducibility", {}).get("value", 0) >= 70:
        roles.append("reproducibility_anchor")
    return roles or ["candidate"]


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
    _merge_openalex_metadata([paper for paper in papers if isinstance(paper, dict)], config)

    updated = 0
    ranking_config = config.get("research", {}).get("ranking", {}) if isinstance(config, dict) else {}
    citation_graph_config = ranking_config.get("citation_graph", {}) if isinstance(ranking_config, dict) else {}
    graph_enabled = citation_graph_config.get("enabled", True) if isinstance(citation_graph_config, dict) else bool(citation_graph_config)
    graph_context = _citation_graph_context(papers, now_year or _dt.datetime.now().year) if graph_enabled else None
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        components, applied_weights, read_first = rank_signal_components(
            paper,
            config,
            now_year=now_year,
            graph_context=graph_context,
        )
        score = paper.get("score")
        if not isinstance(score, dict):
            score = {}
            paper["score"] = score
        score["read_first_score"] = read_first
        score["components"] = components
        score["applied_weights"] = applied_weights
        score["ranking_profile"] = RANKING_PROFILE
        score["field_roles"] = _field_roles(paper, graph_context)
        score.setdefault("warnings", [])
        updated += 1

    _attach_rank_sensitivity([paper for paper in papers if isinstance(paper, dict)])

    papers_path.write_text(
        yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return updated
