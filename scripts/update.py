#!/usr/bin/env python3
"""
update.py — 论文更新入口（candidate 池架构）

两种模式：
  --init   初始化：全量搜索 → candidate 池 → 批量晋升 → 种子扩展
  --daily  每日更新：增量搜索 → candidate 池 → 增量晋升 → 增量种子扩展

数据流：
  数据源 (arXiv / HF / GitHub) → Candidate 池 (SQLite)
  → LLM 相关性筛选 → 展示池 (papers.yaml)
  → 元数据富化 / teaser / 解读 → 构建网站
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from config_bridge import deep_merge
from site_paths import (
    default_assets_dir,
    default_data_dir,
    default_output_dir,
    default_resource_dir,
    hub_workspace_dir,
    resolve_config_path,
    resolve_user_path,
)

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


def load_config(config_path: str = "awesome.yaml") -> dict:
    import yaml
    path = Path(config_path)
    if not path.is_absolute():
        site_path = SITE_DIR / config_path
        path = site_path if site_path.exists() else ROOT / config_path
    if not path.exists():
        logger.error(f"未找到配置文件: {config_path}")
        sys.exit(1)
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    local_path = path.with_name(f"{path.stem}.local{path.suffix}")
    if local_path.exists():
        local_config = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        config = deep_merge(config, local_config)
        logger.info(f"已合并本地覆盖: {local_path}")

    return config


def load_papers_yaml(path: Path) -> List[Dict[str, Any]]:
    import yaml
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []


def save_papers_yaml(path: Path, papers: List[Dict[str, Any]]) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    new_content = yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False)
    if path.exists() and path.read_text(encoding="utf-8") == new_content:
        logger.info(f"未变更 {path.name} ({len(papers)} 条)")
        return
    path.write_text(new_content, encoding="utf-8")
    logger.info(f"已写入 {path.name} ({len(papers)} 条)")


# === Step 1: 数据源 → Candidate 池 ===

def fetch_from_arxiv(config: dict, search_days: int) -> List[Dict]:
    """从 arXiv API 搜索论文。"""
    from scripts.sync import search_arxiv

    research = config.get("research", {})
    keywords = research.get("keywords", [])
    categories = research.get("arxiv_categories", [])

    date_from = (datetime.now() - timedelta(days=search_days)).strftime("%Y%m%d")
    date_to = datetime.now().strftime("%Y%m%d")

    logger.info(f"arXiv API: searching last {search_days} days...")
    try:
        return search_arxiv(keywords, categories, date_from, date_to, max_results=200)
    except Exception as e:
        logger.warning(f"arXiv API failed ({e}), skipping")
        return []


def fetch_from_hf(config: dict, search_days: int) -> List[Dict]:
    """从 HuggingFace Daily/Trending 抓取论文。"""
    from scripts.hf_source import fetch_all_hf_papers

    hf_date_from = (datetime.now() - timedelta(days=search_days)).strftime("%Y-%m-%d")
    hf_config = dict(config)
    hf_config.setdefault("research", {})["date_from"] = hf_date_from
    logger.info(f"HuggingFace: fetching from {hf_date_from}...")
    try:
        return fetch_all_hf_papers(hf_config)
    except Exception as e:
        logger.warning(f"HF source failed (non-fatal): {e}")
        return []


def collect_sources_to_pool(config: dict, pool, search_days: int):
    """Step 1: 从所有数据源收集论文到 candidate 池。"""
    from scripts.paper_sources import collect_paper_sources

    result = collect_paper_sources(config, search_days=search_days, max_results=200)
    for name, summary in result.get("sources", {}).items():
        if not summary.get("enabled"):
            continue
        if summary.get("error"):
            logger.warning("%s source failed: %s", name, summary["error"])
        else:
            logger.info("%s source: %s papers", name, summary.get("count", 0))

    papers = result.get("papers", [])
    if papers:
        added = pool.add_batch(papers, source="unified-sources")
        logger.info(f"Unified sources: +{added} candidates from {len(papers)} merged papers")


# === Step 2: Candidate → 展示池晋升 ===

def promote_candidates(config: dict, pool, papers_yaml: Path) -> int:
    """Step 2: 从 candidate 池中筛选相关论文，晋升到展示池。

    Returns: 晋升的论文数量。
    """
    from scripts.relevance_filter import is_cad_relevant
    from scripts.sync import paper_to_yaml, classify_paper, load_yaml, save_yaml

    research = config.get("research", {})
    project = config.get("project", {})
    research_context = f"{project.get('name', '')}: {project.get('description', '')}"
    relevance_criteria = research.get("relevance_criteria", {})
    taxonomy = research.get("taxonomy", {})
    batch_size = research.get("candidate_pool", {}).get("promote_batch_size", 20)

    # 获取未检查的候选论文
    unchecked = pool.get_unchecked(limit=batch_size * 2)
    if not unchecked:
        logger.info("No new candidates to check")
        return 0

    logger.info(f"Checking {len(unchecked)} candidates for relevance...")

    # 加载现有展示池
    existing = load_yaml(papers_yaml) if papers_yaml.exists() else []
    existing_keys = set()
    for p in existing:
        aid = p.get("arxiv_id") or ""
        if not aid:
            links = p.get("links", {})
            if isinstance(links, dict):
                url = links.get("paper", "")
                if url:
                    import re
                    m = re.search(r"(\d{4}\.\d{4,5})", url)
                    if m:
                        aid = m.group(1)
        existing_keys.add(aid or p.get("title", "").strip().lower())

    promoted = []
    for i, candidate in enumerate(unchecked):
        aid = candidate.get("arxiv_id", "")

        # 跳过已在展示池的论文
        check_key = aid or candidate.get("title", "").strip().lower()
        if check_key in existing_keys:
            pool.mark_relevance(aid, relevant=True)
            pool.mark_promoted(aid)
            continue

        # LLM 相关性判断
        relevant = is_cad_relevant(
            candidate,
            negative_keywords=None,
            min_score=0.0,
            research_context=research_context,
            relevance_criteria=relevance_criteria,
        )
        pool.mark_relevance(aid, relevant=relevant)

        if not relevant:
            continue

        # LLM 分类
        classification = {"category": "Others", "tags": []}
        if taxonomy:
            try:
                classification = classify_paper(
                    candidate.get("title", ""),
                    candidate.get("abstract", ""),
                    [],
                    taxonomy=taxonomy,
                    relevance_criteria=relevance_criteria,
                )
                if not classification.get("relevant", True):
                    pool.mark_relevance(aid, relevant=False)
                    continue
            except Exception as e:
                logger.warning(f"LLM classify failed for {aid}: {e}")

        # 转为展示池格式
        paper_entry = paper_to_yaml(
            {
                "title": candidate["title"],
                "abstract": candidate.get("abstract", ""),
                "authors": candidate.get("authors", []),
                "published": str(candidate.get("year", "")),
                "categories": [],
                "links": candidate.get("links", {}),
            },
            classification,
            source_repo=candidate.get("source", "candidate"),
        )
        if aid:
            paper_entry["arxiv_id"] = aid
        paper_entry["seed_expanded"] = False

        promoted.append(paper_entry)
        pool.mark_promoted(aid)
        existing_keys.add(aid or paper_entry["id"])

        if len(promoted) >= batch_size:
            break

    if promoted:
        existing.extend(promoted)
        save_yaml(papers_yaml, existing)
        logger.info(f"Promoted {len(promoted)} papers to display pool")
    else:
        logger.info("No papers promoted")

    return len(promoted)


# === Step 3: 种子论文 references 扩展 ===

def expand_seeds(config: dict, pool, papers_yaml: Path):
    """Step 3: 从展示池论文的 references 发现新候选论文。"""
    from scripts.seed_discoverer import discover_from_seeds

    seed_config = config.get("research", {}).get("seed_discovery", {})
    if not seed_config.get("enabled", True):
        return

    papers = load_papers_yaml(papers_yaml)
    if not papers:
        return

    max_refs = seed_config.get("max_references_per_paper", 50)
    max_seeds = seed_config.get("max_seeds_per_run", 10)

    logger.info("Seed discovery: expanding references...")
    added = discover_from_seeds(
        papers,
        pool,
        max_refs_per_paper=max_refs,
        max_seeds_per_run=max_seeds,
    )

    if added > 0:
        # 标记已扩展的论文
        from scripts.seed_discoverer import _extract_arxiv_id
        for p in papers:
            aid = _extract_arxiv_id(p)
            if aid and pool.is_seen(aid):
                pool.mark_seed_expanded(aid)
            p["seed_expanded"] = True
        save_papers_yaml(papers_yaml, papers)
        logger.info(f"Seed discovery: +{added} new candidates")


# === Step 4: 元数据富化 ===

def enrich_papers_step(config: dict, papers_yaml: Path):
    """Step 4: 对展示池中未富化的论文做元数据富化。"""
    from scripts.enrich_metadata import enrich_papers
    from scripts.sync import load_yaml, save_yaml

    enrichment_config = config.get("research", {}).get("enrichment", {})
    if not enrichment_config.get("enabled", True):
        return

    papers = load_yaml(papers_yaml) if papers_yaml.exists() else []
    if not papers:
        return

    logger.info("Enriching paper metadata...")
    papers = enrich_papers(papers, config)
    save_yaml(papers_yaml, papers)
    logger.info(f"Metadata enrichment done ({len(papers)} papers)")


# === Step 4.2: PaperRank-lite ===

def rank_papers_step(config: dict, papers_yaml: Path):
    """Add explainable read-first score components to papers.yaml."""
    ranking_config = config.get("research", {}).get("ranking", {})
    if ranking_config.get("enabled", True) is False:
        logger.info("PaperRank-lite disabled, skipping")
        return

    from scripts.paper_rank import enrich_paper_rank_scores

    updated = enrich_paper_rank_scores(papers_yaml, config)
    logger.info(f"PaperRank-lite enriched {updated} papers")


# === Step 4.3: Deep research queue ===

def deep_research_queue_step(config: dict, data_dir: Path):
    """Queue high read-first papers for deep research."""
    from scripts.deep_research_queue import build_deep_research_queue

    resource_dir = Path(os.environ.get("HUB_RESOURCE_DIR", str(data_dir.parent / "resource")))
    queued = build_deep_research_queue(data_dir, config, resource_dir=resource_dir)
    logger.info(f"Deep research queued {queued} papers")


# === Step 4.4: Literature surveys ===

def literature_surveys_step(config: dict, data_dir: Path):
    """Generate taxonomy-driven survey data."""
    from scripts.literature_survey import build_literature_surveys

    topics = build_literature_surveys(data_dir, config)
    logger.info(f"Literature surveys generated {topics} topics")


# === Step 4.5: Datasets ===

def sync_datasets_step(config: dict, data_dir: Path):
    """Sync datasets from HF datasets and benchmark/dataset papers."""
    sections = config.get("website", {}).get("sections", {})
    if not sections.get("datasets", True):
        return
    try:
        from scripts.dataset_sources import sync_datasets

        result = sync_datasets(data_dir, config)
        if result.get("total_added", 0):
            logger.info(
                "Datasets: +%s (HF candidates=%s, paper-derived=%s)",
                result["total_added"],
                result["hf_datasets"],
                result["derived_from_papers"],
            )
    except Exception as e:
        logger.warning(f"Dataset sync failed (non-fatal): {e}")


# === Step 5: Teaser 图 ===

def fetch_teasers_step(config: dict, data_dir: Path):
    """Step 5: 抓取论文 teaser 图。"""
    from fetch_teasers import main as fetch_teasers
    logger.info("Fetching paper teaser images...")
    fetch_teasers()


# === Step 6: 构建网站 ===

def build_step(config: dict, output_dir: Path, data_dir: Path):
    """Step 6: 构建网站。"""
    from build import generate_site, build_site, copy_runtime_assets

    generate_site(config, output_dir)
    copy_runtime_assets(output_dir, data_dir)
    build_site(output_dir)


# === 主入口 ===

def main():
    import argparse
    parser = argparse.ArgumentParser(description="论文更新（candidate 池架构）")
    parser.add_argument("--hub", default=None, help="本地 hub 名称（读取 .local/{hub}/awesome.yaml）")
    parser.add_argument("--config", default="awesome.yaml", help="配置文件路径")
    parser.add_argument("--output", default=None, help="网站输出目录（默认自动按站点隔离）")
    parser.add_argument("--data-dir", default=None, help="数据目录（默认自动按站点隔离）")
    parser.add_argument("--search-days", type=int, default=None,
                        help="覆盖 daily_search_days")
    parser.add_argument("--init", action="store_true",
                        help="初始化模式：全量搜索 + 批量晋升 + 种子扩展")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm build")
    parser.add_argument("--skip-teasers", action="store_true", help="跳过 teaser 图抓取")
    parser.add_argument("--skip-seed-expansion", action="store_true",
                        help="跳过种子 references 扩展")
    args = parser.parse_args()

    config_path = resolve_config_path(ROOT, SITE_DIR, args.config, args.hub)
    config = load_config(str(config_path))
    research = config.get("research", {})

    # 决定搜索范围
    if args.init:
        # 初始化：从 date_from 开始全量搜索
        date_from_str = research.get("date_from", "2020-01-01")
        search_days = (datetime.now() - datetime.strptime(date_from_str, "%Y-%m-%d")).days
        logger.info(f"=== INIT MODE: full search from {date_from_str} ({search_days} days) ===")
    else:
        # 每日更新
        search_days = args.search_days or research.get("daily_search_days", 3)
        logger.info(f"=== DAILY MODE: last {search_days} days ===")

    if args.hub:
        workspace = hub_workspace_dir(ROOT, args.hub)
        default_output = workspace / "website"
        default_data = workspace / "data"
        default_assets = workspace / "assets" / "papers"
        default_resource = workspace / "resource"
    else:
        default_output = default_output_dir(ROOT, SITE_DIR, config)
        default_data = default_data_dir(ROOT, SITE_DIR, config)
        default_assets = default_assets_dir(ROOT, SITE_DIR, config)
        default_resource = default_resource_dir(ROOT, SITE_DIR, config)
    output_dir = resolve_user_path(SITE_DIR, args.output, default_output)
    data_dir = resolve_user_path(SITE_DIR, args.data_dir, default_data)
    assets_dir = default_assets if not args.data_dir else data_dir.parent / "assets" / "papers"
    resource_dir = default_resource if not args.data_dir else data_dir.parent / "resource"
    data_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    resource_dir.mkdir(parents=True, exist_ok=True)
    for empty_file in ("papers.yaml", "resources.yaml", "datasets.yaml", "tools.yaml", "surveys.yaml", "research_runs.yaml"):
        f = data_dir / empty_file
        if not f.exists():
            empty = "topics: []\n" if empty_file == "surveys.yaml" else "runs: []\n" if empty_file == "research_runs.yaml" else "[]\n"
            f.write_text(empty, encoding="utf-8")
    papers_yaml = data_dir / "papers.yaml"

    os.environ["HUB_DATA_DIR"] = str(data_dir)
    os.environ["HUB_ASSETS_DIR"] = str(assets_dir)
    os.environ["HUB_RESOURCE_DIR"] = str(resource_dir)
    os.environ["HUB_CONFIG_PATH"] = str(config_path)

    # 初始化 candidate 池
    from scripts.candidate_pool import CandidatePool
    db_path = research.get("candidate_pool", {}).get("db_path", "data/candidates.db")
    pool = CandidatePool(data_dir.parent / db_path if not Path(db_path).is_absolute() else db_path)

    try:
        # Step 1: 数据源 → Candidate 池
        logger.info("--- Step 1: Collecting from data sources ---")
        collect_sources_to_pool(config, pool, search_days)
        stats = pool.get_stats()
        logger.info(f"Candidate pool: {stats['total']} total, {stats['unchecked']} unchecked")

        # Step 1.5: 初始化模式下，添加初始种子论文到展示池
        if args.init:
            initial_seeds = research.get("seed_discovery", {}).get("initial_seed_arxiv_ids", [])
            if initial_seeds:
                logger.info(f"Adding {len(initial_seeds)} initial seed papers...")
                existing = load_papers_yaml(papers_yaml)
                existing_keys = {p.get("arxiv_id", "") for p in existing}
                for aid in initial_seeds:
                    if aid not in existing_keys:
                        # 直接从 arXiv 获取元数据
                        from scripts.sync import fetch_arxiv_by_id
                        try:
                            paper = fetch_arxiv_by_id(aid)
                            if paper:
                                from scripts.sync import extract_year
                                entry = {
                                    "id": f"seed-{aid}",
                                    "title": paper["title"],
                                    "authors": paper.get("authors", []),
                                    "abstract": paper.get("abstract", ""),
                                    "year": extract_year(paper),
                                    "venue": "arXiv",
                                    "paper_type": ["method"],
                                    "tags": [],
                                    "links": paper.get("links", {}),
                                    "preview": "/assets/placeholder.svg",
                                    "sources": [{"repo": "seed"}],
                                    "arxiv_id": aid,
                                    "seed_expanded": False,
                                }
                                existing.append(entry)
                                pool.add(paper, source="initial_seed")
                                pool.mark_promoted(aid)
                                logger.info(f"  Added seed: {aid}")
                        except Exception as e:
                            logger.warning(f"  Failed to add seed {aid}: {e}")
                save_papers_yaml(papers_yaml, existing)

        # Step 2: Candidate → 展示池晋升
        logger.info("--- Step 2: Promoting candidates ---")
        promoted_count = promote_candidates(config, pool, papers_yaml)

        # Step 3: 种子论文 references 扩展
        if not args.skip_seed_expansion:
            logger.info("--- Step 3: Seed discovery ---")
            expand_seeds(config, pool, papers_yaml)

            # 种子扩展后可能有新 candidate，再晋升一轮
            if promoted_count == 0:
                logger.info("Second promotion round after seed expansion...")
                promote_candidates(config, pool, papers_yaml)

        # Step 4: 元数据富化
        logger.info("--- Step 4: Metadata enrichment ---")
        enrich_papers_step(config, papers_yaml)

        logger.info("--- Step 4.2: PaperRank-lite ---")
        rank_papers_step(config, papers_yaml)

        logger.info("--- Step 4.3: Deep research queue ---")
        deep_research_queue_step(config, data_dir)

        logger.info("--- Step 4.4: Literature surveys ---")
        literature_surveys_step(config, data_dir)

        logger.info("--- Step 4.5: Datasets ---")
        sync_datasets_step(config, data_dir)

        # Step 5: Teaser 图
        if not args.skip_teasers:
            logger.info("--- Step 5: Teaser images ---")
            try:
                fetch_teasers_step(config, data_dir)
            except Exception as e:
                logger.warning(f"Teaser fetch failed (non-fatal): {e}")

        # Step 6: 构建网站
        if not args.skip_build:
            logger.info("--- Step 6: Build website ---")
            build_step(config, output_dir, data_dir)

        # 最终统计
        stats = pool.get_stats()
        papers = load_papers_yaml(papers_yaml)
        logger.info(f"=== Done! ===")
        logger.info(f"Candidate pool: {stats['total']} total, {stats['unchecked']} unchecked, {stats['promoted']} promoted")
        logger.info(f"Display pool: {len(papers)} papers")
        try:
            from scripts.llm_cache import get_default_cache
            llm_stats = get_default_cache().stats()
            for task, item in llm_stats.get("calls_by_task", {}).items():
                logger.info(
                    "LLM %s: calls=%s cache_hits=%s tokens=%s",
                    task,
                    item.get("calls", 0),
                    item.get("cache_hits", 0),
                    item.get("total_tokens", 0),
                )
        except Exception as e:
            logger.debug("LLM stats unavailable: %s", e)

    finally:
        pool.close()


if __name__ == "__main__":
    main()
