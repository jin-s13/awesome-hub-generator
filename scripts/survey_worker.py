#!/usr/bin/env python3
"""Run queued LLM literature-survey synthesis jobs."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from site_paths import hub_workspace_dir, resolve_config_path, resolve_user_path
from scripts.build import load_config
from scripts.literature_survey import process_survey_jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Run queued LLM survey synthesis jobs")
    parser.add_argument("--hub", default=None, help="Local hub name under .local/{hub}")
    parser.add_argument("--config", default="awesome.yaml", help="Config path")
    parser.add_argument("--data-dir", default=None, help="Data directory")
    parser.add_argument("--workers", type=int, default=0, help="Concurrent survey LLM workers")
    parser.add_argument("--limit", type=int, default=0, help="Maximum jobs to process")
    parser.add_argument("--no-retry-failed", action="store_true", help="Do not retry failed jobs")
    args = parser.parse_args()

    site_dir = Path.cwd()
    config_path = resolve_config_path(ROOT, site_dir, args.config, args.hub)
    config = load_config(str(config_path))
    if args.hub:
        default_data = hub_workspace_dir(ROOT, args.hub) / "data"
    else:
        default_data = Path(os.environ.get("HUB_DATA_DIR", str(ROOT / ".local/data")))
    data_dir = resolve_user_path(site_dir, args.data_dir, default_data)
    os.environ["HUB_DATA_DIR"] = str(data_dir)
    os.environ["HUB_CONFIG_PATH"] = str(config_path)

    research = config.get("research", {}) if isinstance(config, dict) else {}
    llm_config = research.get("llm", {}) if isinstance(research.get("llm", {}), dict) else {}
    workers = args.workers or int(llm_config.get("survey_workers", llm_config.get("workers", 2)))
    processed = process_survey_jobs(
        data_dir,
        config,
        workers=max(1, workers),
        limit=max(0, args.limit),
        retry_failed=not args.no_retry_failed,
    )
    print(f"[survey-worker] processed {processed} jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
