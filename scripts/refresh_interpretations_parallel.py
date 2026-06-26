#!/usr/bin/env python3
"""Parallel refresh for paper interpretations.

This runner reuses generate_interpretations.py prompt functions, but executes
per-paper LLM work concurrently and lets the main thread merge results into
papers.yaml at checkpoints. It avoids launching multiple writer processes.
"""
from __future__ import annotations

import argparse
import copy
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import generate_interpretations as gi

logger = logging.getLogger("refresh_interpretations_parallel")


def _score_total(paper: Dict[str, Any]) -> float:
    score = paper.get("score") if isinstance(paper.get("score"), dict) else {}
    try:
        return float(score.get("total") or 0)
    except (TypeError, ValueError):
        return 0.0


def english_pending(paper: Dict[str, Any]) -> bool:
    """Return true if English scoring/TLDR/analysis should run."""
    if not paper.get("title") or not paper.get("abstract"):
        return False
    if not paper.get("tldr") or not paper.get("reasoning"):
        return True
    return _score_total(paper) >= 30 and not paper.get("analysis")


def requested_chinese_fields(paper: Dict[str, Any]) -> List[str]:
    """Return missing Chinese fields that can be generated from current paper data."""
    if not paper.get("title") or not paper.get("abstract"):
        return []
    fields: List[str] = []
    if not paper.get("title_cn"):
        fields.append("title_cn")
    if not paper.get("abstract_cn"):
        fields.append("abstract_cn")
    if paper.get("tldr") and not paper.get("tldr_cn"):
        fields.append("tldr_cn")
    if paper.get("analysis") and not paper.get("analysis_cn"):
        fields.append("analysis_cn")
    return fields


def apply_updates(paper: Dict[str, Any], updates: Dict[str, Any]) -> None:
    """Merge worker updates into the canonical paper dict."""
    for key, value in updates.items():
        if key == "score" and isinstance(value, dict):
            score = paper.get("score")
            if not isinstance(score, dict):
                score = {}
                paper["score"] = score
            score.update(value)
        elif value is not None:
            paper[key] = value


def _process_paper(
    index: int,
    paper: Dict[str, Any],
    keywords: List[str],
    *,
    english: bool,
    chinese: bool,
    deep_threshold: float,
    sleep_seconds: float,
) -> Tuple[int, Dict[str, Any], List[str]]:
    """Process a single paper and return updates plus human-readable events."""
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    working = copy.deepcopy(paper)
    updates: Dict[str, Any] = {}
    events: List[str] = []

    if english and english_pending(working):
        if not working.get("tldr") or not working.get("reasoning"):
            result = gi.generate_tldr_and_reasoning(title, abstract, keywords)
            if result.get("tldr"):
                updates["tldr"] = result["tldr"]
                working["tldr"] = result["tldr"]
            if result.get("reasoning"):
                updates["reasoning"] = result["reasoning"]
                working["reasoning"] = result["reasoning"]
            if "has_real_world" in result:
                updates["has_real_world"] = result["has_real_world"]
                working["has_real_world"] = result["has_real_world"]
            if result.get("keyword_scores"):
                scores = result["keyword_scores"]
                total = round(sum(scores.values()), 1) if scores else 0
                updates["score"] = {"keyword_scores": scores, "total": total}
                score = working.get("score") if isinstance(working.get("score"), dict) else {}
                score.update(updates["score"])
                working["score"] = score
            events.append("english")
            if sleep_seconds:
                time.sleep(sleep_seconds)

        if _score_total(working) >= deep_threshold and not working.get("analysis"):
            analysis = gi.generate_deep_analysis(title, abstract)
            if analysis:
                updates["analysis"] = analysis
                working["analysis"] = analysis
                events.append("analysis")
            if sleep_seconds:
                time.sleep(sleep_seconds)

    if chinese:
        requested = requested_chinese_fields(working)
        if requested:
            combined = gi.generate_chinese_fields(
                title=title,
                abstract=abstract,
                tldr_en=working.get("tldr", "") if "tldr_cn" in requested else "",
                analysis=working.get("analysis") if "analysis_cn" in requested else None,
                requested_fields=requested,
            )
            for field in requested:
                if combined.get(field):
                    updates[field] = combined[field]
                    working[field] = combined[field]
            events.append("chinese")
            if sleep_seconds:
                time.sleep(sleep_seconds)

    return index, updates, events


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _save_papers(path: Path, papers: List[Dict[str, Any]]) -> None:
    path.write_text(
        yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallel refresh paper interpretations")
    parser.add_argument("--data-dir", default=os.environ.get("HUB_DATA_DIR", ".local/data"))
    parser.add_argument("--config", default=os.environ.get("HUB_CONFIG_PATH", "awesome.yaml"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--checkpoint-interval", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--english-only", action="store_true")
    parser.add_argument("--chinese-only", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    data_dir = Path(args.data_dir)
    papers_path = data_dir / "papers.yaml"
    if not papers_path.exists():
        raise SystemExit(f"papers.yaml not found: {papers_path}")
    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8")) or []
    if not isinstance(papers, list):
        raise SystemExit("Invalid papers.yaml format")

    config = _load_config(Path(args.config))
    keywords = config.get("research", {}).get("keywords", []) if isinstance(config, dict) else []
    deep_threshold = float(config.get("research", {}).get("deep_analysis", {}).get("min_score", 30))
    english = not args.chinese_only
    chinese = not args.english_only

    pending = [
        (idx, paper)
        for idx, paper in enumerate(papers)
        if isinstance(paper, dict)
        and (
            (english and english_pending(paper))
            or (chinese and requested_chinese_fields(paper))
        )
    ]
    if args.limit > 0:
        pending = pending[: args.limit]
    logger.info("Pending papers: %s (workers=%s)", len(pending), args.workers)
    if not pending:
        return 0

    completed = 0
    changed_since_save = 0
    failures = 0
    executor = ThreadPoolExecutor(max_workers=max(1, args.workers))
    futures = {
        executor.submit(
            _process_paper,
            idx,
            copy.deepcopy(paper),
            keywords,
            english=english,
            chinese=chinese,
            deep_threshold=deep_threshold,
            sleep_seconds=max(0.0, args.sleep),
        ): idx
        for idx, paper in pending
    }
    try:
        for future in as_completed(futures):
            idx = futures[future]
            title = papers[idx].get("title", f"paper-{idx}") if isinstance(papers[idx], dict) else f"paper-{idx}"
            try:
                _, updates, events = future.result()
            except Exception as exc:  # keep long refreshes moving
                failures += 1
                logger.warning("[%s/%s] failed: %s (%s)", completed + 1, len(pending), title[:60], exc)
                continue
            if updates:
                apply_updates(papers[idx], updates)
                changed_since_save += 1
            completed += 1
            logger.info(
                "[%s/%s] %s %s",
                completed,
                len(pending),
                ",".join(events) or "noop",
                title[:70],
            )
            if changed_since_save >= max(1, args.checkpoint_interval):
                _save_papers(papers_path, papers)
                logger.info("[checkpoint] saved %s completed papers", completed)
                changed_since_save = 0
    except KeyboardInterrupt:
        logger.warning("Interrupted; cancelling pending futures and saving completed results")
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        _save_papers(papers_path, papers)
        raise
    else:
        executor.shutdown(wait=True)

    if changed_since_save:
        _save_papers(papers_path, papers)
    gi.grade_papers(papers, config)
    _save_papers(papers_path, papers)
    gi.backfill_interpretation_links(papers_path)
    logger.info("Done: completed=%s failures=%s", completed, failures)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
