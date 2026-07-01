#!/usr/bin/env python3
"""
discover_sources.py — 自动发现 GitHub 上的 awesome 项目

通过 GitHub Search API 搜索研究方向相关的 awesome 项目，
过滤、排序后返回候选源列表。

用法:
    python scripts/discover_sources.py --keywords CAD "B-Rep"
    python scripts/discover_sources.py --hub awesome-cad-hub  # 从本地 hub 配置读取关键词
"""
from __future__ import annotations

import os
import json
import re
import time
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parents[1]
GENERIC_DISCOVERY_TERMS = {
    "a",
    "ai",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "deep",
    "computer",
    "aided",
    "design",
    "program",
    "programs",
    "programming",
    "generation",
    "generative",
    "reconstruction",
    "text",
    "image",
    "point",
    "cloud",
    "tool",
    "tools",
    "resource",
    "resources",
    "learning",
    "machine",
    "model",
    "models",
    "paper",
    "papers",
    "awesome",
}
CAD_ANCHOR_TERMS = {"cad", "brep", "b-rep", "csg", "nurbs", "cae", "cam", "parametric", "sketch", "extrusion"}


@dataclass
class SourceInfo:
    """上游 awesome 项目信息"""
    full_name: str            # e.g. "owner/repo"
    html_url: str             # GitHub URL
    stars: int
    description: str
    default_branch: str       # e.g. "main" or "master"
    topics: List[str] = field(default_factory=list)


class GitHubDiscoverer:
    """GitHub awesome 项目发现器"""

    def __init__(
        self,
        token: str = "",
        wait_on_rate_limit: bool = True,
        api_version: str = "",
        cache_path: str | Path | None = None,
        search_interval_seconds: float | None = None,
        core_interval_seconds: float | None = None,
        max_rate_limit_sleep_seconds: float | None = None,
    ):
        self.token = token or os.environ.get("GH_TOKEN", "")
        self.wait_on_rate_limit = wait_on_rate_limit
        self.api_version = api_version or os.environ.get("GITHUB_API_VERSION", "2026-03-10")
        self.search_interval_seconds = (
            float(os.environ.get("GITHUB_SEARCH_INTERVAL_SECONDS", "2.5"))
            if search_interval_seconds is None
            else float(search_interval_seconds)
        )
        self.core_interval_seconds = (
            float(os.environ.get("GITHUB_CORE_INTERVAL_SECONDS", "0.25"))
            if core_interval_seconds is None
            else float(core_interval_seconds)
        )
        self.max_rate_limit_sleep_seconds = (
            float(os.environ.get("GITHUB_RATE_LIMIT_MAX_SLEEP_SECONDS", "600"))
            if max_rate_limit_sleep_seconds is None
            else float(max_rate_limit_sleep_seconds)
        )
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: Dict[str, Dict[str, Any]] = self._load_cache()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "awesome-hub-generator/1.0",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
        })
        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        self._rate_limits: Dict[str, Dict[str, int]] = {}
        self._exhausted_buckets: set[str] = set()
        self._rate_limit_warning_printed = False
        self._last_request_at = {"search": 0.0, "core": 0.0}

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        if not self.cache_path or not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _header(headers: Dict[str, Any], name: str) -> str:
        lowered = name.lower()
        for key, value in headers.items():
            if key.lower() == lowered:
                return str(value)
        return ""

    @staticmethod
    def _cache_key(url: str, params: Optional[Dict[str, Any]]) -> str:
        query = urlencode(sorted((params or {}).items()), doseq=True)
        return f"{url}?{query}" if query else url

    def _throttle(self, bucket: str) -> None:
        interval = self.search_interval_seconds if bucket == "search" else self.core_interval_seconds
        if interval <= 0:
            return
        now = time.time()
        elapsed = now - self._last_request_at.get(bucket, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def _mark_requested(self, bucket: str) -> None:
        self._last_request_at[bucket] = time.time()

    def _update_rate_limit_state(self, headers: Dict[str, Any], bucket: str) -> None:
        remaining = self._header(headers, "x-ratelimit-remaining")
        reset = self._header(headers, "x-ratelimit-reset")
        resource = self._header(headers, "x-ratelimit-resource") or bucket
        if not remaining and not reset:
            return
        state = self._rate_limits.setdefault(resource, {})
        if remaining:
            try:
                state["remaining"] = int(remaining)
            except ValueError:
                pass
        if reset:
            try:
                state["reset"] = int(float(reset))
            except ValueError:
                pass

    def _rate_limit_wait_seconds(self, headers: Dict[str, Any], bucket: str, fallback: float = 5.0) -> float:
        retry_after = self._header(headers, "retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        reset = self._header(headers, "x-ratelimit-reset")
        if reset:
            try:
                return max(0.0, float(reset) - time.time() + 1)
            except ValueError:
                pass
        state = self._rate_limits.get(bucket, {})
        if state.get("remaining") == 0 and state.get("reset"):
            return max(0.0, float(state["reset"]) - time.time() + 1)
        return fallback

    def _sleep_for_rate_limit(self, bucket: str, seconds: float, reason: str) -> bool:
        if not self.wait_on_rate_limit:
            self._exhausted_buckets.add(bucket)
            self._warn_rate_limit(f"{reason}，停止本轮自动发现；可配置 GH_TOKEN 或稍后重试。")
            return False
        if seconds > self.max_rate_limit_sleep_seconds:
            self._exhausted_buckets.add(bucket)
            self._warn_rate_limit(
                f"{reason}，需要等待 {seconds:.0f}s，超过上限 {self.max_rate_limit_sleep_seconds:.0f}s；停止本轮自动发现。"
            )
            return False
        print(f"[discover] WARNING: {reason}，等待 {seconds:.0f}s 后继续。")
        time.sleep(seconds)
        return True

    def _check_rate_limit(self, bucket: str) -> bool:
        if bucket in self._exhausted_buckets:
            return False
        state = self._rate_limits.get(bucket, {})
        if state.get("remaining") == 0 and state.get("reset"):
            seconds = max(0.0, float(state["reset"]) - time.time() + 1)
            return self._sleep_for_rate_limit(bucket, seconds, f"GitHub {bucket} API 限流")
        return True

    def _warn_rate_limit(self, message: str) -> None:
        if self._rate_limit_warning_printed:
            return
        print(f"[discover] WARNING: {message}")
        self._rate_limit_warning_printed = True

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None, bucket: str = "core") -> Dict[str, Any]:
        text = self._get_text(url, params=params, bucket=bucket)
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def _get_text(self, url: str, params: Optional[Dict[str, Any]] = None, bucket: str = "core") -> str:
        cache_key = self._cache_key(url, params)
        headers: Dict[str, str] = {}
        cached = self.cache.get(cache_key)
        if cached and cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])

        for attempt in range(3):
            if not self._check_rate_limit(bucket):
                return ""
            self._throttle(bucket)
            resp = self.session.get(url, params=params, timeout=30, headers=headers)
            self._mark_requested(bucket)
            self._update_rate_limit_state(resp.headers, bucket)

            if resp.status_code == 304 and cached:
                return str(cached.get("text") or "")
            if resp.status_code in {403, 429}:
                seconds = self._rate_limit_wait_seconds(resp.headers, bucket, fallback=5.0 * (attempt + 1))
                if attempt < 2 and self._sleep_for_rate_limit(bucket, seconds, "GitHub API 限流或 secondary rate limit"):
                    continue
                return ""
            if resp.status_code != 200:
                print(f"[discover] GitHub API 错误: {resp.status_code} {resp.text[:200]}")
                return ""

            etag = self._header(resp.headers, "etag")
            if etag:
                self.cache[cache_key] = {"etag": etag, "text": resp.text, "cached_at": int(time.time())}
                self._save_cache()
            return resp.text
        return ""

    def _search_repos(self, query: str, sort: str = "stars",
                      order: str = "desc", per_page: int = 10) -> List[Dict]:
        """执行 GitHub Search API 调用"""
        url = "https://api.github.com/search/repositories"
        params = {"q": query, "sort": sort, "order": order, "per_page": per_page}
        payload = self._get_json(url, params=params, bucket="search")

        return payload.get("items", []) if isinstance(payload, dict) else []

    @staticmethod
    def _item_to_source(item: Dict) -> SourceInfo:
        return SourceInfo(
            full_name=item["full_name"],
            html_url=item["html_url"],
            stars=item.get("stargazers_count", 0),
            description=item.get("description", "") or "",
            default_branch=item.get("default_branch", "main"),
            topics=item.get("topics", []),
        )

    @staticmethod
    def _keyword_terms(keywords: List[str]) -> set[str]:
        terms: set[str] = set()
        for keyword in keywords:
            lowered = str(keyword).lower()
            compact = re.sub(r"[^a-z0-9]+", "", lowered)
            if compact and compact not in GENERIC_DISCOVERY_TERMS:
                terms.add(compact)
            for part in re.split(r"[^a-z0-9]+", lowered):
                if len(part) >= 3 and part not in GENERIC_DISCOVERY_TERMS:
                    terms.add(part)
        if "cad" in terms:
            terms.update({"brep", "b-rep", "csg", "parametric", "sketch", "geometry", "geometric", "cae", "cam"})
        return terms

    @staticmethod
    def _source_matches_terms(source: SourceInfo, terms: set[str]) -> bool:
        if not terms:
            return True
        haystack = " ".join(
            [
                source.full_name,
                source.description,
                " ".join(source.topics),
            ]
        ).lower()
        tokens = {token for token in re.split(r"[^a-z0-9]+", haystack) if token}
        compact = re.sub(r"[^a-z0-9]+", "", haystack)
        if CAD_ANCHOR_TERMS & terms:
            return bool((CAD_ANCHOR_TERMS & terms) & tokens) or "brep" in compact
        for term in terms:
            if len(term) <= 4:
                if term in tokens:
                    return True
            elif term in haystack or term in compact:
                return True
        return False

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def discover(self, keywords: List[str], min_stars: int = 5,
                 max_sources: int = 10) -> List[SourceInfo]:
        """
        自动发现 GitHub 上的 awesome 项目。

        使用三种搜索策略，去重、过滤、排序后返回 Top N。
        """
        seen: set = set()
        candidates: List[SourceInfo] = []
        terms = self._keyword_terms(keywords)

        def finish() -> List[SourceInfo]:
            filtered = [s for s in candidates if s.stars >= min_stars and self._source_matches_terms(s, terms)]
            filtered.sort(key=lambda s: s.stars, reverse=True)
            result = filtered[:max_sources]
            print(f"[discover] 候选 {len(candidates)} 个，过滤后 {len(filtered)} 个，取 Top {len(result)}")
            for s in result:
                print(f"  ⭐ {s.stars:>5}  {s.full_name}")
            return result

        # 策略 1: 按 topic 搜索
        print("[discover] 策略 1: 按 topic 搜索...")
        for kw in keywords:
            if "search" in self._exhausted_buckets:
                return finish()
            items = self._search_repos(f"topic:awesome topic:{kw}")
            for item in items:
                name = item["full_name"]
                if name not in seen:
                    seen.add(name)
                    candidates.append(self._item_to_source(item))
            if "search" in self._exhausted_buckets:
                return finish()
            time.sleep(0.3)

        # 策略 2: 按 README 内容搜索
        print("[discover] 策略 2: 按 README 内容搜索...")
        top_kw = keywords[:3]
        kw_query = " ".join(f'"{kw}"' for kw in top_kw)
        items = self._search_repos(f'"awesome" "{kw_query}" in:readme')
        for item in items:
            name = item["full_name"]
            if name not in seen:
                seen.add(name)
                candidates.append(self._item_to_source(item))
        if "search" in self._exhausted_buckets:
            return finish()

        # 策略 3: 按仓库名搜索
        print("[discover] 策略 3: 按仓库名搜索...")
        for kw in keywords:
            if "search" in self._exhausted_buckets:
                return finish()
            items = self._search_repos(f"awesome-{kw} in:name")
            for item in items:
                name = item["full_name"]
                if name not in seen:
                    seen.add(name)
                    candidates.append(self._item_to_source(item))
            if "search" in self._exhausted_buckets:
                return finish()
            time.sleep(0.3)

        # 策略 4: 按 GitHub Trending 搜索
        print("[discover] 策略 4: 按 GitHub Trending 搜索...")
        for kw in keywords:
            if "search" in self._exhausted_buckets:
                return finish()
            items = self._search_repos(f"awesome {kw} stars:>100")
            for item in items:
                name = item["full_name"]
                if name not in seen:
                    seen.add(name)
                    candidates.append(self._item_to_source(item))
            if "search" in self._exhausted_buckets:
                return finish()
            time.sleep(0.3)

        # 策略 5: 搜索 awesome-list 话题
        print("[discover] 策略 5: 搜索 awesome-list 话题...")
        items = self._search_repos("topic:awesome-list")
        for item in items:
            name = item["full_name"]
            # 只保留描述中包含关键词的
            desc = (item.get("description", "") or "").lower()
            if any(kw.lower() in desc for kw in keywords):
                if name not in seen:
                    seen.add(name)
                    candidates.append(self._item_to_source(item))

        return finish()

    def source_from_repo(self, full_name: str) -> SourceInfo:
        """Return SourceInfo for a configured owner/repo string.

        Explicit upstream repos are more stable than GitHub Search for known
        high-quality awesome lists. If the metadata request is unavailable,
        fall back to a minimal SourceInfo so raw README fetching can still try
        common branches.
        """
        normalized = full_name.strip().strip("/")
        url = f"https://api.github.com/repos/{normalized}"
        payload = self._get_json(url, bucket="core")
        if payload:
            return self._item_to_source(payload)
        return SourceInfo(
            full_name=normalized,
            html_url=f"https://github.com/{normalized}",
            stars=0,
            description="",
            default_branch="main",
        )

    def fetch_readme(self, source: SourceInfo) -> Optional[str]:
        """获取上游项目的 README.md 内容"""
        for branch in (source.default_branch, "main", "master"):
            url = f"https://raw.githubusercontent.com/{source.full_name}/{branch}/README.md"
            text = self._get_text(url, bucket="core")
            if text:
                return text
        print(f"[discover] 获取 README 失败: {source.full_name}")
        return None

    def list_repo_files(self, source: SourceInfo) -> List[str]:
        """列出仓库根目录的文件名"""
        url = f"https://api.github.com/repos/{source.full_name}/contents"
        payload = self._get_json(url, bucket="core")
        if isinstance(payload, list):
            return [item["name"] for item in payload if isinstance(item, dict) and item.get("name")]
        return []

    def fetch_file(self, source: SourceInfo, file_path: str) -> Optional[str]:
        """获取仓库中指定文件的内容"""
        url = f"https://raw.githubusercontent.com/{source.full_name}/{source.default_branch}/{file_path}"
        text = self._get_text(url, bucket="core")
        if text:
            return text
        # fallback to master
        url = f"https://raw.githubusercontent.com/{source.full_name}/master/{file_path}"
        text = self._get_text(url, bucket="core")
        return text or None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="自动发现 GitHub awesome 项目")
    parser.add_argument("--hub", default=None, help="本地 hub 名称（读取 .local/{hub}/awesome.yaml）")
    parser.add_argument("--config", default="awesome.yaml", help="配置文件路径")
    parser.add_argument("--keywords", nargs="+", default=[], help="研究方向关键词")
    parser.add_argument("--min-stars", type=int, default=5, help="最少 star 数")
    parser.add_argument("--max-sources", type=int, default=10, help="最多返回几个源")
    args = parser.parse_args()

    if not args.keywords:
        import yaml
        from site_paths import resolve_config_path
        config_path = resolve_config_path(ROOT, Path.cwd(), args.config, args.hub)
        if not config_path.exists():
            print(f"[discover] 错误: 未找到配置文件 {config_path}")
            return
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        args.keywords = config.get("research", {}).get("keywords", [])
        auto = config.get("research", {}).get("auto_discover", {})
        args.min_stars = auto.get("min_stars", args.min_stars)
        args.max_sources = auto.get("max_sources", args.max_sources)

    discoverer = GitHubDiscoverer()
    sources = discoverer.discover(args.keywords, args.min_stars, args.max_sources)

    if not sources:
        print("[discover] 未发现任何 awesome 项目")
        return

    print(f"\n[discover] 发现 {len(sources)} 个 awesome 项目:")
    for s in sources:
        print(f"  {s.full_name} ({s.stars} stars)")


if __name__ == "__main__":
    main()
