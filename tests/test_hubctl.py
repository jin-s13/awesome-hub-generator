"""Tests for managed local hub controller."""

from pathlib import Path
from unittest.mock import Mock

import yaml

from scripts import hubctl


def write_hubs_yaml(path: Path, tmp_path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "hubs": [
                    {
                        "name": "awesome-test-hub",
                        "title": "Awesome Test Hub",
                        "path": str(tmp_path / "awesome-test-hub"),
                        "repo": "git@github.com:example/awesome-test-hub.git",
                        "branch": "main",
                        "site_url": "https://example.github.io/awesome-test-hub",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_load_hubs_resolves_configured_paths(tmp_path):
    config = tmp_path / "hubs.yaml"
    hub_dir = tmp_path / "awesome-test-hub"
    write_hubs_yaml(config, tmp_path)

    hubs = hubctl.load_hubs(config)

    assert len(hubs) == 1
    assert hubs[0].name == "awesome-test-hub"
    assert hubs[0].title == "Awesome Test Hub"
    assert hubs[0].path == hub_dir.resolve()
    assert hubs[0].branch == "main"


def test_select_hubs_defaults_to_all(tmp_path):
    config = tmp_path / "hubs.yaml"
    write_hubs_yaml(config, tmp_path)
    hubs = hubctl.load_hubs(config)

    assert hubctl.select_hubs(hubs, []) == hubs
    assert hubctl.select_hubs(hubs, ["awesome-test-hub"]) == hubs


def test_hub_status_reports_dirty_checkout(tmp_path):
    hub_dir = tmp_path / "awesome-test-hub"
    (hub_dir / ".git").mkdir(parents=True)
    hub = hubctl.ManagedHub(name="awesome-test-hub", path=hub_dir)
    run = Mock()
    run.side_effect = [
        Mock(stdout="main\n", returncode=0),
        Mock(stdout="abc123\n", returncode=0),
        Mock(stdout=" M data/papers.yaml\n", returncode=0),
    ]

    status = hubctl.hub_status(hub, run=run)

    assert status["state"] == "dirty"
    assert status["branch"] == "main"
    assert status["commit"] == "abc123"


def test_pull_hub_uses_fast_forward(tmp_path):
    hub_dir = tmp_path / "awesome-test-hub"
    (hub_dir / ".git").mkdir(parents=True)
    hub = hubctl.ManagedHub(name="awesome-test-hub", path=hub_dir, branch="main")
    run = Mock()
    run.side_effect = [
        Mock(stdout="", returncode=0),
        Mock(returncode=0),
    ]

    assert hubctl.pull_hub(hub, run=run) is True

    assert run.call_args_list[0].args[0] == [
        "git",
        "-C",
        str(hub_dir),
        "status",
        "--porcelain",
    ]
    assert run.call_args_list[1].args[0] == [
        "git",
        "-C",
        str(hub_dir),
        "pull",
        "--ff-only",
        "origin",
        "main",
    ]


def test_serve_hub_delegates_to_existing_script(tmp_path, monkeypatch):
    local_root = tmp_path / ".local"
    hub_dir = local_root / "awesome-test-hub"
    hub_dir.mkdir(parents=True)
    monkeypatch.setattr(hubctl, "ROOT", tmp_path)
    hub = hubctl.ManagedHub(name="awesome-test-hub", path=hub_dir)
    args = Mock(host="127.0.0.1", port=4327, skip_sync=True)
    run = Mock(return_value=Mock(returncode=0))

    assert hubctl.serve_hub(hub, args, run=run) == 0

    cmd = run.call_args.args[0]
    assert cmd[1:] == [
        str(tmp_path / "scripts" / "serve_hub.py"),
        "--hub",
        "awesome-test-hub",
        "--host",
        "127.0.0.1",
        "--port",
        "4327",
        "--skip-sync",
    ]


def test_update_hub_delegates_to_update_script(tmp_path, monkeypatch):
    local_root = tmp_path / ".local"
    hub_dir = local_root / "awesome-test-hub"
    hub_dir.mkdir(parents=True)
    monkeypatch.setattr(hubctl, "ROOT", tmp_path)
    hub = hubctl.ManagedHub(name="awesome-test-hub", path=hub_dir)
    args = Mock(
        search_days=14,
        init=False,
        skip_build=True,
        skip_teasers=False,
        skip_interpretations=True,
        skip_seed_expansion=False,
    )
    run = Mock(return_value=Mock(returncode=0))

    assert hubctl.update_hub(hub, args, run=run) == 0

    cmd = run.call_args.args[0]
    assert cmd[1:] == [
        str(tmp_path / "scripts" / "update.py"),
        "--hub",
        "awesome-test-hub",
        "--search-days",
        "14",
        "--skip-build",
        "--skip-interpretations",
    ]
