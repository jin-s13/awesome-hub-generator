"""Shared test fixtures and helpers."""

from pathlib import Path
from typing import Dict, Any

import pytest


SAMPLE_AWESOME_YAML = """
project:
  name: "Awesome CAD Hub"
  description: "A curated hub for CAD papers."
  github_url: "https://github.com/user/awesome-cad-hub"
  site_url: "https://user.github.io/awesome-cad-hub"

research:
  keywords:
    - "CAD"
    - "B-Rep"
    - "parametric CAD"
    - "CAD generation"
    - "text-to-CAD"

  negative_keywords:
    - "medical imaging"
    - "weather forecast"
    - "protein folding"

  domain_boost_keywords:
    - "neural CAD"
    - "generative CAD"
    - "point cloud"

  arxiv_categories:
    - "cs.CV"
    - "cs.GR"
    - "cs.LG"

  date_from: "2020-01-01"
  daily_search_days: 3

  scoring:
    base_score: 1.5
    weight_coefficient: 2.5
    max_score_per_keyword: 10
    author_bonus:
      enabled: false
      bonus_points: 5.0
      expert_authors: []

  deep_analysis:
    enabled: true
    min_score: 30
    pdf_parser: "pymupdf"
    max_papers_per_run: 10

  keyword_tracking:
    enabled: true
    report_frequency: "weekly"

website:
  sections:
    papers: true
    datasets: true
    projects: true
  nav:
    - label: "Home"
      href: "/"
    - label: "Papers"
      href: "/papers"
  footer: "Built with awesome-hub-generator."
"""


@pytest.fixture
def sample_awesome_config() -> Dict[str, Any]:
    """Return parsed sample awesome.yaml config."""
    import yaml
    return yaml.safe_load(SAMPLE_AWESOME_YAML)


@pytest.fixture
def sample_researcher_config() -> Dict[str, Any]:
    """Return a sample researcher config.json structure."""
    return {
        "search_settings": {
            "search_days": 3,
            "max_results": 100,
            "max_results_per_source": {}
        },
        "data_sources": {
            "enabled": ["arxiv"],
            "journals": [],
            "reports_by_source": True,
            "arxiv": {"fetch_timeout_seconds": 180}
        },
        "target_domains": {
            "domains": ["cs.CV", "cs.GR", "cs.LG"]
        },
        "keywords": {
            "primary_keywords": {
                "weight": 1.0,
                "keywords": ["CAD", "B-Rep", "parametric CAD", "CAD generation", "text-to-CAD"]
            },
            "enable_reference_extraction": True,
            "reference_keywords_config": {
                "max_keywords": 10,
                "similarity_threshold": 0.75,
                "weight_distribution": {
                    "high_importance": {"weight": 1.0, "count": 3},
                    "medium_importance": {"weight": 0.2, "count": 5},
                    "low_importance": {"weight": 0.1, "count": 2}
                }
            },
            "research_context": "研究方向: Awesome CAD Hub"
        },
        "scoring_settings": {
            "keyword_relevance_score": {"max_score_per_keyword": 10},
            "author_bonus": {
                "enabled": False,
                "expert_authors": [],
                "bonus_points": 5.0
            },
            "passing_score_formula": {
                "base_score": 1.5,
                "weight_coefficient": 2.5
            },
            "include_all_in_report": True
        },
        "paths": {
            "data_dir": "data",
            "reference_pdfs": "data/reference_pdfs",
            "reports": "data/reports",
            "downloaded_pdfs": "data/downloaded_pdfs",
            "history_dir": "data/history"
        },
        "keyword_tracker": {
            "enabled": True,
            "database": {"path": "data/keywords/keywords.db"},
            "normalization": {"enabled": True, "batch_size": 25},
            "trend_view": {"default_days": 30},
            "charts": {
                "bar_chart": {"top_n": 15},
                "trend_chart": {"top_n": 5}
            },
            "report": {"enabled": True, "frequency": "weekly"}
        },
        "notifications": {
            "enabled": True,
            "on_success": True,
            "on_failure": True,
            "attach_reports": True,
            "top_n": 5,
            "channels": {
                "email": {"enabled": False},
                "wechat_work": {"enabled": True},
                "dingtalk": {"enabled": False},
                "telegram": {"enabled": False},
                "slack": {"enabled": False},
                "generic_webhook": {"enabled": False}
            }
        },
        "retry": {
            "max_attempts": 5,
            "min_wait": 2,
            "max_wait": 60
        },
        "logging": {
            "rotation_type": "time",
            "keep_days": 30
        },
        "concurrency": {
            "enabled": True,
            "workers": 2
        },
        "pdf_parser": {
            "mode": "pymupdf",
            "mineru_model_version": "vlm",
            "poll_interval": 3,
            "poll_timeout": 300
        },
        "report_settings": {
            "enable_html_report": True,
            "enable_markdown_report": True
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
                "update_check": False
            }
        },
        "webdav": {
            "enabled": True,
            "remote_path": "/arxiv-daily-researcher/",
            "sync_mode": "after_report",
            "cron_schedule": "0 23 * * *",
            "sync_configs": True,
            "sync_history": False,
            "sync_keywords": False,
            "sync_reports": False
        },
        "trend_research": {
            "default_date_range_days": 365,
            "max_results": 500,
            "sort_order": "ascending",
            "report_position": "end",
            "generate_tldr": True,
            "tldr_batch_size": 10,
            "output_formats": ["markdown", "html"],
            "enabled_skills": ["comprehensive_analysis"]
        }
    }


@pytest.fixture
def sample_run_result():
    """Create a mock RunResult-like dict for testing conversion."""
    return {
        "run_timestamp": "2026-06-16 10:00:00",
        "total_papers_fetched": 5,
        "papers_by_source": {"arxiv": 5},
        "qualified_by_source": {"arxiv": 3},
        "analyzed_by_source": {"arxiv": 2},
        "total_qualified": 3,
        "total_analyzed": 2,
        "success": True,
        "scored_papers_by_source": {
            "arxiv": [
                {
                    "paper_metadata": {
                        "paper_id": "2504.12345",
                        "title": "Pi0: A Vision-Language-Action Flow Model",
                        "authors": ["Author A", "Author B"],
                        "abstract": "We propose Pi0, a flow-based VLA model...",
                        "published_date": "2025-04-01",
                        "url": "https://arxiv.org/abs/2504.12345",
                        "pdf_url": "https://arxiv.org/pdf/2504.12345.pdf",
                        "categories": ["cs.RO", "cs.CV"],
                        "source": "arxiv",
                    },
                    "score_response": {
                        "total_score": 85.5,
                        "keyword_scores": {
                            "world model": 9.0,
                            "diffusion model": 8.0,
                            "embodied ai": 9.5,
                        },
                        "author_bonus": 0.0,
                        "expert_authors_found": [],
                        "passing_score": 20.0,
                        "is_qualified": True,
                        "reasoning": "论文核心方法涉及流匹配，面向具身 AI。",
                        "tldr": "提出了一种基于流匹配的 VLA 基础模型。",
                        "extracted_keywords": ["VLA", "Flow Matching", "Robot Foundation Model"],
                    },
                },
                {
                    "paper_metadata": {
                        "paper_id": "2504.67890",
                        "title": "Diffusion Policy: Visuomotor Policy Learning via Action Diffusion",
                        "authors": ["Author C"],
                        "abstract": "Diffusion Policy learns visuomotor policy...",
                        "published_date": "2025-04-02",
                        "url": "https://arxiv.org/abs/2504.67890",
                        "pdf_url": "https://arxiv.org/pdf/2504.67890.pdf",
                        "categories": ["cs.RO", "cs.LG"],
                        "source": "arxiv",
                    },
                    "score_response": {
                        "total_score": 72.0,
                        "keyword_scores": {
                            "world model": 5.0,
                            "diffusion model": 9.0,
                            "embodied ai": 7.0,
                        },
                        "author_bonus": 0.0,
                        "expert_authors_found": [],
                        "passing_score": 20.0,
                        "is_qualified": True,
                        "reasoning": "核心方法基于扩散模型，与关键词高度相关。",
                        "tldr": "提出将扩散模型应用于机器人策略学习。",
                        "extracted_keywords": ["Diffusion Policy", "Imitation Learning", "Robot"],
                    },
                },
            ]
        },
        "analyses_by_source": {
            "arxiv": [
                {
                    "paper_id": "2504.12345",
                    "analysis": {
                        "innovations": ["首次将流匹配应用于 VLA 基础模型"],
                        "methodology": "基于预训练 VLM，使用流匹配目标微调...",
                        "key_results": "在 7 个基准上平均提升 15.3%",
                        "limitations": ["仅在仿真环境中验证"],
                        "tech_stack": ["Flow Matching", "VLM", "Diffusion Transformer"],
                    },
                }
            ]
        },
    }
