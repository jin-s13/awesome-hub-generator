#!/usr/bin/env python3
"""
download_papers.py — 从 arXiv 下载论文 PDF 到 resource/ 目录

复用 arxiv-daily-researcher 子模块的 PDF 下载能力。
resource/ 目录不会被 git 跟踪（已在 .gitignore 中）。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_DIR = ROOT / "resource"

# 尝试导入子模块的 PDF 下载能力
try:
    sys.path.insert(0, str(ROOT / "arxiv-daily-researcher" / "src"))

    # 注入 API Key 到子模块的环境变量
    ark_key = os.environ.get("ARK_API_KEY", "")
    ark_base = os.environ.get("ARK_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    ark_model = os.environ.get("ARK_MODEL_NAME", "deepseek-v4-flash-260425")
    if ark_key:
        os.environ.setdefault("CHEAP_LLM__API_KEY", ark_key)
        os.environ.setdefault("CHEAP_LLM__BASE_URL", ark_base)
        os.environ.setdefault("CHEAP_LLM__MODEL_NAME", ark_model)
        os.environ.setdefault("SMART_LLM__API_KEY", ark_key)
        os.environ.setdefault("SMART_LLM__BASE_URL", ark_base)
        os.environ.setdefault("SMART_LLM__MODEL_NAME", ark_model)

    from agents.analysis_agent import AnalysisAgent
    _HAS_SUBMODULE = True
except ImportError as e:
    print(f"[download] 警告: 无法加载 arxiv-daily-researcher 子模块 ({e})，使用内置下载")
    _HAS_SUBMODULE = False


def _get_downloader():
    """获取 PDF 下载器实例"""
    if _HAS_SUBMODULE:
        try:
            return AnalysisAgent()
        except Exception as e:
            print(f"[download] 子模块 AnalysisAgent 初始化失败 ({e})，使用内置下载")
            return None
    return None


_DOWNLOADER = _get_downloader()


def load_papers() -> List[Dict]:
    """从 papers.yaml 加载论文列表"""
    data_dir = Path(os.environ.get("HUB_DATA_DIR", str(ROOT / ".local/data")))
    papers_path = data_dir / "papers.yaml"
    if not papers_path.exists():
        print(f"[download] 未找到 {papers_path}")
        return []
    with open(papers_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []


def extract_arxiv_id(paper_url: str) -> Optional[str]:
    """从 arXiv URL 中提取 ID"""
    if not paper_url:
        return None
    import re
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d+\.\d+)', paper_url)
    return m.group(1) if m else None


def download_pdf(arxiv_id: str, target_path: Path) -> bool:
    """下载 PDF — 优先复用子模块能力"""
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    # 优先使用子模块的下载能力
    if _DOWNLOADER is not None:
        try:
            pdf_bytes = _DOWNLOADER._download_pdf_bytes(pdf_url)
            if pdf_bytes and len(pdf_bytes) > 10000:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(pdf_bytes)
                print(f"[download] 已下载 (子模块): {arxiv_id} ({len(pdf_bytes)} bytes)")
                return True
        except Exception as e:
            print(f"[download] 子模块下载失败 {arxiv_id}: {e}，使用内置下载")

    # 内置下载（fallback）
    import requests
    try:
        resp = requests.get(pdf_url, timeout=60, headers={
            "User-Agent": "awesome-hub-generator/1.0",
        })
        if resp.status_code == 200 and len(resp.content) > 10000:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(resp.content)
            print(f"[download] 已下载 (内置): {arxiv_id} ({len(resp.content)} bytes)")
            return True
        else:
            print(f"[download] 下载失败 {arxiv_id}: HTTP {resp.status_code}")
            return False
    except Exception as e:
        print(f"[download] 下载异常 {arxiv_id}: {e}")
        return False


def download_all_papers(papers: Optional[List[Dict]] = None, force: bool = False) -> int:
    """下载所有论文的 PDF 到 resource/ 目录"""
    if papers is None:
        papers = load_papers()

    if not papers:
        print("[download] 没有论文需要下载")
        return 0

    downloaded = 0
    skipped = 0
    for paper in papers:
        paper_id = paper.get("id", "")
        if not paper_id:
            continue

        links = paper.get("links", {})
        paper_url = links.get("paper", "")
        arxiv_id = extract_arxiv_id(paper_url)
        if not arxiv_id:
            print(f"[download] 跳过 {paper_id}: 无法提取 arXiv ID")
            continue

        target_path = RESOURCE_DIR / paper_id / "paper.pdf"
        if target_path.exists() and not force:
            skipped += 1
            continue

        if download_pdf(arxiv_id, target_path):
            downloaded += 1
        time.sleep(1)  # Be polite to arXiv

    print(f"[download] 完成: 下载 {downloaded}, 跳过 {skipped}")
    return downloaded


def main():
    import argparse
    parser = argparse.ArgumentParser(description="下载论文 PDF 到 resource/ 目录")
    parser.add_argument("--force", action="store_true", help="强制重新下载")
    args = parser.parse_args()

    download_all_papers(force=args.force)


if __name__ == "__main__":
    main()
