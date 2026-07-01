#!/usr/bin/env python3
"""
discover_datasets.py — Datasets 页面自动填充

两个数据来源:
1. HuggingFace Datasets: 从配置的 HF dataset URL 抓取元数据
2. papers.yaml 提取: 标题含 "dataset"/"benchmark"、paper_type 含 "benchmark"、
   或 links 中含 "dataset" 键的论文，转为 dataset 条目

合并去重后写入 datasets.yaml。

用法:
    python scripts/discover_datasets.py
    python scripts/discover_datasets.py --config awesome.yaml --data-dir .local/data
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = Path.cwd()

# Load .env file
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

logger = logging.getLogger("discover_datasets")

USER_AGENT = "awesome-hub-generator/1.0"
REQUEST_TIMEOUT = 30

# ---------------------------------------------------------------------------
# HTTP 请求
# ---------------------------------------------------------------------------


def _http_get_json(url: str) -> Any:
    """用 urllib.request 发起 GET 请求并解析 JSON 响应。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
        logger.warning("请求失败: %s - %s", url, e)
        return None


# ---------------------------------------------------------------------------
# HuggingFace Datasets 元数据抓取
# ---------------------------------------------------------------------------

_HF_DATASET_URL_RE = re.compile(r"huggingface\.co/datasets/([^/]+/[^/?#]+)")


def _extract_hf_repo_id(url: str) -> Optional[str]:
    """从 HF dataset URL 中提取 repo_id (owner/name)。"""
    m = _HF_DATASET_URL_RE.search(url)
    return m.group(1) if m else None


def _fetch_hf_dataset_metadata(repo_id: str) -> Optional[Dict[str, Any]]:
    """通过 HF API 抓取 dataset 元数据。

    API: https://huggingface.co/api/datasets/{repo_id}
    """
    url = f"https://huggingface.co/api/datasets/{repo_id}"
    logger.info("抓取 HF Dataset 元数据: %s", repo_id)
    data = _http_get_json(url)
    if not data or not isinstance(data, dict):
        logger.warning("HF Dataset %s 返回数据为空或格式异常", repo_id)
        return None

    # 提取字段
    tags = data.get("tags", []) or []
    # 从 tags 中提取任务类别
    task_categories = [
        t.replace("task_categories:", "")
        for t in tags
        if t.startswith("task_categories:")
    ]
    # 从 tags 中提取模态
    modalities = [
        t.replace("modality:", "")
        for t in tags
        if t.startswith("modality:")
    ]
    # 其他自定义 tag
    custom_tags = [
        t for t in tags
        if not t.startswith("task_categories:")
        and not t.startswith("modality:")
        and not t.startswith("language:")
        and not t.startswith("size_categories:")
        and not t.startswith("format:")
        and not t.startswith("library:")
    ]

    # 描述: 优先 cardData.description，其次 description
    description = (
        data.get("cardData", {}).get("description")
        or data.get("description")
        or ""
    ).strip()

    # arxiv 关联
    arxiv_id = data.get("cardData", {}).get("arxiv") or ""

    # size
    size_info = ""
    for t in tags:
        if t.startswith("size_categories:"):
            size_info = t.replace("size_categories:", "")
            break

    # license
    license_info = (
        data.get("cardData", {}).get("license")
        or data.get("license")
        or ""
    )
    if isinstance(license_info, list):
        license_info = license_info[0] if license_info else ""

    # likes
    likes = data.get("likes", 0) or 0

    # downloads
    downloads = data.get("downloads", 0) or 0

    # last_modified
    last_modified = data.get("lastModified", "") or ""

    return {
        "id": repo_id.lower().replace("/", "-"),
        "name": repo_id.split("/")[-1],
        "type": "dataset",
        "category": ", ".join(task_categories) if task_categories else "Dataset",
        "description": description or f"HuggingFace dataset: {repo_id}",
        "tags": custom_tags[:8] if custom_tags else [],
        "links": {
            "dataset": f"https://huggingface.co/datasets/{repo_id}",
            **({"paper": f"https://arxiv.org/abs/{arxiv_id}"} if arxiv_id else {}),
        },
        "sources": [{"repo": repo_id}],
        "metadata": {
            "modalities": modalities,
            "size": size_info,
            "license": license_info,
            "likes": likes,
            "downloads": downloads,
            "last_modified": last_modified,
            "tasks": task_categories,
        },
    }


def fetch_hf_datasets(config: dict) -> List[Dict[str, Any]]:
    """从配置的 HF dataset URLs 抓取元数据。

    config 格式:
        research:
          datasets:
            huggingface:
              - "https://huggingface.co/datasets/ADSKAILab/Zero-To-CAD-1m"
    """
    datasets_config = config.get("research", {}).get("datasets", {})
    hf_urls = datasets_config.get("huggingface", [])

    if not hf_urls:
        logger.info("未配置 HF dataset URL")
        return []

    results: List[Dict[str, Any]] = []
    for url in hf_urls:
        repo_id = _extract_hf_repo_id(url)
        if not repo_id:
            logger.warning("无法解析 HF dataset URL: %s", url)
            continue
        metadata = _fetch_hf_dataset_metadata(repo_id)
        if metadata:
            results.append(metadata)
            logger.info("  ✓ %s (likes=%d)", repo_id, metadata["metadata"]["likes"])

    logger.info("HF Datasets 共抓取 %d 个", len(results))
    return results


# ---------------------------------------------------------------------------
# 从 papers.yaml 提取 dataset/benchmark 条目
# ---------------------------------------------------------------------------

_DATASET_TITLE_RE = re.compile(r"\b(dataset|benchmark)\b", re.IGNORECASE)


def _is_dataset_paper(paper: Dict) -> bool:
    """判断论文是否与 dataset/benchmark 相关。"""
    # 1. 标题含 "dataset" 或 "benchmark"
    title = (paper.get("title") or "").lower()
    if _DATASET_TITLE_RE.search(title):
        return True

    # 2. paper_type 含 "benchmark"
    paper_type = paper.get("paper_type") or []
    if isinstance(paper_type, list) and "benchmark" in paper_type:
        return True

    # 3. links 中含 "dataset" 键
    links = paper.get("links") or {}
    if isinstance(links, dict) and "dataset" in links:
        return True

    return False


def _paper_to_dataset_entry(paper: Dict) -> Dict[str, Any]:
    """将论文条目转换为 dataset 条目。"""
    paper_id = paper.get("id", "")
    title = paper.get("title", "").strip("*")

    # 构建描述: 优先 tldr，其次 abstract 截取
    description = (paper.get("tldr") or "").strip()
    if not description:
        abstract = (paper.get("abstract") or "").strip()
        if abstract:
            # 截取前 300 字符
            description = abstract[:300]
            if len(abstract) > 300:
                description += "..."
        else:
            description = ""

    # 链接: 保留 paper 原有 links，但不包含 paper 自身的 detail 链接
    links = {}
    for key, value in (paper.get("links") or {}).items():
        if value:
            links[key] = value

    # 标签
    tags = paper.get("tags") or []
    if not tags:
        # 从 paper_type 构建标签
        paper_type = paper.get("paper_type") or []
        if isinstance(paper_type, list):
            tags = list(paper_type)

    # 判断类型
    paper_type = paper.get("paper_type") or []
    is_benchmark = isinstance(paper_type, list) and "benchmark" in paper_type
    entry_type = "benchmark" if is_benchmark else "dataset"

    # 分类: 优先使用 paper 的 category
    category = paper.get("category") or "Dataset"

    return {
        "id": paper_id,
        "name": title,
        "type": entry_type,
        "category": category,
        "year": paper.get("year"),
        "description": description,
        "tags": tags[:8] if tags else [],
        "links": links,
        "sources": paper.get("sources") or [],
    }


def extract_datasets_from_papers(papers_yaml: Path) -> List[Dict[str, Any]]:
    """从 papers.yaml 中提取与 dataset/benchmark 相关的条目。"""
    if not papers_yaml.exists():
        logger.info("papers.yaml 不存在，跳过提取")
        return []

    papers = yaml.safe_load(papers_yaml.read_text(encoding="utf-8")) or []
    if not isinstance(papers, list):
        return []

    results: List[Dict[str, Any]] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        if _is_dataset_paper(paper):
            entry = _paper_to_dataset_entry(paper)
            results.append(entry)

    logger.info("从 papers.yaml 提取 %d 个 dataset/benchmark 条目", len(results))
    return results


# ---------------------------------------------------------------------------
# 合并去重
# ---------------------------------------------------------------------------


def _merge_datasets(
    existing: List[Dict], new_entries: List[Dict]
) -> tuple[List[Dict], int]:
    """合并去重，以 id 为 key。新条目覆盖旧条目的空字段。

    Returns:
        (merged_list, added_count)
    """
    merged: Dict[str, Dict] = {e.get("id", ""): e for e in existing if isinstance(e, dict)}
    added = 0

    for entry in new_entries:
        key = entry.get("id", "")
        if not key:
            continue

        if key in merged:
            # 合并: 新条目填充旧条目的空字段
            existing_entry = merged[key]
            for field, value in entry.items():
                if not existing_entry.get(field) and value:
                    existing_entry[field] = value
            # 合并 tags (去重)
            existing_tags = set(existing_entry.get("tags") or [])
            for t in (entry.get("tags") or []):
                existing_tags.add(t)
            existing_entry["tags"] = sorted(existing_tags)[:8]
            # 合并 links
            existing_links = existing_entry.get("links") or {}
            for k, v in (entry.get("links") or {}).items():
                if k not in existing_links and v:
                    existing_links[k] = v
            existing_entry["links"] = existing_links
            # 合并 sources (去重 by repo)
            existing_sources = existing_entry.get("sources") or []
            seen_repos = {s.get("repo") for s in existing_sources if isinstance(s, dict)}
            for s in (entry.get("sources") or []):
                if isinstance(s, dict) and s.get("repo") not in seen_repos:
                    existing_sources.append(s)
                    seen_repos.add(s.get("repo"))
            existing_entry["sources"] = existing_sources
        else:
            merged[key] = entry
            added += 1

    return list(merged.values()), added


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def discover_datasets(config: dict, data_dir: Path = None) -> int:
    """自动发现并填充 datasets.yaml。

    Args:
        config: awesome.yaml 配置 dict
        data_dir: 数据目录，默认从 HUB_DATA_DIR 环境变量获取

    Returns:
        新增条目数
    """
    if data_dir is None:
        data_dir = DATA_DIR

    data_dir.mkdir(parents=True, exist_ok=True)
    datasets_yaml = data_dir / "datasets.yaml"
    papers_yaml = data_dir / "papers.yaml"

    # 加载现有 datasets.yaml
    existing: List[Dict] = []
    if datasets_yaml.exists():
        existing = yaml.safe_load(datasets_yaml.read_text(encoding="utf-8")) or []
        if not isinstance(existing, list):
            existing = []

    logger.info("现有 datasets.yaml: %d 条", len(existing))

    # 来源 1: HuggingFace Datasets
    hf_datasets = fetch_hf_datasets(config)

    # 来源 2: 从 papers.yaml 提取
    paper_datasets = extract_datasets_from_papers(papers_yaml)

    # 合并所有来源
    all_new = hf_datasets + paper_datasets
    merged, added = _merge_datasets(existing, all_new)

    # 按年份降序、名称排序
    merged.sort(
        key=lambda d: (-(d.get("year") or 0), d.get("name") or ""),
    )

    # 写入
    datasets_yaml.write_text(
        yaml.dump(merged, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    logger.info("datasets.yaml 已更新: %d 条 (新增 %d)", len(merged), added)

    return added


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="自动发现并填充 datasets.yaml")
    parser.add_argument("--config", default="awesome.yaml", help="配置文件路径")
    parser.add_argument("--data-dir", default=None, help="数据目录")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    # 加载配置
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = SITE_DIR / args.config
        if not config_path.exists():
            config_path = ROOT / args.config
    if not config_path.exists():
        print(f"错误: 未找到配置文件 {args.config}")
        sys.exit(1)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    # 数据目录
    data_dir = Path(args.data_dir) if args.data_dir else DATA_DIR

    added = discover_datasets(config, data_dir)
    print(f"\n=== Datasets 发现完成 ===")
    print(f"新增: {added} 条")


if __name__ == "__main__":
    main()
