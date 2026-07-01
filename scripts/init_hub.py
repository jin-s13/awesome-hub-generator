#!/usr/bin/env python3
"""Initialize a local hub workspace under .local/{hub}.

This is for generator-repo development, where multiple hubs can live side by
side without turning the generator root into a concrete hub instance.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def title_from_name(name: str) -> str:
    words = re.sub(r"[^A-Za-z0-9]+", " ", name).strip().split()
    return " ".join(word.upper() if word.lower() in {"ai", "cad"} else word.capitalize() for word in words)


def _set_yaml_value_in_block(content: str, block_header: str, key: str, value: str) -> str:
    lines = content.splitlines(keepends=True)
    header_indent = None
    in_block = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if stripped == block_header:
            header_indent = indent
            in_block = True
            continue
        if in_block and header_indent is not None and indent <= header_indent:
            break
        if in_block and stripped.startswith(f"{key}:"):
            prefix = line[:indent]
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"{prefix}{key}: {value}{newline}"
            break
    return "".join(lines)


def _replace_empty_yaml_list_in_block(content: str, block_header: str, key: str, values: list[str]) -> str:
    lines = content.splitlines(keepends=True)
    header_indent = None
    in_block = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if stripped == block_header:
            header_indent = indent
            in_block = True
            continue
        if in_block and header_indent is not None and indent <= header_indent:
            break
        if in_block and stripped == f"{key}: []":
            prefix = line[:indent]
            newline = "\n" if line.endswith("\n") else ""
            replacement = [f"{prefix}{key}:{newline}"]
            replacement.extend(f"{prefix}  - \"{value}\"{newline}" for value in values)
            lines[index:index + 1] = replacement
            break
    return "".join(lines)


def apply_domain_presets(content: str, name: str, title: str) -> str:
    """Apply small source presets for known hub domains."""
    domain = f"{name} {title}".lower()
    if "ai4cad" not in domain and "ai for cad" not in domain:
        return content
    content = _set_yaml_value_in_block(content, "sources:", "upstream_awesome", "true")
    content = _replace_empty_yaml_list_in_block(
        content,
        "upstream_awesome:",
        "repos",
        ["BunnySoCrazy/Awesome-Neural-CAD"],
    )
    content = _set_yaml_value_in_block(content, "upstream_awesome:", "auto_discover", "true")
    content = _set_yaml_value_in_block(content, "auto_discover:", "enabled", "true")
    content = _set_yaml_value_in_block(content, "auto_discover:", "max_sources", "10")
    content = _set_yaml_value_in_block(content, "candidate_pool:", "promote_batch_size", "300")
    return content


def render_config_template(content: str, name: str, title: str, description: str) -> str:
    rendered = content.replace("Awesome CAD Hub", title)
    rendered = rendered.replace("awesome-cad-hub", name)
    if description:
        rendered = re.sub(
            r'description:\s*".*?"',
            f'description: "{description}"',
            rendered,
            count=1,
        )
    rendered = apply_domain_presets(rendered, name, title)
    return rendered


def init_hub(name: str, title: str = "", description: str = "", force: bool = False) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        print("[init-hub] 错误: --name 只能包含小写字母、数字和连字符")
        sys.exit(1)

    title = title or title_from_name(name)
    hub_dir = ROOT / ".local" / name
    config_path = hub_dir / "awesome.yaml"
    template_path = ROOT / "awesome.yaml.example"

    if not template_path.exists():
        print(f"[init-hub] 错误: 未找到模板 {template_path}")
        sys.exit(1)
    if config_path.exists() and not force:
        print(f"[init-hub] 错误: 配置已存在: {config_path}")
        print("[init-hub] 如需覆盖，请加 --force")
        sys.exit(1)

    for subdir in ("data", "assets/papers", "resource", "website"):
        (hub_dir / subdir).mkdir(parents=True, exist_ok=True)

    for name_ in ("papers.yaml", "resources.yaml", "datasets.yaml", "tools.yaml"):
        data_file = hub_dir / "data" / name_
        if not data_file.exists():
            data_file.write_text("[]\n", encoding="utf-8")

    content = template_path.read_text(encoding="utf-8")
    config_path.write_text(render_config_template(content, name, title, description), encoding="utf-8")
    print(f"[init-hub] 已初始化: {hub_dir}")
    print(f"[init-hub] 配置文件: {config_path}")
    print(f"[init-hub] 构建命令: python scripts/build.py --hub {name}")
    return hub_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化本地 .local/{hub} 工作区")
    parser.add_argument("--name", required=True, help="hub 名称，如 awesome-cad-hub")
    parser.add_argument("--title", default="", help="站点标题，如 Awesome CAD Hub")
    parser.add_argument("--description", default="", help="站点描述")
    parser.add_argument("--force", action="store_true", help="覆盖已有 awesome.yaml")
    args = parser.parse_args()

    init_hub(args.name, args.title, args.description, args.force)


if __name__ == "__main__":
    main()
