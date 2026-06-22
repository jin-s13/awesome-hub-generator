"""Tests for config_bridge.py"""

import json
import os
from pathlib import Path

import pytest

from scripts.config_bridge import (
    awesome_to_researcher_config,
    generate_env_file,
    sync_config,
)


class TestAwesomeToResearcherConfig:
    """Test the config mapping from awesome.yaml to researcher config.json."""

    def test_basic_mapping(self, sample_awesome_config):
        """Verify basic fields are mapped correctly."""
        result = awesome_to_researcher_config(sample_awesome_config)
        assert result["search_settings"]["search_days"] == 3
        assert result["target_domains"]["domains"] == ["cs.CV", "cs.GR", "cs.LG"]
        assert result["keywords"]["primary_keywords"]["keywords"] == [
            "CAD", "B-Rep", "parametric CAD", "CAD generation", "text-to-CAD"
        ]
        assert result["scoring_settings"]["passing_score_formula"]["base_score"] == 1.5
        assert result["pdf_parser"]["mode"] == "pymupdf"

    def test_notifications_disabled(self, sample_awesome_config):
        """Notifications should always be disabled in CI/automated mode."""
        result = awesome_to_researcher_config(sample_awesome_config)
        assert result["notifications"]["enabled"] is False
        assert result["webdav"]["enabled"] is False

    def test_empty_keywords(self):
        """Handle empty keywords gracefully."""
        config = {
            "project": {"name": "Test"},
            "research": {"keywords": [], "arxiv_categories": ["cs.CV"]},
        }
        result = awesome_to_researcher_config(config)
        assert result["keywords"]["primary_keywords"]["keywords"] == []

    def test_default_values(self):
        """Test defaults when optional fields are missing."""
        config = {"project": {}, "research": {}}
        result = awesome_to_researcher_config(config)
        assert result["search_settings"]["search_days"] == 3
        assert result["keywords"]["primary_keywords"]["keywords"] == []
        assert result["scoring_settings"]["passing_score_formula"]["base_score"] == 1.5

    def test_author_bonus_enabled(self):
        """Verify author_bonus mapping when enabled."""
        config = {
            "project": {"name": "Test"},
            "research": {
                "scoring": {
                    "author_bonus": {
                        "enabled": True,
                        "bonus_points": 10.0,
                        "expert_authors": ["Dr. Smith", "Prof. Jones"],
                    }
                }
            },
        }
        result = awesome_to_researcher_config(config)
        assert result["scoring_settings"]["author_bonus"]["enabled"] is True
        assert result["scoring_settings"]["author_bonus"]["bonus_points"] == 10.0


class TestGenerateEnvFile:
    """Test .env file generation."""

    def test_generates_correct_content(self):
        """Verify .env content structure."""
        content = generate_env_file(
            ark_api_key="sk-test-key",
            ark_base_url="https://test.api.com/v3",
            ark_model_name="test-model",
            smart_model_name="test-smart-model",
        )
        assert 'CHEAP_LLM__API_KEY="sk-test-key"' in content
        assert 'SMART_LLM__MODEL_NAME="test-smart-model"' in content
        assert "NOTIFICATIONS_ENABLED=false" in content

    def test_smart_model_defaults_to_cheap(self, monkeypatch):
        """SMART_MODEL_NAME should default to ARK_MODEL_NAME if not set."""
        monkeypatch.delenv("SMART_MODEL_NAME", raising=False)
        monkeypatch.delenv("ARK_MODEL_NAME", raising=False)
        content = generate_env_file(
            ark_api_key="sk-key", ark_model_name="cheap-model", smart_model_name=None,
        )
        assert 'SMART_LLM__MODEL_NAME="cheap-model"' in content

    def test_falls_back_to_env_vars(self, monkeypatch):
        """Should use env vars when no values provided."""
        monkeypatch.setenv("ARK_API_KEY", "env-key")
        monkeypatch.setenv("ARK_API_BASE_URL", "https://env.api.com/v3")
        monkeypatch.setenv("ARK_MODEL_NAME", "env-model")
        content = generate_env_file()
        assert 'CHEAP_LLM__API_KEY="env-key"' in content

    def test_writes_to_file(self, tmp_path):
        """Verify writing to a file path."""
        env_file = tmp_path / ".env"
        content = generate_env_file(env_path=env_file, ark_api_key="sk-file-key")
        assert env_file.exists()
        assert 'CHEAP_LLM__API_KEY="sk-file-key"' in env_file.read_text(encoding="utf-8")


class TestSyncConfig:
    """Test the one-shot sync_config function."""

    def test_writes_both_files(self, sample_awesome_config, monkeypatch, tmp_path):
        """Verify sync_config writes both config.json and .env."""
        researcher_dir = tmp_path / "arxiv-daily-researcher"
        researcher_dir.mkdir()
        config_dir = researcher_dir / "configs"
        config_dir.mkdir()

        import scripts.config_bridge as cb
        monkeypatch.setattr(cb, "RESEARCHER_DIR", researcher_dir)
        monkeypatch.setattr(cb, "RESEARCHER_CONFIG_PATH", config_dir / "config.json")
        monkeypatch.setattr(cb, "RESEARCHER_ENV_PATH", researcher_dir / ".env")

        sync_config(sample_awesome_config)

        config_path = config_dir / "config.json"
        assert config_path.exists()
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["search_settings"]["search_days"] == 3

        env_path = researcher_dir / ".env"
        assert env_path.exists()
        assert "NOTIFICATIONS_ENABLED=false" in env_path.read_text(encoding="utf-8")
