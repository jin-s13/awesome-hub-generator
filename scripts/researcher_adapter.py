"""
researcher_adapter.py — arxiv-daily-researcher Adapter Layer

Wraps the arxiv-daily-researcher's DailyResearchPipeline for direct Python
import (not subprocess), and converts its structured output into the
papers.yaml format used by awesome-hub-generator.

Usage:
    from scripts.researcher_adapter import ResearcherAdapter

    adapter = ResearcherAdapter(awesome_config)
    result = adapter.run_daily_research()
    papers = adapter.convert_to_papers_yaml(result)
"""

import json
import logging
import os
import sys
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.config_bridge import (
    awesome_to_researcher_config,
    generate_env_file,
    RESEARCHER_DIR,
    RESEARCHER_CONFIG_PATH,
    RESEARCHER_ENV_PATH,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("HUB_DATA_DIR", str(PROJECT_ROOT / ".local/data")))


def _slugify(text: str) -> str:
    """Create a URL-safe slug from text."""
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].rstrip("-")


def _infer_venue(categories: List[str]) -> str:
    """Infer venue from arXiv categories."""
    if not categories:
        return "arXiv"
    return "arXiv"


def _import_researcher_module(module_path: str) -> Any:
    """
    Import a module from arxiv-daily-researcher by path.

    Adds the researcher's src directory to sys.path if needed.

    Args:
        module_path: Dotted module path relative to researcher src,
                     e.g. "modes.daily_research"

    Returns:
        Imported module.
    """
    researcher_src = RESEARCHER_DIR / "src"
    if str(researcher_src) not in sys.path:
        sys.path.insert(0, str(researcher_src))
    return importlib.import_module(module_path)


class ResearcherAdapter:
    """
    Adapter for arxiv-daily-researcher.

    Provides a clean interface for:
    1. Syncing configuration (awesome.yaml -> researcher config.json + .env)
    2. Running the DailyResearchPipeline via Python import
    3. Converting structured results to papers.yaml format
    4. Deduplicating against existing papers
    """

    def __init__(self, awesome_config: Dict[str, Any]):
        self.awesome_config = awesome_config
        self._pipeline = None
        self._settings = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def sync_config(self) -> None:
        """
        Sync awesome.yaml configuration to researcher's config.json and .env.

        Writes:
            - arxiv-daily-researcher/configs/config.json
            - arxiv-daily-researcher/.env
        """
        # Write config.json
        researcher_config = awesome_to_researcher_config(self.awesome_config)
        RESEARCHER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESEARCHER_CONFIG_PATH.write_text(
            json.dumps(researcher_config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Write .env
        generate_env_file(env_path=RESEARCHER_ENV_PATH)

        logger.info("Configuration synced to arxiv-daily-researcher")

    # ------------------------------------------------------------------
    # Pipeline Execution
    # ------------------------------------------------------------------

    def run_daily_research(self) -> Any:
        """
        Run the DailyResearchPipeline via direct Python import.

        Returns:
            The pipeline's RunResult (dataclass with structured data).

        Raises:
            ImportError: If arxiv-daily-researcher is not available.
            RuntimeError: If the pipeline fails.
        """
        self.sync_config()

        try:
            # Import researcher modules
            config_mod = _import_researcher_module("config")
            pipeline_mod = _import_researcher_module("modes.daily_research")

            # Reload settings from the config file we just wrote
            config_mod.settings.load_from_search_config()

            # Run pipeline
            pipeline = pipeline_mod.DailyResearchPipeline()
            result = pipeline.run()

            if not result.success:
                raise RuntimeError(
                    f"DailyResearchPipeline failed: {result.error_message}"
                )

            return result

        except ImportError as e:
            logger.error(
                f"Failed to import arxiv-daily-researcher: {e}. "
                "Make sure the submodule is initialized."
            )
            raise

    # ------------------------------------------------------------------
    # Result Conversion
    # ------------------------------------------------------------------

    def convert_to_papers_yaml(self, run_result: Any) -> List[Dict[str, Any]]:
        """
        Convert a DailyResearchPipeline RunResult to papers.yaml entries.

        Args:
            run_result: The RunResult dataclass from the pipeline.

        Returns:
            List of paper dicts in papers.yaml format, including
            score/tldr/reasoning/analysis fields.
        """
        papers: List[Dict[str, Any]] = []

        # Build analysis lookup: paper_id -> analysis dict
        analysis_lookup: Dict[str, Dict] = {}
        if hasattr(run_result, "analyses_by_source") and run_result.analyses_by_source:
            for source, analyses in run_result.analyses_by_source.items():
                for entry in analyses:
                    paper_id = entry.get("paper_id", "")
                    analysis_lookup[paper_id] = entry.get("analysis", {})

        # Process scored papers
        if not hasattr(run_result, "scored_papers_by_source"):
            return papers

        for source, scored_list in run_result.scored_papers_by_source.items():
            for scored in scored_list:
                paper_meta = scored.get("paper_metadata")
                score_resp = scored.get("score_response")

                if not paper_meta or not score_resp:
                    continue

                paper_id = paper_meta.paper_id if hasattr(paper_meta, "paper_id") else ""
                title = paper_meta.title if hasattr(paper_meta, "title") else ""
                authors = paper_meta.authors if hasattr(paper_meta, "authors") else []
                abstract = paper_meta.abstract if hasattr(paper_meta, "abstract") else ""
                published = paper_meta.published_date if hasattr(paper_meta, "published_date") else ""
                url = paper_meta.url if hasattr(paper_meta, "url") else ""
                pdf_url = paper_meta.pdf_url if hasattr(paper_meta, "pdf_url") else ""
                categories = paper_meta.categories if hasattr(paper_meta, "categories") else []

                # Determine year
                year = ""
                if isinstance(published, datetime):
                    year = str(published.year)
                elif isinstance(published, str) and len(published) >= 4:
                    year = published[:4]

                # Build entry
                entry: Dict[str, Any] = {
                    "id": _slugify(f"{title}-{year}"),
                    "title": title,
                    "year": year,
                    "venue": _infer_venue(categories),
                    "category": "Others",
                    "tags": score_resp.extracted_keywords[:8] if hasattr(score_resp, "extracted_keywords") else [],
                    "representations": [],
                    "input_modalities": [],
                    "output_modalities": [],
                    "links": {
                        "paper": url,
                        "pdf": pdf_url,
                    },
                    "preview": "/assets/placeholder.svg",
                    "sources": [{"repo": source, "category": "arxiv"}],
                    # Enhanced fields
                    "score": {
                        "total": float(score_resp.total_score) if hasattr(score_resp, "total_score") else 0.0,
                        "keyword_scores": score_resp.keyword_scores if hasattr(score_resp, "keyword_scores") else {},
                        "author_bonus": float(score_resp.author_bonus) if hasattr(score_resp, "author_bonus") else 0.0,
                        "passing_score": float(score_resp.passing_score) if hasattr(score_resp, "passing_score") else 0.0,
                        "is_qualified": bool(score_resp.is_qualified) if hasattr(score_resp, "is_qualified") else False,
                    },
                    "tldr": score_resp.tldr if hasattr(score_resp, "tldr") else "",
                    "reasoning": score_resp.reasoning if hasattr(score_resp, "reasoning") else "",
                    # Bilingual (Chinese) fields — mapped from scored dict if present
                    "abstract_cn": scored.get("abstract_cn", ""),
                }

                # Map title_cn if available in scored dict
                if scored.get("title_cn"):
                    entry["title_cn"] = scored["title_cn"]

                # Map tldr_cn if available in scored dict
                if scored.get("tldr_cn"):
                    entry["tldr_cn"] = scored["tldr_cn"]

                # Attach deep analysis if available
                if paper_id in analysis_lookup:
                    entry["analysis"] = analysis_lookup[paper_id]

                papers.append(entry)

        return papers

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def deduplicate(
        existing: List[Dict[str, Any]], new_items: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Merge new papers into existing list with deduplication.

        Deduplicates by: title (lowercase), id, and paper URL.

        Args:
            existing: Current list of paper dicts.
            new_items: New papers to add.

        Returns:
            Tuple of (merged list, number of new items added).
        """
        existing_titles = {e.get("title", "").lower().strip() for e in existing}
        existing_ids = {e.get("id", "") for e in existing}
        existing_urls = {
            e.get("links", {}).get("paper", "") for e in existing
        }

        added = 0
        merged = list(existing)

        for item in new_items:
            title = item.get("title", "").lower().strip()
            pid = item.get("id", "")
            purl = item.get("links", {}).get("paper", "")

            if title in existing_titles or pid in existing_ids or purl in existing_urls:
                continue

            merged.append(item)
            existing_titles.add(title)
            existing_ids.add(pid)
            existing_urls.add(purl)
            added += 1

        # Sort: newest year first, then by score descending, then by title
        merged.sort(
            key=lambda x: (
                -int(x.get("year", 0) or 0),
                -x.get("score", {}).get("total", 0),
                x.get("title", ""),
            )
        )

        return merged, added

    # ------------------------------------------------------------------
    # High-level Convenience
    # ------------------------------------------------------------------

    def run_and_convert(self) -> List[Dict[str, Any]]:
        """
        Run the full pipeline and convert results in one call.

        Returns:
            List of paper dicts in papers.yaml format.
        """
        result = self.run_daily_research()
        return self.convert_to_papers_yaml(result)

    def run_and_merge(
        self, existing_papers: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Run pipeline, convert, and merge with existing papers.

        Args:
            existing_papers: Current list of paper dicts.

        Returns:
            Tuple of (merged list, number of new papers added).
        """
        new_papers = self.run_and_convert()
        return self.deduplicate(existing_papers, new_papers)
