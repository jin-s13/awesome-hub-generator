"""
init_site.py — 初始化下游 awesome-*-hub 站点仓库

在工作目录下创建一个可直接使用的下游站点，包含:
  - awesome.yaml (从 generator 的模板复制)
  - .github/workflows/daily-update.yml (从 templates/workflows/ 复制)
  - .gitignore

用法:
    # 在 generator 根目录执行
    python scripts/init_site.py --name awesome-cad-hub --title "Awesome CAD Hub"

    # 指定输出目录
    python scripts/init_site.py --name awesome-cad-hub --output /path/to/awesome-cad-hub

初始化完成后，进入站点目录执行全量构建:
    cd awesome-cad-hub
    python ../scripts/build.py   # 或通过 submodule 方式调用
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def init_site(name: str, title: str, output: str, description: str = "") -> None:
    """
    初始化下游站点目录结构。

    Args:
        name: 站点目录名 (如 awesome-cad-hub)
        title: 站点标题 (如 Awesome CAD Hub)
        output: 输出根目录 (默认为当前工作目录)
        description: 站点描述
    """
    output_root = Path(output).resolve()
    site_dir = output_root / name

    if site_dir.exists():
        print(f"[init] 错误: 目录已存在: {site_dir}")
        sys.exit(1)

    site_dir.mkdir(parents=True)
    print(f"[init] 创建站点目录: {site_dir}")

    # 1. 复制 awesome.yaml 模板
    template_yaml = ROOT / "awesome.yaml"
    if template_yaml.exists():
        target_yaml = site_dir / "awesome.yaml"
        content = template_yaml.read_text(encoding="utf-8")
        # 替换项目名称
        content = content.replace("Awesome CAD Hub", title)
        if description:
            # 替换 description 字段
            import re
            content = re.sub(
                r'description:\s*".*?"',
                f'description: "{description}"',
                content,
            )
        target_yaml.write_text(content, encoding="utf-8")
        print(f"[init] 已生成: awesome.yaml")

    # 2. 复制 GitHub Actions workflow 模板
    workflow_src = ROOT / "templates" / "workflows" / "daily-update.yml"
    if workflow_src.exists():
        workflow_dst = site_dir / ".github" / "workflows" / "daily-update.yml"
        workflow_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workflow_src, workflow_dst)
        print(f"[init] 已生成: .github/workflows/daily-update.yml")

    # 3. 生成 .gitignore
    gitignore = site_dir / ".gitignore"
    gitignore.write_text(
        ".local/website/\n.local/researcher/\nnode_modules/\ndist/\n.env\n*.pyc\n__pycache__/\n.DS_Store\n",
        encoding="utf-8",
    )
    print(f"[init] 已生成: .gitignore")

    # 4. 生成 README.md (简短说明)
    readme = site_dir / "README.md"
    readme.write_text(
        f"# {title}\n\n"
        f"Auto-curated awesome list powered by "
        f"[awesome-hub-generator](https://github.com/your-org/awesome-hub-generator).\n\n"
        f"## 快速开始\n\n"
        f"```bash\n"
        f"# 全量构建（首次）\n"
        f"python ../awesome-hub-generator/scripts/build.py\n\n"
        f"# 每日增量更新\n"
        f"python ../awesome-hub-generator/scripts/update.py\n\n"
        f"# 查漏补缺（搜索最近30天）\n"
        f"python ../awesome-hub-generator/scripts/update.py --search-days 30\n"
        f"```\n\n"
        f"## 配置\n\n"
        f"编辑 `awesome.yaml` 修改关键词、分类等。\n",
        encoding="utf-8",
    )
    print(f"[init] 已生成: README.md")

    # 5. 提示后续步骤
    print(f"\n[init] 站点初始化完成: {site_dir}")
    print(f"\n后续步骤:")
    print(f"  1. cd {site_dir}")
    print(f"  2. 编辑 awesome.yaml，配置关键词和 LLM 密钥")
    print(f"  3. 创建 .env 文件 (参考 awesome-hub-generator/.env.example)")
    print(f"  4. 执行全量构建:")
    print(f"     python {{path-to-generator}}/scripts/build.py")
    print(f"  5. 推送到 GitHub，daily-update.yml 会自动每日运行")


def main():
    parser = argparse.ArgumentParser(description="初始化下游 awesome-*-hub 站点")
    parser.add_argument("--name", required=True,
                        help="站点目录名 (如 awesome-cad-hub)")
    parser.add_argument("--title", required=True,
                        help="站点标题 (如 Awesome CAD Hub)")
    parser.add_argument("--output", default=".",
                        help="输出根目录 (默认当前目录)")
    parser.add_argument("--description", default="",
                        help="站点描述")
    args = parser.parse_args()

    init_site(args.name, args.title, args.output, args.description)


if __name__ == "__main__":
    main()
