#!/usr/bin/env python3
"""
update.py — 每日增量更新入口

1. 运行 arxiv-daily-researcher 的 daily_research 模式
2. 解析输出报告，提取新论文
3. 去重合并到 data/papers.yaml
4. 重新构建网站
"""
from __future__ import annotations

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_config() -> dict:
    import yaml
    config_path = ROOT / "awesome.yaml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def run_arxiv_researcher(config: dict) -> bool:
    """运行 arxiv-daily-researcher 的 daily_research 模式"""
    researcher_dir = ROOT / "arxiv-daily-researcher"
    if not researcher_dir.exists():
        print("[update] 未找到 arxiv-daily-researcher submodule，跳过")
        return False

    research = config.get("research", {})
    keywords = research.get("keywords", [])
    search_days = research.get("daily_search_days", 3)

    # 确保 .env 存在
    env_path = researcher_dir / ".env"
    if not env_path.exists():
        # 从父项目环境变量创建
        env_vars = {k: v for k, v in os.environ.items() if k.startswith("ARK_")}
        if env_vars:
            env_content = "\n".join(f"{k}={v}" for k, v in env_vars.items())
            env_path.write_text(env_content, encoding="utf-8")
            print("[update] 已创建 arxiv-daily-researcher/.env")

    print(f"[update] 运行 arxiv-daily-researcher (daily_research 模式)...")
    result = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(researcher_dir),
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        print(f"[update] arxiv-daily-researcher 运行失败:\n{result.stderr[:500]}")
        return False

    print("[update] arxiv-daily-researcher 运行完成")
    return True


def parse_researcher_output(config: dict) -> list:
    """解析 arxiv-daily-researcher 的输出报告，提取论文列表"""
    researcher_dir = ROOT / "arxiv-daily-researcher"
    reports_dir = researcher_dir / "data" / "reports" / "daily_research"

    if not reports_dir.exists():
        print(f"[update] 未找到报告目录: {reports_dir}")
        return []

    papers = []
    # 遍历所有 markdown 报告
    for md_file in reports_dir.rglob("*.md"):
        if md_file.name == "README.md":
            continue
        content = md_file.read_text(encoding="utf-8")
        # 解析 markdown 中的论文条目
        # arxiv-daily-researcher 输出格式：每篇论文有标题、链接、评分等
        entries = re.findall(
            r"\|\s*\[([^\]]+)\]\(([^\)]+)\)\s*\|\s*([^|]+)\s*\|\s*([\d.]+)\s*\|",
            content,
        )
        for title, url, summary, score in entries:
            if "arxiv.org" in url:
                papers.append({
                    "title": title.strip(),
                    "links": {"paper": url.strip()},
                    "abstract": summary.strip(),
                    "score": float(score),
                })

    print(f"[update] 从报告解析到 {len(papers)} 篇论文")
    return papers


def update_from_arxiv_api(config: dict) -> list:
    """直接从 arXiv API 获取最新论文（作为 fallback）"""
    from sync import search_arxiv

    research = config.get("research", {})
    keywords = research.get("keywords", [])
    categories = research.get("arxiv_categories", [])
    search_days = research.get("daily_search_days", 3)

    date_from = (datetime.now() - timedelta(days=search_days)).strftime("%Y%m%d")
    date_to = datetime.now().strftime("%Y%m%d")

    print(f"[update] 从 arXiv API 获取最近 {search_days} 天的论文...")
    papers = search_arxiv(keywords, categories, date_from, date_to, max_results=200)
    return papers


def main():
    import argparse
    import re
    parser = argparse.ArgumentParser(description="每日增量更新")
    parser.add_argument("--config", default="awesome.yaml", help="配置文件路径")
    parser.add_argument("--output", default="output/website", help="网站输出目录")
    parser.add_argument("--skip-researcher", action="store_true", help="跳过 arxiv-daily-researcher")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 分类")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm build")
    args = parser.parse_args()

    config = load_config()
    output_dir = (ROOT / args.output).resolve()

    # Step 1: 尝试运行 arxiv-daily-researcher
    new_papers = []
    if not args.skip_researcher:
        run_arxiv_researcher(config)
        new_papers = parse_researcher_output(config)

    # Step 2: 如果没有结果，直接从 arXiv API 获取
    if not new_papers:
        print("[update] 使用 arXiv API 作为数据源")
        new_papers = update_from_arxiv_api(config)

    # Step 3: 同步到 YAML
    if new_papers:
        from sync import sync_papers
        papers_yaml = output_dir / "data" / "papers.yaml"
        papers_yaml.parent.mkdir(parents=True, exist_ok=True)

        # 如果已有数据，先复制过来
        existing_data = ROOT / "data" / "papers.yaml"
        if existing_data.exists() and not papers_yaml.exists():
            papers_yaml.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(existing_data, papers_yaml)

        added = sync_papers(new_papers, papers_yaml, source_repo="arxiv", skip_llm=args.skip_llm)
        print(f"[update] 新增 {added} 篇论文")
    else:
        print("[update] 未发现新论文")

    # Step 4: 重新构建网站
    if not args.skip_build:
        from build import generate_site, build_site
        generate_site(config, output_dir)

        # 复制 data 到网站目录
        data_src = ROOT / "data"
        data_dst = output_dir / "data"
        if data_src.exists():
            import shutil
            shutil.copytree(data_src, data_dst, dirs_exist_ok=True)

        build_site(output_dir)

    print(f"[update] 完成！")


if __name__ == "__main__":
    main()
