#!/usr/bin/env python3
"""
manage.py — 人工维护论文池

命令：
  list                              列出所有论文
  remove <id>                       从展示池删除论文（写入 overrides）
  add <arxiv_url_or_id>             手动添加论文（自动抓取 metadata）
  modify <id> --field value         修改论文字段（写入 overrides）
  show <id>                         查看论文详情
  stats                             显示统计信息
  import-candidates                 从展示池导入现有论文到 candidate 池
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SITE_DIR = Path.cwd()

for _env_path in [SITE_DIR / ".env", ROOT / ".env"]:
    if _env_path.exists():
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))
        break

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("manage")


def _load_yaml(path: Path) -> Any:
    import yaml
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_yaml(path: Path, data: Any):
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _get_papers_yaml(data_dir: Path) -> Path:
    return data_dir / "papers.yaml"


def _get_overrides_path(data_dir: Path) -> Path:
    return data_dir / "papers.overrides.yaml"


def _load_overrides(data_dir: Path) -> Dict:
    path = _get_overrides_path(data_dir)
    data = _load_yaml(path)
    if not data:
        return {"removed": [], "added": [], "modified": {}}
    data.setdefault("removed", [])
    data.setdefault("added", [])
    data.setdefault("modified", {})
    return data


def _save_overrides(data_dir: Path, overrides: Dict):
    _save_yaml(_get_overrides_path(data_dir), overrides)


def _extract_arxiv_id(input_str: str) -> str:
    """从 URL 或纯 ID 中提取 arXiv ID。"""
    m = re.search(r"(\d{4}\.\d{4,5})", input_str)
    if m:
        return m.group(1)
    return input_str.strip()


def cmd_list(args):
    """列出所有论文。"""
    papers = _load_yaml(_get_papers_yaml(args.data_dir)) or []
    for p in papers:
        category = p.get("category", "Others")
        year = p.get("year", "?")
        title = p.get("title", "")[:60]
        pid = p.get("id", "")
        print(f"  [{category:12s}] {year} {title:60s} ({pid})")
    print(f"\n总计: {len(papers)} 篇")


def cmd_remove(args):
    """从展示池删除论文（写入 overrides.removed）。"""
    overrides = _load_overrides(args.data_dir)
    if args.id not in overrides["removed"]:
        overrides["removed"].append(args.id)
        _save_overrides(args.data_dir, overrides)
        print(f"已标记删除: {args.id}")
    else:
        print(f"已存在于删除列表: {args.id}")


def cmd_add(args):
    """手动添加论文（自动抓取 arXiv metadata）。"""
    arxiv_id = _extract_arxiv_id(args.arxiv)

    # 从 arXiv 获取元数据
    from scripts.sync import search_arxiv
    try:
        papers = search_arxiv([], [], "", "", max_results=1, id_list=[arxiv_id])
    except Exception as e:
        print(f"arXiv API 错误: {e}")
        return

    if not papers:
        print(f"未找到 arXiv 论文: {arxiv_id}")
        return

    paper = papers[0]
    entry = {
        "id": f"manual-{arxiv_id}",
        "title": paper["title"],
        "authors": paper.get("authors", []),
        "abstract": paper.get("abstract", ""),
        "year": paper.get("published", "")[:4] or str(__import__("datetime").datetime.now().year),
        "venue": "arXiv",
        "category": args.category or "Others",
        "tags": [],
        "links": paper.get("links", {}),
        "preview": "/assets/placeholder.svg",
        "sources": [{"repo": "manual", "category": args.category or "Others"}],
        "arxiv_id": arxiv_id,
        "seed_expanded": False,
        "manually_curated": True,
    }

    overrides = _load_overrides(args.data_dir)
    overrides["added"].append(entry)
    _save_overrides(args.data_dir, overrides)
    print(f"已添加: {entry['title'][:60]} (arxiv: {arxiv_id})")


def cmd_modify(args):
    """修改论文字段（写入 overrides.modified）。"""
    overrides = _load_overrides(args.data_dir)
    if args.id not in overrides["modified"]:
        overrides["modified"][args.id] = {}

    # 解析 --field value 参数
    for field, value in args.fields:
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        elif value.startswith("[") and value.endswith("]"):
            value = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        overrides["modified"][args.id][field] = value

    _save_overrides(args.data_dir, overrides)
    print(f"已修改: {args.id}")
    for field, value in args.fields:
        print(f"  {field} = {value}")


def cmd_show(args):
    """查看论文详情。"""
    papers = _load_yaml(_get_papers_yaml(args.data_dir)) or []
    for p in papers:
        if p.get("id") == args.id:
            import yaml
            print(yaml.dump(p, allow_unicode=True, sort_keys=False, default_flow_style=False))
            return
    print(f"未找到论文: {args.id}")


def cmd_stats(args):
    """显示统计信息。"""
    papers = _load_yaml(_get_papers_yaml(args.data_dir)) or []
    overrides = _load_overrides(args.data_dir)

    from collections import Counter
    cats = Counter(p.get("category", "Others") for p in papers)
    years = Counter(p.get("year", "?") for p in papers)

    print(f"=== 展示池统计 ===")
    print(f"  总计: {len(papers)} 篇")
    print(f"\n  分类分布:")
    for cat, cnt in cats.most_common():
        print(f"    {cat:12s}: {cnt}")
    print(f"\n  年份分布:")
    for year, cnt in sorted(years.items(), key=lambda x: x[0] or 0, reverse=True)[:5]:
        print(f"    {year}: {cnt}")

    print(f"\n=== Overrides ===")
    print(f"  删除: {len(overrides['removed'])} 篇")
    print(f"  添加: {len(overrides['added'])} 篇")
    print(f"  修改: {len(overrides['modified'])} 篇")

    # Candidate 池统计
    db_path = args.data_dir.parent / "data" / "candidates.db"
    if db_path.exists():
        from scripts.candidate_pool import CandidatePool
        with CandidatePool(db_path) as pool:
            stats = pool.get_stats()
            print(f"\n=== Candidate 池 ===")
            print(f"  总计: {stats['total']}")
            print(f"  待检查: {stats['unchecked']}")
            print(f"  相关: {stats['relevant']}")
            print(f"  已晋升: {stats['promoted']}")
            print(f"  已扩展: {stats['seed_expanded']}")


def cmd_import_candidates(args):
    """从展示池导入现有论文到 candidate 池。"""
    from scripts.candidate_pool import CandidatePool

    papers = _load_yaml(_get_papers_yaml(args.data_dir)) or []
    db_path = args.data_dir / "candidates.db"
    with CandidatePool(db_path) as pool:
        added = 0
        for p in papers:
            if pool.add(p, source="existing"):
                # 标记为已晋升和已扩展
                aid = p.get("arxiv_id", "")
                if aid:
                    pool.mark_promoted(aid)
                    if p.get("seed_expanded"):
                        pool.mark_seed_expanded(aid)
                added += 1
        print(f"导入 {added}/{len(papers)} 篇论文到 candidate 池")


def main():
    parser = argparse.ArgumentParser(description="人工维护论文池")
    parser.add_argument("--data-dir", default=".local/data", help="数据目录")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出所有论文")

    p_remove = sub.add_parser("remove", help="删除论文")
    p_remove.add_argument("id", help="论文 ID")

    p_add = sub.add_parser("add", help="添加论文")
    p_add.add_argument("arxiv", help="arXiv URL 或 ID")
    p_add.add_argument("--category", default=None, help="分类")

    p_modify = sub.add_parser("modify", help="修改论文字段")
    p_modify.add_argument("id", help="论文 ID")
    p_modify.add_argument("fields", nargs="+", metavar="field=value",
                         help="字段=值（可多个）")

    p_show = sub.add_parser("show", help="查看论文详情")
    p_show.add_argument("id", help="论文 ID")

    sub.add_parser("stats", help="统计信息")

    sub.add_parser("import-candidates", help="导入现有论文到 candidate 池")

    args = parser.parse_args()
    args.data_dir = (SITE_DIR / args.data_dir).resolve()

    # 解析 modify 的 fields
    if args.command == "modify":
        parsed = []
        for item in args.fields:
            if "=" in item:
                field, value = item.split("=", 1)
                parsed.append((field.strip(), value.strip()))
        args.fields = parsed

    commands = {
        "list": cmd_list,
        "remove": cmd_remove,
        "add": cmd_add,
        "modify": cmd_modify,
        "show": cmd_show,
        "stats": cmd_stats,
        "import-candidates": cmd_import_candidates,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
