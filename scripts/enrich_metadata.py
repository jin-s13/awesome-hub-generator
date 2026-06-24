#!/usr/bin/env python3
"""
enrich_metadata.py — arXiv HTML 元数据富化

从 arXiv HTML 页面提取丰富的元数据，增强 papers.yaml 中的论文条目。

提取字段:
  - figure_url: 论文首图 URL（更新到 preview 字段）
  - authors: 完整作者列表
  - affiliations: 机构列表
  - section_headers: 章节标题列表
  - captions: 图表标题列表
  - method_names: 方法名列表
  - method_summary: 方法描述
  - has_real_world: 是否包含真实实验（由 LLM 语义分析，不在本脚本中提取）

用法:
    python scripts/enrich_metadata.py                          # 富化所有论文
    python scripts/enrich_metadata.py --max-workers 5          # 限制并发数
    python scripts/enrich_metadata.py --skip-figures           # 跳过图片提取
"""

from __future__ import annotations

import asyncio
import gzip
import io
import logging
import os
import re
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

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

logger = logging.getLogger("enrich_metadata")

# arXiv ID regex
_ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|html|pdf)/(\d+\.\d+)")

# Method name stop words
_METHOD_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "these",
    "based", "using", "learning", "model", "network", "method",
    "approach", "framework", "system", "algorithm", "data",
    "image", "video", "text", "feature", "layer", "input", "output",
    "results", "training", "inference", "performance", "proposed",
    "novel", "new", "efficient", "effective", "simple", "large",
    "deep", "neural", "convolutional", "recurrent", "attention",
    "transformer", "generative", "discriminative", "supervised",
    "unsupervised", "semi-supervised", "self-supervised",
    "reinforcement", "transfer", "multi-task", "cross-modal",
    "end-to-end", "joint", "unified", "hierarchical",
}

# Affiliation keywords
_AFFILIATION_KEYWORDS = [
    "university", "college", "institute", "school", "lab", "laboratory",
    "research", "center", "centre", "department", "faculty",
    "corporation", "inc", "ltd", "gmbh", "company", "technologies",
    "google", "meta", "microsoft", "amazon", "apple", "nvidia",
    "intel", "ibm", "openai", "deepmind", "qualcomm", "samsung",
    "huawei", "tencent", "alibaba", "baidu", "bytedance",
    "facebook", "twitter", "uber", "lyft", "waymo", "tesla",
    "academy", "college", "polytechnic", "faculty", "school of",
    "department of", "division of", "program of", "center for",
    "national", "federal", "institute of technology", "eth",
    "mpi", "max planck", "cnrs", "inria", "kaist", "postech",
    "mit", "caltech", "stanford", "berkeley", "oxford", "cambridge",
    "harvard", "princeton", "cmu", "ucla", "ucsd", "uc berkeley",
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch URL content with urllib. Returns None on failure."""
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "awesome-hub-generator/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("HTTP error fetching %s: %s", url, e)
        return None


def _extract_arxiv_id(paper: Dict) -> Optional[str]:
    """Extract arXiv ID from paper links."""
    url = (paper.get("links") or {}).get("paper", "") or ""
    m = _ARXIV_ID_RE.search(url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# HTML extraction functions (all regex-based, no BeautifulSoup dependency)
# ---------------------------------------------------------------------------

def _extract_figure_url(html: str, arxiv_id: str) -> Optional[str]:
    """Extract first meaningful figure URL from arXiv HTML."""
    # Pattern 1: <figure> with <img> inside
    fig_pattern = re.compile(
        r'<figure[^>]*>.*?<img[^>]+src=["\']([^"\']+)["\'][^>]*>.*?</figure>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in fig_pattern.finditer(html):
        src = match.group(1)
        if _is_icon_or_logo(src):
            continue
        return _normalize_url(src, arxiv_id)

    # Pattern 2: Any <img> with reasonable extension
    img_pattern = re.compile(
        r'<img[^>]+src=["\']([^"\']+(?:png|jpg|jpeg|gif|webp))["\'][^>]*>',
        re.IGNORECASE,
    )
    for src in img_pattern.findall(html):
        if not _is_icon_or_logo(src):
            return _normalize_url(src, arxiv_id)

    return None


def _is_icon_or_logo(src: str) -> bool:
    """Check if image src looks like an icon/logo."""
    lowered = src.lower()
    return any(kw in lowered for kw in ("icon", "logo", "favicon", "github", "twitter", "badge"))


def _normalize_url(src: str, arxiv_id: str) -> str:
    """Normalize a (possibly relative) URL from an arXiv HTML page.

    arXiv HTML pages are served at https://arxiv.org/html/{arxiv_id} and
    image src attributes use relative paths like "{arxiv_id}v1/figures/img.png"
    (already including the version number), so we prepend only the base URL.
    """
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if src.startswith("/"):
        return f"https://arxiv.org{src}"
    return f"https://arxiv.org/html/{src}"


def _extract_authors_html(html: str) -> List[str]:
    """Extract author names from arXiv HTML."""
    authors: List[str] = []
    # Match ltx_personname spans
    pattern = re.compile(
        r'<span[^>]*class=["\'][^"\']*ltx_personname[^"\']*["\'][^>]*>(.*?)</span>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        name = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        # Filter out lines that look like affiliations
        if name and not any(kw in name.lower() for kw in _AFFILIATION_KEYWORDS):
            authors.append(name)

    # Fallback: look for meta tags
    if not authors:
        meta_pattern = re.compile(
            r'<meta\s+name=["\']citation_author["\'][^>]*content=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        authors = [m.group(1).strip() for m in meta_pattern.finditer(html)]

    return authors


def _extract_affiliations_html(html: str) -> List[str]:
    """Extract affiliations from arXiv HTML."""
    affiliations: List[str] = []

    # Pattern 1: ltx_affiliation spans
    aff_pattern = re.compile(
        r'<span[^>]*class=["\'][^"\']*ltx_affiliation[^"\']*["\'][^>]*>(.*?)</span>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in aff_pattern.finditer(html):
        aff = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        if aff and len(aff) > 5:
            affiliations.append(aff)

    # Pattern 2: citation_author_institution meta tags
    if not affiliations:
        meta_pattern = re.compile(
            r'<meta\s+name=["\']citation_author_institution["\'][^>]*content=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        affiliations = list({m.group(1).strip() for m in meta_pattern.finditer(html)})

    return affiliations


def _extract_section_headers(html: str) -> List[str]:
    """Extract section headers from arXiv HTML."""
    headers: List[str] = []
    pattern = re.compile(
        r'<(h[23])[^>]*>(.*?)</\1>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        header = re.sub(r'<[^>]+>', '', match.group(2)).strip()
        # Remove numbering like "1. ", "2.1 ", "III. "
        header = re.sub(r'^[\d.IVXLCDM]+\s*\.?\s*', '', header).strip()
        if header and len(header) > 2 and len(header) < 100:
            headers.append(header)
        if len(headers) >= 25:
            break
    return headers


def _extract_captions(html: str) -> List[str]:
    """Extract figure/table captions from arXiv HTML."""
    captions: List[str] = []
    pattern = re.compile(
        r'<(figcaption|caption)[^>]*>(.*?)</\1>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        caption = re.sub(r'<[^>]+>', '', match.group(2)).strip()
        if 10 <= len(caption) <= 200:
            captions.append(caption)
        if len(captions) >= 8:
            break
    return captions


def _extract_method_names(html: str, title: str) -> List[str]:
    """Extract method names from arXiv HTML using regex patterns."""
    # Remove HTML tags for text extraction
    text = re.sub(r'<[^>]+>', ' ', html)

    # Pattern: CamelCase words (potential method names)
    camel_pattern = re.compile(r'\b[A-Z][a-z]+[A-Z][a-zA-Z]*\b')
    candidates = camel_pattern.findall(text)

    # Also match ALLCAPS acronyms
    caps_pattern = re.compile(r'\b[A-Z]{2,5}\b')
    candidates += caps_pattern.findall(text)

    # Filter and count frequency
    from collections import Counter
    stop_lower = {w.lower() for w in _METHOD_STOP}
    filtered = [
        w for w in candidates
        if w.lower() not in stop_lower
        and len(w) >= 3
        and not w.isdigit()
    ]

    counter = Counter(filtered)
    # Return top 10 most frequent
    return [name for name, _ in counter.most_common(10)]


def _extract_method_summary(html: str) -> str:
    """Extract method description from arXiv HTML."""
    # Find "Method" or "Approach" section
    method_pattern = re.compile(
        r'<(h[23])[^>]*>(?:.*?(?:method|approach|framework|proposed)[^<]*)</\1>(.*?)(?:<(h[23])|</section>)',
        re.DOTALL | re.IGNORECASE,
    )
    match = method_pattern.search(html)
    if match:
        text = re.sub(r'<[^>]+>', ' ', match.group(2))
        text = re.sub(r'\s+', ' ', text).strip()
        # Truncate to 300-500 chars at sentence boundary
        if len(text) > 500:
            # Find last sentence boundary within 500 chars
            truncated = text[:500]
            last_period = truncated.rfind('.')
            if last_period > 300:
                return truncated[:last_period + 1]
            return truncated[:500] + '...'
        return text[:500]

    return ""


def _fetch_abs_meta(arxiv_id: str, timeout: int = 30) -> Dict[str, Any]:
    """Fetch metadata from arXiv abstract page as fallback."""
    url = f"https://arxiv.org/abs/{arxiv_id}"
    html = _http_get(url, timeout)
    if not html:
        return {}

    result: Dict[str, Any] = {}

    # Authors from meta tags
    authors = re.findall(
        r'<meta\s+name=["\']citation_author["\'][^>]*content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if authors:
        result["authors"] = [a.strip() for a in authors]

    # Affiliations from meta tags
    affiliations = re.findall(
        r'<meta\s+name=["\']citation_author_institution["\'][^>]*content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if affiliations:
        result["affiliations"] = list({a.strip() for a in affiliations})

    return result


# ---------------------------------------------------------------------------
# TeX source fallback functions
# ---------------------------------------------------------------------------

def _fetch_tex_source(arxiv_id: str, timeout: int = 30) -> Optional[str]:
    """从 arXiv 获取 TeX 源文件（tar.gz 压缩包）。

    URL: https://arxiv.org/e-print/{arxiv_id}
    返回解压后的文本内容，或 None 失败时。
    """
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "awesome-hub-generator/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_data = resp.read()
    except Exception as e:
        logger.debug("TeX source fetch error for %s: %s", arxiv_id, e)
        return None

    # Try to decompress as tar.gz
    try:
        with tarfile.open(fileobj=io.BytesIO(raw_data), mode="r:gz") as tar:
            tex_files = []
            for member in tar.getmembers():
                if member.isfile() and member.name.endswith(".tex"):
                    f = tar.extractfile(member)
                    if f:
                        content = f.read().decode("utf-8", errors="replace")
                        tex_files.append((member.size, content))
            if not tex_files:
                logger.debug("No .tex files found in tar.gz for %s", arxiv_id)
                return None
            # Sort by file size descending — main file is usually largest
            tex_files.sort(key=lambda x: x[0], reverse=True)
            combined = "\n\n".join(content for _, content in tex_files)
            logger.debug("TeX source extracted for %s (%d files, %d chars)",
                         arxiv_id, len(tex_files), len(combined))
            return combined
    except (tarfile.TarError, gzip.BadGzipFile):
        pass

    # Try as plain gzip (single .tex file compressed)
    try:
        decompressed = gzip.decompress(raw_data).decode("utf-8", errors="replace")
        logger.debug("TeX source (single gzip) extracted for %s (%d chars)",
                     arxiv_id, len(decompressed))
        return decompressed
    except (OSError, gzip.BadGzipFile):
        pass

    # Try as plain text (not compressed)
    try:
        text = raw_data.decode("utf-8", errors="replace")
        if "\\documentclass" in text or "\\begin{document}" in text:
            logger.debug("TeX source (plain text) extracted for %s (%d chars)",
                         arxiv_id, len(text))
            return text
    except UnicodeDecodeError:
        pass

    logger.debug("TeX source unrecognized format for %s", arxiv_id)
    return None


def _extract_affiliations_from_tex(tex_content: str) -> Dict[str, Any]:
    """从 TeX 源文件内容中提取机构和作者信息。

    解析的 LaTeX 命令:
      - \\author{...} — 作者
      - \\affiliation{...} — 机构（acmart 等模板）
      - \\institute{...} — 机构（IEEE 等模板）
      - \\address{...} — 地址/机构
      - \\thanks{...} — 致谢（跳过）
      - \\email{...} — 邮箱（跳过）

    返回:
        {"authors": [...], "affiliations": [...]}
    """
    # Helper: extract the innermost brace-delimited content
    def _extract_innermost_braces(text: str, start_pos: int) -> Optional[str]:
        """从 start_pos 开始，提取匹配的 { ... } 中最内层非嵌套内容。"""
        if start_pos >= len(text) or text[start_pos] != '{':
            return None
        depth = 0
        inner_start = start_pos + 1
        # Find the innermost level: track depth, return content at max depth
        best_content = None
        i = start_pos
        while i < len(text):
            if text[i] == '{':
                if depth == 0:
                    inner_start = i + 1
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    # This is the outermost closing brace
                    if best_content is None:
                        best_content = text[inner_start:i]
                    break
                elif depth == 0:
                    best_content = text[inner_start:i]
            i += 1
        return best_content

    # Simpler approach: use regex for non-nested braces
    # Pattern: \{([^{}]*)\} matches innermost brace content
    inner_brace_re = re.compile(r'\{([^{}]*)\}')

    def _extract_tex_arg(text: str, cmd: str) -> List[str]:
        """Extract arguments of a LaTeX command, handling nested braces."""
        results = []
        pattern = re.compile(r'\\' + cmd + r'(?:\s*\[[^\]]*\])?\s*\{')
        for m in pattern.finditer(text):
            start = m.end() - 1  # point to the opening brace
            content = _extract_innermost_braces(text, start)
            if content:
                # Clean up LaTeX commands within the content
                cleaned = _clean_tex_text(content)
                if cleaned:
                    results.append(cleaned)
        return results

    def _clean_tex_text(text: str) -> str:
        """Clean LaTeX formatting commands from text."""
        # Remove \texttt{...}, \textsuperscript{...}, etc.
        text = re.sub(r'\\texttt\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\textsuperscript\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\textbf\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\textit\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\emph\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\text\{([^{}]*)\}', r'\1', text)
        # Remove remaining LaTeX commands
        text = re.sub(r'\\[a-zA-Z]+(?:\s*\{[^{}]*\})?', '', text)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Remove leading/trailing punctuation
        text = text.strip('.,;: ')
        return text

    result: Dict[str, Any] = {"authors": [], "affiliations": []}

    # Extract authors from \author{...}
    # Handle multiple authors separated by \and
    author_pattern = re.compile(r'\\author\s*(\[([^\]]*)\])?\s*\{')
    for m in author_pattern.finditer(tex_content):
        start = m.end() - 1
        content = _extract_innermost_braces(tex_content, start)
        if content:
            # Split by \and
            parts = re.split(r'\\and\s*', content)
            for part in parts:
                cleaned = _clean_tex_text(part)
                if cleaned and len(cleaned) > 2:
                    result["authors"].append(cleaned)

    # Extract affiliations from \affiliation{...}
    for aff in _extract_tex_arg(tex_content, "affiliation"):
        if aff and len(aff) > 5:
            result["affiliations"].append(aff)

    # Extract affiliations from \institute{...}
    for aff in _extract_tex_arg(tex_content, "institute"):
        if aff and len(aff) > 5:
            result["affiliations"].append(aff)

    # Extract affiliations from \address{...}
    for aff in _extract_tex_arg(tex_content, "address"):
        if aff and len(aff) > 5:
            result["affiliations"].append(aff)

    # Deduplicate affiliations
    seen = set()
    unique_affs = []
    for aff in result["affiliations"]:
        key = aff.lower().strip()
        if key not in seen:
            seen.add(key)
            unique_affs.append(aff)
    result["affiliations"] = unique_affs

    # Deduplicate authors
    seen = set()
    unique_authors = []
    for author in result["authors"]:
        key = author.lower().strip()
        if key not in seen:
            seen.add(key)
            unique_authors.append(author)
    result["authors"] = unique_authors

    return result


def _fetch_pdf_text(arxiv_id: str, timeout: int = 60) -> Optional[str]:
    """下载 arXiv PDF 并用 pdftotext 提取文本。

    URL: https://arxiv.org/pdf/{arxiv_id}.pdf
    需要系统安装 poppler-utils（提供 pdftotext 命令）。

    返回:
        PDF 文本内容（前 2 页），或 None 失败时
    """
    import tempfile
    import urllib.request
    import subprocess

    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    req = urllib.request.Request(
        url, headers={"User-Agent": "awesome-hub-generator/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            pdf_data = resp.read()
    except Exception as e:
        logger.debug("PDF download error for %s: %s", arxiv_id, e)
        return None

    # Write to temp file and run pdftotext
    try:
        with tempfile.NamedTemporaryFile(delete=True, suffix=".pdf") as tmp:
            tmp.write(pdf_data)
            tmp.flush()
            result = subprocess.run(
                ["pdftotext", "-l", "2", tmp.name, "-"],
                capture_output=True, timeout=30, text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.debug("PDF text extracted for %s (%d chars)",
                             arxiv_id, len(result.stdout))
                return result.stdout
            else:
                logger.debug("pdftotext returned empty or error for %s", arxiv_id)
                return None
    except FileNotFoundError:
        logger.warning("pdftotext not found (install poppler-utils)")
        return None
    except subprocess.TimeoutExpired:
        logger.debug("pdftotext timeout for %s", arxiv_id)
        return None
    except Exception as e:
        logger.debug("PDF text extraction error for %s: %s", arxiv_id, e)
        return None


def _extract_affiliations_from_pdf(text: str) -> Dict[str, Any]:
    """从 PDF 文本中提取机构信息，5 种策略。

    策略:
    1. 关键词行匹配: 在 header 区域（截止到 Abstract/Introduction）逐行扫描，
       含 INST_KEYWORDS 且非句子的行
    2. 编号脚注模式: 匹配 [1] Institution / (2) Lab 格式
    3. 版权行匹配: 匹配 © 2024 Company/University
    4. 全文扫描: 在前 60 行中找含关键词的行
    5. 位置启发式: 定位作者行后，取到 Abstract 之间的短行

    返回:
        {"authors": [...], "affiliations": [...]}
    """
    def looks_like_sentence(line: str) -> bool:
        """判断一行是否像完整句子（小写词比例 > 40% 且不以机构关键词开头）。"""
        words = line.split()
        if not words:
            return True
        lower_count = sum(1 for w in words if w[0].islower() if w)
        ratio = lower_count / len(words)
        first_word_lower = words[0].lower().strip("({[")
        if ratio > 0.4 and not any(first_word_lower.startswith(kw) for kw in _AFFILIATION_KEYWORDS):
            return True
        return False

    def clean_affiliation(s: str) -> str:
        """清理脚注符号、花括号、多余空格。"""
        s = re.sub(r'[\d\[\]()*†‡§¶#]+', '', s)
        s = s.replace('{', '').replace('}', '')
        s = re.sub(r'\s+', ' ', s).strip()
        return s.strip('.,;: ')

    def is_author_line(line: str) -> bool:
        """检测是否像作者行（大写词占比 >= 60% 且词数 >= 4）。"""
        words = line.split()
        if len(words) < 4:
            return False
        upper_count = sum(1 for w in words if w[0].isupper() if w)
        return (upper_count / len(words)) >= 0.6

    lines = text.split('\n')
    result: Dict[str, Any] = {"authors": [], "affiliations": []}

    # Find the header region boundary (stop at Abstract/Introduction)
    header_end = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.search(r'\b(Abstract|Introduction|I\.\s*INTRODUCTION)\b', stripped, re.IGNORECASE):
            header_end = i
            break

    header_lines = lines[:header_end]

    # Strategy 1: 关键词行匹配
    affs = []
    for line in header_lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 8:
            continue
        lowered = stripped.lower()
        if any(kw in lowered for kw in _AFFILIATION_KEYWORDS):
            if not looks_like_sentence(stripped):
                cleaned = clean_affiliation(stripped)
                if cleaned and len(cleaned) > 5:
                    affs.append(cleaned)
    if affs:
        result["affiliations"] = _dedup_affiliations(affs)
        # Extract authors from header
        for line in header_lines:
            stripped = line.strip()
            if is_author_line(stripped):
                result["authors"].append(stripped)
        if result["affiliations"]:
            return result

    # Strategy 2: 编号脚注模式
    affs = []
    footnote_pattern = re.compile(
        r'^[\s(]*[\d\[\]()]+[\s)]*\s*([A-Z][A-Za-z\s,&\-]+(?:university|college|institute|lab|center|school|research|company|inc|ltd))',
        re.IGNORECASE,
    )
    for line in header_lines:
        stripped = line.strip()
        m = footnote_pattern.search(stripped)
        if m:
            cleaned = clean_affiliation(m.group(1))
            if cleaned and len(cleaned) > 5:
                affs.append(cleaned)
    if affs:
        result["affiliations"] = _dedup_affiliations(affs)
        for line in header_lines:
            stripped = line.strip()
            if is_author_line(stripped):
                result["authors"].append(stripped)
        if result["affiliations"]:
            return result

    # Strategy 3: 版权行匹配
    affs = []
    copyright_pattern = re.compile(
        r'©\s*\d{4}\s+([A-Z][A-Za-z\s,&\-]+(?:university|college|institute|lab|center|school|research|company|inc|ltd))',
        re.IGNORECASE,
    )
    for line in lines[:80]:
        m = copyright_pattern.search(line)
        if m:
            cleaned = clean_affiliation(m.group(1))
            if cleaned and len(cleaned) > 5:
                affs.append(cleaned)
    if affs:
        result["affiliations"] = _dedup_affiliations(affs)
        if result["affiliations"]:
            return result

    # Strategy 4: 全文扫描（前 60 行）
    affs = []
    for line in lines[:60]:
        stripped = line.strip()
        if not stripped or len(stripped) < 8:
            continue
        lowered = stripped.lower()
        if any(kw in lowered for kw in _AFFILIATION_KEYWORDS):
            if not looks_like_sentence(stripped):
                cleaned = clean_affiliation(stripped)
                if cleaned and len(cleaned) > 5:
                    affs.append(cleaned)
    if affs:
        result["affiliations"] = _dedup_affiliations(affs)
        if result["affiliations"]:
            return result

    # Strategy 5: 位置启发式
    affs = []
    author_line_idx = None
    for i, line in enumerate(header_lines):
        if is_author_line(line.strip()):
            author_line_idx = i
            break
    if author_line_idx is not None:
        for line in header_lines[author_line_idx + 1:]:
            stripped = line.strip()
            if not stripped:
                continue
            if re.search(r'\b(Abstract|Introduction)\b', stripped, re.IGNORECASE):
                break
            if len(stripped) < 15 or len(stripped) > 200:
                continue
            if any(kw in stripped.lower() for kw in _AFFILIATION_KEYWORDS):
                cleaned = clean_affiliation(stripped)
                if cleaned and len(cleaned) > 5:
                    affs.append(cleaned)
    if affs:
        result["affiliations"] = _dedup_affiliations(affs)
        if result["affiliations"]:
            return result

    return result


def _dedup_affiliations(affs: List[str]) -> List[str]:
    """去重：移除是其他机构子串的短版本。"""
    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for aff in affs:
        key = aff.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(aff)
    # Remove entries that are substrings of longer entries
    filtered = []
    for i, aff in enumerate(unique):
        aff_lower = aff.lower()
        is_substring = False
        for j, other in enumerate(unique):
            if i != j and aff_lower in other.lower():
                is_substring = True
                break
        if not is_substring:
            filtered.append(aff)
    return filtered


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enrich_paper(paper: Dict, timeout: int = 30) -> Dict:
    """Enrich a single paper with metadata from arXiv HTML.

    Args:
        paper: Paper dict from papers.yaml.
        timeout: HTTP request timeout in seconds.

    Returns:
        Updated paper dict with enriched metadata.
    """
    arxiv_id = _extract_arxiv_id(paper)
    if not arxiv_id:
        return paper

    # Fetch arXiv HTML
    html_url = f"https://arxiv.org/html/{arxiv_id}"
    html = _http_get(html_url, timeout)
    if not html or len(html) < 1000:
        # Try abs page as fallback
        abs_meta = _fetch_abs_meta(arxiv_id, timeout)
        if abs_meta:
            enriched = paper.get("enriched", {})
            if abs_meta.get("authors") and not enriched.get("authors"):
                enriched["authors"] = abs_meta["authors"]
            if abs_meta.get("affiliations") and not enriched.get("affiliations"):
                enriched["affiliations"] = abs_meta["affiliations"]
            paper["enriched"] = enriched
        return paper

    enriched: Dict[str, Any] = {}

    # Extract figure URL
    figure_url = _extract_figure_url(html, arxiv_id)
    if figure_url:
        enriched["figure_url"] = figure_url
        # Update preview if it's still a placeholder
        if paper.get("preview", "").endswith("placeholder.svg"):
            paper["preview"] = figure_url

    # Extract authors
    authors = _extract_authors_html(html)
    if authors:
        enriched["authors"] = authors

    # Extract affiliations
    affiliations = _extract_affiliations_html(html)
    if affiliations:
        enriched["affiliations"] = affiliations

    # Extract section headers
    headers = _extract_section_headers(html)
    if headers:
        enriched["section_headers"] = headers

    # Extract captions
    captions = _extract_captions(html)
    if captions:
        enriched["captions"] = captions

    # Extract method names
    title = paper.get("title", "")
    method_names = _extract_method_names(html, title)
    if method_names:
        enriched["method_names"] = method_names

    # Extract method summary
    method_summary = _extract_method_summary(html)
    if method_summary:
        enriched["method_summary"] = method_summary

    # Abs fallback for authors/affiliations if HTML extraction failed
    if not authors or not affiliations:
        abs_meta = _fetch_abs_meta(arxiv_id, timeout)
        if abs_meta.get("authors") and not enriched.get("authors"):
            enriched["authors"] = abs_meta["authors"]
        if abs_meta.get("affiliations") and not enriched.get("affiliations"):
            enriched["affiliations"] = abs_meta["affiliations"]

    # TeX source fallback: if authors or affiliations still empty, try TeX source
    if not enriched.get("authors") or not enriched.get("affiliations"):
        tex_content = _fetch_tex_source(arxiv_id, timeout)
        if tex_content:
            tex_meta = _extract_affiliations_from_tex(tex_content)
            if tex_meta.get("authors") and not enriched.get("authors"):
                enriched["authors"] = tex_meta["authors"]
                logger.debug("TeX fallback authors for %s: %s", arxiv_id, tex_meta["authors"])
            if tex_meta.get("affiliations") and not enriched.get("affiliations"):
                enriched["affiliations"] = tex_meta["affiliations"]
                logger.debug("TeX fallback affiliations for %s: %s", arxiv_id, tex_meta["affiliations"])
        else:
            logger.debug("TeX source fallback failed for %s", arxiv_id)

    # PDF fallback: if authors or affiliations still empty, try PDF text extraction
    if not enriched.get("authors") or not enriched.get("affiliations"):
        pdf_text = _fetch_pdf_text(arxiv_id, timeout)
        if pdf_text:
            pdf_meta = _extract_affiliations_from_pdf(pdf_text)
            if pdf_meta.get("authors") and not enriched.get("authors"):
                enriched["authors"] = pdf_meta["authors"]
                logger.debug("PDF fallback authors for %s: %s", arxiv_id, pdf_meta["authors"])
            if pdf_meta.get("affiliations") and not enriched.get("affiliations"):
                enriched["affiliations"] = pdf_meta["affiliations"]
                logger.debug("PDF fallback affiliations for %s: %s", arxiv_id, pdf_meta["affiliations"])
        else:
            logger.debug("PDF fallback failed for %s", arxiv_id)

    paper["enriched"] = enriched
    return paper


async def _enrich_paper_async(paper: Dict, sem: asyncio.Semaphore, timeout: int = 30) -> Dict:
    """异步包装 enrich_paper 调用，受 semaphore 限流。"""
    async with sem:
        loop = asyncio.get_running_loop()
        # 在线程池中运行同步的 enrich_paper
        return await loop.run_in_executor(None, enrich_paper, paper, timeout)


def enrich_papers(papers: List[Dict], config: dict) -> List[Dict]:
    """Batch enrich papers with metadata from arXiv HTML.

    Args:
        papers: List of paper dicts from papers.yaml.
        config: awesome.yaml config dict.

    Returns:
        Updated list of paper dicts with enriched metadata.
    """
    enrichment_config = config.get("research", {}).get("enrichment", {})
    if not enrichment_config.get("enabled", True):
        logger.info("元数据富化已禁用")
        return papers

    max_workers = enrichment_config.get("max_concurrent", 10)
    timeout = enrichment_config.get("request_timeout", 30)
    extract_figures = enrichment_config.get("extract_figures", True)
    extract_affiliations = enrichment_config.get("extract_affiliations", True)
    extract_methods = enrichment_config.get("extract_methods", True)

    # Filter papers that need enrichment (have arxiv ID, not yet enriched)
    to_enrich = []
    for p in papers:
        arxiv_id = _extract_arxiv_id(p)
        if arxiv_id and not p.get("enriched"):
            to_enrich.append(p)

    if not to_enrich:
        logger.info("没有需要富化的论文（无 arXiv ID）")
        return papers

    logger.info("富化 %d 篇论文（并发 %d）...", len(to_enrich), max_workers)

    # 使用 asyncio 运行
    async def _run():
        sem = asyncio.Semaphore(max_workers)
        tasks = [_enrich_paper_async(p, sem, timeout) for p in to_enrich]
        results = []
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            try:
                result = await coro
                results.append(result)
                if i % 10 == 0:
                    logger.info("  进度: %d/%d", i, len(to_enrich))
            except Exception as e:
                logger.warning("富化失败: %s", e)
                results.append(None)
        return results

    results = asyncio.run(_run())

    enriched_count = sum(1 for r in results if r and r.get("enriched"))
    logger.info("富化完成: %d/%d 篇成功", enriched_count, len(to_enrich))
    return papers


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="arXiv HTML 元数据富化")
    parser.add_argument("--max-workers", type=int, default=None,
                        help="最大并发数（覆盖配置）")
    parser.add_argument("--skip-figures", action="store_true",
                        help="跳过图片提取")
    parser.add_argument("--skip-affiliations", action="store_true",
                        help="跳过机构提取")
    parser.add_argument("--skip-methods", action="store_true",
                        help="跳过方法名提取")
    args = parser.parse_args()

    papers_path = DATA_DIR / "papers.yaml"
    if not papers_path.exists():
        logger.error("未找到 papers.yaml: %s", papers_path)
        return

    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    if not isinstance(papers, list):
        logger.error("papers.yaml 格式错误")
        return

    logger.info("加载 %d 篇论文", len(papers))

    # Build config from args overrides
    config = {
        "research": {
            "enrichment": {
                "enabled": True,
                "max_concurrent": args.max_workers or 10,
                "request_timeout": 30,
                "extract_figures": not args.skip_figures,
                "extract_affiliations": not args.skip_affiliations,
                "extract_methods": not args.skip_methods,
            }
        }
    }

    papers = enrich_papers(papers, config)

    # Save
    papers_path.write_text(
        yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    logger.info("已保存到 %s", papers_path)


if __name__ == "__main__":
    main()
