#!/usr/bin/env python3
"""
ingest_source.py — 从上游 awesome 项目吸纳数据

支持格式：
- Markdown 表格（覆盖率 ~90%）
- Markdown 列表（覆盖率 ~8%）
- YAML 文件（覆盖率 ~1%）
- JSON 文件（覆盖率 ~1%）

用法:
    python scripts/ingest_source.py --readme README.md --repo owner/repo
    python scripts/ingest_source.py --readme README.md --repo owner/repo --output data/ingested.yaml
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from slugify import slugify

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# URL 分类：区分学术论文与非论文资源（实现在 url_classify.py）
# ---------------------------------------------------------------------------
from url_classify import (  # noqa: E402
    is_academic_url,
    detect_resource_type,
    entry_is_paper,
    ACADEMIC_DOMAINS,
    RESOURCE_TYPE_RULES,
)

# ---------------------------------------------------------------------------
# 格式检测
# ---------------------------------------------------------------------------


class FormatDetector:
    """自动检测上游仓库的数据格式"""

    @staticmethod
    def detect(readme_content: str, repo_files: List[str]) -> str:
        """检测 README 的格式类型，返回格式标识"""
        # 1. 检查是否有 YAML/JSON 数据文件
        if any(f.endswith((".yaml", ".yml")) for f in repo_files):
            return "yaml"
        if any(f.endswith(".json") for f in repo_files):
            return "json"

        # 2. 检查 README 中是否有 Markdown 表格
        table_rows = re.findall(r"^\|.+\|.+\|.+$", readme_content, re.MULTILINE)
        if len(table_rows) > 5:
            return "markdown_table"

        # 3. 检查是否有 Markdown 列表
        list_items = re.findall(r"^\s*[-*]\s+\[.+?\]\(.+?\)", readme_content, re.MULTILINE)
        if len(list_items) > 5:
            return "markdown_list"

        return "unknown"


# ---------------------------------------------------------------------------
# Markdown 表格解析器
# ---------------------------------------------------------------------------


class MarkdownTableParser:
    """解析 Markdown 表格格式的 awesome 列表"""

    COLUMN_MAP = {
        "title": ["title", "paper", "name", "project", "method"],
        "year": ["year", "date", "published"],
        "venue": ["venue", "conference", "journal", "publication", "publisher"],
        "links": ["links", "link", "code", "github", "resources", "repo", "repository"],
        "description": ["description", "desc", "note", "notes", "abstract"],
    }

    @classmethod
    def parse(cls, readme: str, source_repo: str = "") -> List[Dict]:
        """解析 Markdown 表格，返回论文条目列表"""
        papers: List[Dict] = []

        # 提取所有表格行
        table_lines = re.findall(r"^\|.+\|.+$", readme, re.MULTILINE)
        if not table_lines:
            return papers

        # 按空行分组
        groups: List[List[str]] = []
        current: List[str] = []
        for line in table_lines:
            if line.strip():
                current.append(line)
            elif current:
                groups.append(current)
                current = []
        if current:
            groups.append(current)

        for group in groups:
            if len(group) < 2:
                continue

            header = [h.strip().lower() for h in group[0].split("|")[1:-1]]
            data_rows = group[2:]  # skip separator row

            col_indices: Dict[str, int] = {}
            for col_name, aliases in cls.COLUMN_MAP.items():
                for i, h in enumerate(header):
                    if h in aliases:
                        col_indices[col_name] = i
                        break

            for row in data_rows:
                cells = [c.strip() for c in row.split("|")[1:-1]]
                if len(cells) < 2:
                    continue
                paper = cls._parse_row(cells, col_indices, source_repo)
                if paper and paper.get("title"):
                    papers.append(paper)

        return papers

    @staticmethod
    def _parse_row(cells: List[str], col_indices: Dict[str, int],
                   source_repo: str) -> Optional[Dict]:
        """解析表格中的一行"""
        title = ""
        year = 0
        venue = "arXiv"
        links: Dict[str, str] = {}
        description = ""

        # Title
        if "title" in col_indices:
            idx = col_indices["title"]
            if idx < len(cells):
                cell = cells[idx]
                m = re.search(r"\[(.+?)\]\((.+?)\)", cell)
                if m:
                    title = m.group(1).strip()
                    links["paper"] = m.group(2)
                else:
                    title = cell.strip()

        if not title:
            return None

        # Year
        if "year" in col_indices:
            idx = col_indices["year"]
            if idx < len(cells):
                ym = re.search(r"(\d{4})", cells[idx])
                if ym:
                    year = int(ym.group(1))

        # Venue
        if "venue" in col_indices:
            idx = col_indices["venue"]
            if idx < len(cells):
                venue = cells[idx].strip()

        # Links
        if "links" in col_indices:
            idx = col_indices["links"]
            if idx < len(cells):
                for m in re.finditer(r"\[(.+?)\]\((.+?)\)", cells[idx]):
                    label = m.group(1).lower()
                    url = m.group(2)
                    if "code" in label or "github" in label:
                        links.setdefault("code", url)
                    elif "paper" in label or "arxiv" in label:
                        links.setdefault("paper", url)
                    elif "project" in label:
                        links.setdefault("project", url)
                    else:
                        links[label] = url

        # Description
        if "description" in col_indices:
            idx = col_indices["description"]
            if idx < len(cells):
                description = cells[idx].strip()[:200]

        paper_id = slugify(f"{title[:60]}-{year}" if year else title[:60])

        return {
            "id": paper_id,
            "title": title,
            "year": year or None,
            "venue": venue,
            "category": "Others",
            "tags": [],
            "representations": [],
            "input_modalities": [],
            "output_modalities": [],
            "links": links,
            "preview": "/assets/placeholder.svg",
            "sources": [{"repo": source_repo, "category": "Others"}],
            "_description": description,
        }


# ---------------------------------------------------------------------------
# Markdown 列表解析器
# ---------------------------------------------------------------------------


class MarkdownListParser:
    """解析 Markdown 列表格式的 awesome 列表"""

    @staticmethod
    def parse(readme: str, source_repo: str = "") -> List[Dict]:
        """解析 Markdown 列表，返回论文条目列表"""
        papers: List[Dict] = []
        pattern = r"^\s*[-*]\s+\[(.+?)\]\((.+?)\)(?:\s*[-–—]\s*(.+))?"

        for line in readme.split("\n"):
            m = re.match(pattern, line)
            if not m:
                continue

            title = m.group(1).strip()
            url = m.group(2)
            description = (m.group(3) or "").strip()

            if not title:
                continue

            links: Dict[str, str] = {}
            if is_academic_url(url):
                links["paper"] = url
            elif "github.com" in url:
                links["code"] = url
            else:
                links["link"] = url

            paper_id = slugify(title[:60])

            entry = {
                "id": paper_id,
                "title": title,
                "year": None,
                "venue": "arXiv" if is_academic_url(url) else "",
                "category": "Others",
                "tags": [],
                "representations": [],
                "input_modalities": [],
                "output_modalities": [],
                "links": links,
                "preview": "/assets/placeholder.svg",
                "sources": [{"repo": source_repo, "category": "Others"}],
                "_description": description[:200] if description else "",
            }
            if not entry_is_paper(entry):
                entry["_type"] = "resource"
                entry["resource_type"] = detect_resource_type(url)
            papers.append(entry)

        return papers


# ---------------------------------------------------------------------------
# YAML / JSON 解析器
# ---------------------------------------------------------------------------


def _normalize_item(item: Dict, source_repo: str) -> Dict:
    """将 YAML/JSON 条目标准化为统一格式"""
    title = item.get("title", item.get("name", ""))
    year = item.get("year", 0)
    if isinstance(year, str):
        ym = re.search(r"(\d{4})", year)
        year = int(ym.group(1)) if ym else 0

    links = dict(item.get("links", {}))
    if not links.get("paper") and item.get("paper"):
        links["paper"] = item["paper"]
    if not links.get("code") and item.get("code"):
        links["code"] = item["code"]

    paper_id = item.get("id", slugify(f"{title[:60]}-{year}" if year else title[:60]))

    return {
        "id": paper_id,
        "title": title,
        "year": year or None,
        "venue": item.get("venue", item.get("conference", "arXiv")),
        "category": item.get("category", "Others"),
        "tags": item.get("tags", []),
        "representations": item.get("representations", []),
        "input_modalities": item.get("input_modalities", []),
        "output_modalities": item.get("output_modalities", []),
        "links": links,
        "preview": item.get("preview", "/assets/placeholder.svg"),
        "sources": [{"repo": source_repo, "category": item.get("category", "Others")}],
    }


class YamlParser:
    """解析 YAML 格式的 awesome 数据"""

    @staticmethod
    def parse(content: str, source_repo: str = "") -> List[Dict]:
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            print(f"[ingest] YAML 解析失败: {e}")
            return []

        items = _extract_list(data)
        return [_normalize_item(item, source_repo) for item in items]


class JsonParser:
    """解析 JSON 格式的 awesome 数据"""

    @staticmethod
    def parse(content: str, source_repo: str = "") -> List[Dict]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[ingest] JSON 解析失败: {e}")
            return []

        items = _extract_list(data)
        return [_normalize_item(item, source_repo) for item in items]


def _extract_list(data: Any) -> List[Dict]:
    """从可能嵌套的结构中提取论文列表"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("papers", "items", "entries", "data", "resources"):
            if key in data and isinstance(data[key], list):
                return data[key]
    return []


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def ingest_source(readme: str, repo_files: List[str],
                  source_repo: str = "") -> List[Dict]:
    """
    从上游 awesome 项目吸纳数据。

    Args:
        readme: README 内容
        repo_files: 仓库根目录的文件列表
        source_repo: 来源仓库标识 (e.g. "owner/repo")

    Returns:
        论文条目列表
    """
    fmt = FormatDetector.detect(readme, repo_files)
    print(f"[ingest] 检测到格式: {fmt} (repo={source_repo})")

    if fmt == "yaml":
        print("[ingest] YAML 格式需要额外获取数据文件，请调用 YamlParser 直接解析文件内容")
        return []
    elif fmt == "json":
        print("[ingest] JSON 格式需要额外获取数据文件，请调用 JsonParser 直接解析文件内容")
        return []
    elif fmt == "markdown_table":
        papers = MarkdownTableParser.parse(readme, source_repo)
        print(f"[ingest] 从 Markdown 表格解析到 {len(papers)} 篇论文")
        return papers
    elif fmt == "markdown_list":
        papers = MarkdownListParser.parse(readme, source_repo)
        print(f"[ingest] 从 Markdown 列表解析到 {len(papers)} 篇论文")
        return papers
    else:
        print("[ingest] 无法识别的格式，跳过")
        return []


def main():
    import argparse
    parser = argparse.ArgumentParser(description="从上游 awesome 项目吸纳数据")
    parser.add_argument("--readme", required=True, help="README 文件路径")
    parser.add_argument("--repo", default="", help="来源仓库标识")
    parser.add_argument("--output", default="", help="输出 YAML 路径")
    args = parser.parse_args()

    readme_path = Path(args.readme)
    if not readme_path.exists():
        print(f"[ingest] 错误: README 文件不存在 {readme_path}")
        sys.exit(1)

    readme = readme_path.read_text(encoding="utf-8")
    papers = ingest_source(readme, [], args.repo)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            yaml.safe_dump(papers, allow_unicode=True, sort_keys=False, width=120),
            encoding="utf-8",
        )
        print(f"[ingest] 已写入 {output_path} ({len(papers)} 条)")
    else:
        print(yaml.safe_dump(papers, allow_unicode=True, sort_keys=False, width=120))


if __name__ == "__main__":
    main()
