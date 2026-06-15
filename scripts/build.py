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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="全量构建 awesome 页面")
    parser.add_argument("--config", default="awesome.yaml", help="配置文件路径")
    parser.add_argument("--output", default="output/website", help="网站输出目录")
    parser.add_argument("--skip-search", action="store_true", help="跳过 arXiv 搜索（仅重新生成网站）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 分类")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm build")
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
            data_dir = output_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            papers_yaml = data_dir / "papers.yaml"
            added = sync_papers(papers, papers_yaml, source_repo="arxiv", skip_llm=args.skip_llm)
            print(f"[build] 新增 {added} 篇论文")
        else:
            print("[build] 未搜索到论文，跳过")

    # Step 2: 生成 Astro 网站
    generate_site(config, output_dir)

    # Step 3: 复制 data 到网站目录
    data_src = ROOT / "data"
    data_dst = output_dir / "data"
    if data_src.exists():
        shutil.copytree(data_src, data_dst, dirs_exist_ok=True)
        print(f"[build] 已复制数据到 {data_dst}")

    # Step 4: 复制 awesome.yaml 到输出目录
    shutil.copy2(ROOT / "awesome.yaml", output_dir / "awesome.yaml")

    # Step 5: 生成 README
    readme_content = f"""# {config['project']['name']}

{config['project']['description']}

- Papers: **auto-generated**
- Last updated: auto-generated

> This site is automatically generated by [awesome-hub-generator](https://github.com/your-username/awesome-hub-generator).
"""
    (output_dir / "README.md").write_text(readme_content, encoding="utf-8")

    # Step 6: 构建网站
    if not args.skip_build:
        build_site(output_dir)

    print(f"[build] 完成！网站已生成到 {output_dir}")
    print(f"[build] 运行 cd {output_dir} && npm run dev 本地预览")


if __name__ == "__main__":
    main()
