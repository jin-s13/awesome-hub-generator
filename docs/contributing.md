# Contributing to awesome-hub-generator

感谢你考虑为 awesome-hub-generator 贡献代码！

## 开发环境

```bash
# 克隆仓库（含子模块）
git clone --recurse-submodules https://github.com/your-username/awesome-hub-generator.git
cd awesome-hub-generator

# 安装 Python 依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

## 项目结构

```
awesome-hub-generator/
├── awesome.yaml              # 用户唯一配置文件
├── arxiv-daily-researcher/   # git submodule: 论文发现引擎
├── scripts/
│   ├── build.py              # 全量构建入口
│   ├── update.py             # 每日更新入口
│   ├── config_bridge.py      # 配置桥接（awesome.yaml → researcher config）
│   ├── researcher_adapter.py # researcher 适配层（Python import 调用）
│   ├── sync.py               # arXiv API fallback 适配器
│   ├── discover_sources.py   # GitHub 自动发现上游 awesome 项目
│   ├── ingest_source.py      # 多格式数据吸纳解析器
│   ├── fetch_teasers.py      # 论文 teaser 图自动获取
│   └── generate_interpretations.py  # TLDR/深度分析/中文翻译生成
├── templates/astro-site/     # Astro 网站模板
├── data/                     # 论文/数据集/工具数据
└── .github/workflows/        # CI/CD 工作流
```

## 开发指南

### 代码风格

- Python: 遵循 PEP 8，使用 `ruff` 检查
- 类型注解: 所有函数参数和返回值需标注类型
- 日志: 使用 `print(f"[模块名] 消息")` 格式

### 测试

```bash
# 语法检查
python3 -c "import py_compile; py_compile.compile('scripts/build.py', doraise=True)"

# 运行解析器测试
python3 scripts/ingest_source.py --readme README.md

# 全量构建测试（跳过搜索和构建）
python3 scripts/build.py --skip-search --skip-build --skip-discover
```

### 提交 PR

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/your-feature`)
3. 提交改动 (`git commit -m 'Add some feature'`)
4. 推送到分支 (`git push origin feature/your-feature`)
5. 创建 Pull Request

## 许可

AGPL-3.0
