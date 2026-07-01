"""Tests for downstream site initialization."""

from scripts.init_site import init_site


def test_init_site_gitignore_excludes_github_discovery_cache(tmp_path):
    init_site(
        "awesome-test-hub",
        "Awesome Test Hub",
        str(tmp_path / "awesome-test-hub"),
        "A test hub.",
    )

    gitignore = (
        tmp_path / "awesome-test-hub" / "awesome-test-hub" / ".gitignore"
    ).read_text(encoding="utf-8")

    assert "data/github_discovery_cache.json" in gitignore
