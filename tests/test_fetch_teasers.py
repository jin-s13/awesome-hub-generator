"""Tests for fetch_teasers.py"""

from unittest.mock import MagicMock

from scripts.fetch_teasers import (
    _extract_arxiv_id,
    _fetch_with_retry,
    _normalize_arxiv_url,
    _fetch_arxiv_html_teaser,
    _is_icon_or_logo,
    download_image,
)


class TestExtractArxivId:
    def test_abs_url(self):
        assert _extract_arxiv_id("https://arxiv.org/abs/2504.12345") == "2504.12345"
    def test_no_match(self):
        assert _extract_arxiv_id("https://example.com/paper") is None


class TestNormalizeArxivUrl:
    def test_absolute_url(self):
        assert _normalize_arxiv_url("https://example.com/img.png", "2303.08774") == "https://example.com/img.png"
    def test_relative_with_slash(self):
        assert _normalize_arxiv_url("/html/2303.08774/x1.png", "2303.08774") == "https://arxiv.org/html/2303.08774/x1.png"


class TestIsIconOrLogo:
    def test_icon_keywords(self):
        assert _is_icon_or_logo("icon-arrow.png") is True
    def test_non_icon_keywords(self):
        assert _is_icon_or_logo("figure1.png") is False


class TestFetchWithRetry:
    def test_success(self, mocker):
        mock_get = mocker.patch("scripts.fetch_teasers.requests.get")
        mock_get.return_value = MagicMock(status_code=200)
        assert _fetch_with_retry("https://example.com") is not None
    def test_404_returns_none(self, mocker):
        mock_get = mocker.patch("scripts.fetch_teasers.requests.get")
        mock_get.return_value = MagicMock(status_code=404)
        assert _fetch_with_retry("https://example.com/404") is None


class TestFetchArxivHtmlTeaser:
    def test_fetch_via_html_parser(self, mocker):
        html = (
            '<html><body>'
            '<figure><img src="https://arxiv.org/html/x1.png" alt="Figure 1"/></figure>'
            '</body></html>'
        )
        mock_response = MagicMock(status_code=200, text=html)
        mocker.patch("scripts.fetch_teasers._fetch_with_retry", return_value=mock_response)
        assert _fetch_arxiv_html_teaser("2303.08774") == "https://arxiv.org/html/x1.png"
    def test_fetch_html_404(self, mocker):
        mocker.patch("scripts.fetch_teasers._fetch_with_retry").return_value = None
        assert _fetch_arxiv_html_teaser("2303.08774") is None


class TestDownloadImage:
    def test_downloads_successfully(self, mocker, tmp_path):
        mocker.patch("scripts.fetch_teasers.requests.get").return_value = MagicMock(
            status_code=200, headers={"Content-Type": "image/png"}, content=b"x" * (20 * 1024))
        dest = tmp_path / "test.png"
        assert download_image("https://example.com/img.png", dest) is True
    def test_rejects_small_images(self, mocker, tmp_path):
        mocker.patch("scripts.fetch_teasers.requests.get").return_value = MagicMock(
            status_code=200, headers={"Content-Type": "image/png"}, content=b"x" * (5 * 1024))
        assert download_image("https://example.com/small.png", tmp_path / "small.png") is False
