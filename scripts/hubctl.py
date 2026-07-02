#!/usr/bin/env python3
"""Manage local generated hub checkouts without using git submodules."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "hubs.yaml"

Run = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class ManagedHub:
    name: str
    path: Path
    repo: str = ""
    branch: str = "main"
    title: str = ""
    site_url: str = ""

    @property
    def display_name(self) -> str:
        return self.title or self.name


def _resolve_hub_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def load_hubs(config_path: Path = DEFAULT_CONFIG) -> list[ManagedHub]:
    """Load managed hub definitions from hubs.yaml."""
    if not config_path.exists():
        raise FileNotFoundError(f"managed hub config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    entries = raw.get("hubs", [])
    if not isinstance(entries, list):
        raise ValueError("hubs.yaml must contain a top-level 'hubs' list")

    hubs: list[ManagedHub] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"hubs[{index}] must be a mapping")
        name = str(entry.get("name") or "").strip()
        path_value = str(entry.get("path") or "").strip()
        if not name:
            raise ValueError(f"hubs[{index}] is missing name")
        if not path_value:
            raise ValueError(f"hubs[{index}] is missing path")
        if name in seen:
            raise ValueError(f"duplicate hub name: {name}")
        seen.add(name)
        hubs.append(
            ManagedHub(
                name=name,
                title=str(entry.get("title") or "").strip(),
                path=_resolve_hub_path(path_value),
                repo=str(entry.get("repo") or "").strip(),
                branch=str(entry.get("branch") or "main").strip() or "main",
                site_url=str(entry.get("site_url") or "").strip(),
            )
        )
    return hubs


def select_hubs(all_hubs: Sequence[ManagedHub], names: Sequence[str]) -> list[ManagedHub]:
    """Select requested hubs by name. Empty names means all hubs."""
    if not names:
        return list(all_hubs)
    by_name = {hub.name: hub for hub in all_hubs}
    missing = [name for name in names if name not in by_name]
    if missing:
        known = ", ".join(sorted(by_name)) or "<none>"
        raise KeyError(f"unknown hub(s): {', '.join(missing)}; known: {known}")
    return [by_name[name] for name in names]


def _run_git(
    hub: ManagedHub,
    args: Sequence[str],
    *,
    run: Run = subprocess.run,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    return run(
        ["git", "-C", str(hub.path), *args],
        text=True,
        capture_output=capture_output,
        check=check,
    )


def _git_output(hub: ManagedHub, args: Sequence[str], *, run: Run = subprocess.run) -> str:
    completed = _run_git(hub, args, run=run, capture_output=True, check=True)
    return str(completed.stdout or "").strip()


def is_git_checkout(hub: ManagedHub) -> bool:
    return (hub.path / ".git").exists()


def hub_status(hub: ManagedHub, *, run: Run = subprocess.run) -> dict[str, str]:
    """Return a compact status dict for one hub."""
    if not hub.path.exists():
        return {"name": hub.name, "state": "missing", "branch": "-", "commit": "-", "path": str(hub.path)}
    if not is_git_checkout(hub):
        return {"name": hub.name, "state": "not-git", "branch": "-", "commit": "-", "path": str(hub.path)}

    branch = _git_output(hub, ["rev-parse", "--abbrev-ref", "HEAD"], run=run)
    commit = _git_output(hub, ["rev-parse", "--short", "HEAD"], run=run)
    dirty = _git_output(hub, ["status", "--porcelain"], run=run)
    state = "dirty" if dirty else "clean"
    return {"name": hub.name, "state": state, "branch": branch, "commit": commit, "path": str(hub.path)}


def print_status(hubs: Iterable[ManagedHub], *, run: Run = subprocess.run) -> None:
    rows = [hub_status(hub, run=run) for hub in hubs]
    if not rows:
        print("No hubs configured.")
        return
    print(f"{'Hub':30} {'State':10} {'Branch':12} {'Commit':10} Path")
    print(f"{'-' * 30} {'-' * 10} {'-' * 12} {'-' * 10} {'-' * 20}")
    for row in rows:
        print(f"{row['name'][:30]:30} {row['state'][:10]:10} {row['branch'][:12]:12} {row['commit'][:10]:10} {row['path']}")


def ensure_clean(hub: ManagedHub, *, run: Run = subprocess.run) -> bool:
    if not is_git_checkout(hub):
        print(f"[hubctl] skip {hub.name}: not a git checkout at {hub.path}", file=sys.stderr)
        return False
    dirty = _git_output(hub, ["status", "--porcelain"], run=run)
    if dirty:
        print(f"[hubctl] skip {hub.name}: local changes exist", file=sys.stderr)
        print(dirty, file=sys.stderr)
        return False
    return True


def pull_hub(hub: ManagedHub, *, run: Run = subprocess.run) -> bool:
    if not ensure_clean(hub, run=run):
        return False
    print(f"[hubctl] pull {hub.name}: origin/{hub.branch}")
    _run_git(hub, ["pull", "--ff-only", "origin", hub.branch], run=run, check=True)
    return True


def push_hub(hub: ManagedHub, *, run: Run = subprocess.run) -> bool:
    if not ensure_clean(hub, run=run):
        return False
    print(f"[hubctl] push {hub.name}: origin {hub.branch}")
    _run_git(hub, ["push", "origin", hub.branch], run=run, check=True)
    return True


def _local_hub_name(hub: ManagedHub) -> str:
    local_root = (ROOT / ".local").resolve()
    try:
        relative = hub.path.resolve().relative_to(local_root)
    except ValueError as exc:
        raise ValueError(f"{hub.name} must live under .local/ to use serve/update: {hub.path}") from exc
    if len(relative.parts) != 1:
        raise ValueError(f"{hub.name} must be a direct child of .local/: {hub.path}")
    return relative.parts[0]


def serve_hub(hub: ManagedHub, args: argparse.Namespace, *, run: Run = subprocess.run) -> int:
    hub_name = _local_hub_name(hub)
    cmd = [sys.executable, str(ROOT / "scripts" / "serve_hub.py"), "--hub", hub_name, "--host", args.host]
    if args.port:
        cmd.extend(["--port", str(args.port)])
    if args.skip_sync:
        cmd.append("--skip-sync")
    print(f"[hubctl] serve {hub.name}")
    completed = run(cmd, cwd=str(ROOT), check=False)
    return int(completed.returncode or 0)


def update_hub(hub: ManagedHub, args: argparse.Namespace, *, run: Run = subprocess.run) -> int:
    hub_name = _local_hub_name(hub)
    cmd = [sys.executable, str(ROOT / "scripts" / "update.py"), "--hub", hub_name]
    if args.search_days is not None:
        cmd.extend(["--search-days", str(args.search_days)])
    for flag in ("init", "skip_build", "skip_teasers", "skip_interpretations", "skip_seed_expansion"):
        if getattr(args, flag, False):
            cmd.append("--" + flag.replace("_", "-"))
    print(f"[hubctl] update {hub.name}")
    completed = run(cmd, cwd=str(ROOT), check=False)
    return int(completed.returncode or 0)


def list_hubs(hubs: Sequence[ManagedHub]) -> None:
    if not hubs:
        print("No hubs configured.")
        return
    for hub in hubs:
        site = f" ({hub.site_url})" if hub.site_url else ""
        print(f"{hub.name}: {hub.path}{site}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage local generated hub checkouts")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="managed hubs YAML path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List configured hubs")
    list_parser.add_argument("hubs", nargs="*", help="Optional hub names")

    status_parser = subparsers.add_parser("status", help="Show git status for configured hubs")
    status_parser.add_argument("hubs", nargs="*", help="Optional hub names")

    pull_parser = subparsers.add_parser("pull", help="Fast-forward pull configured hubs")
    pull_parser.add_argument("hubs", nargs="*", help="Optional hub names; defaults to all")

    push_parser = subparsers.add_parser("push", help="Push configured hubs")
    push_parser.add_argument("hubs", nargs="*", help="Optional hub names; defaults to all")

    serve_parser = subparsers.add_parser("serve", help="Serve a local hub website")
    serve_parser.add_argument("hub", help="Hub name")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Astro dev server host")
    serve_parser.add_argument("--port", type=int, default=None, help="Astro dev server port")
    serve_parser.add_argument("--skip-sync", action="store_true", help="Skip git pull before serving")

    update_parser = subparsers.add_parser("update", help="Run the daily update pipeline for a local hub")
    update_parser.add_argument("hub", help="Hub name")
    update_parser.add_argument("--search-days", type=int, default=None, help="Override daily search window")
    update_parser.add_argument("--init", action="store_true", help="Run update.py init mode")
    update_parser.add_argument("--skip-build", action="store_true", help="Skip website build")
    update_parser.add_argument("--skip-teasers", action="store_true", help="Skip teaser fetching")
    update_parser.add_argument("--skip-interpretations", action="store_true", help="Skip LLM interpretation refresh")
    update_parser.add_argument("--skip-seed-expansion", action="store_true", help="Skip seed reference expansion")

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        all_hubs = load_hubs(Path(args.config))
        if args.command in {"list", "status", "pull", "push"}:
            selected = select_hubs(all_hubs, args.hubs)
        else:
            selected = select_hubs(all_hubs, [args.hub])
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"[hubctl] error: {exc}", file=sys.stderr)
        return 1

    try:
        if args.command == "list":
            list_hubs(selected)
            return 0
        if args.command == "status":
            print_status(selected)
            return 0
        if args.command == "pull":
            ok = [pull_hub(hub) for hub in selected]
            return 0 if all(ok) else 1
        if args.command == "push":
            ok = [push_hub(hub) for hub in selected]
            return 0 if all(ok) else 1
        if args.command == "serve":
            return serve_hub(selected[0], args)
        if args.command == "update":
            return update_hub(selected[0], args)
    except subprocess.CalledProcessError as exc:
        print(f"[hubctl] command failed with exit code {exc.returncode}", file=sys.stderr)
        return int(exc.returncode or 1)
    except ValueError as exc:
        print(f"[hubctl] error: {exc}", file=sys.stderr)
        return 1

    print(f"[hubctl] error: unknown command {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
