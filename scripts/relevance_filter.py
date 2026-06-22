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

# LLM config
API_KEY = os.environ.get("ARK_API_KEY", "")
API_BASE_URL = os.environ.get("ARK_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
MODEL_NAME = os.environ.get("ARK_MODEL_NAME", "deepseek-v4-flash-260425")

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

def _llm_check_relevance(title: str, abstract: str, research_context: str) -> Optional[bool]:
    """用 LLM 判断论文是否与研究领域相关。

    Args:
        title: 论文标题
        abstract: 论文摘要
        research_context: 研究方向描述（从 awesome.yaml project.name 获取）

    Returns:
        True=相关, False=不相关, None=LLM 不可用
    """
    if not API_KEY:
        return None

    prompt = f"""You are a research paper curator. Determine if this paper is relevant to "{research_context}".

Return a JSON object:
{{
  "relevant": true or false,
  "reason": "Brief explanation (1 sentence)"
}}

Title: {title}
Abstract: {abstract[:2000]}

Return ONLY valid JSON, no other text."""

    import urllib.request

    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 256,
        "temperature": 0.1,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{API_BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
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

    import urllib.request

    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 256,
        "temperature": 0.1,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{API_BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
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
) -> bool:
    """判断论文是否与研究方向相关。

    两阶段策略：
    1. 关键词粗筛（快速）：命中负向→排除，命中核心词→保留
    2. LLM 精筛（处理模糊地带）：关键词无法确定时用 LLM 语义判断
    3. Fallback：LLM 不可用时用关键词宽匹配 + score

    Args:
        paper: 论文字典
        negative_keywords: 负向关键词列表
        min_score: 最低 score 门槛
        research_context: 研究方向描述

    Returns:
        True if relevant, False if should be filtered out
    """
    title = paper.get("title") or ""
    abstract = paper.get("abstract") or ""
    text = _get_text(paper)

    # ========== Stage 1: 关键词粗筛（快速，零成本） ==========

    # 1a. 负向关键词快速排除
    if negative_keywords:
        for nk in negative_keywords:
            if nk.lower() in text:
                logger.debug("关键词负向排除: %s", title[:60])
                return False

    # 1b. 核心关键词快速召回（命中即保留，不需要 LLM）
    for kw in CAD_CORE_KEYWORDS:
        if kw in text:
            logger.debug("关键词核心命中: %s", title[:60])
            return True

    # 1c. 标题相义词快速召回
    title_lower = title.lower()
    for kw in CAD_BROAD_KEYWORDS:
        if kw in title_lower:
            logger.debug("关键词相词命中: %s", title[:60])
            return True

    # ========== Stage 2: LLM 精筛（处理模糊地带） ==========

    # 有 score 的论文：高分直接保留，低分用 LLM 判断
    score = paper.get("score", {}).get("total")
    if score is not None and score >= min_score:
        # 高分论文，用 LLM 确认（可选，因为关键词没命中但 score 高）
        if title and abstract and research_context:
            llm_result = _llm_check_relevance(title, abstract, research_context)
            if llm_result is True:
                logger.debug("LLM 确认保留(高分): %s", title[:60])
                return True
            if llm_result is False:
                logger.debug("LLM 排除(高分): %s", title[:60])
                return False
        # LLM 不可用，按 score 保留
        return True

    # 无 score 或低分论文：用 LLM 判断
    if title and abstract and research_context:
        llm_result = _llm_check_relevance(title, abstract, research_context)
        if llm_result is True:
            logger.debug("LLM 判定相关: %s", title[:60])
            return True
        if llm_result is False:
            logger.debug("LLM 判定不相关: %s", title[:60])
            return False
        # llm_result is None → LLM 不可用，走 fallback

    # ========== Stage 3: Fallback（LLM 不可用时） ==========

    # 无 abstract 的上游精选论文 → 保守保留
    if not paper.get("abstract") and paper.get("sources"):
        return True

    return False


def filter_papers(
    papers: List[Dict],
    negative_keywords: Optional[List[str]] = None,
    min_score: float = 5.0,
    research_context: str = "",
) -> Tuple[List[Dict], List[Dict]]:
    """过滤论文列表。

    Args:
        papers: 论文列表
        negative_keywords: 负向关键词
        min_score: 最低 score
        research_context: 研究方向描述

    Returns:
        (relevant_papers, removed_papers)
    """
    relevant = []
    removed = []
    for paper in papers:
        if is_cad_relevant(paper, negative_keywords, min_score, research_context):
            relevant.append(paper)
        else:
            removed.append(paper)
    return relevant, removed
