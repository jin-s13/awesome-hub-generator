"""Tests for the local MinerU FastAPI adapter."""

import io
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock


RESEARCHER_SRC = Path(__file__).resolve().parents[1] / "arxiv-daily-researcher" / "src"
if str(RESEARCHER_SRC) not in sys.path:
    sys.path.insert(0, str(RESEARCHER_SRC))

from parsers.mineru_parser import MineruParser  # noqa: E402
import parsers.mineru_parser as mineru_parser_module  # noqa: E402
import scripts.fetch_teasers as fetch_teasers  # noqa: E402
from scripts.config_bridge import awesome_to_researcher_config  # noqa: E402
from config import Settings  # noqa: E402


class _JsonResponse:
    def __init__(self, data, status_code=200, content=b""):
        self._data = data
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _zip_with_image(path="paper/images/figure1.png", data=None):
    payload = data or b"x" * (12 * 1024)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(path, payload)
        zf.writestr("paper/txt/paper.md", "![figure](images/figure1.png)")
    return buffer.getvalue()


def test_local_mineru_parser_uploads_pdf_and_returns_markdown(monkeypatch):
    monkeypatch.setattr(mineru_parser_module.settings, "MINERU_API_KEY", "", raising=False)
    monkeypatch.setattr(mineru_parser_module.settings, "MINERU_BASE_URL", "http://mineru.local:2511/docs#/", raising=False)
    monkeypatch.setattr(mineru_parser_module.settings, "MINERU_API_MODE", "local", raising=False)
    monkeypatch.setattr(mineru_parser_module.settings, "MINERU_MODEL_VERSION", "pipeline", raising=False)
    monkeypatch.setattr(mineru_parser_module.settings, "MINERU_POLL_INTERVAL", 0, raising=False)
    monkeypatch.setattr(mineru_parser_module.settings, "MINERU_POLL_TIMEOUT", 30, raising=False)

    pdf_response = _JsonResponse({}, content=b"%PDF-1.4")
    parse_response = _JsonResponse(
        {
            "status": "completed",
            "results": {
                "2501.00001": {
                    "md_content": "## Parsed by local MinerU",
                    "images": {},
                }
            },
        }
    )
    get_mock = MagicMock(return_value=pdf_response)
    post_mock = MagicMock(return_value=parse_response)
    monkeypatch.setattr(mineru_parser_module.requests, "get", get_mock)
    monkeypatch.setattr(mineru_parser_module.requests, "post", post_mock)

    parser = MineruParser()

    assert parser.is_configured() is True
    assert parser.parse_pdf("https://arxiv.org/pdf/2501.00001.pdf") == "## Parsed by local MinerU"

    get_mock.assert_called_once_with("https://arxiv.org/pdf/2501.00001.pdf", timeout=60)
    post_mock.assert_called_once()
    assert post_mock.call_args.args[0] == "http://mineru.local:2511/file_parse"
    assert post_mock.call_args.kwargs["data"]["return_md"] == "true"
    assert post_mock.call_args.kwargs["data"]["backend"] == "pipeline"
    uploaded = post_mock.call_args.kwargs["files"]["files"]
    assert uploaded[0] == "2501.00001.pdf"
    assert uploaded[2] == "application/pdf"


def test_fetch_teasers_uses_local_mineru_zip_without_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_teasers, "MINERU_API_KEY", "")
    monkeypatch.setattr(fetch_teasers, "MINERU_BASE_URL", "http://mineru.local:2511/docs#/")
    monkeypatch.setattr(fetch_teasers, "MINERU_API_MODE", "local", raising=False)

    pdf_response = _JsonResponse({}, content=b"%PDF-1.4")
    zip_response = _JsonResponse({}, content=_zip_with_image())
    zip_response.headers = {"Content-Type": "application/zip"}
    get_mock = MagicMock(return_value=pdf_response)
    post_mock = MagicMock(return_value=zip_response)
    monkeypatch.setattr(fetch_teasers.requests, "get", get_mock)
    monkeypatch.setattr(fetch_teasers.requests, "post", post_mock)

    dest = tmp_path / "teaser.png"

    assert fetch_teasers._extract_pdf_figures_mineru("2501.00001", dest) is True
    assert dest.read_bytes() == b"x" * (12 * 1024)

    get_mock.assert_called_once_with(
        "https://arxiv.org/pdf/2501.00001.pdf",
        timeout=60,
        verify=fetch_teasers.MINERU_VERIFY_SSL,
    )
    post_mock.assert_called_once()
    assert post_mock.call_args.args[0] == "http://mineru.local:2511/file_parse"
    assert post_mock.call_args.kwargs["data"]["response_format_zip"] == "true"


def test_github_actions_forces_official_mineru_for_parser(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_IN_CI", raising=False)
    monkeypatch.setattr(mineru_parser_module.settings, "MINERU_API_KEY", "", raising=False)
    monkeypatch.setattr(mineru_parser_module.settings, "MINERU_BASE_URL", "http://mineru.local:2511", raising=False)
    monkeypatch.setattr(mineru_parser_module.settings, "MINERU_API_MODE", "auto", raising=False)

    parser = MineruParser()

    assert parser.base_url == "https://mineru.net/api/v4"
    assert parser.api_mode == "official"
    assert parser._is_local_api() is False
    assert parser.is_configured() is False


def test_github_actions_forces_official_mineru_for_teasers(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_IN_CI", raising=False)
    monkeypatch.setattr(fetch_teasers, "MINERU_BASE_URL", "http://mineru.local:2511")
    monkeypatch.setattr(fetch_teasers, "MINERU_API_MODE", "auto", raising=False)

    assert fetch_teasers._is_local_mineru_api() is False


def test_github_actions_does_not_export_local_mineru_to_researcher_config(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_IN_CI", raising=False)

    config = awesome_to_researcher_config(
        {
            "project": {"name": "Test"},
            "research": {
                "deep_analysis": {
                    "pdf_parser": "mineru",
                    "mineru_base_url": "http://mineru.local:2511",
                    "mineru_api_mode": "local",
                }
            },
        }
    )

    assert config["pdf_parser"]["base_url"] == "https://mineru.net/api/v4"
    assert config["pdf_parser"]["api_mode"] == "official"


def test_github_actions_settings_ignores_local_mineru_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_IN_CI", raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "pdf_parser": {
            "mode": "mineru",
            "base_url": "http://mineru.local:2511",
            "api_mode": "local"
          }
        }
        """,
        encoding="utf-8",
    )

    settings = Settings()
    settings.load_from_search_config(config_path)

    assert settings.MINERU_BASE_URL == "https://mineru.net/api/v4"
    assert settings.MINERU_API_MODE == "official"
