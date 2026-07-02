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

PLACEHOLDER_PREVIEW = "/assets/placeholder.svg"


def _clean_markdown_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .;-–—")


def _extract_image_url(text: str) -> str:
    """Extract a teaser/preview image URL from Markdown or HTML snippets."""
    if not text:
        return ""
    markdown_image = re.search(r"!\[[^\]]*]\((https?://[^)\s]+|[^)\s]+)\)", text)
    if markdown_image:
        url = markdown_image.group(1).strip()
        if "shields.io" not in url and "komarev.com" not in url:
            return url
    html_image = re.search(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", text, re.I)
    if html_image:
        url = html_image.group(1).strip()
        if "shields.io" not in url and "komarev.com" not in url:
            return url
    return ""


def _classify_link(label: str, url: str) -> str:
    label_l = _clean_markdown_text(label).lower()
    url_l = (url or "").lower()
    if "github.com" in url_l or "code" in label_l or "github" in label_l or "repo" in label_l:
        return "code"
    if "paper" in label_l or "arxiv" in label_l or is_academic_url(url):
        return "paper"
    if "project" in label_l or "website" in label_l or "homepage" in label_l or "demo" in label_l:
        return "project"
    if "pdf" in label_l or url_l.endswith(".pdf"):
        return "pdf"
    return slugify(label_l) or "link"


def _merge_markdown_links(text: str, links: Dict[str, str]) -> None:
    text = text or ""
    wrapped_image_link = r"\[!\[([^\]]*)\]\(([^)]*)\)\]\((https?://[^)]+)\)"
    for match in re.finditer(wrapped_image_link, text):
        label, url = match.group(1), match.group(3).strip()
        links.setdefault(_classify_link(label, url), url)
    text = re.sub(wrapped_image_link, " ", text)
    for match in re.finditer(r"\[([^\]]+)]\((https?://[^)]+)\)", text):
        label, url = match.group(1), match.group(2).strip()
        if match.start() > 0 and text[match.start() - 1] == "!":
            continue
        if label.lstrip().startswith("!"):
            continue
        links.setdefault(_classify_link(label, url), url)


def _parse_authors(text: str) -> List[str]:
    cleaned = _clean_markdown_text(text)
    if not cleaned or cleaned in {"-", "—", "N/A"}:
        return []
    parts = re.split(r"\s*(?:,|;|\band\b|&)\s*", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _first_non_placeholder(*values: str) -> str:
    for value in values:
        if value and value != PLACEHOLDER_PREVIEW:
            return value
    return PLACEHOLDER_PREVIEW

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

        # 4. 检查是否有 HTML 列表
        li_count = len(re.findall(r'<li>', readme_content))
        if li_count > 5:
            return "html_list"

        return "unknown"


# ---------------------------------------------------------------------------
# Markdown 表格解析器
# ---------------------------------------------------------------------------


class MarkdownTableParser:
    """解析 Markdown 表格格式的 awesome 列表"""

    COLUMN_MAP = {
        "title": ["title", "paper", "name", "project", "method"],
        "authors": ["authors", "author"],
        "year": ["year", "date", "published"],
        "venue": ["venue", "conference", "journal", "publication", "publisher"],
        "links": ["links", "link", "code", "github", "resources", "repo", "repository"],
        "paper_link": ["paper url", "paper link", "arxiv", "pdf"],
        "code_link": ["code url", "github url", "repo url"],
        "project_link": ["project page", "website", "homepage", "demo"],
        "image": ["image", "teaser", "preview", "figure", "thumbnail"],
        "description": ["description", "desc", "note", "notes", "abstract"],
    }

    @classmethod
    def parse(cls, readme: str, source_repo: str = "") -> List[Dict]:
        """解析 Markdown 表格，返回论文条目列表"""
        papers: List[Dict] = []

        # 按 README 原始连续 table block 分组；不能先全局抽取表格行，
        # 否则图片展示表和论文元数据表会被粘在一起。
        groups: List[List[str]] = []
        current: List[str] = []
        for line in readme.splitlines():
            if re.match(r"^\s*\|.*\|\s*$", line):
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
        authors: List[str] = []
        preview = PLACEHOLDER_PREVIEW

        for cell in cells:
            preview = _first_non_placeholder(preview, _extract_image_url(cell))

        # Title
        if "title" in col_indices:
            idx = col_indices["title"]
            if idx < len(cells):
                cell = cells[idx]
                _merge_markdown_links(cell, links)
                plain_title = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]+\)", " ", cell)
                plain_title = re.sub(r"<br\s*/?>", " ", plain_title, flags=re.I)
                plain_title = _clean_markdown_text(plain_title)
                m = re.search(r"(?<!!)\[(.+?)\]\((.+?)\)", cell)
                if m:
                    title = plain_title or _clean_markdown_text(m.group(1))
                    links.setdefault(_classify_link(m.group(1), m.group(2)), m.group(2))
                elif plain_title:
                    title = plain_title
                else:
                    # 如果 cell 中没有 markdown 链接，尝试直接提取 URL
                    url_match = re.search(r'https?://[^\s]+', cell)
                    if url_match:
                        url = url_match.group(0)
                        if "arxiv.org" in url:
                            links["paper"] = url
                        elif "github.com" in url:
                            links["code"] = url
                        else:
                            links["link"] = url
                        # 从 URL 周围提取标题文本
                        title_text = re.sub(r'https?://[^\s]+', '', cell).strip()
                        title_text = re.sub(r'[|\[\]]', '', title_text).strip()
                        if title_text:
                            title = title_text
                        else:
                            title = cell.strip()
                title = _clean_markdown_text(title)

        if not title:
            return None

        # Authors
        if "authors" in col_indices:
            idx = col_indices["authors"]
            if idx < len(cells):
                authors = _parse_authors(cells[idx])

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
                _merge_markdown_links(cells[idx], links)

        for column_name, link_key in (("paper_link", "paper"), ("code_link", "code"), ("project_link", "project")):
            if column_name in col_indices:
                idx = col_indices[column_name]
                if idx < len(cells):
                    _merge_markdown_links(cells[idx], links)
                    direct_url = re.search(r"https?://[^\s)]+", cells[idx])
                    if direct_url:
                        links.setdefault(link_key, direct_url.group(0))

        if "image" in col_indices:
            idx = col_indices["image"]
            if idx < len(cells):
                preview = _first_non_placeholder(preview, _extract_image_url(cells[idx]))

        # Description
        if "description" in col_indices:
            idx = col_indices["description"]
            if idx < len(cells):
                description = _clean_markdown_text(cells[idx])[:500]

        paper_id = slugify(f"{title[:60]}-{year}" if year else title[:60])

        return {
            "id": paper_id,
            "title": title,
            "authors": authors,
            "year": year or None,
            "venue": venue,
            "category": "Others",
            "tags": [],
            "representations": [],
            "input_modalities": [],
            "output_modalities": [],
            "links": links,
            "preview": preview,
            "sources": [{"repo": source_repo, "category": "Others"}],
            "_description": description,
        }


# ---------------------------------------------------------------------------
# Markdown 列表解析器
# ---------------------------------------------------------------------------


class MarkdownListParser:
    """解析 Markdown 列表格式的 awesome 列表"""

    @staticmethod
    def _clean_text(text: str) -> str:
        return _clean_markdown_text(text)

    @classmethod
    def _parse_rich_awesome_line(cls, line: str, source_repo: str) -> Optional[Dict]:
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        if not bullet:
            return None
        body = bullet.group(1).strip()
        link_matches = list(re.finditer(r"\[\[?([^\]]+?)\]\((https?://[^)]+)\)\]?", body))
        if not link_matches:
            return None

        links: Dict[str, str] = {}
        preview = _extract_image_url(body) or PLACEHOLDER_PREVIEW
        for match in link_matches:
            label = cls._clean_text(match.group(1)).lower()
            url = match.group(2).strip()
            if label.startswith("!"):
                continue
            if "code" in label or "github" in label:
                links.setdefault("code", url)
            elif "project" in label:
                links.setdefault("project", url)
            elif "paper" in label or "arxiv" in label or is_academic_url(url):
                links.setdefault("paper", url)
            else:
                links.setdefault(label or "link", url)
        if not links:
            return None

        text = body
        for match in reversed(link_matches):
            text = text[:match.start()] + text[match.end():]

        venue = "arXiv" if is_academic_url(links.get("paper", "")) else ""
        venue_match = re.search(r"\*\*`([^`]+)`\*\*|\*\*([^*]*(?:20\d{2}|[’']\d{2}|\b\d{2}\b)[^*]*)\*\*", text)
        if venue_match:
            venue = cls._clean_text(venue_match.group(1) or venue_match.group(2) or venue)
            text = text[:venue_match.start()].strip()

        label_match = re.match(r"^\[(.*?)\]\s*(.*)$", text)
        if label_match:
            label = cls._clean_text(label_match.group(1))
            rest = cls._clean_text(label_match.group(2))
            title = rest or label
        else:
            title = cls._clean_text(text)

        if not title:
            return None

        year = None
        year_match = re.search(r"(20\d{2})", venue)
        if year_match:
            year = int(year_match.group(1))
        else:
            short_year = re.search(r"[’'](\d{2})|\b(\d{2})(?:\.\d+)?\b", venue)
            if short_year:
                yy = int(short_year.group(1) or short_year.group(2))
                if 0 <= yy <= 40:
                    year = 2000 + yy
        arxiv_year = None
        arxiv_match = re.search(r"arxiv\.org/abs/(\d{2})\d{2}\.\d+", links.get("paper", ""), re.I)
        if arxiv_match:
            arxiv_year = 2000 + int(arxiv_match.group(1))
        if arxiv_year and (not year or (venue.lower().startswith("arxiv") and year != arxiv_year)):
            year = arxiv_year

        paper_id = slugify(f"{title[:60]}-{year}" if year else title[:60])
        entry = {
            "id": paper_id,
            "title": title,
            "year": year,
            "venue": venue,
            "category": "Others",
            "tags": [],
            "representations": [],
            "input_modalities": [],
            "output_modalities": [],
            "links": links,
            "preview": preview,
            "sources": [{"repo": source_repo, "category": "Others"}],
            "_description": "",
        }
        if not entry_is_paper(entry):
            entry["_type"] = "resource"
            entry["resource_type"] = detect_resource_type(next(iter(links.values()), ""))
        return entry

    @classmethod
    def _parse_bold_awesome_block(cls, block: str, source_repo: str) -> Optional[Dict]:
        bullet = re.match(r"^\s*[-*]\s+(.+)$", block.strip(), re.S)
        if not bullet:
            return None
        body = bullet.group(1).strip()
        links: Dict[str, str] = {}
        _merge_markdown_links(body, links)
        if not links:
            return None

        preview = _extract_image_url(body) or PLACEHOLDER_PREVIEW

        title = ""
        italic_title = re.search(r"_(.+?)_", body, re.S)
        if italic_title:
            title = cls._clean_text(italic_title.group(1))
        if not title:
            bold_title = re.search(r"\*\*(.+?)\*\*", body, re.S)
            if bold_title:
                title = cls._clean_text(bold_title.group(1))
        if not title:
            return None

        venue = "arXiv" if is_academic_url(links.get("paper", "")) else ""
        venue_match = re.search(r"```(.+?)```", body, re.S)
        if venue_match:
            venue = cls._clean_text(venue_match.group(1))

        year = None
        year_match = re.search(r"(20\d{2})", venue)
        if year_match:
            year = int(year_match.group(1))
        else:
            arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{2})\d{2}\.\d+", links.get("paper", ""), re.I)
            if arxiv_match:
                year = 2000 + int(arxiv_match.group(1))

        paper_id = slugify(f"{title[:60]}-{year}" if year else title[:60])
        entry = {
            "id": paper_id,
            "title": title,
            "year": year,
            "venue": venue,
            "category": "Others",
            "tags": [],
            "representations": [],
            "input_modalities": [],
            "output_modalities": [],
            "links": links,
            "preview": preview,
            "sources": [{"repo": source_repo, "category": "Others"}],
            "_description": "",
        }
        if not entry_is_paper(entry):
            entry["_type"] = "resource"
            entry["resource_type"] = detect_resource_type(next(iter(links.values()), ""))
        return entry

    @staticmethod
    def parse(readme: str, source_repo: str = "") -> List[Dict]:
        """解析 Markdown 列表，返回论文条目列表"""
        papers: List[Dict] = []
        pattern = r"^\s*[-*]\s+\[(.+?)\]\((.+?)\)(?:\s*[-–—]\s*(.+))?"

        blocks: List[str] = []
        current: List[str] = []
        for line in readme.split("\n"):
            if re.match(r"^\s*[-*]\s+", line):
                if current:
                    blocks.append(" ".join(current))
                current = [line]
            elif current and line.strip() and not re.match(r"^\s*#{1,6}\s+", line):
                current.append(line)
            else:
                if current:
                    blocks.append(" ".join(current))
                    current = []
        if current:
            blocks.append(" ".join(current))

        for line in blocks:
            rich_entry = MarkdownListParser._parse_rich_awesome_line(line, source_repo)
            if not rich_entry:
                rich_entry = MarkdownListParser._parse_bold_awesome_block(line, source_repo)
            if rich_entry:
                papers.append(rich_entry)
                continue

            m = re.match(pattern, line)
            if not m:
                continue

            title = m.group(1).strip()
            url = m.group(2)
            description = (m.group(3) or "").strip()
            preview = _extract_image_url(line) or PLACEHOLDER_PREVIEW

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
                "preview": preview,
                "sources": [{"repo": source_repo, "category": "Others"}],
                "_description": description[:200] if description else "",
            }
            if not entry_is_paper(entry):
                entry["_type"] = "resource"
                entry["resource_type"] = detect_resource_type(url)
            papers.append(entry)

        # 匹配 HTML <li> 格式
        li_pattern = r'<li>(.*?)</li>'
        for match in re.finditer(li_pattern, readme, re.DOTALL):
            li_content = match.group(1)
            # 提取链接
            a_match = re.search(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', li_content)
            if not a_match:
                continue

            url = a_match.group(1)
            title = re.sub(r'<[^>]+>', '', a_match.group(2)).strip()
            preview = _extract_image_url(li_content) or PLACEHOLDER_PREVIEW

            if not title:
                continue

            # 提取描述（<a> 标签后的文本）
            description = ""
            after_link = li_content.split("</a>", 1)
            if len(after_link) > 1:
                description = re.sub(r'<[^>]+>', '', after_link[1]).strip()
                description = re.sub(r'\s+', ' ', description).strip()

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
                "preview": preview,
                "sources": [{"repo": source_repo, "category": "Others"}],
                "_description": description[:200] if description else "",
            }
            if not entry_is_paper(entry):
                entry["_type"] = "resource"
                entry["resource_type"] = detect_resource_type(url)
            papers.append(entry)

        return papers


class HtmlListParser:
    """解析 HTML 列表格式的 awesome 列表"""

    @staticmethod
    def parse(readme: str, source_repo: str = "") -> List[Dict]:
        """解析 HTML 列表，返回论文条目列表"""
        papers: List[Dict] = []

        # 匹配 <li> 标签
        li_pattern = re.compile(r'<li>(.*?)</li>', re.DOTALL)
        for match in li_pattern.finditer(readme):
            li_content = match.group(1)

            # 提取 <a> 标签
            a_match = re.search(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', li_content)
            if not a_match:
                continue

            url = a_match.group(1)
            title = re.sub(r'<[^>]+>', '', a_match.group(2)).strip()

            if not title:
                continue

            # 提取描述（<a> 标签后的文本）
            desc = ""
            after_link = li_content.split("</a>", 1)
            if len(after_link) > 1:
                desc = re.sub(r'<[^>]+>', '', after_link[1]).strip()
                desc = re.sub(r'\s+', ' ', desc).strip()

            links: Dict[str, str] = {}
            if is_academic_url(url):
                links["paper"] = url
            elif "github.com" in url:
                links["code"] = url
            else:
                links["link"] = url

            paper_id = slugify(title[:60])

            papers.append({
                "id": paper_id,
                "title": title,
                "year": None,
                "venue": "arXiv" if "arxiv.org" in url else "",
                "category": "Others",
                "tags": [],
                "representations": [],
                "input_modalities": [],
                "output_modalities": [],
                "links": links,
                "preview": "/assets/placeholder.svg",
                "sources": [{"repo": source_repo, "category": "Others"}],
                "_description": desc[:200] if desc else "",
            })

        return papers


# ---------------------------------------------------------------------------
# YAML / JSON 解析器
# ---------------------------------------------------------------------------


def _normalize_item(item: Dict, source_repo: str) -> Dict:
    """将 YAML/JSON 条目标准化为统一格式"""
    title = item.get("title", item.get("name", ""))
    links = dict(item.get("links", {}))
    if not links.get("paper") and item.get("paper"):
        links["paper"] = item["paper"]
    if not links.get("paper") and item.get("arxiv"):
        links["paper"] = item["arxiv"]
    if not links.get("pdf") and item.get("pdf"):
        links["pdf"] = item["pdf"]
    if not links.get("code") and item.get("code"):
        links["code"] = item["code"]
    if not links.get("code") and item.get("github"):
        links["code"] = item["github"]
    if not links.get("project") and item.get("project"):
        links["project"] = item["project"]
    if not links.get("project") and item.get("website"):
        links["project"] = item["website"]
    preview = _first_non_placeholder(
        item.get("preview", ""),
        item.get("teaser", ""),
        item.get("image", ""),
        item.get("thumbnail", ""),
        item.get("figure", ""),
    )
    authors = item.get("authors", item.get("author", []))
    if isinstance(authors, str):
        authors = _parse_authors(authors)
    if not isinstance(authors, list):
        authors = []

    # 统一使用 extract_year
    from sync import extract_year
    year = extract_year({
        "year": item.get("year"),
        "venue": item.get("venue", ""),
        "links": links,
    })

    paper_id = item.get("id", slugify(f"{title[:60]}-{year}" if year else title[:60]))

    return {
        "id": paper_id,
        "title": title,
        "authors": authors,
        "abstract": item.get("abstract", item.get("description", "")),
        "year": year or None,
        "venue": item.get("venue", item.get("conference", "arXiv")),
        "category": item.get("category", "Others"),
        "tags": item.get("tags", []),
        "representations": item.get("representations", []),
        "input_modalities": item.get("input_modalities", []),
        "output_modalities": item.get("output_modalities", []),
        "links": links,
        "preview": preview,
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
    elif fmt == "html_list":
        papers = HtmlListParser.parse(readme, source_repo)
        print(f"[ingest] 从 HTML 列表解析到 {len(papers)} 篇论文")
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
