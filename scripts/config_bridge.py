"""
config_bridge.py — Configuration Bridge

Translates awesome.yaml (user-facing config) into arxiv-daily-researcher's
config.json and .env formats. This is the ONLY place where config mapping
logic lives.

Usage:
    from scripts.config_bridge import awesome_to_researcher_config, generate_env_file
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESEARCHER_DIR = PROJECT_ROOT / "arxiv-daily-researcher"
RESEARCHER_CONFIG_PATH = RESEARCHER_DIR / "configs" / "config.json"
RESEARCHER_ENV_PATH = RESEARCHER_DIR / ".env"


def awesome_to_researcher_config(awesome_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert awesome.yaml config dict to researcher config.json dict.

    Args:
        awesome_config: Parsed awesome.yaml as a dict.

    Returns:
        Dict ready to be written as researcher config.json.
    """
    research = awesome_config.get("research", {})
    project = awesome_config.get("project", {})
    scoring = research.get("scoring", {})
    deep_analysis = research.get("deep_analysis", {})
    keyword_tracking = research.get("keyword_tracking", {})
    author_bonus = scoring.get("author_bonus", {})

    # --- search_settings ---
    search_days = research.get("daily_search_days", 3)

    # --- target_domains ---
    domains = research.get("arxiv_categories", ["cs.CV", "cs.LG"])

    # --- keywords ---
    primary_keywords = research.get("keywords", [])
    research_context = f"研究方向: {project.get('name', '')}"

    # --- scoring_settings ---
    max_score_per_keyword = scoring.get("max_score_per_keyword", 10)
    base_score = scoring.get("base_score", 1.5)
    weight_coefficient = scoring.get("weight_coefficient", 2.5)

    # --- pdf_parser ---
    pdf_parser_mode = deep_analysis.get("pdf_parser", "pymupdf")

    # --- keyword_tracker ---
    kt_enabled = keyword_tracking.get("enabled", True)
    kt_frequency = keyword_tracking.get("report_frequency", "weekly")

    config = {
        "search_settings": {
            "search_days": search_days,
            "max_results": 100,
            "max_results_per_source": {},
        },
        "data_sources": {
            "enabled": ["arxiv"],
            "journals": [],
            "reports_by_source": True,
            "arxiv": {"fetch_timeout_seconds": 180},
        },
        "run_lock": {
            "max_age_hours": 12,
        },
        "target_domains": {
            "domains": domains,
        },
        "keywords": {
            "primary_keywords": {
                "weight": 1.0,
                "keywords": primary_keywords,
            },
            "enable_reference_extraction": True,
            "reference_keywords_config": {
                "max_keywords": 10,
                "similarity_threshold": 0.75,
                "weight_distribution": {
                    "high_importance": {"weight": 1.0, "count": 3},
                    "medium_importance": {"weight": 0.2, "count": 5},
                    "low_importance": {"weight": 0.1, "count": 2},
                },
            },
            "research_context": research_context,
        },
        "scoring_settings": {
            "keyword_relevance_score": {
                "max_score_per_keyword": max_score_per_keyword,
            },
            "author_bonus": {
                "enabled": author_bonus.get("enabled", False),
                "expert_authors": author_bonus.get("expert_authors", []),
                "bonus_points": author_bonus.get("bonus_points", 5.0),
            },
            "passing_score_formula": {
                "base_score": base_score,
                "weight_coefficient": weight_coefficient,
            },
            "include_all_in_report": True,
        },
        "paths": {
            "data_dir": "data",
            "reference_pdfs": "data/reference_pdfs",
            "reports": "data/reports",
            "downloaded_pdfs": "data/downloaded_pdfs",
            "history_dir": "data/history",
        },
        "keyword_tracker": {
            "enabled": kt_enabled,
            "database": {"path": "data/keywords/keywords.db"},
            "normalization": {"enabled": True, "batch_size": 25},
            "trend_view": {"default_days": 30},
            "charts": {
                "bar_chart": {"top_n": 15},
                "trend_chart": {"top_n": 5},
            },
            "report": {
                "enabled": kt_enabled,
                "frequency": kt_frequency,
            },
        },
        "notifications": {
            "enabled": False,
            "on_success": False,
            "on_failure": False,
            "attach_reports": False,
            "top_n": 5,
            "channels": {
                "email": {"enabled": False},
                "wechat_work": {"enabled": False},
                "dingtalk": {"enabled": False},
                "telegram": {"enabled": False},
                "slack": {"enabled": False},
                "generic_webhook": {"enabled": False},
            },
        },
        "retry": {
            "max_attempts": 5,
            "min_wait": 2,
            "max_wait": 60,
        },
        "logging": {
            "rotation_type": "time",
            "keep_days": 30,
        },
        "concurrency": {
            "enabled": True,
            "workers": 2,
        },
        "pdf_parser": {
            "mode": pdf_parser_mode,
            "mineru_model_version": "vlm",
            "poll_interval": 3,
            "poll_timeout": 300,
        },
        "report_settings": {
            "enable_html_report": True,
            "enable_markdown_report": True,
        },
        "auto_update": {"enabled": True},
        "token_tracking": {"enabled": True},
        "proxy": {
            "enabled": False,
            "url": "",
            "no_proxy": "localhost,127.0.0.1",
            "scope": {
                "arxiv": True,
                "openalex": False,
                "semantic_scholar": False,
                "llm_api": False,
                "notifications": False,
                "update_check": False,
            },
        },
        "webdav": {
            "enabled": False,
            "remote_path": "/arxiv-daily-researcher/",
            "sync_mode": "after_report",
            "cron_schedule": "0 23 * * *",
            "sync_configs": False,
            "sync_history": False,
            "sync_keywords": False,
            "sync_reports": False,
        },
        "trend_research": {
            "default_date_range_days": 365,
            "max_results": 500,
            "sort_order": "ascending",
            "report_position": "end",
            "generate_tldr": True,
            "tldr_batch_size": 10,
            "output_formats": ["markdown", "html"],
            "enabled_skills": ["comprehensive_analysis"],
        },
    }

    return config


def generate_env_file(
    env_path: Optional[Path] = None,
    ark_api_key: Optional[str] = None,
    ark_base_url: Optional[str] = None,
    ark_model_name: Optional[str] = None,
    smart_model_name: Optional[str] = None,
) -> str:
    """
    Generate .env file content for arxiv-daily-researcher.

    Falls back to environment variables if values not provided.

    Args:
        env_path: Path to write .env file. If None, just returns content.
        ark_api_key: API key for LLM service.
        ark_base_url: Base URL for LLM API.
        ark_model_name: Model name for CHEAP_LLM (scoring).
        smart_model_name: Model name for SMART_LLM (deep analysis).

    Returns:
        The generated .env file content as a string.
    """
    api_key = ark_api_key or os.environ.get("ARK_API_KEY", "")
    base_url = ark_base_url or os.environ.get(
        "ARK_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
    )
    cheap_model = ark_model_name or os.environ.get("ARK_MODEL_NAME", "deepseek-v4-flash-260425")
    smart_model = smart_model_name or os.environ.get(
        "SMART_MODEL_NAME", cheap_model
    )

    lines = [
        f'CHEAP_LLM__API_KEY="{api_key}"',
        f'CHEAP_LLM__BASE_URL="{base_url}"',
        f'CHEAP_LLM__MODEL_NAME="{cheap_model}"',
        f'SMART_LLM__API_KEY="{api_key}"',
        f'SMART_LLM__BASE_URL="{base_url}"',
        f'SMART_LLM__MODEL_NAME="{smart_model}"',
        "",
        "# ================================================",
        "# Disable notifications for CI/automated runs",
        "# ================================================",
        "NOTIFICATIONS_ENABLED=false",
        "",
        "# ================================================",
        "# Disable WebDAV sync for CI/automated runs",
        "# ================================================",
        "WEBDAV_ENABLED=false",
    ]

    content = "\n".join(lines) + "\n"

    if env_path:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(content, encoding="utf-8")

    return content


def sync_config(awesome_config: Dict[str, Any]) -> None:
    """
    One-shot sync: convert awesome.yaml and write both config.json and .env.

    Args:
        awesome_config: Parsed awesome.yaml as a dict.
    """
    # Write config.json
    researcher_config = awesome_to_researcher_config(awesome_config)
    RESEARCHER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Use json.dumps with indent (json5 is only needed for reading comments)
    RESEARCHER_CONFIG_PATH.write_text(
        json.dumps(researcher_config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Write .env
    generate_env_file(env_path=RESEARCHER_ENV_PATH)
