"""Tests for fetch_teasers.py"""

from unittest.mock import MagicMock

from scripts.fetch_teasers import (
    _extract_arxiv_id,
    _extract_openreview_id,
    _candidate_pdf_urls,
    _sync_existing_teaser_asset,
    _fetch_with_retry,
    _normalize_arxiv_url,
    _fetch_arxiv_html_teaser,
    _is_icon_or_logo,
    fetch_teaser_for_paper_detailed,
    _mark_teaser_fallback_warning,
    _remove_teaser_fallback_warnings,
    _should_fetch_teaser_preview,
    download_image,
)


class TestExtractArxivId:
    def test_abs_url(self):
        assert _extract_arxiv_id("https://arxiv.org/abs/2504.12345") == "2504.12345"
    def test_no_match(self):
        assert _extract_arxiv_id("https://example.com/paper") is None


class TestExtractOpenReviewId:
    def test_forum_url(self):
        assert _extract_openreview_id("https://openreview.net/forum?id=X2HnTFsFm8") == "X2HnTFsFm8"

    def test_pdf_url(self):
        assert _extract_openreview_id("https://openreview.net/pdf?id=cvGdPXaydP") == "cvGdPXaydP"


class TestCandidatePdfUrls:
    def test_prefers_explicit_pdf_links(self):
        links = {
            "paper": "https://example.com/landing",
            "pdf": "https://example.com/paper.pdf",
        }
        assert _candidate_pdf_urls(links) == ["https://example.com/paper.pdf"]

    def test_keeps_direct_paper_pdf(self):
        assert _candidate_pdf_urls({"paper": "https://example.com/paper.pdf"}) == ["https://example.com/paper.pdf"]

    def test_derives_cvf_openaccess_pdf(self):
        assert _candidate_pdf_urls(
            {
                "paper": (
                    "https://openaccess.thecvf.com/content/CVPR2025/html/"
                    "Tan_SceneDiffuser_City-Scale_Traffic_Simulation_via_a_Generative_World_Model_CVPR_2025_paper.html"
                )
            }
        ) == [
            (
                "https://openaccess.thecvf.com/content/CVPR2025/papers/"
                "Tan_SceneDiffuser_City-Scale_Traffic_Simulation_via_a_Generative_World_Model_CVPR_2025_paper.pdf"
            )
        ]

    def test_derives_neurips_abstract_pdf(self):
        assert _candidate_pdf_urls(
            {
                "paper": (
                    "https://proceedings.neurips.cc/paper_files/paper/2022/hash/"
                    "827cb489449ea216e4a257c47e407d18-Abstract-Conference.html"
                )
            }
        ) == [
            (
                "https://proceedings.neurips.cc/paper_files/paper/2022/file/"
                "827cb489449ea216e4a257c47e407d18-Paper-Conference.pdf"
            )
        ]


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


class TestShouldFetchTeaserPreview:
    def test_fetches_placeholder(self):
        assert _should_fetch_teaser_preview("/assets/placeholder.svg") is True

    def test_retries_generated_svg_fallback_by_default(self):
        assert _should_fetch_teaser_preview("/assets/papers/example/teaser.svg") is True

    def test_can_skip_generated_svg_fallback_when_disabled(self):
        assert _should_fetch_teaser_preview("/assets/papers/example/teaser.svg", retry_fallbacks=False) is False

    def test_skips_existing_real_teaser(self):
        assert _should_fetch_teaser_preview("/assets/papers/example/teaser.png") is False


class TestTeaserFallbackWarnings:
    def test_marks_unresolved_svg_fallback(self):
        paper = {"id": "p1", "preview": "/assets/papers/p1/teaser.svg"}
        _mark_teaser_fallback_warning(paper, "no real teaser found")
        assert "generated_fallback_teaser" in paper["generation_notes"]
        assert "warning_unresolved_teaser_fallback" in paper["generation_notes"]

    def test_removes_fallback_warnings_after_real_teaser(self):
        paper = {"generation_notes": ["generated_fallback_teaser", "warning_unresolved_teaser_fallback", "other"]}
        _remove_teaser_fallback_warnings(paper)
        assert paper["generation_notes"] == ["other"]

    def test_syncs_existing_teaser_asset_for_duplicate_fallback_row(self, monkeypatch, tmp_path):
        assets_dir = tmp_path / "assets"
        teaser = assets_dir / "p1" / "teaser.png"
        teaser.parent.mkdir(parents=True)
        teaser.write_bytes(b"x" * 12000)
        monkeypatch.setattr("scripts.fetch_teasers.ASSETS_DIR", assets_dir)
        paper = {
            "id": "p1",
            "preview": "/assets/placeholder.svg",
            "generation_notes": ["generated_fallback_teaser", "warning_unresolved_teaser_fallback"],
        }

        assert _sync_existing_teaser_asset(paper) is True
        assert paper["preview"] == "/assets/papers/p1/teaser.png"
        assert "generation_notes" not in paper


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


class TestFetchTeaserForPaperDetailed:
    def test_openreview_has_actionable_reason(self):
        result, reason = fetch_teaser_for_paper_detailed(
            {"id": "p1", "links": {"paper": "https://openreview.net/forum?id=X2HnTFsFm8"}}
        )
        assert result is None
        assert "OpenReview" in reason
        assert "no direct PDF or arXiv URL" in reason

    def test_publisher_landing_page_has_actionable_reason(self):
        result, reason = fetch_teaser_for_paper_detailed(
            {"id": "p1", "links": {"paper": "https://ieeexplore.ieee.org/abstract/document/10538211/"}}
        )
        assert result is None
        assert "publisher landing page" in reason

    def test_direct_pdf_uses_local_pdf_extraction(self, mocker):
        mocker.patch("scripts.fetch_teasers._extract_pdf_url_figures_local", return_value=True)
        result, reason = fetch_teaser_for_paper_detailed(
            {"id": "p1", "links": {"paper": "https://example.com/paper.pdf"}}
        )
        assert result == "/assets/papers/p1/teaser.png"
        assert reason == "direct PDF extraction succeeded"


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
