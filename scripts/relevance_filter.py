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
        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*"relevant"[^{}]*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            return bool(result.get("relevant", False))
        # Fallback: check for true/false in text
        return "true" in content.lower() and "false" not in content.lower()
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


def is_cad_relevant(
    paper: Dict,
    negative_keywords: Optional[List[str]] = None,
    min_score: float = 5.0,
    research_context: str = "",
    relevance_criteria: Optional[Dict] = None,
    domain_keywords: Optional[List[str]] = None,
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

    # 无 abstract 的上游精选论文 → 保守保留
    if not is_candidate and not abstract and paper.get("sources"):
        return True

    # 不是候选 → 直接排除
    if not is_candidate:
        return False

    # ========== Stage 2: LLM 精筛 ==========
    if title and abstract and research_context:
        llm_result = _llm_check_relevance(title, abstract, research_context, relevance_criteria)
        if llm_result is True:
            return True
        if llm_result is False:
            return False
        # llm_result is None → LLM 不可用，走 fallback

    # ========== Stage 3: Fallback ==========
    return True


def filter_papers(
    papers: List[Dict],
    negative_keywords: Optional[List[str]] = None,
    min_score: float = 5.0,
    research_context: str = "",
    relevance_criteria: Optional[Dict] = None,
    domain_keywords: Optional[List[str]] = None,
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
    relevant = []
    removed = []
    for paper in papers:
        if is_cad_relevant(paper, negative_keywords, min_score, research_context, relevance_criteria, domain_keywords):
            relevant.append(paper)
        else:
            removed.append(paper)
    return relevant, removed
