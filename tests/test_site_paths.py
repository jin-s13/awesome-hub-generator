"""Tests for site workspace path helpers."""

from scripts.site_paths import (
    default_assets_dir,
    default_data_dir,
    default_output_dir,
    default_resource_dir,
    hub_config_path,
    hub_workspace_dir,
    project_slug,
    resolve_config_path,
    resolve_user_path,
    workspace_dir,
)


def test_project_slug_prefers_explicit_slug():
    config = {"project": {"name": "Awesome CAD Hub", "slug": "awesome-cad-hub"}}

    assert project_slug(config) == "awesome-cad-hub"


def test_project_slug_normalizes_name():
    config = {"project": {"name": "Awesome World Model Hub!"}}

    assert project_slug(config) == "awesome-world-model-hub"


def test_generator_root_uses_scoped_local_workspace(tmp_path):
    config = {"project": {"name": "Awesome CAD Hub"}}

    assert workspace_dir(tmp_path, tmp_path, config) == tmp_path / ".local" / "awesome-cad-hub"
    assert default_data_dir(tmp_path, tmp_path, config) == tmp_path / ".local" / "awesome-cad-hub" / "data"
    assert default_assets_dir(tmp_path, tmp_path, config) == tmp_path / ".local" / "awesome-cad-hub" / "assets" / "papers"
    assert default_resource_dir(tmp_path, tmp_path, config) == tmp_path / ".local" / "awesome-cad-hub" / "resource"
    assert default_output_dir(tmp_path, tmp_path, config) == tmp_path / ".local" / "awesome-cad-hub" / "website"


def test_downstream_site_uses_repo_local_workspace(tmp_path):
    root = tmp_path / "awesome-hub-generator"
    site_dir = tmp_path / "awesome-cad-hub"
    root.mkdir()
    site_dir.mkdir()
    config = {"project": {"name": "Awesome CAD Hub"}}

    assert workspace_dir(root, site_dir, config) == site_dir / ".local"
    assert default_data_dir(root, site_dir, config) == site_dir / ".local" / "data"
    assert default_assets_dir(root, site_dir, config) == site_dir / ".local" / "assets" / "papers"
    assert default_resource_dir(root, site_dir, config) == site_dir / ".local" / "resource"
    assert default_output_dir(root, site_dir, config) == site_dir / ".local" / "website"


def test_resolve_user_path_keeps_explicit_paths_relative_to_site(tmp_path):
    site_dir = tmp_path / "site"
    default = tmp_path / "default"

    assert resolve_user_path(site_dir, "custom/data", default) == site_dir / "custom" / "data"
    assert resolve_user_path(site_dir, None, default) == default


def test_resolve_config_path_checks_site_before_root(tmp_path):
    root = tmp_path / "awesome-hub-generator"
    site_dir = tmp_path / "awesome-cad-hub"
    root.mkdir()
    site_dir.mkdir()
    (root / "awesome.yaml").write_text("project: {}\n", encoding="utf-8")
    (site_dir / "awesome.yaml").write_text("project: {name: Site}\n", encoding="utf-8")

    assert resolve_config_path(root, site_dir, "awesome.yaml") == site_dir / "awesome.yaml"


def test_resolve_config_path_falls_back_to_root(tmp_path):
    root = tmp_path / "awesome-hub-generator"
    site_dir = tmp_path / "awesome-cad-hub"
    root.mkdir()
    site_dir.mkdir()
    (root / "awesome.yaml").write_text("project: {}\n", encoding="utf-8")

    assert resolve_config_path(root, site_dir, "awesome.yaml") == root / "awesome.yaml"


def test_hub_config_path_uses_root_local_workspace(tmp_path):
    root = tmp_path / "awesome-hub-generator"
    root.mkdir()

    assert hub_workspace_dir(root, "awesome-cad-hub") == root / ".local" / "awesome-cad-hub"
    assert hub_config_path(root, "awesome-cad-hub") == root / ".local" / "awesome-cad-hub" / "awesome.yaml"
    assert resolve_config_path(root, root, hub="awesome-cad-hub") == root / ".local" / "awesome-cad-hub" / "awesome.yaml"
