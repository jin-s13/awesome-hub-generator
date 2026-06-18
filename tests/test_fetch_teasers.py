"""Tests for fetch_teasers.py"""

from unittest.mock import MagicMock, patch

import pytest

from scripts.fetch_teasers import (
    _extract_arxiv_id,
    _fetch_with_retry,
    download_image,
)


class TestExtractArxivId:
    """Test arXiv ID extraction from URLs."""

    def test_abs_url(self):
        assert _extract_arxiv_id("https://arxiv.org/abs/2504.12345") == "2504.12345"

    def test_html_url(self):
        assert _extract_arxiv_id("https://arxiv.org/html/2504.12345v1") == "2504.12345"

    def test_pdf_url(self):
        assert _extract_arxiv_id("https://arxiv.org/pdf/2504.12345.pdf") == "2504.12345"

    def test_no_match(self):
        assert _extract_arxiv_id("https://example.com/paper") is None

    def test_empty(self):
        assert _extract_arxiv_id("") is None


class TestFetchWithRetry:
    """Test HTTP fetch with retry."""

    def test_success(self, mocker):
        mock_get = mocker.patch("scripts.fetch_teasers.requests.get")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        result = _fetch_with_retry("https://example.com")
        assert result is not None
        mock_get.assert_called_once()

    def test_404_returns_none(self, mocker):
        mock_get = mocker.patch("scripts.fetch_teasers.requests.get")
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = _fetch_with_retry("https://example.com/404")
        assert result is None
        mock_get.assert_called_once()

    def test_retry_on_error(self, mocker):
        import requests
        mock_get = mocker.patch("scripts.fetch_teasers.requests.get")
        mock_get.side_effect = [
            requests.RequestException("Timeout"),
            MagicMock(status_code=200),
        ]

        result = _fetch_with_retry("https://example.com", max_retries=1)
        assert result is not None
        assert mock_get.call_count == 2


class TestDownloadImage:
    """Test image download."""

    def test_downloads_successfully(self, mocker, tmp_path):
        mock_get = mocker.patch("scripts.fetch_teasers.requests.get")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.content = b"x" * (20 * 1024)  # 20KB
        mock_get.return_value = mock_resp

        dest = tmp_path / "test.png"
        result = download_image("https://example.com/img.png", dest)
        assert result is True
        assert dest.exists()
        assert dest.read_bytes() == b"x" * (20 * 1024)

    def test_rejects_small_images(self, mocker, tmp_path):
        mock_get = mocker.patch("scripts.fetch_teasers.requests.get")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.content = b"x" * (5 * 1024)  # 5KB — too small
        mock_get.return_value = mock_resp

        dest = tmp_path / "small.png"
        result = download_image("https://example.com/small.png", dest)
        assert result is False
        assert not dest.exists()

    def test_rejects_non_image(self, mocker, tmp_path):
        mock_get = mocker.patch("scripts.fetch_teasers.requests.get")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_get.return_value = mock_resp

        dest = tmp_path / "notimage.png"
        result = download_image("https://example.com/notimage", dest)
        assert result is False
