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
import time
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import requests

ROOT = Path(__file__).resolve().parents[1]


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

    def __init__(self, token: str = ""):
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "awesome-hub-generator/1.0",
            "Accept": "application/vnd.github.v3+json",
        })
        if self.token:
            self.session.headers.update({"Authorization": f"token {self.token}"})
        self._rate_limit_remaining: Optional[int] = None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> None:
        if self._rate_limit_remaining is not None and self._rate_limit_remaining <= 1:
            print("[discover] API 限流即将耗尽，等待 60 秒...")
            time.sleep(60)

    def _search_repos(self, query: str, sort: str = "stars",
                      order: str = "desc", per_page: int = 10) -> List[Dict]:
        """执行 GitHub Search API 调用"""
        self._check_rate_limit()
        url = "https://api.github.com/search/repositories"
        params = {"q": query, "sort": sort, "order": order, "per_page": per_page}

        resp = self.session.get(url, params=params, timeout=30)

        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            self._rate_limit_remaining = int(remaining)

        if resp.status_code == 403:
            print("[discover] API 限流 (403)，等待 60 秒后重试...")
            time.sleep(60)
            return self._search_repos(query, sort, order, per_page)

        if resp.status_code != 200:
            print(f"[discover] GitHub API 错误: {resp.status_code} {resp.text[:200]}")
            return []

        return resp.json().get("items", [])

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

        # 策略 1: 按 topic 搜索
        print("[discover] 策略 1: 按 topic 搜索...")
        for kw in keywords:
            items = self._search_repos(f"topic:awesome topic:{kw}")
            for item in items:
                name = item["full_name"]
                if name not in seen:
                    seen.add(name)
                    candidates.append(self._item_to_source(item))
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

        # 策略 3: 按仓库名搜索
        print("[discover] 策略 3: 按仓库名搜索...")
        for kw in keywords:
            items = self._search_repos(f"awesome-{kw} in:name")
            for item in items:
                name = item["full_name"]
                if name not in seen:
                    seen.add(name)
                    candidates.append(self._item_to_source(item))
            time.sleep(0.3)

        # 策略 4: 按 GitHub Trending 搜索
        print("[discover] 策略 4: 按 GitHub Trending 搜索...")
        for kw in keywords:
            items = self._search_repos(f"awesome {kw} stars:>100")
            for item in items:
                name = item["full_name"]
                if name not in seen:
                    seen.add(name)
                    candidates.append(self._item_to_source(item))
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

        # 过滤：最低 star 数
        filtered = [s for s in candidates if s.stars >= min_stars]

        # 按 stars 降序，取 Top N
        filtered.sort(key=lambda s: s.stars, reverse=True)
        result = filtered[:max_sources]

        print(f"[discover] 候选 {len(candidates)} 个，过滤后 {len(filtered)} 个，取 Top {len(result)}")
        for s in result:
            print(f"  ⭐ {s.stars:>5}  {s.full_name}")

        return result

    def fetch_readme(self, source: SourceInfo) -> Optional[str]:
        """获取上游项目的 README.md 内容"""
        for branch in (source.default_branch, "main", "master"):
            url = f"https://raw.githubusercontent.com/{source.full_name}/{branch}/README.md"
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
            except Exception:
                continue
        print(f"[discover] 获取 README 失败: {source.full_name}")
        return None

    def list_repo_files(self, source: SourceInfo) -> List[str]:
        """列出仓库根目录的文件名"""
        url = f"https://api.github.com/repos/{source.full_name}/contents"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                return [item["name"] for item in resp.json()]
        except Exception as e:
            print(f"[discover] 列出文件失败 {source.full_name}: {e}")
        return []

    def fetch_file(self, source: SourceInfo, file_path: str) -> Optional[str]:
        """获取仓库中指定文件的内容"""
        url = f"https://raw.githubusercontent.com/{source.full_name}/{source.default_branch}/{file_path}"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        # fallback to master
        url = f"https://raw.githubusercontent.com/{source.full_name}/master/{file_path}"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return None


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
