"""Tests for local hub initialization."""

from unittest.mock import patch

import pytest

from scripts.init_hub import init_hub, render_config_template, title_from_name


def test_title_from_name_handles_common_acronyms():
    assert title_from_name("awesome-cad-hub") == "Awesome CAD Hub"
    assert title_from_name("awesome-ai-agent-hub") == "Awesome AI Agent Hub"


def test_render_config_template_rewrites_project_fields():
    content = (
        'project:\n'
        '  name: "Awesome CAD Hub"\n'
        '  description: "Old description."\n'
        '  github_url: "https://github.com/jin-s13/awesome-cad-hub"\n'
    )

    rendered = render_config_template(content, "awesome-test-hub", "Awesome Test Hub", "New description.")

    assert 'name: "Awesome Test Hub"' in rendered
    assert 'description: "New description."' in rendered
    assert "awesome-test-hub" in rendered


def test_render_config_template_enables_ai4cad_awesome_discovery():
    content = (
        'project:\n'
        '  name: "Awesome CAD Hub"\n'
        'research:\n'
        '  sources:\n'
        '    arxiv: true\n'
        '    upstream_awesome: false\n'
        '  upstream_awesome:\n'
        '    repos: []\n'
        '    auto_discover: false\n'
        '  auto_discover:\n'
        '    enabled: false\n'
        '    max_sources: 3\n'
        '  candidate_pool:\n'
        '    promote_batch_size: 20\n'
    )

    rendered = render_config_template(content, "awesome-ai4cad-hub", "Awesome AI4CAD Hub", "")

    assert "    upstream_awesome: true\n" in rendered
    assert "    auto_discover: true\n" in rendered
    assert "      - \"BunnySoCrazy/Awesome-Neural-CAD\"\n" in rendered
    assert "    enabled: true\n" in rendered
    assert "    max_sources: 10\n" in rendered
    assert "    promote_batch_size: 300\n" in rendered


def test_init_hub_creates_workspace(tmp_path):
    template = tmp_path / "awesome.yaml.example"
    template.write_text(
        'project:\n'
        '  name: "Awesome CAD Hub"\n'
        '  description: "A curated hub."\n'
        '  github_url: "https://github.com/jin-s13/awesome-cad-hub"\n',
        encoding="utf-8",
    )

    with patch("scripts.init_hub.ROOT", tmp_path):
        hub_dir = init_hub("awesome-test-hub", "Awesome Test Hub", "Test hub.")

    assert hub_dir == tmp_path / ".local" / "awesome-test-hub"
    assert (hub_dir / "awesome.yaml").exists()
    assert (hub_dir / "data" / "papers.yaml").read_text(encoding="utf-8") == "[]\n"
    assert (hub_dir / "assets" / "papers").is_dir()
    assert (hub_dir / "resource").is_dir()
    assert (hub_dir / "website").is_dir()
    assert 'name: "Awesome Test Hub"' in (hub_dir / "awesome.yaml").read_text(encoding="utf-8")


def test_init_hub_refuses_existing_config_without_force(tmp_path):
    (tmp_path / "awesome.yaml.example").write_text('project:\n  name: "Awesome CAD Hub"\n', encoding="utf-8")
    config = tmp_path / ".local" / "awesome-test-hub" / "awesome.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("project: {}\n", encoding="utf-8")

    with patch("scripts.init_hub.ROOT", tmp_path):
        with pytest.raises(SystemExit):
            init_hub("awesome-test-hub")
