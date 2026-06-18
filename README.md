# awesome-hub-generator

> 告诉它你的研究方向，它自动帮你建一个 awesome 页面，每天更新。

**awesome-hub-generator** 是一个端到端的 awesome 页面生成器。你只需要配置研究方向关键词，它就会：

1. **全量构建**：从 arXiv 搜索历史论文，LLM 评分+深度分析，生成完整的 Astro 静态网站
2. **每日更新**：定时检查 arXiv 新论文，自动去重合并到页面中
3. **自动部署**：通过 GitHub Actions 构建并部署到 GitHub Pages

## 快速开始

### 1. Fork 本项目

点击右上角的 **Fork** 按钮。

### 2. 配置研究方向

编辑 `awesome.yaml`，修改为你关心的研究方向：

```yaml
project:
  name: "Awesome CAD Hub"
  description: "A curated hub for CAD papers, datasets, tools, and Neural CAD research."
  site_url: "https://your-username.github.io/awesome-cad-hub"

research:
  # 搜索关键词
  keywords:
    - "CAD"
    - "B-Rep"
    - "parametric CAD"
    - "text-to-CAD"

  # 负向关键词（命中直接排除）
  negative_keywords:
    - "medical imaging"
    - "weather forecast"
    - "protein folding"

  # 领域加分词（额外加权）
  domain_boost_keywords:
    - "neural CAD"
    - "generative CAD"

  # arXiv 分类
  arxiv_categories:
    - "cs.CV"
    - "cs.GR"
    - "cs.LG"

  # 全量构建的起始日期
  date_from: "2020-01-01"
```

### 3. 配置 API Key (GitHub Secrets)

在 GitHub 仓库的 **Settings → Secrets and variables → Actions** 中添加：

| Secret | 说明 | 示例值 |
|--------|------|--------|
| `ARK_API_KEY` | 火山引擎 API Key | `sk-xxxxx` |
| `ARK_API_BASE_URL` | API 地址（可选） | `https://ark.cn-beijing.volces.com/api/v3` |
| `ARK_MODEL_NAME` | 评分用模型（可选） | `deepseek-v4-flash-260425` |
| `SMART_MODEL_NAME` | 深度分析用模型（可选，默认同 ARK_MODEL_NAME） | `deepseek-v4-flash-260425` |

> 支持火山引擎 DeepSeek 等任意兼容 OpenAI 格式的 API。

### 4. 全量构建

在 GitHub 仓库的 **Actions → Full build → Run workflow** 中手动触发。

首次构建会搜索 arXiv 历史论文，LLM 评分+深度分析后生成完整的 Astro 网站并部署到 GitHub Pages。

### 5. 每日自动更新

`daily-update.yml` 工作流默认每天 UTC 0:00（北京时间 8:00）自动运行，检查 arXiv 新论文，有新增则自动更新网站。

## 网站特性

生成的网站包含以下页面：

| 页面 | 路由 | 内容 |
|------|------|------|
| 首页 | `/` | 精选论文（按评分排序）、导航 |
| 论文列表 | `/papers` | 全部论文卡片（含评分徽章、TLDR）、筛选 |
| 论文详情 | `/papers/[id]` | TLDR、关键词评分条形图、深度分析（创新点/方法/局限性）、资源链接 |
| 趋势 | `/trends` | 关键词评分趋势、标签频率 Top 30、年份分布 |
| 数据集 | `/datasets` | 数据集列表 |
| 工具 | `/tools` | 工具列表 |

## 项目结构

```
awesome-hub-generator/
├── awesome.yaml                 # ← 核心配置文件（你只需改这个）
├── arxiv-daily-researcher/      # git submodule: 论文发现引擎
├── scripts/
│   ├── build.py                 # 全量构建入口
│   ├── update.py                # 每日更新入口
│   ├── config_bridge.py         # 配置桥接器（awesome.yaml → researcher config）
│   ├── researcher_adapter.py    # researcher 适配层（Python import 调用）
│   ├── sync.py                  # arXiv API fallback（researcher 不可用时）
│   ├── discover_sources.py      # GitHub 自动发现上游 awesome 项目
│   ├── ingest_source.py         # 多格式数据解析器
│   └── fetch_teasers.py         # 论文 teaser 图自动获取
├── templates/
│   └── astro-site/              # Astro 网站模板
│       ├── src/pages/
│       │   ├── index.astro      # 首页
│       │   ├── papers.astro     # 论文列表
│       │   ├── papers/[id].astro# 论文详情（动态路由）
│       │   ├── trends.astro     # 关键词趋势
│       │   ├── datasets.astro   # 数据集
│       │   └── tools.astro      # 工具
│       └── public/styles/       # 全局样式
├── .github/workflows/
│   ├── full-build.yml           # 全量构建工作流
│   ├── daily-update.yml         # 每日更新工作流
│   └── fetch-teasers.yml        # 论文 teaser 图定时获取
├── data/                        # 论文/数据集/工具数据
│   ├── papers.yaml
│   ├── datasets.yaml
│   └── tools.yaml
└── output/website/              # 生成的网站（自动创建）
    ├── src/                     # Astro 源码
    └── dist/                    # 构建产物（部署到 GitHub Pages）
```

## 工作原理

```
                    ┌─────────────────────┐
                    │   awesome.yaml      │
                    │  (研究方向配置)      │
                    └────────┬────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                              ▼
    ┌──────────────────────┐      ┌──────────────────────┐
    │  全量构建 (build.py)  │      │ 每日更新 (update.py)  │
    │                      │      │                      │
    │ Step 1: 论文发现      │      │ Step 1: 运行          │
    │   ├─ ResearcherAdapter│      │   ResearcherAdapter  │
    │   │  (Python import)  │      │   (Python import)    │
    │   └─ Fallback: arXiv  │      │                      │
    │      API (sync.py)    │      │ Step 2: 去重合并      │
    │ Step 2: 自动发现      │      │   → data/papers.yaml  │
    │   GitHub awesome 项目 │      │                      │
    │ Step 3: 生成网站      │      │ Step 3: 重新构建网站   │
    │   + npm build         │      │                      │
    └────────┬─────────────┘      └────────┬─────────────┘
             │                             │
             └──────────────┬──────────────┘
                            ▼
                  ┌──────────────────────┐
                  │  GitHub Pages        │
                  │  (静态网站)           │
                  │  - 论文卡片（含评分）  │
                  │  - 详情页（含深度分析）│
                  │  - 关键词趋势图       │
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

除了自动生成的论文，你还可以在 `data/datasets.yaml` 和 `data/tools.yaml` 中手动维护数据集和工具列表。

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
```

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

# 3. 复制 .env 并填入 API Key
cp .env.example .env

# 4. 全量构建（跳过搜索，使用已有数据）
python scripts/build.py --skip-search --skip-discover --skip-download

# 5. 本地预览
cd output/website && npm run dev
```

## 许可证

AGPL-3.0
