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

def load_config() -> dict:
    import yaml
    config_path = ROOT / "awesome.yaml"
    if not config_path.exists():
        print("[build] 错误: 未找到 awesome.yaml")
        sys.exit(1)
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


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
        shutil.rmtree(dst_dir)
    for item in src_dir.rglob("*"):
        if item.is_file() and ".git" not in item.parts:
            rel = item.relative_to(src_dir)
            dst_file = dst_dir / rel
            render_template(item, dst_file, variables)


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
        "GENERATOR_REPO": "your-username/awesome-hub-generator",
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


def discover_and_ingest(config: dict) -> int:
    """
    自动发现 GitHub 上的 awesome 项目并吸纳数据。
    Returns: 吸纳的论文总数
    """
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

    print(f"[build] Phase 2: 自动发现 GitHub awesome 项目 (keywords={keywords[:3]}...)")
    sources = discoverer.discover(keywords, min_stars, max_sources)

    if not sources:
        print("[build] 未发现上游 awesome 项目")
        return 0

    from sync import load_yaml, save_yaml, deduplicate

    root_data_dir = ROOT / "data"
    root_data_dir.mkdir(parents=True, exist_ok=True)
    papers_yaml = root_data_dir / "papers.yaml"
    existing = load_yaml(papers_yaml)

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

        # 去重合并到现有数据
        merged, added = deduplicate(existing, ingested)
        existing = merged
        total_ingested += added
        print(f"[build]    吸纳 {added} 篇新论文 (共 {len(ingested)} 篇解析)")

    if total_ingested > 0:
        save_yaml(papers_yaml, existing)
        # 确保 datasets.yaml 和 tools.yaml 存在
        for empty_file in ["datasets.yaml", "tools.yaml"]:
            ef = root_data_dir / empty_file
            if not ef.exists():
                ef.write_text("[]\n", encoding="utf-8")

    print(f"[build] Phase 2 完成，共吸纳 {total_ingested} 篇论文")
    return total_ingested


def main():
    import argparse
    parser = argparse.ArgumentParser(description="全量构建 awesome 页面")
    parser.add_argument("--config", default="awesome.yaml", help="配置文件路径")
    parser.add_argument("--output", default="output/website", help="网站输出目录")
    parser.add_argument("--skip-search", action="store_true", help="跳过 arXiv 搜索（仅重新生成网站）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 分类")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm build")
    parser.add_argument("--skip-discover", action="store_true", help="跳过自动发现上游 awesome 项目")
    args = parser.parse_args()

    config = load_config()
    research = config.get("research", {})
    output_dir = (ROOT / args.output).resolve()

    # Step 1: 搜索 arXiv 并生成 data/papers.yaml
    if not args.skip_search:
        from sync import search_arxiv, sync_papers

        keywords = research.get("keywords", [])
        categories = research.get("arxiv_categories", [])
        date_from = research.get("date_from", "")
        date_to = research.get("date_to", "")

        print(f"[build] 搜索 arXiv: keywords={keywords}, categories={categories}, from={date_from}")

        papers = search_arxiv(keywords, categories, date_from, date_to, max_results=500)
        if papers:
            # 先写入 ROOT/data/，后续 Step 3 会统一复制到输出目录
            root_data_dir = ROOT / "data"
            root_data_dir.mkdir(parents=True, exist_ok=True)
            papers_yaml = root_data_dir / "papers.yaml"
            added = sync_papers(papers, papers_yaml, source_repo="arxiv", skip_llm=args.skip_llm)
            print(f"[build] 新增 {added} 篇论文")
            # 创建空的 datasets.yaml 和 tools.yaml（Astro 模板需要）
            for empty_file in ["datasets.yaml", "tools.yaml"]:
                ef = root_data_dir / empty_file
                if not ef.exists():
                    ef.write_text("[]\n", encoding="utf-8")
        else:
            print("[build] 未搜索到论文，跳过")

    # Step 2: 自动发现并吸纳上游 awesome 项目数据
    if not args.skip_discover:
        discover_and_ingest(config)

    # Step 3: 生成 Astro 网站
    generate_site(config, output_dir)

    # Step 4: 复制 data 到网站目录
    data_src = ROOT / "data"
    data_dst = output_dir / "data"
    if data_src.exists():
        shutil.copytree(data_src, data_dst, dirs_exist_ok=True)
        print(f"[build] 已复制数据到 {data_dst}")

    # Step 5: 复制 awesome.yaml 到输出目录
    shutil.copy2(ROOT / "awesome.yaml", output_dir / "awesome.yaml")

    # Step 6: 生成 README
    readme_content = f"""# {config['project']['name']}

{config['project']['description']}

- Papers: **auto-generated**
- Last updated: auto-generated

> This site is automatically generated by [awesome-hub-generator](https://github.com/your-username/awesome-hub-generator).
"""
    (output_dir / "README.md").write_text(readme_content, encoding="utf-8")

    # Step 7: 构建网站
    if not args.skip_build:
        build_site(output_dir)

    print(f"[build] 完成！网站已生成到 {output_dir}")
    print(f"[build] 运行 cd {output_dir} && npm run dev 本地预览")


if __name__ == "__main__":
    main()
