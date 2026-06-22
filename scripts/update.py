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

from config_bridge import deep_merge

# CWD is the site root (downstream repo root, or generator root for dev).
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

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger("update")


def load_config() -> dict:
    import yaml
    config_path = SITE_DIR / "awesome.yaml"
    if not config_path.exists():
        config_path = ROOT / "awesome.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    # Check for local override file in the same directory
    local_path = config_path.with_name(f"{config_path.stem}.local{config_path.suffix}")
    if local_path.exists():
        local_config = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        config = deep_merge(config, local_config)
        logger.info(f"已合并本地覆盖: {local_path}")

    return config


def load_papers_yaml(path: Path) -> List[Dict[str, Any]]:
    """Load existing papers from YAML file."""
    import yaml
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []


def save_papers_yaml(path: Path, papers: List[Dict[str, Any]]) -> None:
    """Save papers to YAML file with idempotent write."""
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    new_content = yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False)
    if path.exists() and path.read_text(encoding="utf-8") == new_content:
        logger.info(f"未变更 {path.name} ({len(papers)} 条)")
        return
    path.write_text(new_content, encoding="utf-8")


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
    parser = argparse.ArgumentParser(description="每日增量更新 / 查漏补缺")
    parser.add_argument("--config", default="awesome.yaml", help="配置文件路径")
    parser.add_argument("--output", default=".local/website", help="网站输出目录")
    parser.add_argument("--data-dir", default=".local/data", help="数据目录（产出物隔离）")
    parser.add_argument("--search-days", type=int, default=None,
                        help="覆盖 awesome.yaml 中的 daily_search_days（用于 gap-fill）")
    parser.add_argument("--skip-researcher", action="store_true",
                        help="跳过 arxiv-daily-researcher（使用 arXiv API fallback）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 分类")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm build")
    parser.add_argument("--skip-teasers", action="store_true", help="跳过 teaser 图抓取")
    args = parser.parse_args()

    config = load_config()
    # Override search_days if specified (for gap-fill mode)
    if args.search_days is not None:
        config.setdefault("research", {})["daily_search_days"] = args.search_days
        logger.info(f"Gap-fill mode: searching last {args.search_days} days")

    # Pre-read config sections used across multiple steps
    history_config = config.get("research", {}).get("history", {})
    sources_config = config.get("research", {}).get("sources", {})
    enrichment_config = config.get("research", {}).get("enrichment", {})

    output_dir = (SITE_DIR / args.output).resolve()
    data_dir = (SITE_DIR / args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    papers_yaml = data_dir / "papers.yaml"

    import os
    os.environ["HUB_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("HUB_ASSETS_DIR", str(data_dir.parent / "assets" / "papers"))

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

    # Step 1.1: HuggingFace 数据源（如果启用）
    if sources_config.get("huggingface_daily", False) or sources_config.get("huggingface_trending", False):
        try:
            from scripts.hf_source import fetch_all_hf_papers
            logger.info("Fetching HuggingFace data sources...")
            hf_papers = fetch_all_hf_papers(config)
            if hf_papers:
                new_papers.extend(hf_papers)
                logger.info(f"HF sources: {len(hf_papers)} papers")
        except Exception as e:
            logger.warning(f"HF source fetch failed (non-fatal): {e}")

    # Step 1.2: 跨天去重历史记录
    if history_config.get("enabled", True) and new_papers:
        try:
            from scripts.history_manager import HistoryManager

            hm = HistoryManager(
                data_dir / ".history.json",
                retention_days=history_config.get("retention_days", 30),
            )
            weekend_mode = history_config.get("weekend_mode", True)
            new_papers, seen_papers = hm.filter_seen(new_papers, weekend_mode=weekend_mode)
            logger.info(f"History filter: {len(new_papers)} new, {len(seen_papers)} seen")

            # Backfill if not enough papers
            min_papers = history_config.get("min_papers_per_run", 20)
            if len(new_papers) < min_papers and seen_papers:
                backfill = hm.backfill(seen_papers, min_papers - len(new_papers))
                if backfill:
                    new_papers.extend(backfill)
                    logger.info(f"Backfilled {len(backfill)} papers from history")
        except Exception as e:
            logger.warning(f"History management failed (non-fatal): {e}")

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
            before_count = len(new_papers)
            merged, added = ResearcherAdapter.deduplicate(existing, new_papers)
            save_papers_yaml(papers_yaml, merged)
            skipped = before_count - added
            logger.info(f"Added {added}, skipped {skipped} duplicates (total: {len(merged)})")

        logger.info(f"Added {added} new papers")
    else:
        logger.info("No new papers found")

    # Step 2.1: 记录到历史记录
    if history_config.get("enabled", True) and new_papers:
        try:
            from scripts.history_manager import HistoryManager
            hm = HistoryManager(
                data_dir / ".history.json",
                retention_days=history_config.get("retention_days", 30),
            )
            hm.add_entries(new_papers)
            hm.prune()
        except Exception as e:
            logger.warning(f"History recording failed (non-fatal): {e}")

    # Step 2.2: 元数据富化（arXiv HTML 提取）
    if enrichment_config.get("enabled", True):
        try:
            from scripts.enrich_metadata import enrich_papers
            from scripts.sync import load_yaml, save_yaml

            logger.info("Enriching paper metadata...")
            papers = load_yaml(papers_yaml)
            if papers:
                papers = enrich_papers(papers, config)
                save_yaml(papers_yaml, papers)
                logger.info(f"Metadata enrichment done ({len(papers)} papers)")
        except Exception as e:
            logger.warning(f"Metadata enrichment failed (non-fatal): {e}")

    # Step 3: 获取论文 teaser 图
    if not args.skip_teasers:
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
        data_src = data_dir
        data_dst = output_dir / "data"
        if data_src.exists():
            shutil.copytree(data_src, data_dst, dirs_exist_ok=True)

        build_site(output_dir)

    logger.info("Update complete!")


if __name__ == "__main__":
    main()
