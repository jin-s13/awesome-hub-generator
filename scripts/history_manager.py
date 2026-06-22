#!/usr/bin/env python3
"""
history_manager.py — 跨天去重历史记录管理

维护跨天去重状态，避免每日更新时重复推荐已推荐过的论文。

数据结构 (DATA_DIR / ".history.json"):
    [
      {"id": "2401.12345", "date": "2026-06-22", "title": "论文标题"},
      ...
    ]

独立实现，不依赖 dailypaper-skills。

用法:
    python scripts/history_manager.py --stats
    python scripts/history_manager.py --prune
    python scripts/history_manager.py --prune --stats
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

SITE_DIR = Path.cwd()

# Load .env file: check CWD first, then ROOT
for _env_path in [SITE_DIR / ".env", ROOT / ".env"]:
    if _env_path.exists():
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))
        break

DATA_DIR = Path(os.environ.get("HUB_DATA_DIR", str(SITE_DIR / ".local/data")))

logger = logging.getLogger("history_manager")


# Regex to extract arxiv_id from URL: arxiv.org/(abs|html|pdf)/<id>
_ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|html|pdf)/(\d+\.\d+)")


def _extract_arxiv_id(paper: Dict) -> str:
    """从 paper["links"]["paper"] URL 中正则提取 arxiv_id。

    如果无法提取，返回空字符串。
    """
    url = (paper.get("links") or {}).get("paper", "") or ""
    m = _ARXIV_ID_RE.search(url)
    return m.group(1) if m else ""


def _dedup_key(paper: Dict) -> str:
    """获取去重键：优先 arxiv_id，fallback 用 title.lower().strip()。"""
    arxiv_id = _extract_arxiv_id(paper)
    if arxiv_id:
        return arxiv_id
    return (paper.get("title") or "").lower().strip()


def _is_trending_paper(paper: Dict) -> bool:
    """判断论文是否来自 trending 源（如 huggingface-trending / hf-trending）。"""
    # Check sources list: [{"repo": "huggingface-trending", "category": ...}]
    for src in (paper.get("sources") or []):
        repo = ""
        if isinstance(src, dict):
            repo = src.get("repo", "") or ""
        elif isinstance(src, str):
            repo = src
        if "trending" in repo.lower():
            return True
    # Check direct source field (e.g. paper["source"] = "hf-trending")
    direct_source = (paper.get("source") or "").lower()
    if "trending" in direct_source:
        return True
    return False


def _is_weekend(dt: Optional[datetime] = None) -> bool:
    """判断给定日期是否为周末（周六日）。weekday() >= 5。"""
    dt = dt or datetime.now()
    return dt.weekday() >= 5


class HistoryManager:
    """跨天去重历史记录管理器。

    维护一个 JSON 文件，记录已推荐过的论文 ID 和日期，
    用于跨天去重，避免每日更新时重复推荐。
    """

    def __init__(self, history_path: Path, retention_days: int = 30):
        """初始化历史记录管理器。

        Args:
            history_path: 历史记录 JSON 文件路径。
            retention_days: 超过 N 天的记录自动删除。
        """
        self.history_path = Path(history_path)
        self.retention_days = retention_days

    def load(self) -> List[Dict]:
        """加载历史记录，返回列表。

        文件不存在时返回空列表。
        JSON 解析失败时返回空列表并警告。
        """
        if not self.history_path.exists():
            return []
        try:
            with open(self.history_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"历史记录解析失败，返回空列表: {e}")
            return []

    def save(self, entries: List[Dict]) -> None:
        """保存历史记录。"""
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    def get_seen_ids(self) -> Dict[str, str]:
        """返回 {arxiv_id: earliest_date} 字典，同一 ID 保留最早日期。"""
        seen: Dict[str, str] = {}
        for entry in self.load():
            eid = entry.get("id", "")
            edate = entry.get("date", "")
            if not eid:
                continue
            if eid not in seen or (edate and edate < seen[eid]):
                seen[eid] = edate
        return seen

    def add_entries(self, papers: List[Dict], date: str = None) -> int:
        """添加论文到历史记录。按 title/id 去重，保留最早 date。

        Args:
            papers: 论文列表（papers.yaml 格式）。
            date: 日期字符串 "YYYY-MM-DD"，默认当天。

        Returns:
            新增数量。
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        history = self.load()

        # Build seen index from existing history (keep earliest date)
        seen: Dict[str, str] = {}
        for entry in history:
            eid = entry.get("id", "")
            edate = entry.get("date", "")
            if eid and (eid not in seen or (edate and edate < seen[eid])):
                seen[eid] = edate

        added = 0
        for paper in papers:
            key = _dedup_key(paper)
            if not key:
                continue
            title = (paper.get("title") or "")[:200]

            if key not in seen:
                history.append({"id": key, "date": date, "title": title})
                seen[key] = date
                added += 1
            elif date < seen[key]:
                # Update to preserve earliest date
                for entry in history:
                    if entry.get("id") == key:
                        entry["date"] = date
                        break
                seen[key] = date

        self.save(history)
        return added

    def prune(self) -> int:
        """删除超过 retention_days 的记录。

        Returns:
            删除数量。
        """
        history = self.load()
        cutoff = (datetime.now() - timedelta(days=self.retention_days)).strftime("%Y-%m-%d")
        kept = [h for h in history if h.get("date", "") >= cutoff]
        removed = len(history) - len(kept)
        if removed > 0:
            self.save(kept)
        return removed

    def filter_seen(
        self, papers: List[Dict], weekend_mode: bool = False
    ) -> Tuple[List[Dict], List[Dict]]:
        """将论文分为 (new, seen) 两组。

        Args:
            papers: 论文列表。
            weekend_mode: True 时，周末（周六日）放宽规则：
                来源为 "huggingface-trending" 的论文可再推，
                标记 paper["is_re_recommend"] = True。

        Returns:
            (new_papers, seen_papers) 元组。
        """
        seen_ids = self.get_seen_ids()
        is_weekend = _is_weekend() if weekend_mode else False

        new_papers: List[Dict] = []
        seen_papers: List[Dict] = []

        for paper in papers:
            key = _dedup_key(paper)
            if key and key in seen_ids:
                # Already seen
                if weekend_mode and is_weekend and _is_trending_paper(paper):
                    # Weekend relaxation: trending papers can be re-recommended
                    paper["is_re_recommend"] = True
                    new_papers.append(paper)
                else:
                    seen_papers.append(paper)
            else:
                new_papers.append(paper)

        return new_papers, seen_papers

    def backfill(
        self, seen_papers: List[Dict], min_count: int = 20
    ) -> List[Dict]:
        """当新论文不足 min_count 时，从已见论文中按 score 回填。

        从 seen_papers 中按 score.total 降序取，补足到 min_count。
        标记回填论文 paper["is_re_recommend"] = True。

        Args:
            seen_papers: 已见论文列表。
            min_count: 需要回填的论文数量。

        Returns:
            回填的论文列表（已标记 is_re_recommend=True）。
        """
        if not seen_papers or min_count <= 0:
            return []

        def _score_total(p: Dict) -> float:
            score = p.get("score")
            if isinstance(score, dict):
                return float(score.get("total") or 0.0)
            if isinstance(score, (int, float)):
                return float(score)
            return 0.0

        sorted_papers = sorted(seen_papers, key=_score_total, reverse=True)
        backfill_papers = sorted_papers[:min_count]
        for p in backfill_papers:
            p["is_re_recommend"] = True
        return backfill_papers


def main():
    """CLI 入口：查看/清理历史记录"""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="跨天去重历史记录管理")
    parser.add_argument(
        "--history-path",
        default=str(DATA_DIR / ".history.json"),
        help=f"历史记录文件路径 (默认: {DATA_DIR / '.history.json'})",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=30,
        help="保留天数（超过则清理），默认 30",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="手动清理超过 retention_days 的记录",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="查看历史记录统计",
    )
    args = parser.parse_args()

    manager = HistoryManager(Path(args.history_path), args.retention_days)

    # --prune: clean up old entries
    if args.prune:
        removed = manager.prune()
        logger.info(f"清理完成：删除 {removed} 条过期记录（>{args.retention_days} 天）")

    # --stats or default (no args): show statistics
    show_stats = args.stats or not args.prune
    if show_stats:
        entries = manager.load()
        if not entries:
            logger.info("历史记录为空")
            return

        dates = [e.get("date", "") for e in entries if e.get("date")]
        date_range = f"{min(dates)} ~ {max(dates)}" if dates else "N/A"

        logger.info(f"历史记录路径: {manager.history_path}")
        logger.info(f"记录总数: {len(entries)} 条")
        logger.info(f"日期范围: {date_range}")
        logger.info(f"保留天数: {args.retention_days} 天")

        # Date distribution
        date_counts: Dict[str, int] = {}
        for d in dates:
            date_counts[d] = date_counts.get(d, 0) + 1
        if date_counts:
            logger.info("按日期分布:")
            for d in sorted(date_counts.keys(), reverse=True):
                logger.info(f"  {d}: {date_counts[d]} 条")


if __name__ == "__main__":
    main()
