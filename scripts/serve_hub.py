#!/usr/bin/env python3
"""Sync a local hub checkout, then start its Astro dev server."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]

Run = Callable[..., subprocess.CompletedProcess]


def sync_hub_repo(
    hub_dir: Path,
    *,
    remote: str = "origin",
    branch: str = "main",
    run: Run = subprocess.run,
) -> bool:
    """Fast-forward a local hub repo when it is safe to do so.

    Returns True only when a pull command was attempted and succeeded. Dirty or
    non-git workspaces are intentionally skipped so local edits are not touched.
    """
    hub_dir = hub_dir.resolve()
    if not (hub_dir / ".git").exists():
        print(f"[serve-hub] sync skipped: {hub_dir} is not a git checkout")
        return False

    status = run(
        ["git", "-C", str(hub_dir), "status", "--porcelain"],
        text=True,
        capture_output=True,
        check=True,
    )
    if status.stdout.strip():
        print(f"[serve-hub] sync skipped: local changes exist in {hub_dir}")
        print(status.stdout.rstrip())
        return False

    print(f"[serve-hub] syncing {hub_dir} from {remote}/{branch} ...")
    run(
        ["git", "-C", str(hub_dir), "pull", "--ff-only", remote, branch],
        check=True,
    )
    return True


def start_dev_server(
    website_dir: Path,
    *,
    host: str,
    port: int | None,
    run: Run = subprocess.run,
) -> int:
    if not website_dir.exists():
        print(f"[serve-hub] error: website directory not found: {website_dir}", file=sys.stderr)
        return 1

    cmd: list[str] = ["npm", "run", "dev", "--", "--host", host]
    if port:
        cmd.extend(["--port", str(port)])
    print(f"[serve-hub] starting dev server in {website_dir}")
    completed = run(cmd, cwd=str(website_dir), check=False)
    return int(completed.returncode or 0)


def ensure_node_dependencies(website_dir: Path, *, run: Run = subprocess.run) -> None:
    """Install website dependencies when render-only regenerated the site."""
    astro_bin = website_dir / "node_modules" / ".bin" / "astro"
    if astro_bin.exists():
        return
    if not (website_dir / "package-lock.json").exists():
        raise FileNotFoundError(f"package-lock.json not found in {website_dir}")
    print(f"[serve-hub] installing website dependencies in {website_dir}")
    run(["npm", "ci"], cwd=str(website_dir), check=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步本地 hub 后启动 Astro dev server")
    parser.add_argument("--hub", required=True, help="本地 hub 名称，如 awesome-world-model-hub")
    parser.add_argument("--remote", default="origin", help="git remote 名称，默认 origin")
    parser.add_argument("--branch", default="main", help="同步分支，默认 main")
    parser.add_argument("--host", default="127.0.0.1", help="Astro dev server host")
    parser.add_argument("--port", type=int, default=None, help="Astro dev server port")
    parser.add_argument("--skip-sync", action="store_true", help="跳过启动前 git pull")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    hub_dir = ROOT / ".local" / args.hub
    if not hub_dir.exists():
        print(f"[serve-hub] error: hub not found: {hub_dir}", file=sys.stderr)
        print(f"[serve-hub] initialize it first: python scripts/init_hub.py --name {args.hub}", file=sys.stderr)
        return 1

    if not args.skip_sync:
        try:
            sync_hub_repo(hub_dir, remote=args.remote, branch=args.branch)
        except subprocess.CalledProcessError as exc:
            print(f"[serve-hub] sync failed with exit code {exc.returncode}; continuing to local dev server", file=sys.stderr)

    env = os.environ.copy()
    env.setdefault("HUB_DATA_DIR", str(hub_dir / "data"))
    env.setdefault("HUB_ASSETS_DIR", str(hub_dir / "assets" / "papers"))
    env.setdefault("HUB_RESOURCE_DIR", str(hub_dir / "resource"))
    env.setdefault("HUB_CONFIG_PATH", str(hub_dir / "awesome.yaml"))
    os.environ.update(env)
    website_dir = hub_dir / "website"
    try:
        ensure_node_dependencies(website_dir)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"[serve-hub] dependency install failed: {exc}", file=sys.stderr)
        return 1
    return start_dev_server(website_dir, host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
