"""CAD 相关性过滤：判断论文是否与计算机辅助设计（CAD）相关。

三级判断逻辑：
1. 命中 negative_keywords → 不相关（删除）
2. 有 CAD 核心词 → 相关（保留）
3. 无 CAD 核心词且 score 低 → 不相关（删除）
4. 无 CAD 核心词且无 score → 看标题是否有 CAD 相义词
"""
from __future__ import annotations
from typing import Dict, List, Optional

# CAD 核心关键词（命中任一即认为相关）
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

# CAD 相义词（弱相关，需组合判断）
CAD_BROAD_KEYWORDS = [
    "primitive", "wireframe", "shape generation", "shape abstraction",
    "shape parsing", "shape program", "point cloud completion",
    "mesh generation", "mesh abstraction", "reverse engineer",
    "geometric model", "curve reconstruction", "surface reconstruction",
    "superquadric", "convex decomposition", "binary space partition",
    "shape structure", "part decomposition", "part assembly",
    "roof model", "house wireframe", "building wireframe",
]


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
) -> bool:
    """判断论文是否与 CAD 相关。

    Args:
        paper: 论文字典
        negative_keywords: 负向关键词列表（命中则不相关）
        min_score: 无 CAD 核心词时的最低 score 门槛
    Returns:
        True if relevant, False if should be filtered out
    """
    text = _get_text(paper)

    # 1. 命中 negative_keywords → 不相关
    if negative_keywords:
        for nk in negative_keywords:
            if nk.lower() in text:
                return False

    # 2. 有 CAD 核心词 → 相关
    for kw in CAD_CORE_KEYWORDS:
        if kw in text:
            return True

    # 3. 标题含 CAD 相义词 → 相关（线框/建筑/形状抽象等）
    title = (paper.get("title") or "").lower()
    for kw in CAD_BROAD_KEYWORDS:
        if kw in title:
            return True

    # 4. 有 score → 看分数
    score = paper.get("score", {}).get("total")
    if score is not None and score >= min_score:
        return True

    # 5. 无 abstract 的上游精选论文 → 保守保留
    if not paper.get("abstract") and paper.get("sources"):
        return True

    # 6. 有 abstract 但无核心词/相义词且 score 低 → 不相关
    return False


def filter_papers(
    papers: List[Dict],
    negative_keywords: Optional[List[str]] = None,
    min_score: float = 5.0,
) -> tuple:
    """过滤论文列表。

    Returns:
        (relevant_papers, removed_papers)
    """
    relevant = []
    removed = []
    for paper in papers:
        if is_cad_relevant(paper, negative_keywords, min_score):
            relevant.append(paper)
        else:
            removed.append(paper)
    return relevant, removed
