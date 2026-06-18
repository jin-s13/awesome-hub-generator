#!/usr/bin/env python3
"""
update.py — 每日增量更新入口

1. 通过 ResearcherAdapter 运行 arxiv-daily-researcher（Python import 方式）
2. 将结构化结果转换为 papers.yaml 格式
3. 去重合并到 data/papers.yaml
4. 重新构建网站

Fallback: 当 researcher 不可用时，降级到 sync.py 的 arXiv API 搜索。
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger("update")


def load_config() -> dict:
    import yaml
    config_path = ROOT / "awesome.yaml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def load_papers_yaml(path: Path) -> List[Dict[str, Any]]:
    """Load existing papers from YAML file."""
    import yaml
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []


def save_papers_yaml(path: Path, papers: List[Dict[str, Any]]) -> None:
    """Save papers to YAML file."""
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(papers, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def update_from_arxiv_api(config: dict) -> List[Dict[str, Any]]:
    """Fallback: directly fetch from arXiv API when researcher is unavailable."""
    from scripts.sync import search_arxiv, sync_papers

    research = config.get("research", {})
    keywords = research.get("keywords", [])
    categories = research.get("arxiv_categories", [])
    search_days = research.get("daily_search_days", 3)

    date_from = (datetime.now() - timedelta(days=search_days)).strftime("%Y%m%d")
    date_to = datetime.now().strftime("%Y%m%d")

    logger.info(f"Fallback: fetching from arXiv API (last {search_days} days)...")
    papers = search_arxiv(keywords, categories, date_from, date_to, max_results=200)
    return papers


def main():
    import argparse
    parser = argparse.ArgumentParser(description="每日增量更新")
    parser.add_argument("--config", default="awesome.yaml", help="配置文件路径")
    parser.add_argument("--output", default="output/website", help="网站输出目录")
    parser.add_argument("--skip-researcher", action="store_true",
                        help="跳过 arxiv-daily-researcher（使用 arXiv API fallback）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 分类")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm build")
    args = parser.parse_args()

    config = load_config()
    output_dir = (ROOT / args.output).resolve()
    papers_yaml = ROOT / "data" / "papers.yaml"

    # Step 1: 论文发现
    new_papers: List[Dict[str, Any]] = []

    if not args.skip_researcher:
        try:
            from scripts.researcher_adapter import ResearcherAdapter

            logger.info("Running arxiv-daily-researcher via ResearcherAdapter...")
            adapter = ResearcherAdapter(config)
            result = adapter.run_daily_research()
            new_papers = adapter.convert_to_papers_yaml(result)
            logger.info(f"Researcher found {len(new_papers)} papers")
        except ImportError as e:
            logger.warning(f"Researcher unavailable ({e}), falling back to arXiv API")
        except Exception as e:
            logger.warning(f"Researcher failed ({e}), falling back to arXiv API")

    if not new_papers:
        logger.info("Using arXiv API as data source")
        new_papers = update_from_arxiv_api(config)

    # Step 2: 去重合并到 papers.yaml
    if new_papers:
        existing = load_papers_yaml(papers_yaml)
        logger.info(f"Existing papers: {len(existing)}")

        if args.skip_researcher:
            # Fallback path: use sync.py's LLM classification
            from scripts.sync import sync_papers
            added = sync_papers(
                new_papers, papers_yaml,
                source_repo="arxiv", skip_llm=args.skip_llm
            )
        else:
            # Researcher path: papers already have scores/analysis, just deduplicate
            from scripts.researcher_adapter import ResearcherAdapter
            merged, added = ResearcherAdapter.deduplicate(existing, new_papers)
            save_papers_yaml(papers_yaml, merged)
            logger.info(f"New: {added}, Total: {len(merged)}")

        logger.info(f"Added {added} new papers")
    else:
        logger.info("No new papers found")

    # Step 3: 获取论文 teaser 图
    try:
        from fetch_teasers import main as fetch_teasers
        logger.info("Fetching paper teaser images...")
        fetch_teasers()
    except Exception as e:
        logger.warning(f"Teaser fetch failed (non-fatal): {e}")

    # Step 4: 重新构建网站
    if not args.skip_build:
        from build import generate_site, build_site

        generate_site(config, output_dir)

        # Copy data to website directory
        data_src = ROOT / "data"
        data_dst = output_dir / "data"
        if data_src.exists():
            shutil.copytree(data_src, data_dst, dirs_exist_ok=True)

        build_site(output_dir)

    logger.info("Update complete!")


if __name__ == "__main__":
    main()
