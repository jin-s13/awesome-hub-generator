#!/usr/bin/env python3
"""
sync.py — arXiv 论文适配器

从 arXiv API 获取论文元数据，调用 LLM 进行分类和标签推断，
然后合并到 data/papers.yaml 中。
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Load .env file if present
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _val = _val.strip("\"'")
                os.environ.setdefault(_key.strip(), _val)

import yaml
import requests
from slugify import slugify
from volcenginesdkarkruntime import Ark
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from scripts.llm_cache import (
        LLMCallResult,
        estimate_tokens_from_messages,
        estimate_tokens_from_text,
        get_default_cache,
        paper_identity_from,
        usage_from_provider,
    )
except ImportError:
    from llm_cache import (  # type: ignore
        LLMCallResult,
        estimate_tokens_from_messages,
        estimate_tokens_from_text,
        get_default_cache,
        paper_identity_from,
        usage_from_provider,
    )

ROOT = Path(__file__).resolve().parents[1]

# ---- LLM 调用 ----

def _get_ark_client() -> Optional[Ark]:
    """获取火山引擎 Ark 客户端"""
    api_key = os.environ.get("ARK_API_KEY", "")
    base_url = os.environ.get("ARK_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    if not api_key:
        print("[sync] 警告: 未配置 ARK_API_KEY，跳过 LLM 分类")
        return None
    return Ark(base_url=base_url, api_key=api_key)


def llm_chat_with_usage(messages: List[Dict], model: str = "", max_tokens: int = 1024) -> LLMCallResult:
    """调用火山引擎 DeepSeek LLM，返回文本和 token 用量。"""
    client = _get_ark_client()
    if not client:
        return LLMCallResult("")

    model = model or os.environ.get("ARK_MODEL_NAME", "deepseek-v4-flash-260425")

    try:
        response = client.responses.create(
            model=model,
            input=messages,
            temperature=0.1,
            max_output_tokens=max_tokens,
        )
        # responses API 返回格式
        text = ""
        for output in response.output:
            if output.type == "message":
                for content in output.content:
                    if content.type == "output_text":
                        text = content.text
                        break
        usage = usage_from_provider(
            getattr(response, "usage", None),
            prompt_fallback=estimate_tokens_from_messages(messages),
            completion_fallback=estimate_tokens_from_text(text),
        )
        return LLMCallResult.from_text(text, usage)
    except Exception as e:
        print(f"[sync] LLM 调用失败: {e}")
        return LLMCallResult("")


def llm_chat(messages: List[Dict], model: str = "") -> str:
    """调用火山引擎 DeepSeek LLM。"""
    return llm_chat_with_usage(messages, model).text


def classify_paper(title: str, abstract: str, categories: List[str],
                   research_context: str = "",
                   taxonomy: Optional[Dict] = None,
                   relevance_criteria: Optional[Dict] = None) -> Dict:
    """调用 LLM 对论文进行分类，返回 paper_type, tags, relevant 等字段。

    Args:
        research_context: 研究方向描述，用于判断相关性。为空时不过滤。
        taxonomy: 分类体系配置，含 paper_types 列表和 dimensions 列表。
        relevance_criteria: 相关性标准，含 include 和 exclude 列表。
    """
    tax = taxonomy or {}
    paper_types = tax.get("paper_types", [])
    if paper_types:
        pt_lines = "\n".join(f'  - "{pt["label"]}": {pt["description"]}' for pt in paper_types)
        pt_labels = ", ".join(f'"{pt["label"]}"' for pt in paper_types)
        pt_section = f"""- "paper_type": list of one or more labels from [{pt_labels}]
  Select ALL that apply:
{pt_lines}"""
    else:
        pt_section = '- "paper_type": ["method"]'

    dimensions = tax.get("dimensions", [])
    dim_lines = []
    for dim in dimensions:
        name = dim.get("name", "tags")
        desc = dim.get("description", "relevant attributes")
        dim_lines.append(f'- "{name}": list of {desc}')

    # 相关性判断指令
    relevance_instruction = ""
    if research_context and relevance_criteria:
        include_items = "\n".join(f"  - {item}" for item in relevance_criteria.get("include", []))
        exclude_items = "\n".join(f"  - {item}" for item in relevance_criteria.get("exclude", []))
        relevance_instruction = f"""
- "relevant": true or false — Is this paper directly relevant to "{research_context}"?
  A paper is RELEVANT if its core contribution matches any of:
{include_items}
  A paper is NOT RELEVANT if it is primarily about:
{exclude_items}"""

    dim_section = "\n".join(dim_lines) if dim_lines else '- "tags": list of 3-6 relevant tags'

    prompt = f"""Analyze this research paper and return a JSON object with these fields:
{pt_section}
{dim_section}{relevance_instruction}

Title: {title}
Abstract: {abstract[:800]}
arXiv Categories: {', '.join(categories)}

Return ONLY valid JSON, no other text."""

    model = os.environ.get("ARK_MODEL_NAME", "deepseek-v4-flash-260425")
    messages = [{"role": "user", "content": prompt}]
    paper_identity = paper_identity_from(
        title=title,
    )
    cache = get_default_cache()
    raw = cache.get_or_call_llm(
        task_type="classify_paper",
        model=model,
        prompt_version="classify_v1",
        paper_identity=paper_identity,
        abstract=abstract,
        criteria={
            "research_context": research_context,
            "taxonomy": taxonomy or {},
            "relevance_criteria": relevance_criteria or {},
        },
        messages=messages,
        call_func=lambda: llm_chat_with_usage(messages, model=model),
    ).text
    fallback = {"paper_type": ["method"], "tags": []}
    if not raw:
        return fallback

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group(0))
            # 确保 paper_type 是 list
            pt = result.get("paper_type")
            if isinstance(pt, str):
                result["paper_type"] = [pt]
            elif not isinstance(pt, list):
                result["paper_type"] = ["method"]
            return result
        except json.JSONDecodeError:
            pass
    return fallback


# ---- arXiv API ----

ARXIV_API_URL = "https://export.arxiv.org/api/query"


def fetch_arxiv_by_id(arxiv_id: str) -> Optional[Dict]:
    """通过 arXiv ID 获取单篇论文元数据。"""
    url = f"{ARXIV_API_URL}?id_list={arxiv_id}"
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "awesome-hub-generator/1.0"})
            resp.raise_for_status()
            entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL)
            if not entries:
                return None
            entry = entries[0]
            return {
                "title": _clean_xml(_extract_tag(entry, "title")),
                "abstract": _clean_xml(_extract_tag(entry, "summary")),
                "published": _extract_tag(entry, "published")[:10],
                "categories": re.findall(r'term="([^"]+)"', entry),
                "authors": _extract_authors(entry),
                "links": {"paper": f"https://arxiv.org/abs/{arxiv_id}"},
                "arxiv_id": arxiv_id,
            }
        except requests.RequestException as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                logger.warning(f"arXiv fetch failed for {arxiv_id}: {e}")
                return None


def search_arxiv(keywords: List[str], categories: List[str],
                 date_from: str = "", date_to: str = "",
                 max_results: int = 500) -> List[Dict]:
    """通过 arXiv API 搜索论文"""
    # arXiv API URL 长度有限制，关键词太多时需要分批查询
    # 每次最多用 10 个关键词
    BATCH_SIZE = 10
    all_papers = []
    seen_ids = set()

    for batch_start in range(0, len(keywords), BATCH_SIZE):
        batch_kw = keywords[batch_start:batch_start + BATCH_SIZE]

        # Build query
        kw_parts = []
        for kw in batch_kw:
            if " " in kw:
                kw_parts.append(f'%22{kw.replace(" ", "+")}%22')
            else:
                kw_parts.append(kw)
        query = "+OR+".join(f"all:{kw}" for kw in kw_parts)
        # 始终用括号包裹关键词 OR 子句，避免 AND 优先级高于 OR 导致语义错误
        query = f"({query})"

        if categories:
            cat_parts = "+OR+".join(f"cat:{c}" for c in categories)
            query = f"{query}+AND+({cat_parts})"

        if date_from:
            date_from_clean = date_from.replace("-", "")
            date_to_clean = date_to.replace("-", "") if date_to else datetime.now().strftime("%Y%m%d")
            query += f"+AND+submittedDate:[{date_from_clean}0000+TO+{date_to_clean}2359]"

        url = f"{ARXIV_API_URL}?search_query={query}&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
        print(f"[sync] arXiv API batch {batch_start//BATCH_SIZE + 1}: {len(batch_kw)} keywords")

        # Retry with backoff
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=120, headers={"User-Agent": "awesome-hub-generator/1.0"})
                resp.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt < 2:
                    wait = 2 ** attempt
                    print(f"[sync] arXiv API error ({e}), retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"[sync] arXiv API failed after 3 attempts: {e}")
                    raise

        # Parse arXiv XML response
        for entry in re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL):
            arxiv_id = _extract_arxiv_id(entry)
            title = _clean_xml(_extract_tag(entry, "title"))
            abstract = _clean_xml(_extract_tag(entry, "summary"))
            published = _extract_tag(entry, "published")[:10]
            cats = re.findall(r'term="([^"]+)"', entry)
            authors = _extract_authors(entry)

            links = {"paper": f"https://arxiv.org/abs/{arxiv_id}"}
            code_match = re.search(r"github\.com/[\w\-\.]+/[\w\-\.]+", abstract)
            if code_match:
                links["code"] = f"https://{code_match.group(0)}"

            pid = arxiv_id
            if pid not in seen_ids:
                seen_ids.add(pid)
                all_papers.append({
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "abstract": abstract,
                    "published": published,
                    "categories": cats,
                    "authors": authors,
                    "links": links,
                })

        # 避免请求过于频繁
        time.sleep(1)

    print(f"[sync] arXiv API 返回 {len(all_papers)} 篇论文（去重后）")
    return all_papers


def _extract_arxiv_id(entry: str) -> str:
    m = re.search(r"<id>https?://arxiv\.org/abs/([^<]+)</id>", entry)
    return m.group(1).strip() if m else ""


def _extract_tag(text: str, tag: str) -> str:
    m = re.search(f"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_authors(entry: str) -> List[str]:
    """Extract author names from an arXiv <entry> XML block."""
    names = re.findall(r"<author>.*?<name>(.*?)</name>.*?</author>", entry, re.DOTALL)
    return [_clean_xml(n) for n in names if _clean_xml(n)]


def _clean_xml(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"&[a-z]+;", "", text)
    return text.strip()


# ---- YAML 处理 ----

def load_yaml(path: Path) -> List[Dict]:
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    return []


def write_if_changed(path: Path, data: Any) -> bool:
    """幂等写入：如果内容不变则不写文件。

    Args:
        path: 文件路径
        data: Python 对象（将用 YAML 序列化）

    Returns:
        True 如果文件被写入，False 如果内容未变
    """
    new_content = yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    if path.exists() and path.read_text(encoding="utf-8") == new_content:
        return False
    path.write_text(new_content, encoding="utf-8")
    return True


def save_yaml(path: Path, data: List[Dict]) -> None:
    """Save data to YAML file with idempotent write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not write_if_changed(path, data):
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            rel = path
        print(f"[sync] 未变更 {rel} ({len(data)} 条)")
        return
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = path
    print(f"[sync] 已写入 {rel} ({len(data)} 条)")


def infer_venue(categories: List[str]) -> str:
    """从 arXiv 分类推断会议/期刊"""
    cat_str = " ".join(categories).lower()
    venue_map = [
        (r"cvpr", "CVPR"), (r"iccv", "ICCV"), (r"eccv", "ECCV"),
        (r"neurips|nips", "NeurIPS"), (r"iclr", "ICLR"), (r"icml", "ICML"),
        (r"aaai", "AAAI"), (r"siggraph", "SIGGRAPH"), (r"acl|emnlp|naacl", "ACL/EMNLP"),
        (r"tog|tvcg", "ACM TOG"), (r"pami|tpami", "TPAMI"),
    ]
    for pattern, venue in venue_map:
        if re.search(pattern, cat_str):
            return venue
    return "arXiv"


def extract_year(paper: Dict) -> int:
    """统一提取论文年份，按优先级尝试多个来源。

    1. paper["year"] — 已有年份
    2. paper["published"] — 发布日期（arXiv 格式 "2024-01-15T..."）
    3. paper["venue"] — 会议名含年份（如 "SIGGRAPH Asia 2025"）
    4. paper["links"]["paper"] — arXiv URL 中的年份（如 2401.12345）
    5. 当前年份（fallback）
    """
    # 1. 已有 year
    year = paper.get("year")
    if year and isinstance(year, int) and 1990 <= year <= 2030:
        return year
    if year and isinstance(year, str):
        m = re.search(r"(20\d{2})", year)
        if m:
            y = int(m.group(1))
            if 1990 <= y <= 2030:
                return y

    # 2. published 日期
    published = paper.get("published") or paper.get("publishedAt") or ""
    if published:
        m = re.search(r"(20\d{2})", str(published))
        if m:
            y = int(m.group(1))
            if 1990 <= y <= 2030:
                return y

    # 3. venue 含年份（如 "NeurIPS 2025", "CVPR 2021"）
    venue = paper.get("venue") or ""
    if venue:
        m = re.search(r"(20\d{2})", str(venue))
        if m:
            y = int(m.group(1))
            if 1990 <= y <= 2030:
                return y

    # 4. arXiv URL 中的年份（如 2401.12345 -> 2024）
    links = paper.get("links", {})
    if isinstance(links, dict):
        url = links.get("paper", "") or links.get("pdf", "")
        if url:
            m = re.search(r"/(\d{2})(\d{2})\.\d+", url)
            if m:
                y = 2000 + int(m.group(1))
                if 1990 <= y <= 2030:
                    return y

    # 5. fallback
    return datetime.now().year


def paper_to_yaml(paper: Dict, classification: Dict, source_repo: str = "arxiv") -> Dict:
    """将 arXiv 论文元数据转为 YAML 条目"""
    year = extract_year(paper)

    paper_type = classification.get("paper_type", ["method"])
    if isinstance(paper_type, str):
        paper_type = [paper_type]
    tags = classification.get("tags", [])
    # Add arXiv category tags
    for c in paper.get("categories", []):
        tag = c.split(".")[-1] if "." in c else c
        if tag not in tags:
            tags.append(tag)

    entry = {
        "id": slugify(f"{paper['title'][:60]}-{year}"),
        "title": paper["title"],
        "authors": paper.get("authors", []),
        "abstract": paper.get("abstract", ""),
        "year": year,
        "venue": infer_venue(paper.get("categories", [])),
        "paper_type": paper_type,
        "tags": tags[:8],
        "links": paper.get("links", {}),
        "preview": "/assets/placeholder.svg",
        "sources": [{"repo": source_repo}],
    }

    # 动态添加 taxonomy dimensions（techniques, inputs, outputs 等）
    for key, value in classification.items():
        if key in ("paper_type", "tags", "relevant", "category"):
            continue
        if isinstance(value, list):
            entry[key] = value

    return entry


def _filter_negative_keywords(papers: List[Dict], negative_keywords: List[str]) -> List[Dict]:
    """过滤掉命中负向关键词的论文。

    优先使用 LLM 语义理解（避免关键词误杀），
    LLM 不可用时 fallback 到关键词匹配。
    """
    if not negative_keywords:
        return papers

    # Try LLM-based filtering first
    api_key = os.environ.get("ARK_API_KEY", "")
    if api_key:
        try:
            from relevance_filter import _llm_filter_negative
            result = []
            for p in papers:
                title = p.get("title", "")
                abstract = p.get("abstract", "")
                if title and abstract:
                    llm_result = _llm_filter_negative(title, abstract, negative_keywords)
                    if llm_result is True:
                        continue  # excluded by LLM
                    if llm_result is False:
                        result.append(p)  # confirmed not excluded
                        continue
                    # llm_result is None → fallback to keyword matching
                # Fallback: keyword matching
                text = (title + " " + abstract).lower()
                nk_lower = [k.lower() for k in negative_keywords]
                if not any(nk in text for nk in nk_lower):
                    result.append(p)
            return result
        except ImportError:
            pass

    # Fallback: keyword matching
    nk_lower = [k.lower() for k in negative_keywords]
    result = []
    for p in papers:
        text = (p.get("title", "") + " " + p.get("abstract", "")).lower()
        if not any(nk in text for nk in nk_lower):
            result.append(p)
    return result


def deduplicate(existing: List[Dict], new_items: List[Dict]) -> Tuple[List[Dict], int]:
    """去重合并，返回合并后的列表和新增数量"""
    existing_titles = {e.get("title", "").lower().strip() for e in existing}
    existing_ids = {e.get("id", "") for e in existing}
    existing_paper_urls = {e.get("links", {}).get("paper", "") for e in existing}

    added = 0
    merged = list(existing)
    for item in new_items:
        title = item.get("title", "").lower().strip()
        pid = item.get("id", "")
        purl = item.get("links", {}).get("paper", "")
        if title in existing_titles or pid in existing_ids or purl in existing_paper_urls:
            continue
        merged.append(item)
        existing_titles.add(title)
        existing_ids.add(pid)
        existing_paper_urls.add(purl)
        added += 1

    # Sort: newest year first, then by title
    merged.sort(key=lambda x: (-int(x.get("year") or 0), x.get("title") or ""))
    return merged, added


# ---- 主入口 ----

def sync_papers(new_papers: List[Dict], output_path: Path, source_repo: str = "arxiv",
                skip_llm: bool = False, max_papers: Optional[int] = None,
                negative_keywords: Optional[List[str]] = None,
                research_context: str = "",
                taxonomy: Optional[Dict] = None,
                relevance_criteria: Optional[Dict] = None) -> int:
    """
    将新论文同步到 YAML 文件。
    Returns: 新增论文数量
    """
    if max_papers and len(new_papers) > max_papers:
        new_papers = new_papers[:max_papers]
        print(f"[sync] 限制为前 {max_papers} 篇论文")

    existing = load_yaml(output_path)
    print(f"[sync] 现有论文: {len(existing)} 篇")

    if negative_keywords:
        before = len(new_papers)
        new_papers = _filter_negative_keywords(new_papers, negative_keywords)
        filtered = before - len(new_papers)
        if filtered:
            print(f"[sync] 负向关键词过滤: 排除 {filtered} 篇不相关论文")

    # LLM 分类 + 相关性过滤
    classified = []
    rejected = 0
    for i, paper in enumerate(new_papers):
        if skip_llm:
            classification = {"category": "Others", "tags": []}
        else:
            print(f"[sync] 分类 [{i+1}/{len(new_papers)}]: {paper['title'][:60]}...")
            classification = classify_paper(
                paper["title"], paper["abstract"], paper.get("categories", []),
                research_context, taxonomy, relevance_criteria,
            )

        # 相关性过滤：LLM 判定不相关的论文直接拒绝
        if research_context and relevance_criteria and classification.get("relevant") is False:
            rejected += 1
            print(f"[sync]   ✗ 不相关，跳过")
            continue

        classified.append(paper_to_yaml(paper, classification, source_repo))

    if rejected:
        print(f"[sync] LLM 相关性过滤: 拒绝 {rejected} 篇不相关论文")

    # 去重合并
    merged, added = deduplicate(existing, classified)
    save_yaml(output_path, merged)
    print(f"[sync] 新增: {added} 篇, 总计: {len(merged)} 篇")
    return added


def main():
    import argparse
    parser = argparse.ArgumentParser(description="arXiv 论文适配器")
    parser.add_argument("--keywords", nargs="+", default=[], help="搜索关键词")
    parser.add_argument("--categories", nargs="+", default=[], help="arXiv 分类过滤")
    parser.add_argument("--date-from", default="", help="起始日期 YYYYMMDD")
    parser.add_argument("--date-to", default="", help="结束日期 YYYYMMDD")
    parser.add_argument("--max-results", type=int, default=200, help="最大结果数")
    parser.add_argument("--output", default=".local/data/papers.yaml", help="输出 YAML 路径")
    parser.add_argument("--source-repo", default="arxiv", help="来源标识")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 分类")
    parser.add_argument("--arxiv-ids", nargs="+", default=[], help="直接指定 arxiv ID 列表（跳过搜索）")
    args = parser.parse_args()

    output_path = (ROOT / args.output).resolve()

    if args.arxiv_ids:
        # 通过 arxiv ID 获取论文
        papers = []
        for aid in args.arxiv_ids:
            result = search_arxiv([], [], max_results=1)
            # search_arxiv with specific IDs
            url = f"{ARXIV_API_URL}?id_list={aid}"
            resp = requests.get(url, timeout=30, headers={"User-Agent": "awesome-hub-generator/1.0"})
            resp.raise_for_status()
            for entry in re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL):
                papers.append({
                    "arxiv_id": aid,
                    "title": _clean_xml(_extract_tag(entry, "title")),
                    "abstract": _clean_xml(_extract_tag(entry, "summary")),
                    "published": _extract_tag(entry, "published")[:10],
                    "categories": re.findall(r'term="([^"]+)"', entry),
                    "links": {"paper": f"https://arxiv.org/abs/{aid}"},
                })
    else:
        papers = search_arxiv(args.keywords, args.categories, args.date_from, args.date_to, args.max_results)

    if not papers:
        print("[sync] 未找到论文")
        return

    added = sync_papers(papers, output_path, args.source_repo, args.skip_llm)
    print(f"[sync] 完成！新增 {added} 篇论文")


if __name__ == "__main__":
    main()
