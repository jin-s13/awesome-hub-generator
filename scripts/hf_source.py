#!/usr/bin/env python3
"""
hf_source.py — HuggingFace Daily Papers + Trending 数据源

从 HuggingFace API 抓取 Daily Papers 和 Trending Papers，
转换为 papers.yaml 兼容格式。独立实现，不依赖 dailypaper-skills。

用法:
    python scripts/hf_source.py                        # 抓取当天 daily + trending
    python scripts/hf_source.py --start 2026-06-01     # 从指定日期开始
    python scripts/hf_source.py --start 2026-06-01 --end 2026-06-07
    python scripts/hf_source.py --trending-only        # 仅抓取 trending
    python scripts/hf_source.py --daily-only           # 仅抓取 daily
"""
from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

# 确保项目根目录在 sys.path 中，支持直接运行脚本
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.researcher_adapter import _slugify

logger = logging.getLogger("hf_source")

HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HF_TRENDING_URL = "https://huggingface.co/api/daily_papers?sort=trending&limit=50"
USER_AGENT = "awesome-hub-generator/1.0"
REQUEST_TIMEOUT = 30


# ---------------------------------------------------------------------------
# HTTP 请求
# ---------------------------------------------------------------------------


def _http_get_json(url: str) -> Any:
    """用 urllib.request 发起 GET 请求并解析 JSON 响应。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except urllib.error.HTTPError as e:
        logger.error("HTTP %s 请求失败: %s", e.code, url)
        return []
    except urllib.error.URLError as e:
        logger.error("URL 错误: %s - %s", url, e.reason)
        return []
    except json.JSONDecodeError as e:
        logger.error("JSON 解析失败: %s - %s", url, e)
        return []


# ---------------------------------------------------------------------------
# 数据解析
# ---------------------------------------------------------------------------


def _parse_authors(authors: Any) -> List[str]:
    """
    兼容两种 authors 格式:
    - dict 列表: [{"name": "Author A"}, ...]
    - 字符串列表: ["Author A", ...]
    """
    if not authors or not isinstance(authors, list):
        return []
    result: List[str] = []
    for a in authors:
        if isinstance(a, dict):
            name = a.get("name", "")
        elif isinstance(a, str):
            name = a
        else:
            continue
        if name:
            result.append(name.strip())
    return result


def _build_paper_dict(paper_data: Dict, source_repo: str) -> Dict[str, Any]:
    """
    将 HF API 返回的 paper 对象转换为 papers.yaml 兼容格式。

    Args:
        paper_data: HF API 返回的 paper 对象 (含 id, title, summary 等)
        source_repo: "huggingface-daily" 或 "huggingface-trending"

    Returns:
        标准 paper dict
    """
    arxiv_id = paper_data.get("id", "")
    title = paper_data.get("title", "")
    abstract = paper_data.get("summary", "")
    upvotes = paper_data.get("upvotes", 0) or 0
    authors = _parse_authors(paper_data.get("authors", []))

    # 从 publishedAt 提取年份（统一使用 extract_year）
    from sync import extract_year
    published_at = paper_data.get("publishedAt", "")
    paper_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""
    year = extract_year({
        "published": published_at,
        "links": {"paper": paper_url},
        "venue": "arXiv",
    })

    return {
        "id": _slugify(f"{title}-{year}"),
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "year": year,
        "venue": "arXiv",
        "links": {"paper": paper_url},
        "preview": "/assets/placeholder.svg",
        "sources": [{"repo": source_repo, "category": "arxiv"}],
        "score": {"total": 0, "upvotes": upvotes},
        "tldr": "",
        "reasoning": "",
    }


def _date_range(start_date: str, end_date: str) -> List[str]:
    """生成 start_date 到 end_date（含两端）的日期字符串列表。"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates: List[str] = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def fetch_hf_daily_papers(start_date: str = None, end_date: str = None) -> List[Dict]:
    """按日期范围抓取 HF Daily Papers，返回标准论文 dict 列表。

    Args:
        start_date: 起始日期 (YYYY-MM-DD)，默认当天
        end_date: 结束日期 (YYYY-MM-DD)，默认等于 start_date

    Returns:
        论文 dict 列表
    """
    today = datetime.now().strftime("%Y-%m-%d")
    start_date = start_date or today
    end_date = end_date or start_date

    dates = _date_range(start_date, end_date)
    logger.info("抓取 HF Daily Papers: %s ~ %s (%d 天)", start_date, end_date, len(dates))

    papers: List[Dict] = []
    for date in dates:
        url = f"{HF_DAILY_PAPERS_URL}?date={date}&limit=100"
        logger.debug("请求: %s", url)
        data = _http_get_json(url)
        if not isinstance(data, list):
            logger.warning("日期 %s 返回数据格式异常，跳过", date)
            continue

        count = 0
        for item in data:
            paper_data = item.get("paper") if isinstance(item, dict) else None
            if not paper_data:
                continue
            paper = _build_paper_dict(paper_data, "huggingface-daily")
            papers.append(paper)
            count += 1

        logger.info("  日期 %s: 抓取 %d 篇", date, count)

    logger.info("HF Daily Papers 共抓取 %d 篇", len(papers))
    return papers


def fetch_hf_trending_papers() -> List[Dict]:
    """抓取 HF Trending Papers。

    Returns:
        论文 dict 列表
    """
    logger.info("抓取 HF Trending Papers...")
    data = _http_get_json(HF_TRENDING_URL)
    if not isinstance(data, list):
        logger.warning("Trending 返回数据格式异常")
        return []

    papers: List[Dict] = []
    for item in data:
        paper_data = item.get("paper") if isinstance(item, dict) else None
        if not paper_data:
            continue
        paper = _build_paper_dict(paper_data, "huggingface-trending")
        papers.append(paper)

    logger.info("HF Trending Papers 共抓取 %d 篇", len(papers))
    return papers


def _merge_papers(daily_papers: List[Dict], trending_papers: List[Dict]) -> List[Dict]:
    """
    合并 daily 和 trending 论文列表。

    同一 arxiv_id 在两边都出现时:
    - 合并 sources 列表
    - 保留更高的 upvotes

    Args:
        daily_papers: daily 论文列表
        trending_papers: trending 论文列表

    Returns:
        合并去重后的论文列表
    """
    merged: Dict[str, Dict] = {}

    for paper in daily_papers + trending_papers:
        arxiv_url = paper.get("links", {}).get("paper", "")
        key = arxiv_url or paper.get("id", "")

        if key in merged:
            existing = merged[key]
            # 合并 sources
            existing_sources = existing.get("sources", [])
            new_sources = paper.get("sources", [])
            existing_repos = {s.get("repo") for s in existing_sources}
            for s in new_sources:
                if s.get("repo") not in existing_repos:
                    existing_sources.append(s)
                    existing_repos.add(s.get("repo"))
            existing["sources"] = existing_sources

            # 保留更高 upvotes
            existing_upvotes = existing.get("score", {}).get("upvotes", 0)
            new_upvotes = paper.get("score", {}).get("upvotes", 0)
            if new_upvotes > existing_upvotes:
                existing["score"]["upvotes"] = new_upvotes
        else:
            merged[key] = paper

    return list(merged.values())


def fetch_all_hf_papers(config: dict) -> List[Dict]:
    """根据 config['research']['sources'] 配置，抓取所有启用的 HF 数据源。

    Args:
        config: awesome.yaml 配置 dict

    Returns:
        合并去重后的论文列表
    """
    sources = config.get("research", {}).get("sources", {})

    daily_enabled = sources.get("huggingface_daily", False)
    trending_enabled = sources.get("huggingface_trending", False)

    if not daily_enabled and not trending_enabled:
        logger.info("未启用任何 HF 数据源")
        return []

    daily_papers: List[Dict] = []
    trending_papers: List[Dict] = []

    if daily_enabled:
        date_from = config.get("research", {}).get("date_from")
        if date_from:
            today = datetime.now()
            start = datetime.strptime(date_from, "%Y-%m-%d")
            # 限制 HF Daily 最多抓取 90 天，避免逐天请求过多
            max_days = 90
            if (today - start).days > max_days:
                start = today - timedelta(days=max_days)
                logger.warning(
                    "HF Daily 日期范围超过 %d 天，仅抓取最近 %d 天 (%s ~ %s)",
                    max_days, max_days, start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"),
                )
            daily_papers = fetch_hf_daily_papers(
                start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
            )
        else:
            daily_papers = fetch_hf_daily_papers()

    if trending_enabled:
        trending_papers = fetch_hf_trending_papers()

    merged = _merge_papers(daily_papers, trending_papers)
    logger.info("HF 数据源合并后共 %d 篇论文", len(merged))
    return merged


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="HuggingFace Daily Papers + Trending 数据源"
    )
    parser.add_argument("--start", default=None, help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="结束日期 (YYYY-MM-DD)")
    parser.add_argument(
        "--trending-only", action="store_true", help="仅抓取 trending"
    )
    parser.add_argument(
        "--daily-only", action="store_true", help="仅抓取 daily"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    if args.trending_only:
        papers = fetch_hf_trending_papers()
    elif args.daily_only:
        papers = fetch_hf_daily_papers(args.start, args.end)
    else:
        daily_papers = fetch_hf_daily_papers(args.start, args.end)
        trending_papers = fetch_hf_trending_papers()
        papers = _merge_papers(daily_papers, trending_papers)

    print(f"\n=== 抓取结果统计 ===")
    print(f"总计: {len(papers)} 篇")

    source_counts: Dict[str, int] = {}
    for p in papers:
        for s in p.get("sources", []):
            repo = s.get("repo", "unknown")
            source_counts[repo] = source_counts.get(repo, 0) + 1

    for repo, count in sorted(source_counts.items()):
        print(f"  {repo}: {count} 篇")

    if papers:
        print(f"\n前 5 篇论文:")
        for p in papers[:5]:
            upvotes = p.get("score", {}).get("upvotes", 0)
            print(f"  [{upvotes}↑] {p['title'][:80]}")


if __name__ == "__main__":
    main()
