#!/usr/bin/env python3
"""
build.py — 全量构建入口

从零开始：
1. 读取 awesome.yaml 配置
2. 通过 arXiv API 搜索历史论文
3. LLM 分类并生成 data/papers.yaml
4. 从模板生成 Astro 网站
5. 构建网站
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

# Load .env file if present (so config_bridge/researcher can read ARK_API_KEY etc.)
_env_path = ROOT / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

def load_config(config_path: str = "awesome.yaml") -> dict:
    import yaml
    path = ROOT / config_path if not os.path.isabs(config_path) else Path(config_path)
    if not path.exists():
        print(f"[build] 错误: 未找到 {config_path}")
        sys.exit(1)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def render_template(src: Path, dst: Path, variables: dict) -> None:
    """渲染模板文件，替换 {{VAR}} 占位符"""
    if dst.is_dir():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    content = src.read_text(encoding="utf-8")
    for key, value in variables.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    dst.write_text(content, encoding="utf-8")


def copy_template(src_dir: Path, dst_dir: Path, variables: dict) -> None:
    """递归复制模板目录并渲染"""
    if dst_dir.exists():
        # Use subprocess for stubborn directories like node_modules
        subprocess.run(["rm", "-rf", str(dst_dir)], capture_output=True)
    for item in src_dir.rglob("*"):
        if item.is_file() and ".git" not in item.parts:
            rel = item.relative_to(src_dir)
            dst_file = dst_dir / rel
            # Skip binary files (images, etc.)
            binary_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf"}
            if item.suffix.lower() in binary_extensions:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst_file)
            else:
                render_template(item, dst_file, variables)


def split_papers_resources(data_dir: Path) -> None:
    """把 papers.yaml 中的非论文资源（博客/reddit/视频等）分离到 resources.yaml"""
    import yaml
    from url_classify import entry_is_paper, detect_resource_type

    papers_path = data_dir / "papers.yaml"
    resources_path = data_dir / "resources.yaml"
    if not papers_path.exists():
        return

    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8")) or []
    if not isinstance(papers, list):
        return

    existing_resources = []
    if resources_path.exists():
        existing_resources = yaml.safe_load(resources_path.read_text(encoding="utf-8")) or []
    existing_ids = {r.get("id") for r in existing_resources if isinstance(r, dict)}

    keep_papers = []
    new_resources = []
    for paper in papers:
        if entry_is_paper(paper):
            paper.pop("_type", None)
            paper.pop("resource_type", None)
            keep_papers.append(paper)
        else:
            if paper.get("id") in existing_ids:
                continue
            url = ""
            for v in (paper.get("links") or {}).values():
                if v:
                    url = str(v)
                    break
            rtype = paper.get("resource_type") or detect_resource_type(url)
            resource = {
                "id": paper.get("id", ""),
                "name": paper.get("title", "").strip("*"),
                "type": rtype,
                "category": paper.get("category", "Others"),
                "description": paper.get("_description") or "",
                "tags": paper.get("tags") or [],
                "links": paper.get("links") or {},
                "sources": paper.get("sources") or [],
            }
            if paper.get("year"):
                resource["year"] = paper["year"]
            new_resources.append(resource)

    if new_resources:
        all_resources = existing_resources + new_resources
        resources_path.write_text(
            yaml.dump(all_resources, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        print(f"[build] 分离 {len(new_resources)} 篇非论文资源到 resources.yaml")

    papers_path.write_text(
        yaml.dump(keep_papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"[build] papers.yaml 保留 {len(keep_papers)} 篇论文")


def filter_irrelevant_papers(data_dir: Path, config: dict) -> None:
    """过滤与 CAD 不相关的论文"""
    import yaml
    from relevance_filter import filter_papers

    papers_path = data_dir / "papers.yaml"
    if not papers_path.exists():
        return

    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8")) or []
    if not isinstance(papers, list) or not papers:
        return

    research = config.get("research", {})
    negative = research.get("negative_keywords", [])
    min_score = research.get("scoring", {}).get("filter_min_score", 5.0)

    relevant, removed = filter_papers(papers, negative, min_score)

    if removed:
        papers_path.write_text(
            yaml.dump(relevant, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        print(f"[build] 过滤 {len(removed)} 篇不相关论文，保留 {len(relevant)} 篇")
        for p in removed:
            print(f"[build]   - {(p.get('title') or '')[:60]}")
    else:
        print(f"[build] 无不相关论文需过滤 ({len(relevant)} 篇)")


def generate_site(config: dict, output_dir: Path) -> None:
    """从模板生成 Astro 网站到输出目录"""
    project = config.get("project", {})
    website = config.get("website", {})

    variables = {
        "PROJECT_NAME": project.get("name", "Awesome Research Hub"),
        "PROJECT_SLUG": project.get("name", "awesome-research-hub").lower().replace(" ", "-"),
        "PROJECT_DESCRIPTION": project.get("description", ""),
        "SITE_URL": project.get("site_url", "https://example.github.io/awesome-hub"),
        "GITHUB_URL": project.get("github_url", "https://github.com/example/awesome-hub"),
        "GENERATOR_REPO": project.get("generator_repo", "your-username/awesome-hub-generator"),
        "FOOTER_HTML": website.get("footer", "Built with awesome-hub-generator."),
    }

    template_dir = ROOT / "templates" / "astro-site"
    if not template_dir.exists():
        print(f"[build] 错误: 模板目录不存在 {template_dir}")
        sys.exit(1)

    print(f"[build] 生成网站到 {output_dir}")
    copy_template(template_dir, output_dir, variables)
    print("[build] 网站模板生成完成")


def build_site(output_dir: Path) -> None:
    """在输出目录中执行 npm build"""
    print("[build] 安装依赖并构建网站...")
    result = subprocess.run(["npm", "install"], cwd=str(output_dir), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[build] npm install 失败:\n{result.stderr}")
        return

    result = subprocess.run(["npm", "run", "build"], cwd=str(output_dir), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[build] npm build 失败:\n{result.stderr}")
        return
    print(f"[build] 网站构建完成，输出目录: {output_dir / 'dist'}")


def discover_and_ingest(config: dict, data_dir: Path = None) -> int:
    """
    自动发现 GitHub 上的 awesome 项目并吸纳数据。
    Returns: 吸纳的论文总数
    """
    if data_dir is None:
        data_dir = ROOT / ".local/data"
    research = config.get("research", {})
    auto = research.get("auto_discover", {})
    if not auto.get("enabled", True):
        print("[build] 自动发现已禁用，跳过")
        return 0

    keywords = research.get("keywords", [])
    if not keywords:
        return 0

    from discover_sources import GitHubDiscoverer
    from ingest_source import ingest_source, FormatDetector

    discoverer = GitHubDiscoverer()
    min_stars = auto.get("min_stars", 5)
    max_sources = auto.get("max_sources", 10)

    print(f"[build] Phase 1: 自动发现 GitHub awesome 项目 (keywords={keywords[:3]}...)")
    sources = discoverer.discover(keywords, min_stars, max_sources)

    if not sources:
        print("[build] 未发现上游 awesome 项目")
        return 0

    from sync import load_yaml, save_yaml, deduplicate

    root_data_dir = data_dir
    root_data_dir.mkdir(parents=True, exist_ok=True)
    papers_yaml = root_data_dir / "papers.yaml"
    existing = load_yaml(papers_yaml)

    # 同时提取 datasets/tools
    datasets_yaml = root_data_dir / "datasets.yaml"
    tools_yaml = root_data_dir / "tools.yaml"
    existing_datasets = load_yaml(datasets_yaml) if datasets_yaml.exists() else []
    existing_tools = load_yaml(tools_yaml) if tools_yaml.exists() else []

    total_ingested = 0
    for source in sources:
        print(f"\n[build]  处理上游源: {source.full_name}")

        readme = discoverer.fetch_readme(source)
        if not readme:
            print(f"[build]    跳过: 无法获取 README")
            continue

        repo_files = discoverer.list_repo_files(source)
        fmt = FormatDetector.detect(readme, repo_files)

        if fmt in ("yaml", "json"):
            # 查找数据文件
            data_files = [f for f in repo_files if f.endswith((".yaml", ".yml", ".json"))]
            if not data_files:
                print(f"[build]    跳过: 未找到数据文件")
                continue
            from ingest_source import YamlParser, JsonParser
            parser = YamlParser if fmt == "yaml" else JsonParser
            ingested = []
            for df in data_files:
                content = discoverer.fetch_file(source, df)
                if content:
                    ingested.extend(parser.parse(content, source.full_name))
        else:
            ingested = ingest_source(readme, repo_files, source.full_name)

        if not ingested:
            print(f"[build]    未解析到论文")
            continue

        # 预过滤：用 negative_keywords 排除明显不相关条目
        negative = research.get("negative_keywords", [])
        if negative:
            before = len(ingested)
            ingested = [
                e for e in ingested
                if not any(nk.lower() in " ".join([
                    e.get("title") or "", e.get("_description") or ""
                ]).lower() for nk in negative)
            ]
            if before != len(ingested):
                print(f"[build]    预过滤 {before - len(ingested)} 篇不相关条目")

        # 去重合并到现有数据
        merged, added = deduplicate(existing, ingested)
        existing = merged
        total_ingested += added
        print(f"[build]    吸纳 {added} 篇新论文 (共 {len(ingested)} 篇解析)")

        # 从上游 README 提取 datasets/tools 线索
        ds, tools = _extract_datasets_tools_from_readme(readme, source.full_name)
        existing_datasets.extend(ds)
        existing_tools.extend(tools)

    if total_ingested > 0:
        save_yaml(papers_yaml, existing)
        # 去重保存 datasets/tools
        _dedupe_and_save(datasets_yaml, existing_datasets, ["name"])
        _dedupe_and_save(tools_yaml, existing_tools, ["name"])

    print(f"[build] Phase 1 完成，共吸纳 {total_ingested} 篇论文")
    return total_ingested


def _extract_datasets_tools_from_readme(readme: str, repo: str):
    """从上游 README 中简单提取 datasets/tools 线索。"""
    import re
    datasets = []
    tools = []
    lines = readme.splitlines()
    section = None
    for line in lines:
        lower = line.lower().strip()
        if lower.startswith("#"):
            if "dataset" in lower:
                section = "dataset"
            elif "tool" in lower or "library" in lower or "software" in lower:
                section = "tool"
            else:
                section = None
            continue
        if section:
            m = re.match(r"\s*[-*]\s*\[(.+?)\]\((https?://[^\)]+)\)", line)
            if m:
                name, url = m.group(1).strip(), m.group(2).strip()
                item = {"name": name, "url": url, "source": repo}
                if section == "dataset":
                    datasets.append(item)
                else:
                    tools.append(item)
    return datasets, tools


def _dedupe_and_save(path, items, key_fields):
    """简单去重并保存到 YAML。"""
    from sync import save_yaml
    seen = set()
    result = []
    for item in items:
        key = tuple(item.get(k, "") for k in key_fields)
        if key not in seen:
            seen.add(key)
            result.append(item)
    save_yaml(path, result)
    print(f"[build] {path.name}: {len(result)} 条")


def download_and_interpret(config: dict) -> None:
    """下载论文 PDF 并生成解读文件（已弃用，由 researcher_adapter 替代）"""
    print("[build] 跳过 PDF 下载和解读生成（已弃用）")


def generate_readme_with_table(config: dict, output_dir: Path, data_dir: Path = None) -> None:
    """生成包含论文表格的 README.md，其中包含「解读」列"""
    import yaml

    if data_dir is None:
        data_dir = ROOT / ".local/data"
    papers_path = data_dir / "papers.yaml"
    papers = []
    if papers_path.exists():
        data = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
        papers = data if isinstance(data, list) else []

    # Sort: newest first, then by title
    papers.sort(key=lambda p: (-(p.get("year") or 0), p.get("title", "")))

    generator_repo = config.get("project", {}).get("generator_repo", "awesome-hub-generator")
    lines = [
        f"# {config['project']['name']}",
        "",
        config["project"].get("description", ""),
        "",
        f"- Papers: **{len(papers)}**",
        "- Last updated: auto-generated",
        "",
        f"> This site is automatically generated by [awesome-hub-generator](https://github.com/{generator_repo}).",
        "",
        "## Papers",
        "",
        "| Paper | Year | Venue | 解读 |",
        "|-------|------|-------|------|",
    ]

    for p in papers:
        title = p.get("title", "")
        year = p.get("year", "")
        venue = p.get("venue", "arXiv")
        links = p.get("links", {})
        paper_url = links.get("paper", "")
        paper_id = p.get("id", "")

        # Paper title with link
        if paper_url:
            paper_cell = f"[{title}]({paper_url})"
        else:
            paper_cell = title

        # 解读 column: link to interpretation file if exists
        interp_path = ROOT / "resource" / paper_id / "README.md"
        if interp_path.exists():
            interp_cell = f"[解读](./resource/{paper_id}/README.md)"
        else:
            interp_cell = ""

        lines.append(f"| {paper_cell} | {year} | {venue} | {interp_cell} |")

    lines.extend(["", "---", "", "*This README is auto-generated.*"])
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[build] README 已生成 ({len(papers)} 篇论文)")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="全量构建 awesome 页面")
    parser.add_argument("--config", default="awesome.yaml", help="配置文件路径")
    parser.add_argument("--output", default=".local/website", help="网站输出目录")
    parser.add_argument("--data-dir", default=".local/data", help="数据目录（产出物隔离，已 gitignore）")
    parser.add_argument("--skip-search", action="store_true", help="跳过 arXiv 搜索（仅重新生成网站）")
    parser.add_argument("--skip-researcher", action="store_true",
                        help="跳过 arxiv-daily-researcher（使用 arXiv API fallback）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 分类")
    parser.add_argument("--max-papers", type=int, default=0,
                        help="最大论文数（0=不限，实验建议 20）")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm build")
    parser.add_argument("--skip-discover", action="store_true", help="跳过自动发现上游 awesome 项目")
    parser.add_argument("--skip-download", action="store_true", help="跳过 PDF 下载和解读生成（已弃用）")
    parser.add_argument("--skip-teasers", action="store_true", help="跳过论文 teaser 图获取")
    parser.add_argument("--skip-interpretations", action="store_true", help="跳过论文解读生成")
    args = parser.parse_args()

    config = load_config(args.config)
    research = config.get("research", {})
    output_dir = (ROOT / args.output).resolve()
    data_dir = (ROOT / args.data_dir).resolve()

    # 测试隔离时通过环境变量传递 data_dir 给子脚本
    import os
    os.environ["HUB_DATA_DIR"] = str(data_dir)

    root_data_dir = data_dir
    root_data_dir.mkdir(parents=True, exist_ok=True)
    papers_yaml = root_data_dir / "papers.yaml"

    # Ensure datasets.yaml and tools.yaml exist
    for empty_file in ["datasets.yaml", "tools.yaml"]:
        ef = root_data_dir / empty_file
        if not ef.exists():
            ef.write_text("[]\n", encoding="utf-8")

    # Step 1: 自动发现并吸纳上游 awesome 项目数据（精选论文优先）
    if not args.skip_discover:
        discover_and_ingest(config, data_dir)

    # Step 2: 搜索 arXiv 补充最新论文
    if not args.skip_search:
        # Try researcher path first
        new_papers = []
        if not args.skip_researcher:
            try:
                from scripts.researcher_adapter import ResearcherAdapter

                print("[build] Running arxiv-daily-researcher via ResearcherAdapter...")
                adapter = ResearcherAdapter(config)
                result = adapter.run_daily_research()
                new_papers = adapter.convert_to_papers_yaml(result)
                print(f"[build] Researcher found {len(new_papers)} papers")
            except ImportError as e:
                print(f"[build] Researcher unavailable ({e}), falling back to arXiv API")
            except Exception as e:
                import traceback
                print(f"[build] Researcher failed ({type(e).__name__}: {e}), falling back to arXiv API")
                traceback.print_exc()

        # Fallback to arXiv API
        if not new_papers:
            from sync import search_arxiv, sync_papers

            keywords = research.get("keywords", [])
            categories = research.get("arxiv_categories", [])
            date_from = research.get("date_from", "")
            date_to = research.get("date_to", "")
            negative_keywords = research.get("negative_keywords", [])

            print(f"[build] Searching arXiv: keywords={keywords}, categories={categories}, from={date_from}")

            papers = search_arxiv(keywords, categories, date_from, date_to, max_results=args.max_papers or 500)
            if papers:
                added = sync_papers(papers, papers_yaml, source_repo="arxiv", skip_llm=args.skip_llm,
                                    max_papers=args.max_papers or None,
                                    negative_keywords=negative_keywords)
                print(f"[build] Added {added} papers from arXiv API")
            else:
                print("[build] No papers found from arXiv API")
        else:
            # Researcher path: merge with dedup
            from scripts.researcher_adapter import ResearcherAdapter
            from sync import load_yaml, save_yaml

            existing = load_yaml(papers_yaml)
            merged, added = ResearcherAdapter.deduplicate(existing, new_papers)
            save_yaml(papers_yaml, merged)
            print(f"[build] Added {added} new papers (total: {len(merged)})")

    # teaser 图默认写入模板 public/assets；测试隔离时写到 data_dir 同级
    os.environ.setdefault("HUB_ASSETS_DIR", str(data_dir.parent / "assets" / "papers"))

    # Step 2.5: 分离非论文资源到 resources.yaml
    split_papers_resources(data_dir)

    # Step 2.6: 过滤与 CAD 不相关的论文
    filter_irrelevant_papers(data_dir, config)

    # Step 3: 获取论文 teaser 图
    if not args.skip_teasers:
        try:
            from fetch_teasers import main as fetch_teasers
            print("[build] 获取论文 teaser 图...")
            fetch_teasers()
        except Exception as e:
            print(f"[build] Teaser 获取失败（非致命）: {e}")

    # Step 4: 生成论文解读（TLDR/reasoning/analysis）
    if not args.skip_interpretations:
        try:
            from generate_interpretations import main as gen_interp
            print("[build] 生成论文解读...")
            gen_interp()
        except Exception as e:
            print(f"[build] 解读生成失败（非致命）: {e}")

    # Step 5: 生成 Astro 网站
    generate_site(config, output_dir)

    # Step 5: 复制 data 到网站目录
    data_src = data_dir
    data_dst = output_dir / "data"
    if data_src.exists():
        shutil.copytree(data_src, data_dst, dirs_exist_ok=True)
        print(f"[build] 已复制数据到 {data_dst}")

    # Step 5.5: 复制 teaser 图到网站 public 目录
    assets_src = data_dir.parent / "assets" / "papers"
    assets_dst = output_dir / "public" / "assets" / "papers"
    if assets_src.exists():
        shutil.copytree(assets_src, assets_dst, dirs_exist_ok=True)
        print(f"[build] 已复制 teaser 图到 {assets_dst}")

    # Step 6: 复制 resource 到网站目录（供 Astro 访问解读文件）
    resource_src = ROOT / "resource"
    resource_dst = output_dir / "resource"
    if resource_src.exists():
        shutil.copytree(resource_src, resource_dst, dirs_exist_ok=True)
        print(f"[build] 已复制资源到 {resource_dst}")

    # Step 7: 复制 awesome.yaml 到输出目录
    shutil.copy2(ROOT / "awesome.yaml", output_dir / "awesome.yaml")

    # Step 8: 生成 README（含论文表格和「解读」列）
    generate_readme_with_table(config, output_dir, data_dir)

    # Step 9: 构建网站
    if not args.skip_build:
        build_site(output_dir)

    print(f"[build] 完成！网站已生成到 {output_dir}")
    print(f"[build] 运行 cd {output_dir} && npm run dev 本地预览")


if __name__ == "__main__":
    main()
