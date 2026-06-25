#!/usr/bin/env python3
"""LLM 调用缓存和 token 统计。

所有需要调用模型的固定流程都应通过这个模块：
1. 用 task/model/prompt/paper/criteria 生成稳定 cache key
2. 命中缓存时跳过真实模型调用
3. 未命中时记录真实 token 消耗
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_LOCK = threading.Lock()
_DEFAULT_CACHES: Dict[str, "LLMCache"] = {}


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def stable_hash(value: Any, length: int = 16) -> str:
    """Return a short stable SHA256 hash for arbitrary JSON-like data."""
    text = value if isinstance(value, str) else _stable_json(value)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest[:length] if length else digest


def _normalize_title(title: str) -> str:
    title = re.sub(r"\s+", " ", (title or "").strip().lower())
    title = re.sub(r"[^\w\s.-]", "", title)
    return title


def paper_identity_from(
    *,
    arxiv_id: str = "",
    doi: str = "",
    semantic_scholar_id: str = "",
    title: str = "",
) -> str:
    """Build a stable paper identity from the best available identifier."""
    if arxiv_id:
        return f"arxiv:{arxiv_id.strip().lower()}"
    if doi:
        return f"doi:{doi.strip().lower()}"
    if semantic_scholar_id:
        return f"s2:{semantic_scholar_id.strip().lower()}"
    normalized = _normalize_title(title)
    if normalized:
        return f"title:{stable_hash(normalized, 20)}"
    return "paper:unknown"


def extract_arxiv_id_from_text(text: str) -> str:
    match = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", text or "")
    return match.group(1) if match else ""


def paper_identity_from_paper(paper: Dict[str, Any]) -> str:
    links = paper.get("links") or {}
    link_text = " ".join(str(v) for v in links.values()) if isinstance(links, dict) else ""
    return paper_identity_from(
        arxiv_id=paper.get("arxiv_id") or extract_arxiv_id_from_text(link_text),
        doi=paper.get("doi", ""),
        semantic_scholar_id=paper.get("semantic_scholar_id", ""),
        title=paper.get("title", ""),
    )


def estimate_tokens_from_text(text: str) -> int:
    """Rough fallback estimate when provider usage is missing."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_tokens_from_messages(messages: List[Dict[str, Any]]) -> int:
    return estimate_tokens_from_text(_stable_json(messages))


def usage_from_provider(
    usage: Any,
    *,
    prompt_fallback: int = 0,
    completion_fallback: int = 0,
) -> Dict[str, int]:
    """Normalize usage objects from Responses API or Chat Completions."""
    prompt = 0
    completion = 0
    total = 0

    if usage is None:
        prompt = prompt_fallback
        completion = completion_fallback
    elif isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total = int(usage.get("total_tokens") or 0)
    else:
        prompt = int(
            getattr(usage, "prompt_tokens", 0)
            or getattr(usage, "input_tokens", 0)
            or 0
        )
        completion = int(
            getattr(usage, "completion_tokens", 0)
            or getattr(usage, "output_tokens", 0)
            or 0
        )
        total = int(getattr(usage, "total_tokens", 0) or 0)

    if not prompt:
        prompt = prompt_fallback
    if not completion:
        completion = completion_fallback
    if not total:
        total = prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


@dataclass
class LLMCallResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_text(cls, text: str, usage: Optional[Dict[str, int]] = None) -> "LLMCallResult":
        usage = usage or {}
        return cls(
            text=text or "",
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
        )


def default_cache_path() -> Path:
    if os.environ.get("HUB_LLM_CACHE_DB"):
        return Path(os.environ["HUB_LLM_CACHE_DB"])
    data_dir = Path(os.environ.get("HUB_DATA_DIR", str(Path.cwd() / ".local/data")))
    return data_dir / "llm_cache.db"


def get_default_cache() -> "LLMCache":
    path = str(default_cache_path().resolve())
    cache = _DEFAULT_CACHES.get(path)
    if cache is None:
        cache = LLMCache(path)
        _DEFAULT_CACHES[path] = cache
    return cache


class LLMCache:
    """SQLite-backed LLM cache and call ledger."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = os.environ.get("HUB_RUN_ID") or datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        with _LOCK:
            conn = self._get_conn()
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'llm_cache'"
            ).fetchone()
            if existing:
                cols = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(llm_cache)").fetchall()
                }
                if "task_type" not in cols or "response_json" not in cols:
                    legacy_name = f"llm_cache_legacy_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    conn.execute(f"ALTER TABLE llm_cache RENAME TO {legacy_name}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    paper_identity TEXT NOT NULL,
                    abstract_hash TEXT NOT NULL,
                    criteria_hash TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    response_text TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    cache_hit INTEGER NOT NULL,
                    task_type TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    paper_identity TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_cache_task ON llm_cache(task_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_run ON llm_calls(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_task ON llm_calls(task_type)")
            conn.commit()

    def build_cache_key(
        self,
        *,
        task_type: str,
        model: str,
        prompt_version: str,
        paper_identity: str = "",
        abstract: str = "",
        criteria: Any = None,
        prompt: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, str]:
        """Build the structured cache key and component hashes."""
        paper_identity = paper_identity or "paper:unknown"
        abs_hash = stable_hash(abstract or "", 16)
        crit_hash = stable_hash(criteria or {}, 16)
        prompt_payload = messages if messages is not None else prompt
        prompt_hash = stable_hash(prompt_payload or "", 16)
        cache_key = ":".join([
            task_type,
            model or "default-model",
            prompt_version,
            paper_identity,
            f"abs:{abs_hash}",
            f"criteria:{crit_hash}",
            f"prompt:{prompt_hash}",
        ])
        return {
            "cache_key": cache_key,
            "task_type": task_type,
            "model": model or "default-model",
            "prompt_version": prompt_version,
            "paper_identity": paper_identity,
            "abstract_hash": abs_hash,
            "criteria_hash": crit_hash,
            "prompt_hash": prompt_hash,
        }

    def get_by_key(self, cache_key: str) -> Optional[Dict[str, Any]]:
        with _LOCK:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM llm_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["response"] = json.loads(data["response_json"])
        except (json.JSONDecodeError, TypeError):
            data["response"] = {"text": data.get("response_text", "")}
        return data

    def put_by_key(self, key_info: Dict[str, str], result: LLMCallResult) -> None:
        now = datetime.now().isoformat()
        response_json = {
            "text": result.text,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
        }
        with _LOCK:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO llm_cache
                   (cache_key, task_type, model, prompt_version, paper_identity,
                    abstract_hash, criteria_hash, prompt_hash, response_json,
                    response_text, prompt_tokens, completion_tokens, total_tokens,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           COALESCE((SELECT created_at FROM llm_cache WHERE cache_key = ?), ?), ?)""",
                (
                    key_info["cache_key"],
                    key_info["task_type"],
                    key_info["model"],
                    key_info["prompt_version"],
                    key_info["paper_identity"],
                    key_info["abstract_hash"],
                    key_info["criteria_hash"],
                    key_info["prompt_hash"],
                    json.dumps(response_json, ensure_ascii=False),
                    result.text,
                    result.prompt_tokens,
                    result.completion_tokens,
                    result.total_tokens,
                    key_info["cache_key"],
                    now,
                    now,
                ),
            )
            conn.commit()

    def record_call(self, key_info: Dict[str, str], *, cache_hit: bool, result: Optional[LLMCallResult] = None) -> None:
        result = result or LLMCallResult("")
        # Cache hits cost no new tokens, but they remain visible in hit counts.
        prompt_tokens = 0 if cache_hit else result.prompt_tokens
        completion_tokens = 0 if cache_hit else result.completion_tokens
        total_tokens = 0 if cache_hit else result.total_tokens
        with _LOCK:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO llm_calls
                   (run_id, cache_key, cache_hit, task_type, model, prompt_version,
                    paper_identity, prompt_tokens, completion_tokens, total_tokens, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.run_id,
                    key_info["cache_key"],
                    1 if cache_hit else 0,
                    key_info["task_type"],
                    key_info["model"],
                    key_info["prompt_version"],
                    key_info["paper_identity"],
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def get_or_call_llm(
        self,
        *,
        task_type: str,
        model: str,
        prompt_version: str,
        messages: List[Dict[str, Any]],
        call_func: Callable[[], LLMCallResult],
        paper_identity: str = "",
        abstract: str = "",
        criteria: Any = None,
    ) -> LLMCallResult:
        key_info = self.build_cache_key(
            task_type=task_type,
            model=model,
            prompt_version=prompt_version,
            paper_identity=paper_identity,
            abstract=abstract,
            criteria=criteria,
            messages=messages,
        )
        cached = self.get_by_key(key_info["cache_key"])
        if cached is not None:
            result = LLMCallResult(
                text=cached.get("response_text", ""),
                prompt_tokens=int(cached.get("prompt_tokens", 0) or 0),
                completion_tokens=int(cached.get("completion_tokens", 0) or 0),
                total_tokens=int(cached.get("total_tokens", 0) or 0),
            )
            self.record_call(key_info, cache_hit=True, result=result)
            return result

        result = call_func()
        self.record_call(key_info, cache_hit=False, result=result)
        if result.text:
            self.put_by_key(key_info, result)
        return result

    # Backward-compatible prompt-hash API.
    def get(self, prompt: str, llm_type: str = "default") -> Optional[Dict]:
        key_info = self.build_cache_key(
            task_type=llm_type,
            model="legacy",
            prompt_version="legacy_v1",
            prompt=prompt,
        )
        cached = self.get_by_key(key_info["cache_key"])
        if cached is None:
            return None
        try:
            return json.loads(cached["response_text"])
        except (json.JSONDecodeError, TypeError):
            return {"text": cached["response_text"]}

    def put(self, prompt: str, response: Dict, llm_type: str = "default"):
        key_info = self.build_cache_key(
            task_type=llm_type,
            model="legacy",
            prompt_version="legacy_v1",
            prompt=prompt,
        )
        self.put_by_key(key_info, LLMCallResult(text=json.dumps(response, ensure_ascii=False)))

    def get_or_call(self, prompt: str, llm_func, llm_type: str = "default") -> Dict:
        cached = self.get(prompt, llm_type)
        if cached is not None:
            return cached
        result = llm_func()
        if result:
            self.put(prompt, result, llm_type)
        return result

    def stats(self) -> Dict[str, Any]:
        with _LOCK:
            conn = self._get_conn()
            cache_total = conn.execute("SELECT COUNT(*) as n FROM llm_cache").fetchone()["n"]
            cache_by_task = conn.execute(
                "SELECT task_type, COUNT(*) as n FROM llm_cache GROUP BY task_type"
            ).fetchall()
            calls = conn.execute(
                """SELECT task_type,
                          COUNT(*) as calls,
                          SUM(cache_hit) as cache_hits,
                          SUM(prompt_tokens) as prompt_tokens,
                          SUM(completion_tokens) as completion_tokens,
                          SUM(total_tokens) as total_tokens
                   FROM llm_calls
                   GROUP BY task_type"""
            ).fetchall()
        return {
            "run_id": self.run_id,
            "cache_total": cache_total,
            "cache_by_task": {row["task_type"]: row["n"] for row in cache_by_task},
            "calls_by_task": {
                row["task_type"]: {
                    "calls": row["calls"] or 0,
                    "cache_hits": row["cache_hits"] or 0,
                    "prompt_tokens": row["prompt_tokens"] or 0,
                    "completion_tokens": row["completion_tokens"] or 0,
                    "total_tokens": row["total_tokens"] or 0,
                }
                for row in calls
            },
        }

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
