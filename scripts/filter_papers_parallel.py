#!/usr/bin/env python3
"""Parallel relevance filtering for papers.yaml."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    for env_path in (Path.cwd() / ".env", ROOT / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        return


_load_env()

from scripts import relevance_filter as rf  # noqa: E402

logger = logging.getLogger("filter_papers_parallel")


def filter_options(config: Dict[str, Any]) -> Dict[str, Any]:
    research = config.get("research", {}) if isinstance(config, dict) else {}
    project = config.get("project", {}) if isinstance(config, dict) else {}
    domain_keywords = research.get("keywords", []) + research.get("domain_boost_keywords", [])
    return {
        "negative_keywords": research.get("negative_keywords", []),
        "min_score": research.get("scoring", {}).get("filter_min_score", 5.0),
        "research_context": project.get("description") or " ".join(domain_keywords[:5]),
        "relevance_criteria": research.get("relevance_criteria", {}),
        "domain_keywords": domain_keywords,
    }


def _judge(index: int, paper: Dict[str, Any], options: Dict[str, Any]) -> Tuple[int, bool, str]:
    title = str(paper.get("title") or f"paper-{index}")
    try:
        keep = rf.is_cad_relevant(paper, **options)
        return index, keep, ""
    except Exception as exc:
        return index, True, f"{title[:80]}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallel relevance filtering")
    parser.add_argument("--data-dir", default=os.environ.get("HUB_DATA_DIR", ".local/data"))
    parser.add_argument("--config", default=os.environ.get("HUB_CONFIG_PATH", "awesome.yaml"))
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    data_dir = Path(args.data_dir)
    papers_path = data_dir / "papers.yaml"
    config_path = Path(args.config)
    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8")) or []
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(papers, list):
        raise SystemExit("Invalid papers.yaml")
    options = filter_options(config)

    keep_flags = [True] * len(papers)
    failures: List[str] = []
    logger.info("Filtering %s papers with %s workers", len(papers), args.workers)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(_judge, index, paper, options): index
            for index, paper in enumerate(papers)
            if isinstance(paper, dict)
        }
        completed = 0
        for future in as_completed(futures):
            index, keep, error = future.result()
            keep_flags[index] = keep
            if error:
                failures.append(error)
            completed += 1
            if completed % 25 == 0:
                logger.info("Checked %s/%s papers", completed, len(futures))

    relevant = [paper for paper, keep in zip(papers, keep_flags) if keep]
    removed = [paper for paper, keep in zip(papers, keep_flags) if not keep]
    papers_path.write_text(
        yaml.dump(relevant, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    (data_dir / "removed_papers.yaml").write_text(
        yaml.dump(removed, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    logger.info("Kept %s papers; removed %s papers; failures kept %s papers", len(relevant), len(removed), len(failures))
    for title in [str(p.get("title", ""))[:80] for p in removed[:20] if isinstance(p, dict)]:
        logger.info("Removed: %s", title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
