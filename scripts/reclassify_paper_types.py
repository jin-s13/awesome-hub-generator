#!/usr/bin/env python3
"""Re-run taxonomy classification for existing papers.

This is intentionally narrower than a full build: it updates paper_type, tags,
and configured taxonomy dimensions without re-fetching papers, teasers, or
Chinese interpretation fields.
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from site_paths import default_data_dir, hub_workspace_dir, resolve_config_path
from sync import classify_paper


Classifier = Callable[[str, str, List[str], str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


def _research_context(research: Dict[str, Any], project_description: str = "") -> str:
    keywords = research.get("keywords", []) + research.get("domain_boost_keywords", [])
    return project_description or " ".join(keywords[:5])


def reclassify_papers(
    papers: List[Dict[str, Any]],
    research: Dict[str, Any],
    *,
    project_description: str = "",
    classify_func: Classifier = classify_paper,
    limit: int | None = None,
    workers: int = 1,
) -> Tuple[int, int]:
    """Update papers in-place with taxonomy classification.

    Returns:
        (updated_count, rejected_count)
    """
    taxonomy = research.get("taxonomy", {})
    relevance_criteria = research.get("relevance_criteria", {})
    context = _research_context(research, project_description)
    dimensions = {
        dim.get("name")
        for dim in taxonomy.get("dimensions", [])
        if isinstance(dim, dict) and dim.get("name")
    }

    updated = 0
    rejected = 0
    target_papers = papers[:limit] if limit else papers

    def classify_one(index: int, paper: Dict[str, Any]) -> Tuple[int, Dict[str, Any] | None]:
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        if not title or not abstract:
            return index, None

        print(f"[reclassify] [{index}/{len(target_papers)}] {title[:72]}...")
        result = classify_func(
            title,
            abstract,
            paper.get("categories", []),
            context,
            taxonomy,
            relevance_criteria,
        )
        return index, result

    def apply_result(paper: Dict[str, Any], result: Dict[str, Any] | None) -> None:
        nonlocal updated, rejected
        if not result:
            return
        if context and relevance_criteria and result.get("relevant") is False:
            paper["relevant"] = False
            rejected += 1
            return

        paper_type = result.get("paper_type") or ["method"]
        if isinstance(paper_type, str):
            paper_type = [paper_type]
        paper["paper_type"] = [str(item) for item in paper_type if item] or ["method"]
        paper.pop("category", None)

        tags = result.get("tags")
        if isinstance(tags, list):
            paper["tags"] = [str(tag) for tag in tags if tag][:8]

        for key in dimensions:
            value = result.get(key)
            if isinstance(value, list):
                paper[key] = value

        updated += 1

    if workers <= 1:
        for index, paper in enumerate(target_papers, start=1):
            _, result = classify_one(index, paper)
            apply_result(paper, result)
        return updated, rejected

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(classify_one, index, paper): (index, paper)
            for index, paper in enumerate(target_papers, start=1)
        }
        for future in as_completed(futures):
            _, paper = futures[future]
            try:
                _, result = future.result()
            except Exception as exc:
                print(f"[reclassify] failed: {paper.get('title', '')[:72]} ({exc})")
                continue
            apply_result(paper, result)

    return updated, rejected


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-run LLM paper_type classification for existing papers")
    parser.add_argument("--config", default="awesome.yaml", help="Path to awesome.yaml")
    parser.add_argument("--hub", default="", help="Local hub name under .local/")
    parser.add_argument("--data-dir", default="", help="Override data directory")
    parser.add_argument("--limit", type=int, default=0, help="Limit papers for smoke tests")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent LLM classification workers")
    args = parser.parse_args()

    cwd = Path.cwd()
    workspace = hub_workspace_dir(ROOT, args.hub) if args.hub else cwd
    config_path = resolve_config_path(ROOT, cwd, args.config, args.hub)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    data_dir = Path(args.data_dir) if args.data_dir else (
        workspace / "data" if args.hub else default_data_dir(ROOT, cwd, config)
    )
    if not data_dir.is_absolute():
        data_dir = workspace / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HUB_DATA_DIR"] = str(data_dir)
    os.environ["HUB_LLM_CACHE_DB"] = str(data_dir / "llm_cache.db")

    papers_path = data_dir / "papers.yaml"
    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8")) if papers_path.exists() else []
    if not isinstance(papers, list):
        raise SystemExit(f"Invalid papers file: {papers_path}")

    updated, rejected = reclassify_papers(
        papers,
        config.get("research", {}),
        project_description=config.get("project", {}).get("description", ""),
        limit=args.limit or None,
        workers=max(1, args.workers),
    )
    papers_path.write_text(
        yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"[reclassify] updated={updated} rejected={rejected} file={papers_path}")


if __name__ == "__main__":
    main()
