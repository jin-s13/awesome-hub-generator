"""种子论文 references 发现模块。

通过 Semantic Scholar API 获取展示池论文的参考文献列表，
将其加入 candidate 池作为新候选论文来源。
"""
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Semantic Scholar API
_S2_BASE = "https://api.semanticscholar.org/graph/v1"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s must be a number, using %.2f", name, default)
        return default
    if value < 0:
        logger.warning("%s must be non-negative, using %.2f", name, default)
        return default
    return value


def _semantic_scholar_api_key() -> str:
    return os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or os.environ.get("S2_API_KEY") or ""


def _s2_headers() -> Dict[str, str]:
    headers = {"User-Agent": "awesome-hub-generator/1.0"}
    api_key = _semantic_scholar_api_key()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _rate_limit_interval() -> float:
    return _env_float("SEMANTIC_SCHOLAR_REQUEST_INTERVAL_SECONDS", _env_float("S2_RATE_LIMIT_SECONDS", 1.0))


def _extract_arxiv_id(paper: Dict) -> Optional[str]:
    """从论文数据中提取 arXiv ID。"""
    arxiv_id = paper.get("arxiv_id") or ""
    if arxiv_id:
        return arxiv_id
    links = paper.get("links", {})
    if isinstance(links, dict):
        url = links.get("paper", "")
    else:
        url = ""
    if url:
        m = re.search(r"(\d{4}\.\d{4,5})", url)
        if m:
            return m.group(1)
    return None


def fetch_references(
    arxiv_id: str,
    max_refs: int = 50,
    timeout: int = 30,
) -> List[Dict]:
    """通过 Semantic Scholar API 获取论文的参考文献列表。

    Args:
        arxiv_id: arXiv 论文 ID（如 "2104.01268"）
        max_refs: 最多获取多少条参考文献
        timeout: HTTP 超时秒数

    Returns:
        参考文献列表，每条包含 title, abstract, authors, year, arxiv_id
    """
    url = f"{_S2_BASE}/paper/arXiv:{arxiv_id}/references"
    fields = "title,abstract,authors,year,externalIds"
    params = {"fields": fields, "limit": min(max_refs, 100)}
    data: Dict[str, Any] | None = None

    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers=_s2_headers())
            if resp.status_code == 404:
                logger.debug(f"S2: paper {arxiv_id} not found")
                return []
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                if _semantic_scholar_api_key():
                    logger.warning(
                        "S2 rate limited even with SEMANTIC_SCHOLAR_API_KEY, waiting %ss; "
                        "increase SEMANTIC_SCHOLAR_REQUEST_INTERVAL_SECONDS or reduce seed expansion volume.",
                        wait,
                    )
                else:
                    logger.warning(
                        "S2 rate limited without SEMANTIC_SCHOLAR_API_KEY, waiting %ss; "
                        "configure the repository secret to get authenticated limits.",
                        wait,
                    )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            logger.error(f"S2 API failed for {arxiv_id}: {e}")
            return []

    if data is None:
        logger.warning(f"S2 API returned no data for {arxiv_id} after retries; skipping references")
        return []

    refs = []
    for item in data.get("data", []):
        paper = item.get("citedPaper", {})
        if not paper.get("title"):
            continue
        ext_ids = paper.get("externalIds", {}) or {}
        ref_arxiv_id = ext_ids.get("ArXiv", "")
        authors = [
            a.get("name", "")
            for a in (paper.get("authors") or [])
            if a.get("name")
        ]
        refs.append(
            {
                "title": paper["title"],
                "abstract": paper.get("abstract") or "",
                "authors": authors,
                "year": paper.get("year"),
                "arxiv_id": ref_arxiv_id,
                "links": (
                    {"paper": f"https://arxiv.org/abs/{ref_arxiv_id}"}
                    if ref_arxiv_id
                    else {}
                ),
            }
        )
        if len(refs) >= max_refs:
            break

    logger.info(f"S2: {arxiv_id} -> {len(refs)} references")
    return refs


def discover_from_seeds(
    seed_papers: List[Dict],
    candidate_pool,
    max_refs_per_paper: int = 50,
    max_seeds_per_run: int = 10,
) -> int:
    """从展示池论文的 references 发现新候选论文。

    只处理 seed_expanded=False 的论文，扩展后标记为已扩展。

    Args:
        seed_papers: 展示池论文列表（papers.yaml 格式）
        candidate_pool: CandidatePool 实例
        max_refs_per_paper: 每篇种子最多获取多少 references
        max_seeds_per_run: 每次运行最多处理多少篇种子

    Returns:
        新增到 candidate 池的论文数量
    """
    # 找出需要扩展的种子论文
    seed_arxiv_ids = []
    seed_map = {}  # arxiv_id -> paper
    for p in seed_papers:
        aid = _extract_arxiv_id(p)
        if aid:
            seed_map[aid] = p
            seed_arxiv_ids.append(aid)

    if not seed_arxiv_ids:
        logger.info("No seed papers with arXiv ID to expand")
        return 0

    # 过滤出未扩展的
    unexpanded = candidate_pool.get_unexpanded_seeds(seed_arxiv_ids)
    # 同时检查 papers.yaml 中的 seed_expanded 标记
    already_expanded_in_yaml = {
        _extract_arxiv_id(p)
        for p in seed_papers
        if p.get("seed_expanded")
    }
    to_expand = [
        aid for aid in unexpanded
        if aid not in already_expanded_in_yaml
    ]

    if not to_expand:
        logger.info("All seed papers already expanded")
        return 0

    # 限制每次运行数量
    to_expand = to_expand[:max_seeds_per_run]
    logger.info(f"Expanding {len(to_expand)} seed papers...")

    total_added = 0
    for aid in to_expand:
        refs = fetch_references(aid, max_refs_per_paper)
        added = 0
        for ref in refs:
            if candidate_pool.add(ref, source="seed_ref"):
                added += 1
        total_added += added

        # 标记为已扩展
        candidate_pool.mark_seed_expanded(aid)

        logger.info(f"  {aid}: +{added} new candidates")

        # 速率限制
        time.sleep(_rate_limit_interval())

    logger.info(f"Seed discovery: +{total_added} new candidates from {len(to_expand)} seeds")
    return total_added
