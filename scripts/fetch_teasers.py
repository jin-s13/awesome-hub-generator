"""
fetch_teasers.py — Fetch paper teaser images from multiple sources.

Multi-source fallback (in order):
1. arXiv HTML <figure> tags (preferred)
2. Project page (extracted from abstract)
3. arXiv PDF thumbnail
4. MinerU PDF parsing (extracts actual figures from PDF)
5. pdfimages embedded figure extraction (fallback if MinerU unavailable)
"""

import io
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
import re
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

import requests
import yaml

import urllib3

# ROOT = generator root (for templates, scripts)
ROOT = Path(__file__).resolve().parents[1]
# SITE_DIR = current working directory (downstream repo root, or generator for dev)
SITE_DIR = Path.cwd()

# Load .env file: check CWD first, then ROOT
for _env_path in [SITE_DIR / ".env", ROOT / ".env"]:
    if _env_path.exists():
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _key, _val = _line.split("=", 1)
                    _val = _val.strip("\"'")
                    os.environ.setdefault(_key.strip(), _val)
        break

logger = logging.getLogger("fetch_teasers")
GENERATED_FALLBACK_TEASER_NOTE = "generated_fallback_teaser"
UNRESOLVED_TEASER_FALLBACK_WARNING = "warning_unresolved_teaser_fallback"
TEASER_FALLBACK_NOTES = {GENERATED_FALLBACK_TEASER_NOTE, UNRESOLVED_TEASER_FALLBACK_WARNING}

DATA_DIR = Path(os.environ.get("HUB_DATA_DIR", str(SITE_DIR / ".local/data")))
ASSETS_DIR = Path(os.environ.get("HUB_ASSETS_DIR", str(SITE_DIR / ".local/assets/papers")))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; awesome-hub-generator/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}

# MinerU API
MINERU_BASE_URL = "https://mineru.net/api/v4"
MINERU_API_KEY = os.environ.get("MINERU_API_KEY", "")
MINERU_VERIFY_SSL = os.environ.get("MINERU_VERIFY_SSL", "true").lower() not in ("0", "false", "no")
MINERU_POLL_INTERVAL = 3
MINERU_POLL_TIMEOUT = 60

if not MINERU_VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _extract_arxiv_id(url: str) -> Optional[str]:
    """Extract arXiv ID from a URL."""
    m = re.search(r"arxiv\.org/(?:abs|html|pdf)/(\d+\.\d+)", url)
    return m.group(1) if m else None


def _normalize_arxiv_url(src: str, arxiv_id: str) -> str:
    """Normalize a (possibly relative) URL from an arXiv HTML page to absolute."""
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if src.startswith("/"):
        return f"https://arxiv.org{src}"
    # Relative path like "2606.16605v1/figs/ARB4WMb.png"
    return f"https://arxiv.org/html/{src}"


def _is_icon_or_logo(src: str) -> bool:
    """Return True if the image src looks like an icon/logo and should be skipped."""
    if not src:
        return False
    lowered = src.lower()
    return any(kw in lowered for kw in ("icon", "logo", "favicon", "github", "twitter"))


def _fetch_with_retry(url: str, timeout: int = 15, max_retries: int = 2) -> Optional[requests.Response]:
    """Fetch a URL with retry."""
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                return resp
            elif resp.status_code == 404:
                return None
        except requests.RequestException as e:
            if attempt < max_retries:
                time.sleep(1)
                continue
            logger.debug(f"Failed to fetch {url}: {e}")
    return None


def _fetch_arxiv_html_teaser(arxiv_id: str) -> Optional[str]:
    """
    Try to fetch teaser image from arXiv HTML page.
    Looks for the first meaningful <figure> or <img> tag.
    """
    html_url = f"https://arxiv.org/html/{arxiv_id}"
    resp = _fetch_with_retry(html_url)
    if not resp:
        return None

    html = resp.text

    # Pattern 1: <figure> with <img> inside (preferred)
    figure_pattern = re.compile(
        r'<figure[^>]*>.*?<img[^>]+src=["\']([^"\']+)["\'][^>]*>.*?</figure>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in figure_pattern.finditer(html):
        img_src = match.group(1)
        img_src = _normalize_arxiv_url(img_src, arxiv_id)
        if _is_icon_or_logo(img_src):
            continue
        return img_src

    # Pattern 2: Any <img> with reasonable size (not icon/logo)
    img_pattern = re.compile(
        r'<img[^>]+src=["\']([^"\']+(?:png|jpg|jpeg|gif|webp))["\'][^>]*>',
        re.IGNORECASE,
    )
    for src in img_pattern.findall(html):
        if not _is_icon_or_logo(src):
            src = _normalize_arxiv_url(src, arxiv_id)
            return src

    return None


def _extract_project_page(arxiv_id: str) -> Optional[str]:
    """
    Try to find the project page URL from the arXiv abstract page.
    Common patterns: "project page", "project website", "github.io", etc.
    """
    abs_url = f"https://arxiv.org/abs/{arxiv_id}"
    resp = _fetch_with_retry(abs_url)
    if not resp:
        return None

    html = resp.text

    # Look for project page links in the abstract
    # Common patterns in arXiv abstracts
    project_patterns = [
        r'project\s+(?:page|website|site|homepage)[:\s]*(https?://[^\s<)"]+)',
        r'project\s+page[:\s]*(?:https?://[^\s<)"]+)',
        r'our\s+(?:project\s+)?(?:page|website)[:\s]*(https?://[^\s<)"]+)',
        r'code\s+(?:and\s+)?(?:project\s+)?page[:\s]*(https?://[^\s<)"]+)',
        r'(https?://\w+\.github\.io/[^\s<)"]+)',
        r'(https?://[^\s<)"]+\.github\.io/[^\s<)"]+)',
    ]

    for pattern in project_patterns:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            url = m.group(1).rstrip(".,)")
            # Clean up URL
            url = re.sub(r'[<>"\'\]\)]', '', url)
            return url

    return None


def _fetch_project_page_teaser(project_url: str) -> Optional[str]:
    """
    Try to fetch teaser image from the project page.
    Looks for the first large image (teaser / overview figure).
    """
    resp = _fetch_with_retry(project_url)
    if not resp:
        return None

    html = resp.text

    # Pattern 1: Look for images with "teaser" in class/id/alt
    teaser_pattern = re.compile(
        r'<img[^>]*(?:class|id|alt)["\']?[^"\']*teaser[^"\']*["\']?[^>]*src=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    match = teaser_pattern.search(html)
    if match:
        src = match.group(1)
        if src.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(project_url)
            src = f"{parsed.scheme}://{parsed.netloc}{src}"
        return src

    # Pattern 2: First large image (skip icons/logos)
    img_pattern = re.compile(
        r'<img[^>]+src=["\']([^"\']+(?:png|jpg|jpeg|gif|webp))["\'][^>]*>',
        re.IGNORECASE,
    )
    for src in img_pattern.findall(html):
        if any(skip in src.lower() for skip in ["icon", "logo", "github", "twitter", "favicon"]):
            continue
        if src.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(project_url)
            src = f"{parsed.scheme}://{parsed.netloc}{src}"
        return src

    return None


def _fetch_arxiv_pdf_thumbnail(arxiv_id: str) -> Optional[str]:
    """Try arXiv PDF thumbnail URLs."""
    for thumb_path in ["images/teaser.png", "images/0001.png"]:
        thumb_url = f"https://arxiv.org/html/{arxiv_id}/{thumb_path}"
        resp = _fetch_with_retry(thumb_url)
        if resp:
            return thumb_url
    return None


def _extract_pdf_figures_mineru(arxiv_id: str, dest_path: Path) -> bool:
    """
    Extract figures from PDF using MinerU cloud API.

    MinerU returns a ZIP containing:
    - images/ directory with extracted figures from the PDF
    - full.md with markdown content referencing those images

    This gives us the actual Figure 1, Figure 2, etc. from the paper.
    """
    if not MINERU_API_KEY:
        return False

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    logger.debug(f"    Submitting to MinerU: {pdf_url}")

    # Step 1: Submit task
    try:
        resp = requests.post(
            f"{MINERU_BASE_URL}/extract/task",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {MINERU_API_KEY}",
            },
            json={
                "url": pdf_url,
                "model_version": "vlm",
                "enable_formula": False,
                "enable_table": False,
            },
            timeout=30,
            verify=MINERU_VERIFY_SSL,
        )
        result = resp.json()
        if result.get("code") != 0:
            logger.debug(f"    MinerU submit failed: {result.get('msg')}")
            return False
        task_id = result["data"]["task_id"]
    except Exception as e:
        logger.debug(f"    MinerU submit error: {e}")
        return False

    # Step 2: Poll until done
    start_time = time.time()
    zip_url = None
    while time.time() - start_time < MINERU_POLL_TIMEOUT:
        try:
            resp = requests.get(
                f"{MINERU_BASE_URL}/extract/task/{task_id}",
                headers={"Authorization": f"Bearer {MINERU_API_KEY}"},
                timeout=30,
                verify=MINERU_VERIFY_SSL,
            )
            result = resp.json()
            if result.get("code") != 0:
                break
            state = result["data"].get("state")
            if state == "done":
                zip_url = result["data"].get("full_zip_url")
                break
            elif state == "failed":
                logger.debug(f"    MinerU task failed: {result['data'].get('err_msg')}")
                break
        except Exception:
            pass
        time.sleep(MINERU_POLL_INTERVAL)

    if not zip_url:
        return False

    # Step 3: Download ZIP and extract first large image
    try:
        resp = requests.get(zip_url, timeout=60, verify=MINERU_VERIFY_SSL)
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            # Look for images in the images/ directory
            image_files = sorted(
                [f for f in zf.namelist() if f.startswith("images/") and any(
                    f.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]
                )]
            )

            if not image_files:
                logger.debug(f"    No images found in MinerU ZIP")
                return False

            # Try each image, use the first one > 10KB
            for img_path in image_files:
                data = zf.read(img_path)
                if len(data) > 10 * 1024:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    dest_path.write_bytes(data)
                    logger.debug(f"    MinerU extracted: {img_path} ({len(data)} bytes)")
                    return True

            # If all images are small, still use the first one
            data = zf.read(image_files[0])
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(data)
            return True

    except Exception as e:
        logger.debug(f"    MinerU ZIP download/extract error: {e}")
        return False


def _extract_pdf_figures_local(arxiv_id: str, dest_path: Path) -> bool:
    """
    Extract embedded figures from the arXiv PDF using pdfimages.

    pdfimages extracts actual embedded images (figures, diagrams, photos)
    from the PDF, NOT rendered page snapshots. This gives us the real
    Figure 1, Figure 2, etc. from the paper.

    Falls back to pdftoppm first-page rendering if no embedded figures found.
    """
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    pdf_path = dest_path.parent / f"{arxiv_id}.pdf"

    # Download PDF
    resp = _fetch_with_retry(pdf_url, timeout=120)
    if not resp:
        return False

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(resp.content)
    if pdf_path.stat().st_size < 50000:  # Too small to be a real PDF
        pdf_path.unlink()
        return False

    # Strategy 1: Extract embedded figures with pdfimages
    try:
        prefix = str(dest_path.parent / f"{arxiv_id}_fig")
        subprocess.run(
            ["pdfimages", "-png", str(pdf_path), prefix],
            capture_output=True, timeout=120,
        )

        # Find extracted images > 10KB (these are actual figures)
        extracted = sorted(dest_path.parent.glob(f"{arxiv_id}_fig-*.png"))
        large = [f for f in extracted if f.stat().st_size > 10240]

        if large:
            # Use the first large figure as teaser
            large[0].rename(dest_path)
            # Clean up remaining extracted images
            for f in extracted:
                if f.exists():
                    f.unlink()
            return True

        # Clean up small/icon images
        for f in extracted:
            if f.exists():
                f.unlink()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Strategy 2: Fall back to pdftoppm first page (if no embedded figures)
    try:
        prefix = str(dest_path.parent / f"{arxiv_id}_page")
        subprocess.run(
            ["pdftoppm", "-f", "1", "-l", "1", "-png", "-scale-to", "800", str(pdf_path), prefix],
            capture_output=True, timeout=60,
        )
        generated = list(dest_path.parent.glob(f"{arxiv_id}_page-*.png"))
        if generated:
            generated[0].rename(dest_path)
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    finally:
        if pdf_path.exists():
            pdf_path.unlink()
        for f in dest_path.parent.glob(f"{arxiv_id}_fig-*"):
            f.unlink()
        for f in dest_path.parent.glob(f"{arxiv_id}_page-*"):
            f.unlink()

    return False


def download_image(url: str, dest_path: Path) -> bool:
    """Download an image from URL to destination path."""
    resp = _fetch_with_retry(url, timeout=20)
    if not resp:
        return False

    content_type = resp.headers.get("Content-Type", "")
    if "image" not in content_type:
        return False

    if len(resp.content) < 10 * 1024:
        return False

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(resp.content)
    return True


def check_image_reachability(url: str, timeout: int = 10) -> bool:
    """检查图片 URL 是否可达。用 HTTP HEAD 请求验证。"""
    try:
        req = Request(url, method="HEAD")
        req.add_header("User-Agent", "awesome-hub-generator/1.0")
        resp = urlopen(req, timeout=timeout)
        status = resp.getcode()
        return status is not None and 200 <= status < 400
    except (URLError, OSError, ValueError):
        return False


def localize_image(paper: Dict, assets_dir: Path, timeout: int = 30) -> bool:
    """将论文的 preview URL 图片下载到本地 assets 目录。

    1. 检查 preview 是否已经是本地路径（以 /assets/ 开头）
    2. 如果是远程 URL，检查可达性
    3. 下载到 assets_dir / paper_id / "teaser.png"
    4. 更新 paper["preview"] 为本地路径
    """
    preview = paper.get("preview", "")
    if not preview:
        return False

    # 已经是本地路径，无需处理
    if preview.startswith("/assets/"):
        return False

    # 只处理远程 URL
    if not (preview.startswith("http://") or preview.startswith("https://")):
        return False

    paper_id = paper.get("id", "")
    if not paper_id:
        return False

    dest_path = assets_dir / paper_id / "teaser.png"
    if dest_path.exists():
        paper["preview"] = f"/assets/papers/{paper_id}/teaser.png"
        return True

    logger.info(f"  Localizing image for {paper_id}...")
    if download_image(preview, dest_path):
        paper["preview"] = f"/assets/papers/{paper_id}/teaser.png"
        logger.info(f"    Localized: {preview[:80]} -> {dest_path}")
        return True

    logger.debug(f"    Failed to localize image for {paper_id}")
    return False


def _load_image_localization_config() -> Dict[str, Any]:
    """从 awesome.yaml 读取 image_localization 配置。"""
    env_config = Path(os.environ.get("HUB_CONFIG_PATH", "")) if os.environ.get("HUB_CONFIG_PATH") else None
    candidates = [p for p in [env_config, SITE_DIR / "awesome.yaml", ROOT / "awesome.yaml.example"] if p]
    for config_path in candidates:
        if config_path.exists():
            try:
                config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                if config and isinstance(config, dict):
                    il_config = config.get("research", {}).get("image_localization", {})
                    if isinstance(il_config, dict):
                        return il_config
            except Exception:
                pass
            break
    return {}


def _should_fetch_teaser_preview(preview: str, retry_fallbacks: bool = True) -> bool:
    """Return True when the current preview is missing or only a generated fallback."""
    if not preview:
        return True
    if "/assets/placeholder.svg" in preview:
        return True
    if retry_fallbacks and preview.endswith("/teaser.svg"):
        return True
    return False


def _is_teaser_fallback_preview(preview: str) -> bool:
    """Return True for missing, placeholder, or generated SVG teaser previews."""
    return not preview or "/assets/placeholder.svg" in preview or preview.endswith("/teaser.svg")


def _ensure_generation_note(paper: Dict[str, Any], note: str) -> None:
    notes = paper.get("generation_notes")
    if not isinstance(notes, list):
        notes = []
    if note not in notes:
        notes.append(note)
    paper["generation_notes"] = notes


def _remove_teaser_fallback_warnings(paper: Dict[str, Any]) -> bool:
    notes = paper.get("generation_notes")
    if not isinstance(notes, list):
        return False
    cleaned = [note for note in notes if note not in TEASER_FALLBACK_NOTES]
    if cleaned == notes:
        return False
    paper["generation_notes"] = cleaned
    if not paper["generation_notes"]:
        paper.pop("generation_notes", None)
    return True


def _mark_teaser_fallback_warning(paper: Dict[str, Any], reason: str) -> bool:
    before = list(paper.get("generation_notes") or [])
    _ensure_generation_note(paper, GENERATED_FALLBACK_TEASER_NOTE)
    _ensure_generation_note(paper, UNRESOLVED_TEASER_FALLBACK_WARNING)
    logger.warning(
        "TEASER FALLBACK UNRESOLVED: %s preview=%s reason=%s",
        paper.get("id", "<missing-id>"),
        paper.get("preview", ""),
        reason,
    )
    return before != paper.get("generation_notes", [])


def fetch_teaser_for_paper(paper: Dict[str, Any]) -> Optional[str]:
    """
    Fetch teaser image for a single paper using multi-source fallback.
    Returns the local path if successful, None otherwise.
    """
    paper_id = paper.get("id", "")
    links = paper.get("links", {})
    paper_url = links.get("paper", "")

    arxiv_id = _extract_arxiv_id(paper_url)
    if not arxiv_id:
        logger.debug(f"No arXiv ID found for {paper_id}")
        return None

    dest_path = ASSETS_DIR / paper_id / "teaser.png"
    if dest_path.exists():
        return f"/assets/papers/{paper_id}/teaser.png"

    logger.info(f"  Fetching teaser for {paper_id}...")

    # Source 1: arXiv HTML <figure> tags
    img_url = _fetch_arxiv_html_teaser(arxiv_id)
    if img_url:
        logger.debug(f"    Found in arXiv HTML: {img_url[:80]}")
        if download_image(img_url, dest_path):
            logger.info(f"    Downloaded from arXiv HTML")
            return f"/assets/papers/{paper_id}/teaser.png"

    # Source 2: Project page
    project_url = _extract_project_page(arxiv_id)
    if project_url:
        logger.debug(f"    Found project page: {project_url}")
        img_url = _fetch_project_page_teaser(project_url)
        if img_url:
            logger.debug(f"    Found teaser on project page: {img_url[:80]}")
            if download_image(img_url, dest_path):
                logger.info(f"    Downloaded from project page")
                return f"/assets/papers/{paper_id}/teaser.png"

    # Source 3: arXiv PDF thumbnail
    img_url = _fetch_arxiv_pdf_thumbnail(arxiv_id)
    if img_url:
        logger.debug(f"    Found PDF thumbnail: {img_url}")
        if download_image(img_url, dest_path):
            logger.info(f"    Downloaded from PDF thumbnail")
            return f"/assets/papers/{paper_id}/teaser.png"

    # Source 4: MinerU PDF parsing (extracts actual figures from PDF)
    # Requires MINERU_API_KEY environment variable
    logger.debug(f"    Trying MinerU PDF parsing...")
    if _extract_pdf_figures_mineru(arxiv_id, dest_path):
        logger.info(f"    Extracted Figure 1 via MinerU")
        return f"/assets/papers/{paper_id}/teaser.png"

    # Source 5: Local pdfimages embedded figure extraction (fallback)
    logger.debug(f"    Trying local PDF figure extraction...")
    if _extract_pdf_figures_local(arxiv_id, dest_path):
        logger.info(f"    Extracted Figure 1 via pdfimages")
        return f"/assets/papers/{paper_id}/teaser.png"

    logger.debug(f"    No teaser found for {paper_id}")
    return None


class _TeaserTimeout(Exception):
    pass


def _teaser_timeout_handler(signum, frame):
    raise _TeaserTimeout()


def main(retry_fallbacks: bool = True, workers: int = 1):
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    papers_path = DATA_DIR / "papers.yaml"
    if not papers_path.exists():
        logger.error(f"Papers file not found: {papers_path}")
        return

    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    if not isinstance(papers, list):
        logger.error("Invalid papers.yaml format")
        return

    logger.info(f"Fetching teasers for {len(papers)} papers...")
    success_count = 0
    metadata_changed = False
    save_interval = 10
    since_save = 0
    workers = max(1, workers)
    candidates = [paper for paper in papers if _should_fetch_teaser_preview(paper.get("preview", ""), retry_fallbacks=retry_fallbacks)]
    skip_count = len(papers) - len(candidates)

    def save_progress() -> None:
        papers_path.write_text(
            yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )

    signal.signal(signal.SIGALRM, _teaser_timeout_handler)

    logger.info(f"Retry fallbacks: {retry_fallbacks}; candidates: {len(candidates)}; skipped: {skip_count}; workers: {workers}")

    if workers == 1:
        for paper in candidates:
            try:
                signal.alarm(120)
                result = fetch_teaser_for_paper(paper)
                signal.alarm(0)
                if result:
                    paper["preview"] = result
                    _remove_teaser_fallback_warnings(paper)
                    success_count += 1
                    since_save += 1
                elif _is_teaser_fallback_preview(paper.get("preview", "")):
                    _mark_teaser_fallback_warning(paper, "real teaser fetch failed")
            except _TeaserTimeout:
                signal.alarm(0)
                logger.warning(f"    Timeout (120s) for {paper.get('id')}, skipping")
                if _is_teaser_fallback_preview(paper.get("preview", "")):
                    _mark_teaser_fallback_warning(paper, "timeout while fetching real teaser")
            except Exception as e:
                signal.alarm(0)
                logger.warning(f"    Error for {paper.get('id')}: {e}, skipping")
                if _is_teaser_fallback_preview(paper.get("preview", "")):
                    _mark_teaser_fallback_warning(paper, f"error while fetching real teaser: {e}")

            time.sleep(0.5)
            if since_save >= save_interval:
                save_progress()
                logger.info(f"  [checkpoint] saved {success_count} new teasers so far")
                since_save = 0
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(fetch_teaser_for_paper, paper): paper for paper in candidates}
            for future in as_completed(futures):
                paper = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    logger.warning(f"    Error for {paper.get('id')}: {e}, skipping")
                    if _is_teaser_fallback_preview(paper.get("preview", "")):
                        metadata_changed = _mark_teaser_fallback_warning(paper, f"error while fetching real teaser: {e}") or metadata_changed
                    continue
                if result:
                    paper["preview"] = result
                    _remove_teaser_fallback_warnings(paper)
                    success_count += 1
                    since_save += 1
                elif _is_teaser_fallback_preview(paper.get("preview", "")):
                    _mark_teaser_fallback_warning(paper, "real teaser fetch failed")
                if since_save >= save_interval:
                    save_progress()
                    logger.info(f"  [checkpoint] saved {success_count} new teasers so far")
                    since_save = 0

    fallback_count = 0
    for paper in papers:
        preview = paper.get("preview", "")
        if _is_teaser_fallback_preview(preview):
            fallback_count += 1
            metadata_changed = _mark_teaser_fallback_warning(
                paper,
                "final preview remains fallback; requires follow-up investigation",
            ) or metadata_changed
        else:
            metadata_changed = _remove_teaser_fallback_warnings(paper) or metadata_changed

    if fallback_count:
        logger.warning(
            "TEASER FALLBACK SUMMARY: %s papers still use fallback previews and require investigation.",
            fallback_count,
        )

    # === 图片本地化步骤 ===
    il_config = _load_image_localization_config()
    if il_config.get("enabled", True):
        logger.info("Image localization enabled, processing...")
        check_reachability = il_config.get("check_reachability", True)
        download_fallback = il_config.get("download_fallback", True)
        localize_count = 0

        for paper in papers:
            preview = paper.get("preview", "")
            if not preview:
                continue
            # 跳过 placeholder
            if "/assets/placeholder.svg" in preview:
                continue
            # 已经是本地路径
            if preview.startswith("/assets/"):
                continue
            # 只处理远程 URL
            if not (preview.startswith("http://") or preview.startswith("https://")):
                continue

            paper_id = paper.get("id", "")

            # 可达性检查
            if check_reachability:
                if not check_image_reachability(preview):
                    logger.debug(f"    Image unreachable for {paper_id}: {preview[:80]}")
                    if not download_fallback:
                        continue
                    # download_fallback=true 时，尝试下载
                else:
                    # 可达但 download_fallback 未开启，跳过
                    if not download_fallback:
                        continue

            # 下载到本地
            if localize_image(paper, ASSETS_DIR):
                localize_count += 1
                since_save += 1

            if since_save >= save_interval:
                papers_path.write_text(
                    yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
                    encoding="utf-8",
                )
                logger.info(f"  [checkpoint] saved {localize_count} localized images so far")
                since_save = 0

        if localize_count > 0:
            papers_path.write_text(
                yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
                encoding="utf-8",
            )
            logger.info(f"Localized {localize_count} images")

    if success_count > 0 or metadata_changed:
        save_progress()
        logger.info(f"Updated papers.yaml with {success_count} new teasers")

    logger.info(f"Done: {success_count} fetched, {skip_count} already have images, {len(papers) - success_count - skip_count} no image found")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch or refresh paper teaser images.")
    parser.add_argument(
        "--retry-fallbacks",
        action="store_true",
        default=True,
        help="Retry generated per-paper teaser.svg fallbacks and replace them with real PNGs when possible (default).",
    )
    parser.add_argument(
        "--no-retry-fallbacks",
        action="store_false",
        dest="retry_fallbacks",
        help="Only fetch missing/placeholder teasers; keep existing teaser.svg fallbacks.",
    )
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel teaser fetch workers.")
    args = parser.parse_args()
    main(retry_fallbacks=args.retry_fallbacks, workers=args.workers)
