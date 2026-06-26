"""Site workspace path helpers.

The generator can be run in two modes:
- from the generator repo root, where multiple hubs should be isolated under
  .local/{project-slug}/
- from a downstream hub repo, where that repo's own .local/ is already scoped
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional


def project_slug(config: Dict[str, Any]) -> str:
    project = config.get("project", {}) if isinstance(config, dict) else {}
    raw = project.get("slug") or project.get("name") or "awesome-research-hub"
    slug = re.sub(r"[^a-z0-9]+", "-", str(raw).strip().lower()).strip("-")
    return slug or "awesome-research-hub"


def workspace_dir(root: Path, site_dir: Path, config: Dict[str, Any]) -> Path:
    root = root.resolve()
    site_dir = site_dir.resolve()
    if site_dir == root:
        return root / ".local" / project_slug(config)
    return site_dir / ".local"


def hub_workspace_dir(root: Path, hub: str) -> Path:
    return root.resolve() / ".local" / hub


def hub_config_path(root: Path, hub: str) -> Path:
    return hub_workspace_dir(root, hub) / "awesome.yaml"


def default_data_dir(root: Path, site_dir: Path, config: Dict[str, Any]) -> Path:
    return workspace_dir(root, site_dir, config) / "data"


def default_assets_dir(root: Path, site_dir: Path, config: Dict[str, Any]) -> Path:
    return workspace_dir(root, site_dir, config) / "assets" / "papers"


def default_output_dir(root: Path, site_dir: Path, config: Dict[str, Any]) -> Path:
    return workspace_dir(root, site_dir, config) / "website"


def default_resource_dir(root: Path, site_dir: Path, config: Dict[str, Any]) -> Path:
    return workspace_dir(root, site_dir, config) / "resource"


def resolve_user_path(site_dir: Path, value: Optional[str], default: Path) -> Path:
    if not value:
        return default.resolve()
    path = Path(value)
    if not path.is_absolute():
        path = site_dir / path
    return path.resolve()


def resolve_config_path(root: Path, site_dir: Path, config_path: Optional[str] = None, hub: Optional[str] = None) -> Path:
    if hub:
        return hub_config_path(root, hub).resolve()
    path = Path(config_path or "awesome.yaml")
    if path.is_absolute():
        return path.resolve()
    site_path = site_dir / path
    if site_path.exists():
        return site_path.resolve()
    return (root / path).resolve()


def template_config_path(root: Path) -> Path:
    return root.resolve() / "awesome.yaml.example"
