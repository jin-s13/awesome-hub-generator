#!/usr/bin/env python3
"""
sync.py — arXiv 论文适配器

从 arXiv API 获取论文元数据，调用 LLM 进行分类和标签推断，
然后合并到 data/papers.yaml 中。
"""
from __future__ import annotations

import os
import re
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import yaml
import requests
from slugify import slugify
from volcenginesdkarkruntime import Ark

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


def llm_chat(messages: List[Dict], model: str = "") -> str:
    """调用火山引擎 DeepSeek LLM"""
    client = _get_ark_client()
    if not client:
        return ""

    model = model or os.environ.get("ARK_MODEL_NAME", "deepseek-v4-flash-260425")

    try:
        response = client.responses.create(
            model=model,
            input=messages,
            temperature=0.1,
            max_output_tokens=1024,
        )
        # responses API 返回格式
        for output in response.output:
            if output.type == "message":
                for content in output.content:
                    if content.type == "output_text":
                        return content.text
        return ""
    except Exception as e:
        print(f"[sync] LLM 调用失败: {e}")
        return ""


def classify_paper(title: str, abstract: str, categories: List[str]) -> Dict:
    """调用 LLM 对论文进行分类，返回 category, tags, representations, modalities"""
    prompt = f"""Analyze this research paper and return a JSON object with these fields:
- "category": one of ["Generation", "Reconstruction", "Analysis", "Survey", "Abstraction", "Others"]
- "tags": list of 3-6 relevant tags (short keywords)
- "representations": list of data representations used (e.g., ["B-Rep", "Point Cloud", "Mesh", "CAD Program"])
- "input_modalities": list of input types (e.g., ["Text", "Image", "Point Cloud", "Latent"])
- "output_modalities": list of output types (e.g., ["CAD Model", "CAD Program", "B-Rep"])

Title: {title}
Abstract: {abstract[:800]}
arXiv Categories: {', '.join(categories)}

Return ONLY valid JSON, no other text."""

    raw = llm_chat([{"role": "user", "content": prompt}])
    if not raw:
        return {"category": "Others", "tags": [], "representations": [], "input_modalities": [], "output_modalities": []}

    # Extract JSON from response
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    return {"category": "Others", "tags": [], "representations": [], "input_modalities": [], "output_modalities": []}


# ---- arXiv API ----

ARXIV_API_URL = "https://export.arxiv.org/api/query"

def search_arxiv(keywords: List[str], categories: List[str],
                 date_from: str = "", date_to: str = "",
                 max_results: int = 500) -> List[Dict]:
    """通过 arXiv API 搜索论文"""
    # Build query
    kw_parts = []
    for kw in keywords:
        if " " in kw:
            kw_parts.append(f'%22{kw.replace(" ", "+")}%22')
        else:
            kw_parts.append(kw)
    query = "+OR+".join(f"all:{kw}" for kw in kw_parts)

    if categories:
        cat_parts = "+OR+".join(f"cat:{c}" for c in categories)
        query = f"({query})+AND+({cat_parts})"

    if date_from:
        # arXiv API 需要 YYYYMMDD 格式，去掉连字符
        date_from_clean = date_from.replace("-", "")
        date_to_clean = date_to.replace("-", "") if date_to else datetime.now().strftime("%Y%m%d")
        query += f"+AND+submittedDate:[{date_from_clean}0000+TO+{date_to_clean}2359]"

    url = f"{ARXIV_API_URL}?search_query={query}&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    print(f"[sync] arXiv API: {url[:120]}...")

    resp = requests.get(url, timeout=120, headers={"User-Agent": "awesome-hub-generator/1.0"})
    resp.raise_for_status()

    papers = []
    for entry in re.findall(r"<entry>(.*?)</entry>", resp.text, re.DOTALL):
        arxiv_id = _extract_arxiv_id(entry)
        title = _clean_xml(_extract_tag(entry, "title"))
        abstract = _clean_xml(_extract_tag(entry, "summary"))
        published = _extract_tag(entry, "published")[:10]
        cats = re.findall(r'term="([^"]+)"', entry)

        links = {"paper": f"https://arxiv.org/abs/{arxiv_id}"}
        # Check for code links in abstract
        code_match = re.search(r"github\.com/[\w\-\.]+/[\w\-\.]+", abstract)
        if code_match:
            links["code"] = f"https://{code_match.group(0)}"

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "published": published,
            "categories": cats,
            "links": links,
        })

    print(f"[sync] 从 arXiv 获取到 {len(papers)} 篇论文")
    return papers


def _extract_arxiv_id(entry: str) -> str:
    m = re.search(r"<id>https?://arxiv\.org/abs/([^<]+)</id>", entry)
    return m.group(1).strip() if m else ""


def _extract_tag(text: str, tag: str) -> str:
    m = re.search(f"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else ""


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


def save_yaml(path: Path, data: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
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


def paper_to_yaml(paper: Dict, classification: Dict, source_repo: str = "arxiv") -> Dict:
    """将 arXiv 论文元数据转为 YAML 条目"""
    year_match = re.search(r"(\d{4})", paper.get("published", ""))
    year = int(year_match.group(1)) if year_match else datetime.now().year

    cat = classification.get("category", "Others")
    tags = classification.get("tags", [])
    # Add arXiv category tags
    for c in paper.get("categories", []):
        tag = c.split(".")[-1] if "." in c else c
        if tag not in tags:
            tags.append(tag)

    return {
        "id": slugify(f"{paper['title'][:60]}-{year}"),
        "title": paper["title"],
        "year": year,
        "venue": infer_venue(paper.get("categories", [])),
        "category": cat,
        "tags": tags[:8],
        "representations": classification.get("representations", []),
        "input_modalities": classification.get("input_modalities", []),
        "output_modalities": classification.get("output_modalities", []),
        "links": paper.get("links", {}),
        "preview": "/assets/placeholder.svg",
        "sources": [{"repo": source_repo, "category": cat}],
    }


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
    merged.sort(key=lambda x: (-int(x.get("year", 0)), x.get("title", "")))
    return merged, added


# ---- 主入口 ----

def sync_papers(new_papers: List[Dict], output_path: Path, source_repo: str = "arxiv",
                skip_llm: bool = False) -> int:
    """
    将新论文同步到 YAML 文件。
    Returns: 新增论文数量
    """
    existing = load_yaml(output_path)
    print(f"[sync] 现有论文: {len(existing)} 篇")

    # LLM 分类
    classified = []
    for i, paper in enumerate(new_papers):
        if skip_llm:
            classification = {"category": "Others", "tags": [], "representations": [], "input_modalities": [], "output_modalities": []}
        else:
            print(f"[sync] 分类 [{i+1}/{len(new_papers)}]: {paper['title'][:60]}...")
            classification = classify_paper(paper["title"], paper["abstract"], paper.get("categories", []))

        classified.append(paper_to_yaml(paper, classification, source_repo))

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
    parser.add_argument("--output", default="data/papers.yaml", help="输出 YAML 路径")
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
