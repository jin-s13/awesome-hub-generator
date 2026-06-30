"""Tests for local hub dev server helper."""

from pathlib import Path
from unittest.mock import Mock

from scripts.serve_hub import sync_hub_repo


def test_sync_hub_repo_pulls_clean_git_checkout(tmp_path):
    hub_dir = tmp_path / "awesome-world-model-hub"
    (hub_dir / ".git").mkdir(parents=True)
    run = Mock()
    run.side_effect = [
        Mock(stdout="", returncode=0),
        Mock(returncode=0),
    ]

    assert sync_hub_repo(hub_dir, remote="origin", branch="main", run=run)

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


def test_sync_hub_repo_skips_dirty_checkout(tmp_path):
    hub_dir = tmp_path / "awesome-world-model-hub"
    (hub_dir / ".git").mkdir(parents=True)
    run = Mock(return_value=Mock(stdout=" M data/papers.yaml\n", returncode=0))

    assert not sync_hub_repo(hub_dir, remote="origin", branch="main", run=run)

    run.assert_called_once()


def test_sync_hub_repo_skips_non_git_workspace(tmp_path):
    hub_dir = tmp_path / "awesome-world-model-hub"
    hub_dir.mkdir()
    run = Mock()

    assert not sync_hub_repo(hub_dir, remote="origin", branch="main", run=run)

    run.assert_not_called()

