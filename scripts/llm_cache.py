#!/usr/bin/env python3
"""LLM 调用缓存 — 避免相同 prompt 重复调用 LLM。

使用 SQLite 存储，按 prompt 的 hash 作为 key。
所有 LLM 调用（相关性筛选、分类、解读等）都应通过此模块。
"""

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, Optional

_LOCK = threading.Lock()


def _hash_prompt(prompt: str) -> str:
    """对 prompt 做 SHA256 hash 作为 cache key。"""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class LLMCache:
    """LLM 调用缓存，线程安全。"""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """每个线程使用独立的连接。"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        with _LOCK:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    prompt_hash TEXT NOT NULL,
                    response TEXT NOT NULL,
                    llm_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_type
                ON llm_cache(llm_type)
            """)
            conn.commit()

    def get(self, prompt: str, llm_type: str = "default") -> Optional[Dict]:
        """查询缓存。命中返回 dict，未命中返回 None。"""
        key = _hash_prompt(prompt)
        with _LOCK:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT response FROM llm_cache WHERE cache_key = ? AND llm_type = ?",
                (key, llm_type),
            ).fetchone()
        if row:
            try:
                return json.loads(row["response"])
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def put(self, prompt: str, response: Dict, llm_type: str = "default"):
        """写入缓存。"""
        key = _hash_prompt(prompt)
        with _LOCK:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO llm_cache
                   (cache_key, prompt_hash, response, llm_type, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, key[:16], json.dumps(response, ensure_ascii=False),
                 llm_type, datetime.now().isoformat()),
            )
            conn.commit()

    def get_or_call(self, prompt: str, llm_func, llm_type: str = "default") -> Dict:
        """查询缓存，未命中则调用 llm_func 并缓存结果。

        Args:
            prompt: LLM prompt
            llm_func: 无参数的 callable，返回 dict
            llm_type: LLM 调用类型（relevance / classify / tldr / analysis / translate）
        """
        cached = self.get(prompt, llm_type)
        if cached is not None:
            return cached
        result = llm_func()
        if result:
            self.put(prompt, result, llm_type)
        return result

    def stats(self) -> Dict[str, int]:
        """返回缓存统计。"""
        with _LOCK:
            conn = self._get_conn()
            total = conn.execute("SELECT COUNT(*) as n FROM llm_cache").fetchone()["n"]
            by_type = conn.execute(
                "SELECT llm_type, COUNT(*) as n FROM llm_cache GROUP BY llm_type"
            ).fetchall()
        return {
            "total": total,
            **{row["llm_type"]: row["n"] for row in by_type},
        }

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
