"""Tests for hub repository README and AWESOME.md generation."""

from scripts.repo_readme import render_awesome, render_readme


def test_render_readme_links_web_ui_awesome_list_and_generator(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "datasets.yaml").write_text("[]\n", encoding="utf-8")
    (data_dir / "research_runs.yaml").write_text("[]\n", encoding="utf-8")
    config = {
        "project": {
            "name": "Awesome Test Hub",
            "description": "A curated test hub.",
            "site_url": "https://example.com/test",
            "generator_repo": "jin-s13/awesome-hub-generator",
        }
    }
    papers = [{"title": "Paper 1", "analysis": "Deep note", "openalex": {"id": "W1"}}]

    readme = render_readme(config, papers, data_dir)

    assert "# Awesome Test Hub" in readme
    assert "[中文 Web UI](https://example.com/test/zh/)" in readme
    assert "[Awesome](https://github.com/sindresorhus/awesome)" in readme
    assert "https://awesome.re/badge.svg" in readme
    assert "[Traditional Awesome List](./AWESOME.md)" in readme
    assert "[Generator](https://github.com/jin-s13/awesome-hub-generator)" in readme
    assert "main:data/" in readme
    assert "gh-pages" in readme
    assert "GH_TOKEN" in readme
    assert "GH_DISCOVERY_TOKEN" in readme
    assert "SEMANTIC_SCHOLAR_API_KEY" in readme
    assert "ARK_SURVEY_TIMEOUT_SECONDS" in readme
    assert "SEMANTIC_SCHOLAR_REQUEST_INTERVAL_SECONDS" in readme
    assert "GITHUB_TOKEN" not in readme
    assert "world models" not in readme.lower()


def test_render_awesome_outputs_traditional_paper_table(tmp_path):
    config = {
        "project": {
            "name": "Awesome Test Hub",
            "description": "A curated test hub.",
            "site_url": "https://example.com/test",
        }
    }
    papers = [
        {
            "title": "Paper 1",
            "year": 2026,
            "paper_type": ["method"],
            "tldr": "A short summary.",
            "links": {"paper": "https://arxiv.org/abs/1234.5678"},
            "score": {"read_first_score": 88.2},
        }
    ]

    awesome = render_awesome(config, papers, tmp_path / "data")

    assert "# Awesome Test Hub: Traditional Awesome List" in awesome
    assert "| Year | Score | Type | Paper | TLDR |" in awesome
    assert "[Paper 1](https://arxiv.org/abs/1234.5678)" in awesome
    assert "88.2" in awesome
