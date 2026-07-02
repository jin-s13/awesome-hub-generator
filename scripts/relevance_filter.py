"""论文相关性过滤：用 LLM 语义理解替代关键词匹配。

三级判断逻辑：
1. 命中 negative_keywords（关键词匹配，快速排除）→ 不相关
2. LLM 语义判断（标题+摘要）→ 相关/不相关
3. LLM 不可用时 fallback 到关键词匹配
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("relevance_filter")

try:
    from scripts.llm_cache import (
        LLMCallResult,
        get_default_cache,
        paper_identity_from,
    )
    from scripts.openai_responses import call_openai_responses
except ImportError:
    from llm_cache import (  # type: ignore
        LLMCallResult,
        get_default_cache,
        paper_identity_from,
    )
    from openai_responses import call_openai_responses  # type: ignore

# LLM config
API_KEY = os.environ.get("ARK_API_KEY", "")
API_BASE_URL = os.environ.get("ARK_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
MODEL_NAME = os.environ.get("ARK_MODEL_NAME", "deepseek-v4-flash")

# Fallback keywords (only used when LLM is unavailable)
CAD_CORE_KEYWORDS = [
    "cad", "b-rep", "brep", "boundary representation",
    "csg", "constructive solid geometry",
    "parametric model", "parametric design", "parametric cad",
    "sketch generation", "sketch inference", "cad sketch",
    "extrude", "revolve", "sweep", "loft",
    "nurbs", "bezier curve", "b-spline",
    "step file", "iges",
    "solid model", "solid modeling",
    "engineering design", "engineering draw", "engineering sketch",
    "manufactur", "3d print", "additive manufactur",
    "assembly model", "parametric assembly",
    "machining feature", "feature recognition",
    "construction sequence", "cad program", "cad code",
    "cad generation", "cad reconstruction", "cad retrieval",
    "cad alignment", "cad model",
    "text-to-cad", "text2cad", "img2cad",
    "cad query", "querycad",
    "bim", "ifc", "building information model",
]

CAD_BROAD_KEYWORDS = [
    "primitive", "wireframe", "shape generation", "shape abstraction",
    "shape parsing", "shape program", "point cloud completion",
    "mesh generation", "mesh abstraction", "reverse engineer",
    "geometric model", "curve reconstruction", "surface reconstruction",
    "superquadric", "convex decomposition", "binary space partition",
    "shape structure", "part decomposition", "part assembly",
    "roof model", "house wireframe", "building wireframe",
]

GENERIC_RELEVANCE_TERMS = {
    "agent",
    "agents",
    "ai",
    "llm",
    "llms",
    "large",
    "language",
    "model",
    "models",
    "system",
    "systems",
    "framework",
    "frameworks",
    "benchmark",
    "benchmarks",
    "evaluation",
    "evaluations",
    "tool",
    "tools",
    "use",
    "using",
    "memory",
    "rag",
    "retrieval",
    "knowledge",
    "graph",
    "graphs",
    "coding",
    "reasoning",
    "training",
    "learning",
    "task",
    "tasks",
}

RELEVANCE_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "or",
    "that",
    "the",
    "their",
    "to",
    "via",
    "with",
    "without",
}

def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

def _responses_call(messages: List[Dict], max_tokens: int) -> LLMCallResult:
    """Call /responses and return response text with token usage."""
    return call_openai_responses(
        api_key=API_KEY,
        base_url=API_BASE_URL,
        model=MODEL_NAME,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.1,
        timeout=30,
    )

def _llm_check_relevance(title: str, abstract: str, research_context: str,
                         relevance_criteria: Optional[Dict] = None) -> Optional[bool]:
    """用 LLM 判断论文是否与研究领域相关。

    Args:
        title: 论文标题
        abstract: 论文摘要
        research_context: 研究方向描述
        relevance_criteria: 配置中的 include/exclude 标准

    Returns:
        True=相关, False=不相关, None=LLM 不可用
    """
    if not API_KEY:
        return None

    # 从配置构建 prompt，不再硬编码 CAD 标准
    if relevance_criteria:
        include_items = "\n".join(f"- {item}" for item in relevance_criteria.get("include", []))
        exclude_items = "\n".join(f"- {item}" for item in relevance_criteria.get("exclude", []))
        criteria_section = f"""
A paper is RELEVANT only if its CORE CONTRIBUTION matches any of:
{include_items}

A paper is NOT RELEVANT if it is primarily about:
{exclude_items}

Adjacent terminology alone is not enough. If the paper merely mentions the topic,
uses a neighboring domain, or lacks a direct contribution to the configured scope,
mark relevant=false."""
    else:
        criteria_section = ""

    prompt = f"""You are a strict research paper curator for "{research_context}".
{criteria_section}

Return a JSON object:
{{
  "relevant": true or false,
  "reason": "Brief explanation (1 sentence)"
}}

Title: {title}
Abstract: {abstract[:2000]}

Return ONLY valid JSON, no other text."""

    try:
        messages = [{"role": "user", "content": prompt}]
        paper_identity = paper_identity_from(title=title)
        content = get_default_cache().get_or_call_llm(
            task_type="relevance_check",
            model=MODEL_NAME,
            prompt_version="relevance_v2",
            paper_identity=paper_identity,
            abstract=abstract,
            criteria={
                "research_context": research_context,
                "relevance_criteria": relevance_criteria or {},
            },
            messages=messages,
            call_func=lambda: _responses_call(messages, 256),
        ).text
        if not content.strip():
            return None
        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*"relevant"[^{}]*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            return bool(result.get("relevant", False))
        # Fallback: check for explicit true/false in text. Ambiguous text is unknown.
        lowered = content.lower()
        if "true" in lowered and "false" not in lowered:
            return True
        if "false" in lowered and "true" not in lowered:
            return False
        return None
    except Exception as e:
        logger.debug("LLM relevance check failed: %s", e)
        return None


def _llm_filter_negative(title: str, abstract: str, negative_keywords: List[str]) -> Optional[bool]:
    """用 LLM 判断论文是否命中负向关键词的语义。

    Args:
        title: 论文标题
        abstract: 论文摘要
        negative_keywords: 负向关键词列表

    Returns:
        True=命中负向（应排除）, False=未命中, None=LLM 不可用
    """
    if not API_KEY or not negative_keywords:
        return None

    kw_list = ", ".join(negative_keywords[:15])
    prompt = f"""You are a research paper curator. Determine if this paper matches any of the EXCLUDED topics.

Excluded topics: {kw_list}

Return a JSON object:
{{
  "is_excluded": true or false,
  "matched_topic": "which topic matched (or null)",
  "reason": "Brief explanation (1 sentence)"
}}

A paper should be EXCLUDED if its core subject matches any excluded topic.
A paper should NOT be excluded if it merely mentions an excluded topic in passing.

Title: {title}
Abstract: {abstract[:2000]}

Return ONLY valid JSON, no other text."""

    try:
        messages = [{"role": "user", "content": prompt}]
        content = get_default_cache().get_or_call_llm(
            task_type="negative_filter",
            model=MODEL_NAME,
            prompt_version="negative_filter_v1",
            paper_identity=paper_identity_from(title=title),
            abstract=abstract,
            criteria={"negative_keywords": negative_keywords[:15]},
            messages=messages,
            call_func=lambda: _responses_call(messages, 256),
        ).text
        json_match = re.search(r'\{[^{}]*"is_excluded"[^{}]*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            return bool(result.get("is_excluded", False))
        return None
    except Exception as e:
        logger.debug("LLM negative filter failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _get_text(paper: Dict) -> str:
    """拼接论文的可搜索文本"""
    parts = [
        paper.get("title") or "",
        paper.get("abstract") or "",
        " ".join(paper.get("tags") or []),
        paper.get("category") or "",
    ]
    return " ".join(parts).lower()


def _phrase_in_text(phrase: str, text: str) -> bool:
    normalized = _norm(phrase)
    if not normalized:
        return False
    return re.search(r"(^|[^a-z0-9])" + re.escape(normalized) + r"([^a-z0-9]|$)", text) is not None


def _add_unique(terms: List[str], term: str) -> None:
    normalized = _norm(term)
    if normalized and normalized not in terms:
        terms.append(normalized)


def _add_term_variants(terms: List[str], term: str) -> None:
    _add_unique(terms, term)
    words = _norm(term).split()
    if len(words) == 2 and words[0] == "self" and words[1].endswith("ing"):
        stem = words[1][:-3]
        if stem.endswith("ov"):
            _add_unique(terms, f"self {stem}ement")
        elif stem.endswith("v"):
            _add_unique(terms, f"self {stem[:-1]}ution")


def _informative_words(text: str) -> List[str]:
    return [
        word
        for word in _norm(text).split()
        if word not in RELEVANCE_STOPWORDS and word not in GENERIC_RELEVANCE_TERMS
    ]


def _anchor_terms_from_text(text: str) -> List[str]:
    terms: List[str] = []
    normalized = _norm(text)
    if not normalized:
        return terms

    chunks = re.split(
        r",|;|/|\(|\)|\bor\b|\band\b|\bwithout\b|\bwith\b|\bfor\b|\bvia\b|\busing\b|\bthat\b|\bto\b",
        normalized,
    )
    for chunk in chunks:
        words = _informative_words(chunk)
        if len(words) >= 2:
            _add_term_variants(terms, " ".join(words))
            for size in range(min(4, len(words)), 1, -1):
                for idx in range(0, len(words) - size + 1):
                    _add_term_variants(terms, " ".join(words[idx: idx + size]))

    words = _informative_words(normalized)
    for size in range(4, 1, -1):
        for idx in range(0, len(words) - size + 1):
            _add_term_variants(terms, " ".join(words[idx: idx + size]))

    return terms


def _strict_terms_from_criteria(relevance_criteria: Optional[Dict]) -> List[str]:
    if not relevance_criteria:
        return []

    configured = (
        relevance_criteria.get("required_terms")
        or relevance_criteria.get("fallback_required_terms")
        or relevance_criteria.get("must_match")
        or []
    )
    terms: List[str] = []
    for item in configured:
        for term in _anchor_terms_from_text(str(item)):
            _add_unique(terms, term)

    for item in relevance_criteria.get("include", []) or []:
        for term in _anchor_terms_from_text(str(item)):
            _add_unique(terms, term)

    return terms


def _strict_terms_from_keywords(domain_keywords: Optional[List[str]]) -> List[str]:
    terms: List[str] = []
    for keyword in domain_keywords or []:
        for term in _anchor_terms_from_text(str(keyword)):
            _add_unique(terms, term)
    return terms


def _strict_relevance_fallback(
    paper: Dict,
    relevance_criteria: Optional[Dict],
    domain_keywords: Optional[List[str]] = None,
) -> bool:
    """Conservative non-LLM relevance check for configured research scopes.

    When the curator has provided relevance criteria, adjacent vocabulary such as
    "agent", "LLM", "memory", or "tool use" is not enough. The fallback requires
    specific scope evidence from the criteria or strong skill/evolution patterns.
    """
    if paper.get("relevant") is False:
        return False

    text = _norm(_get_text(paper))
    title = _norm(paper.get("title") or "")
    abstract = _norm(paper.get("abstract") or "")

    for item in (relevance_criteria or {}).get("exclude", []) or []:
        excluded_terms = _strict_terms_from_criteria({"include": [item]})
        if excluded_terms and any(_phrase_in_text(term, text) for term in excluded_terms):
            positive_terms = _strict_terms_from_criteria(relevance_criteria)
            if not any(_phrase_in_text(term, text) for term in positive_terms):
                return False

    strict_terms = _strict_terms_from_criteria(relevance_criteria)
    for term in strict_terms:
        if _phrase_in_text(term, text):
            return True

    for term in _strict_terms_from_keywords(domain_keywords):
        if _phrase_in_text(term, text):
            return True

    # Without abstracts, keep only clearly scoped academic entries.
    if not abstract:
        return any(_phrase_in_text(term, title) for term in [*strict_terms, *_strict_terms_from_keywords(domain_keywords)])

    return False


def is_cad_relevant(
    paper: Dict,
    negative_keywords: Optional[List[str]] = None,
    min_score: float = 5.0,
    research_context: str = "",
    relevance_criteria: Optional[Dict] = None,
    domain_keywords: Optional[List[str]] = None,
    use_llm: bool = True,
) -> bool:
    """判断论文是否与研究方向相关。

    两阶段策略：
    1. 关键词粗筛（快速召回候选）：命中负向→排除；命中领域词→候选；有 score→候选
    2. LLM 精筛（对所有候选做最终判断）
    3. Fallback：LLM 不可用时按关键词 + score 保守判断

    Args:
        paper: 论文字典
        negative_keywords: 负向关键词列表
        min_score: 最低 score 门槛
        research_context: 研究方向描述
        relevance_criteria: 配置中的 include/exclude 标准
        domain_keywords: 领域核心关键词（来自 config），替代硬编码 CAD 词

    Returns:
        True if relevant, False if should be filtered out
    """
    title = paper.get("title") or ""
    abstract = paper.get("abstract") or ""
    text = _get_text(paper)

    if paper.get("relevant") is False:
        return False
    if paper.get("relevant") is True:
        return True

    # ========== Stage 1: 关键词粗筛 ==========

    # 1a. 负向关键词快速排除
    if negative_keywords:
        for nk in negative_keywords:
            if nk.lower() in text:
                logger.debug("关键词负向排除: %s", title[:60])
                return False

    # 当提供了 relevance_criteria 时，跳过领域特定的关键词粗筛，直接用 LLM 判断
    if relevance_criteria:
        is_candidate = True
    else:
        # 1b. 判断是否为候选论文（使用领域关键词）
        is_candidate = False

        # 领域关键词召回（优先用 config 的 domain_keywords，fallback 到 CAD_CORE_KEYWORDS）
        core_keywords = domain_keywords if domain_keywords else CAD_CORE_KEYWORDS
        for kw in core_keywords:
            if re.search(r"\b" + re.escape(kw.lower()) + r"\b", text):
                logger.debug("关键词核心命中(候选): %s", title[:60])
                is_candidate = True
                break

        # 标题相义词召回（仅 CAD fallback 模式下使用）
        if not is_candidate and not domain_keywords:
            title_lower = title.lower()
            for kw in CAD_BROAD_KEYWORDS:
                if kw in title_lower:
                    logger.debug("关键词相词命中(候选): %s", title[:60])
                    is_candidate = True
                    break

        # 有 score 的论文也是候选
        score = paper.get("score", {}).get("total")
        if not is_candidate and score is not None and score >= min_score:
            is_candidate = True

    # 无 abstract 的上游精选论文 → 没有显式范围标准时保守保留；
    # 有范围标准时必须有明确的主线证据。
    if not is_candidate and not abstract and paper.get("sources"):
        if relevance_criteria:
            return _strict_relevance_fallback(paper, relevance_criteria, domain_keywords)
        return True

    # 不是候选 → 直接排除
    if not is_candidate:
        return False

    # ========== Stage 2: LLM 精筛 ==========
    if use_llm and title and abstract and research_context:
        llm_result = _llm_check_relevance(title, abstract, research_context, relevance_criteria)
        if llm_result is True:
            return True
        if llm_result is False:
            return False
        # llm_result is None → LLM 不可用，走 fallback

    # ========== Stage 3: Fallback ==========
    if relevance_criteria:
        return _strict_relevance_fallback(paper, relevance_criteria, domain_keywords)
    return True


def filter_papers(
    papers: List[Dict],
    negative_keywords: Optional[List[str]] = None,
    min_score: float = 5.0,
    research_context: str = "",
    relevance_criteria: Optional[Dict] = None,
    domain_keywords: Optional[List[str]] = None,
    use_llm: bool = True,
    llm_workers: int = 1,
) -> Tuple[List[Dict], List[Dict]]:
    """过滤论文列表。

    Args:
        papers: 论文列表
        negative_keywords: 负向关键词
        min_score: 最低 score
        research_context: 研究方向描述
        relevance_criteria: 配置中的 include/exclude 标准
        domain_keywords: 领域核心关键词（来自 config）

    Returns:
        (relevant_papers, removed_papers)
    """
    def check_one(index: int, paper: Dict) -> Tuple[int, Dict, bool]:
        return index, paper, is_cad_relevant(
            paper,
            negative_keywords,
            min_score,
            research_context,
            relevance_criteria,
            domain_keywords,
            use_llm=use_llm,
        )

    workers = max(1, int(llm_workers or 1))
    results: List[Tuple[int, Dict, bool]] = []
    if not use_llm or len(papers) <= 1 or workers <= 1:
        for index, paper in enumerate(papers):
            results.append(check_one(index, paper))
    else:
        logger.info("LLM relevance filtering %d papers with %d workers", len(papers), workers)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(check_one, index, paper): (index, paper) for index, paper in enumerate(papers)}
            completed = 0
            for future in as_completed(futures):
                index, paper = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.warning("LLM relevance failed for %s: %s", (paper.get("title") or "")[:80], exc)
                    results.append((index, paper, False))
                completed += 1
                logger.info("LLM relevance progress: %d/%d", completed, len(papers))

    relevant = []
    removed = []
    for _index, paper, is_relevant in sorted(results, key=lambda item: item[0]):
        if is_relevant:
            relevant.append(paper)
        else:
            removed.append(paper)
    return relevant, removed
