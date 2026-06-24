"""Candidate 论文池管理（SQLite 后端）。

提供候选论文的添加、去重、状态查询和晋升管理。
所有 LLM 调用状态通过字段标记，确保幂等性。
"""
import json
import sqlite3
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    abstract TEXT,
    authors TEXT,
    year INTEGER,
    links TEXT,
    source TEXT,
    added_at TEXT,
    relevance_checked INTEGER DEFAULT 0,
    relevance_checked_at TEXT,
    promoted INTEGER DEFAULT 0,
    promoted_at TEXT,
    seed_expanded INTEGER DEFAULT 0,
    seed_expanded_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_relevance ON candidates(relevance_checked);
CREATE INDEX IF NOT EXISTS idx_promoted ON candidates(promoted);
CREATE INDEX IF NOT EXISTS idx_seed_expanded ON candidates(seed_expanded);
"""


def _dedup_key(paper: Dict) -> str:
    """计算去重键：优先用 arxiv_id，否则用 title hash。"""
    arxiv_id = paper.get("arxiv_id") or ""
    if not arxiv_id:
        links = paper.get("links", {})
        url = links.get("paper", "") if isinstance(links, dict) else ""
        if url:
            import re
            m = re.search(r"(\d{4}\.\d{4,5})", url)
            if m:
                arxiv_id = m.group(1)
    if arxiv_id:
        return arxiv_id
    title = (paper.get("title") or "").strip().lower()
    return "title:" + hashlib.md5(title.encode()).hexdigest()[:16]


class CandidatePool:
    """Candidate 论文池，SQLite 后端。"""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # === 添加 ===

    def add(self, paper: Dict, source: str = "unknown") -> bool:
        """添加单篇论文到 candidate 池。已存在则跳过。

        Returns: True 如果新增，False 如果已存在。
        """
        key = _dedup_key(paper)
        existing = self._conn.execute(
            "SELECT arxiv_id FROM candidates WHERE arxiv_id = ?", (key,)
        ).fetchone()
        if existing:
            return False

        links = paper.get("links", {})
        if not isinstance(links, dict):
            links = {}
        authors = paper.get("authors", [])
        self._conn.execute(
            """INSERT INTO candidates
               (arxiv_id, title, abstract, authors, year, links, source, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key,
                paper.get("title", ""),
                paper.get("abstract", ""),
                json.dumps(authors, ensure_ascii=False),
                paper.get("year"),
                json.dumps(links, ensure_ascii=False),
                source,
                datetime.now().isoformat(),
            ),
        )
        self._conn.commit()
        return True

    def add_batch(self, papers: List[Dict], source: str = "unknown") -> int:
        """批量添加论文。返回新增数量。"""
        added = 0
        for p in papers:
            if self.add(p, source):
                added += 1
        logger.info(f"Candidate pool: added {added}/{len(papers)} from {source}")
        return added

    # === 查询 ===

    def get_unchecked(self, limit: int = 50) -> List[Dict]:
        """获取未做相关性检查的候选论文。"""
        rows = self._conn.execute(
            """SELECT * FROM candidates
               WHERE relevance_checked = 0 AND promoted = 0
               ORDER BY added_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_unexpanded_seeds(self, arxiv_ids: List[str]) -> List[str]:
        """从给定的 arxiv_id 列表中，找出尚未做过 seed 扩展的。"""
        if not arxiv_ids:
            return []
        placeholders = ",".join("?" * len(arxiv_ids))
        rows = self._conn.execute(
            f"""SELECT arxiv_id FROM candidates
                WHERE arxiv_id IN ({placeholders})
                  AND (seed_expanded = 0 OR seed_expanded IS NULL)""",
            arxiv_ids,
        ).fetchall()
        return [r["arxiv_id"] for r in rows]

    def get_stats(self) -> Dict[str, int]:
        """获取池子统计信息。"""
        total = self._conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        unchecked = self._conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE relevance_checked = 0"
        ).fetchone()[0]
        relevant = self._conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE relevance_checked = 1"
        ).fetchone()[0]
        promoted = self._conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE promoted = 1"
        ).fetchone()[0]
        expanded = self._conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE seed_expanded = 1"
        ).fetchone()[0]
        return {
            "total": total,
            "unchecked": unchecked,
            "relevant": relevant,
            "promoted": promoted,
            "seed_expanded": expanded,
        }

    # === 状态更新 ===

    def mark_relevance(self, arxiv_id: str, relevant: bool):
        """标记相关性检查结果。"""
        self._conn.execute(
            """UPDATE candidates
               SET relevance_checked = ?, relevance_checked_at = ?
               WHERE arxiv_id = ?""",
            (1 if relevant else 2, datetime.now().isoformat(), arxiv_id),
        )
        self._conn.commit()

    def mark_promoted(self, arxiv_id: str):
        """标记为已晋升到展示池。"""
        self._conn.execute(
            """UPDATE candidates
               SET promoted = 1, promoted_at = ?, relevance_checked = 1
               WHERE arxiv_id = ?""",
            (datetime.now().isoformat(), arxiv_id),
        )
        self._conn.commit()

    def mark_seed_expanded(self, arxiv_id: str):
        """标记为已完成种子 references 扩展。"""
        self._conn.execute(
            """UPDATE candidates
               SET seed_expanded = 1, seed_expanded_at = ?
               WHERE arxiv_id = ?""",
            (datetime.now().isoformat(), arxiv_id),
        )
        self._conn.commit()

    def is_promoted(self, arxiv_id: str) -> bool:
        """检查是否已晋升。"""
        row = self._conn.execute(
            "SELECT promoted FROM candidates WHERE arxiv_id = ?", (arxiv_id,)
        ).fetchone()
        return row is not None and row["promoted"] == 1

    def is_seen(self, arxiv_id: str) -> bool:
        """检查是否已在池中。"""
        row = self._conn.execute(
            "SELECT arxiv_id FROM candidates WHERE arxiv_id = ?", (arxiv_id,)
        ).fetchone()
        return row is not None

    # === 晋升 ===

    def get_promotable(self, limit: int = 20) -> List[Dict]:
        """获取可晋升的论文（相关性检查通过但尚未晋升）。"""
        rows = self._conn.execute(
            """SELECT * FROM candidates
               WHERE relevance_checked = 1 AND promoted = 0
               ORDER BY relevance_checked_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # === 内部工具 ===

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict:
        d = dict(row)
        if d.get("authors"):
            d["authors"] = json.loads(d["authors"])
        else:
            d["authors"] = []
        if d.get("links"):
            d["links"] = json.loads(d["links"])
        else:
            d["links"] = {}
        return d
