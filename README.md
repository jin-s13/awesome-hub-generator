# awesome-hub-generator

> 告诉它你的研究方向，它自动帮你建一个 awesome 页面，每天更新。

**awesome-hub-generator** 是一个端到端的 awesome 页面生成器**工具**。你只需要配置研究方向关键词，它就会：

1. **全量构建**：从 arXiv / Hugging Face / 上游 awesome 源搜索历史论文，LLM 评分+深度分析，生成完整的 Astro 静态网站
2. **每日更新**：定时检查 arXiv / Hugging Face 新论文与数据集，自动去重合并到页面中
3. **自动部署**：通过 GitHub Actions 构建并部署到 GitHub Pages

> **架构说明**：本仓库是通用生成器工具，不包含 GitHub Actions 配置。GHA 工作流模板放在 `templates/workflows/` 下，供下游站点仓库（如 `awesome-cad-hub`）使用。

## 快速开始

### 1. 创建本地 hub

在 generator 根目录执行：

```bash
python scripts/init_hub.py --name awesome-cad-hub --title "Awesome CAD Hub"
```

这会创建 `.local/awesome-cad-hub/` 工作区，包含 `awesome.yaml`、`data/`、`assets/`、`resource/` 和 `website/`。

### 2. 配置研究方向

编辑 `.local/awesome-cad-hub/awesome.yaml`：

```yaml
project:
  name: "Awesome CAD Hub"
  description: "A curated hub for CAD papers, datasets, tools, and Neural CAD research."
  site_url: "https://your-username.github.io/awesome-cad-hub"

research:
  keywords:
    - "CAD"
    - "B-Rep"
    - "parametric CAD"
    - "text-to-CAD"

  negative_keywords:
    - "medical imaging"
    - "weather forecast"

  arxiv_categories:
    - "cs.CV"
    - "cs.GR"
    - "cs.LG"

  date_from: "2020-01-01"
  daily_search_days: 3
```

### 3. 配置 API Key

在站点目录下创建 `.env` 文件：

```bash
cp .env.example .env
# 编辑 .env 填入 API Key
```

或在 GitHub 仓库的 **Settings → Secrets and variables → Actions** 中添加：

| Secret | 说明 | 示例值 |
|--------|------|--------|
| `ARK_API_KEY` | 火山引擎 API Key | `ark-xxxxx` |
| `ARK_API_BASE_URL` | API 地址（可选） | `https://ark.cn-beijing.volces.com/api/coding/v3` |
| `ARK_MODEL_NAME` | 评分用模型（可选） | `deepseek-v4-flash` |
| `SMART_MODEL_NAME` | 深度分析用模型（可选） | `deepseek-v4-pro` |

### 4. 全量构建（首次初始化）

```bash
python scripts/build.py --hub awesome-cad-hub
```

首次构建会搜索 arXiv 历史论文，LLM 评分+深度分析后生成完整的 Astro 网站。已有完整数据的论文会自动跳过，不重复处理。

### 5. 本地预览

```bash
cd .local/awesome-cad-hub/website
npm install
cd ../../..
python scripts/serve_hub.py --hub awesome-cad-hub --port 4327
```

`serve_hub.py` 会在启动前检查 `.local/{hub}` 是否是干净的 git checkout；如果是，会先执行
`git pull --ff-only origin main`，再启动 Astro dev server。若存在本地未提交改动，则会跳过同步并继续使用本地内容启动，避免覆盖人工修改。

### 6. 下游仓库部署

需要 GitHub Pages 部署时，再创建独立下游仓库：

```bash
python scripts/init_site.py --name awesome-cad-hub --title "Awesome CAD Hub"
```

将站点推送到 GitHub 后，`.github/workflows/daily-update.yml` 会每天自动运行，检查 arXiv 新论文并更新网站。

也可手动触发 gap-fill 查漏补缺：在 Actions 界面输入 `search_days`（如 30），搜索最近 30 天的论文。

启用每日更新前，先在下游站点仓库配置：

- Repository variable: `GENERATOR_REPO=jin-s13/awesome-hub-generator`（或你的 fork）
- Required secret: `ARK_API_KEY`
- Optional secrets: `ARK_API_BASE_URL`, `ARK_MODEL_NAME`, `SMART_MODEL_NAME`, `MINERU_API_KEY`, `OPENALEX_API_KEY`, `OPENALEX_MAILTO`
- `GITHUB_TOKEN` 使用 GitHub Actions 内置 token 自动注入，用于 upstream awesome 项目发现；无需手动创建 secret。

workflow 默认每天 UTC 00:00 运行，即北京时间 08:00。下游仓库模式会把数据写入 `.local/data`、`.local/assets`、`.local/resource`，并从 `.local/website/dist` 部署 GitHub Pages。

下游项目需要读取结构化元数据时，应读取 hub 仓库 `main` 分支的 `data/`、`assets/` 和 `resource/`。`gh-pages` 分支只保存已经构建好的静态网页产物，适合浏览器访问，不适合作为元数据源。

## 网站特性

| 页面 | 路由 | 内容 |
|------|------|------|
| 首页 | `/` | 精选论文（按评分排序）、导航 |
| 论文列表 | `/papers` | 全部论文卡片（含评分徽章、TLDR）、筛选 |
| 论文详情 | `/papers/[id]` | TLDR、关键词评分条形图、深度分析、资源链接 |
| 趋势 | `/trends` | 关键词评分趋势、标签频率 Top 30、年份分布 |
| 数据集 | `/datasets` | 数据集列表 |
| 工具 | `/tools` | 工具列表 |

## 项目结构

```
awesome-hub-generator/              ← 通用生成器工具（本仓库）
├── arxiv-daily-researcher/         # git submodule: 论文发现引擎
├── scripts/
│   ├── build.py                    # 全量构建入口
│   ├── update.py                   # 每日更新入口（支持 --search-days gap-fill）
│   ├── init_hub.py                 # 本地 .local/{hub} 初始化脚本
│   ├── init_site.py                # 下游站点初始化脚本
│   ├── config_bridge.py            # 配置桥接器
│   ├── researcher_adapter.py       # researcher 适配层
│   ├── sync.py                     # arXiv API fallback
│   ├── discover_sources.py         # GitHub 自动发现上游 awesome 项目
│   ├── ingest_source.py            # 多格式数据解析器
│   ├── fetch_teasers.py            # 论文 teaser 图自动获取
│   └── generate_interpretations.py # 论文解读+中文翻译生成
├── templates/
│   ├── astro-site/                 # Astro 网站模板
│   └── workflows/
│       └── daily-update.yml        # 下游仓库 GHA 模板（含 teaser fetch）
├── awesome.yaml.example            # 通用配置模板
├── examples/                       # 可选示例配置
└── .local/                         # 本地产出物（gitignore）
    └── awesome-cad-hub/            # 本地 hub 工作区
        ├── awesome.yaml
        ├── data/                   # papers.yaml, resources.yaml 等
        ├── assets/                 # teaser 图片
        ├── resource/               # 论文解读与衍生材料
        └── website/                # 生成的 Astro 网站

awesome-cad-hub/                    ← 下游站点仓库（独立部署）
├── awesome.yaml                    # 站点配置
├── .github/workflows/
│   └── daily-update.yml            # 每日更新工作流（从模板复制）
├── .gitignore
└── README.md
```

默认路径会按运行位置自动切换：如果直接在生成器仓库根目录运行，请用 `--hub awesome-cad-hub`，它会读取 `.local/awesome-cad-hub/awesome.yaml` 并写入同一工作区的 `data`、`assets`、`resource` 和 `website`；如果在下游站点仓库里运行，则使用该仓库自己的 `.local/data`、`.local/assets`、`.local/resource` 和 `.local/website`。

## 工作原理

```
                    ┌─────────────────────┐
                    │   awesome.yaml      │
                    │  (.local 或下游仓库) │
                    └────────┬────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                              ▼
    ┌──────────────────────┐      ┌──────────────────────┐
    │  全量构建 (build.py)  │      │ 每日更新 (update.py)  │
    │  首次初始化 / 手动    │      │ 定时自动 + 手动 gap   │
    │                      │      │                      │
    │ Step 1: 论文发现      │      │ Step 1: 搜索最近N天   │
    │ Step 2: LLM评分+分析  │      │ Step 2: 去重合并      │
    │ Step 3: teaser图获取  │      │   (跳过已有论文)      │
    │ Step 4: 生成网站      │      │ Step 3: teaser图获取  │
    │                      │      │ Step 4: 重新构建网站   │
    └────────┬─────────────┘      └────────┬─────────────┘
             │                             │
             └──────────────┬──────────────┘
                            ▼
                  ┌──────────────────────┐
                  │  GitHub Pages        │
                  │  (下游仓库部署)       │
                  └──────────────────────┘
```

### 双 LLM 策略

系统使用两阶段 LLM 调用来平衡成本和质量：

1. **CHEAP_LLM（评分）**：对每篇论文逐关键词打分（0-10），生成 TLDR 和评分理由。使用低成本模型。
2. **SMART_LLM（深度分析）**：仅对高分论文（≥30分）进行 PDF 深度分析，提取创新点/方法/局限性。使用更强模型。

> 如果只有一个 API Key，两个阶段共用同一个 Key，仅通过 `SMART_MODEL_NAME` 区分模型。

### Fallback 机制

当 `arxiv-daily-researcher` 不可用时（如 submodule 未初始化），系统自动降级到 `sync.py` 的 arXiv API 搜索 + 单 LLM 分类模式。

## 自定义

### 修改网站外观

编辑 `templates/astro-site/public/styles/global.css` 中的 CSS 变量。

### 添加 datasets 和 tools

除了自动生成的论文，你还可以在站点工作区的 `data/datasets.yaml` 和 `data/tools.yaml` 中手动维护数据集和工具列表。下游站点仓库中默认是 `.local/data/...`；直接在生成器仓库根目录运行时默认是 `.local/{project-slug}/data/...`。注意 `.local/` 已 gitignore，如需持久化请通过 `awesome.yaml` 的 `auto_discover` 和 `research.datasets` 配置自动发现上游项目。

`datasets.yaml` 会自动合并三类来源：Hugging Face Datasets 关键词检索、上游 awesome README 的 dataset section、以及 `papers.yaml` 中被分类为 `benchmark` 或明确提到 dataset 的论文。手动已有条目会优先保留，自动条目按名称和链接去重。

```yaml
research:
  sources:
    huggingface_datasets: true
    upstream_awesome: true
    alphaxiv: false
  datasets:
    huggingface: true
    huggingface_limit_per_keyword: 20
    derive_from_papers: true
  alphaxiv:
    enabled: false
    endpoint: ""
```

论文搜索会先进入统一来源层：arXiv、Hugging Face Daily/Trending、上游 awesome 项目和可选 AlphaXiv 增强源会被规范化、去重、合并 provenance，再进入候选池或展示池。AlphaXiv 默认关闭；不配置 endpoint 时不会发请求，也不需要额外 key。

上游 awesome 项目既可以自动发现，也可以显式配置已知高质量仓库。显式仓库会优先抓取，适合避免 GitHub Search 匿名限流：

```yaml
research:
  sources:
    upstream_awesome: true
  upstream_awesome:
    repos:
      - "LMD0311/Awesome-World-Model"
    auto_discover: false
```

### 调整评分策略

在 `awesome.yaml` 的 `research.scoring` 中调整：

```yaml
research:
  scoring:
    base_score: 1.5            # 基础分
    weight_coefficient: 2.5    # 权重系数
    max_score_per_keyword: 10  # 每个关键词最高分
    author_bonus:
      enabled: false
      bonus_points: 5.0
      expert_authors: []

  ranking:
    enabled: true              # 生成可解释的 read-first 排序分
    weights:
      topical_relevance: 0.25
      citation_impact: 0.15
      graph_prestige: 0.15
      citation_velocity: 0.10
      methodology_quality: 0.15
      reproducibility: 0.15
      recency: 0.05
    citation_graph:
      enabled: true            # 使用已同步的 OpenAlex-shaped 元数据构建局部引用图
      fetch_openalex: false     # 可选：构建时按标题/DOI/arXiv 链接实时查询 OpenAlex
      timeout: 20
      workers: 6                # OpenAlex 并发请求数；网络较稳时可调到 10
      api_key: ""                # 可选；也可用 OPENALEX_API_KEY 环境变量
```

`scoring` 继续用于旧的关键词总分和过滤；`ranking` 会保留原始 `score.total`，额外写入 `score.read_first_score`、组件分、权重、field roles 和 rank sensitivity，用于首页排序、论文卡片和详情页解释。若论文中已有 OpenAlex-shaped 的 `openalex.id`、`cited_by_count`、`referenced_works` 等字段，或启用 `fetch_openalex` 后查询成功，还会生成 citation impact、citation velocity 和局部 graph prestige；没有这些字段时会自动排除，不会阻塞离线构建。OpenAlex 查询支持 `workers` 并发，适合批量刷新；匿名额度耗尽时可配置 `api_key` 或设置 `OPENALEX_API_KEY`。

高 `read_first_score` 论文还会进入深度研究队列：

```yaml
research:
  deep_research:
    enabled: true
    min_read_first_score: 70
    max_papers_per_run: 10
```

该步骤会生成 `data/research_runs.yaml` 和 `resource/{paper_id}/research.md` 研究占位报告，并写入 critique 与 next research actions；`data/surveys.yaml` 会按 taxonomy、paper_type、tags 和评分组件自动生成结构化文献综述与综合归纳，供 `/analysis` 页面展示。

### 调整深度分析

```yaml
research:
  deep_analysis:
    enabled: true               # 是否对高分论文做 PDF 深度分析
    min_score: 30               # 最低评分门槛
    pdf_parser: "pymupdf"       # pymupdf（本地）或 mineru（云端）
    max_papers_per_run: 10      # 每次运行最多分析多少篇
```

## 本地开发

```bash
# 1. 初始化 submodule
git submodule update --init --recursive

# 2. 安装 Python 依赖
python -m pip install -r requirements.txt

# 3. 创建本地 hub 并配置
python scripts/init_hub.py --name awesome-cad-hub --title "Awesome CAD Hub"
cp .env.example .env  # 编辑填入 API Key

# 4. 全量构建
python scripts/build.py --hub awesome-cad-hub

# 5. 本地预览（启动前自动同步 .local/awesome-cad-hub）
python scripts/serve_hub.py --hub awesome-cad-hub --port 4327

# 6. 增量更新（每日）
python scripts/update.py --hub awesome-cad-hub

# 7. 查漏补缺（搜索最近30天）
python scripts/update.py --hub awesome-cad-hub --search-days 30
```

## 许可证

AGPL-3.0
