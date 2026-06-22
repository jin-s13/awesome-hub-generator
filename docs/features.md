# awesome-hub-generator 功能文档

> 本文档详细说明所有已实现功能及其实现逻辑。
> 最后更新: 2026-06-22

---

## 目录

1. [架构概览](#1-架构概览)
2. [数据源层](#2-数据源层)
3. [数据处理层](#3-数据处理层)
4. [LLM 应用层](#4-llm-应用层)
5. [网站生成层](#5-网站生成层)
6. [配置与工具层](#6-配置与工具层)
7. [完整 Pipeline](#7-完整-pipeline)

---

## 1. 架构概览

```
                    ┌─────────────────────┐
                    │   awesome.yaml      │  ← 用户唯一配置
                    └────────┬────────────┘
                             │
                    ┌────────┴────────┐
                    │  config_bridge  │  ← 配置转换
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                              ▼
    ┌──────────────────────┐      ┌──────────────────────┐
    │   build.py           │      │   update.py          │
    │   (全量构建)          │      │   (每日增量更新)      │
    └────────┬─────────────┘      └────────┬─────────────┘
             │                             │
             └──────────────┬──────────────┘
                            ▼
                  ┌──────────────────────┐
                  │  templates/astro-site │  → 静态网站
                  └──────────────────────┘
```

---

## 2. 数据源层

### 2.1 arXiv API 搜索 (`sync.py`)

**文件**: [sync.py](../scripts/sync.py)

**功能**: 通过 arXiv API 搜索论文，作为 ResearcherAdapter 不可用时的 fallback 数据源。

**实现逻辑**:

1. `search_arxiv(keywords, categories, date_from, date_to, max_results)`:
   - 关键词分批查询（每批 10 个），避免查询字符串过长
   - 用 `urllib.request` 请求 arXiv API Atom XML 端点
   - 用正则解析 XML 提取 title/abstract/authors/categories/links
   - 去重（按 arXiv ID）、排序（按 published 时间降序）
   - 内置重试机制（失败后等待 3 秒重试，最多 3 次）

2. `classify_paper(title, abstract, categories)`:
   - 调用火山引擎 DeepSeek LLM 对论文进行分类
   - 输出: category（枚举值）、tags（最多 8 个）、representations/input_modalities/output_modalities
   - 分类枚举: Generation / Reconstruction / Analysis / Survey / Abstraction / Others

3. `sync_papers(new_papers, output_path, ...)`:
   - 主流程: 负向关键词过滤 → LLM 分类 → 格式转换 → 去重合并 → YAML 写入
   - 负向过滤优先用 LLM 语义判断（避免关键词误杀），LLM 不可用时 fallback 到关键词匹配

4. `write_if_changed(path, data)`:
   - 幂等写入: 序列化后比较新旧内容，内容不变不写文件，减少 git 变动

### 2.2 arxiv-daily-researcher 适配 (`researcher_adapter.py`)

**文件**: [researcher_adapter.py](../scripts/researcher_adapter.py)

**功能**: 封装 `arxiv-daily-researcher` 子模块，以 Python import 方式运行论文发现 pipeline。

**实现逻辑**:

1. `ResearcherAdapter.run_daily_research()`:
   - 先调用 `config_bridge.sync_config()` 同步配置
   - 通过 `importlib` 动态导入 researcher 模块
   - 直接调用 `DailyResearchPipeline` 类（非 subprocess 方式）
   - 返回 `RunResult` dataclass（含 scored_papers、analyses 等）

2. `convert_to_papers_yaml(run_result)`:
   - 将 researcher 的结构化结果转换为 `papers.yaml` 标准格式
   - 保留: score（含 keyword_scores/total）、tldr、reasoning、analysis
   - 从 analyses_by_source 中提取深度分析内容

3. `deduplicate(existing, new_items)`:
   - 三重去重: title（小写）/ id / paper URL
   - 排序: 年份降序 → score 降序 → 标题升序

### 2.3 HuggingFace 数据源 (`hf_source.py`)

**文件**: [hf_source.py](../scripts/hf_source.py)

**功能**: 从 HuggingFace Daily Papers 和 Trending 端点抓取论文，作为 arXiv 的补充数据源。

**实现逻辑**:

1. `fetch_hf_daily_papers(start_date, end_date)`:
   - 按日期范围循环请求 `https://huggingface.co/api/daily_papers?date=YYYY-MM-DD&limit=100`
   - 无日期参数时默认抓当天
   - 用标准库 `urllib.request`，User-Agent: `awesome-hub-generator/1.0`

2. `fetch_hf_trending_papers()`:
   - 请求 `https://huggingface.co/api/daily_papers?sort=trending&limit=50`
   - 全局 trending，不依赖日期

3. `_merge_papers(daily_papers, trending_papers)`:
   - 按 arxiv_id 去重合并
   - 合并 sources 列表（标记来源为 huggingface-daily / huggingface-trending）
   - 保留更高 upvotes

4. `fetch_all_hf_papers(config)`:
   - 根据 `awesome.yaml` 的 `research.sources` 配置决定是否启用
   - 返回标准论文 dict 列表，与现有 pipeline 兼容

### 2.4 GitHub 自动发现 (`discover_sources.py` + `ingest_source.py`)

**文件**: [discover_sources.py](../scripts/discover_sources.py), [ingest_source.py](../scripts/ingest_source.py)

**功能**: 自动发现 GitHub 上已有的 awesome 项目，从中吸纳论文数据。

**实现逻辑**:

`discover_sources.py`:
1. `GitHubDiscoverer.discover(keywords, min_stars, max_sources)`:
   - 5 种搜索策略依次执行，去重后按 stars 降序取 Top N:
     - 策略 1: topic 搜索（`topic:awesome topic:{kw}`）
     - 策略 2: README 内容搜索（`"awesome" "{kw}" in:readme`）
     - 策略 3: 仓库名搜索（`awesome-{kw} in:name`）
     - 策略 4: GitHub Trending 搜索（`awesome {kw} stars:>100`）
     - 策略 5: awesome-list 话题搜索（`topic:awesome-list`，过滤描述含关键词的）
   - 内置 GitHub API 限流检测和自动等待

`ingest_source.py`:
2. `FormatDetector.detect(readme_content, repo_files)`:
   - 自动检测格式: YAML/JSON 数据文件 → Markdown 表格 → Markdown 列表 → HTML 列表

3. `MarkdownTableParser.parse(readme, source_repo)`:
   - 解析 Markdown 表格，智能列映射（title/year/venue/links/description）
   - 支持单元格内 Markdown 链接和纯 URL 提取

4. `MarkdownListParser.parse(readme, source_repo)`:
   - 同时支持 Markdown 列表（`- [title](url)`）和 HTML `<li>` 格式

5. `HtmlListParser.parse(readme, source_repo)`:
   - 解析 HTML `<li>` 列表，提取 `<a>` 标签链接和标题

---

## 3. 数据处理层

### 3.1 元数据富化 (`enrich_metadata.py`)

**文件**: [enrich_metadata.py](../scripts/enrich_metadata.py)

**功能**: 从 arXiv 多级来源提取丰富的论文元数据，增强 `papers.yaml` 中的论文条目。

**实现逻辑**:

**多级 fallback 链**（按优先级）:
```
提取机构/作者
    ├── 1. arXiv HTML 页面         ← 正则解析
    ├── 2. arXiv abs 页面 meta 标签 ← 正则解析
    ├── 3. TeX source 解析         ← tar.gz 解压 + LaTeX 解析
    └── 4. PDF 文本提取            ← pdftotext + 5 种策略
```

**提取的字段**:
| 字段 | 来源 | 提取方式 |
|------|------|---------|
| figure_url | HTML `<figure>` 内 `<img>` | 正则匹配，过滤 icon/logo |
| authors | HTML `ltx_personname` span / abs `<meta>` | 正则匹配 |
| affiliations | HTML / abs / TeX / PDF | 多级 fallback |
| section_headers | HTML `<h2>/<h3>` | 正则匹配，去编号 |
| captions | HTML `<figcaption>/<caption>` | 正则匹配 |
| method_names | HTML 全文 | CamelCase + ALLCAPS 正则 + 频率统计 |
| method_summary | HTML Method/Approach 章节 | 正则定位 + 文本截取 |

**并发控制**: asyncio + `Semaphore(max_workers)`，默认并发 10。

**TeX source 解析**:
- 请求 `https://arxiv.org/e-print/{arxiv_id}` 获取 tar.gz
- 解压后搜索 `.tex` 文件，按文件大小降序处理
- 解析 `\author{}`、`\affiliation{}`、`\institute{}`、`\address{}`

**PDF 机构提取**（5 种策略）:
1. 关键词行匹配
2. 编号脚注模式: `[1] Institution`
3. 版权行匹配: `© 2024 Company`
4. 全文扫描（前 60 行）
5. 位置启发式（作者行后到 Abstract 之间）

### 3.2 论文相关性过滤 (`relevance_filter.py`)

**文件**: [relevance_filter.py](../scripts/relevance_filter.py)

**功能**: 判断论文是否与研究方向相关，过滤不相关论文。

**三级判断逻辑**:
```
Stage 1: 关键词粗筛（零成本）
  ├── 命中负向关键词 → 直接排除
  ├── 命中核心关键词 → 直接保留
  └── 标题含相义词 → 直接保留

Stage 2: LLM 精筛（仅处理模糊地带）
  ├── 有 score 且高分 → LLM 确认
  └── 无 score 或低分 → LLM 判断

Stage 3: Fallback（LLM 不可用时）
  └── 无 abstract 的上游精选 → 保守保留，其余排除
```

**LLM 调用**:
- `_llm_check_relevance()`: 用 LLM 判断论文是否与研究领域相关
- `_llm_filter_negative()`: 用 LLM 判断是否命中负向关键词语义
- 使用 `research_context`（从 `project.name` 获取）作为研究方向描述

### 3.3 跨天去重历史记录 (`history_manager.py`)

**文件**: [history_manager.py](../scripts/history_manager.py)

**功能**: 维护已推荐论文的历史记录，避免每日更新时重复推荐。

**实现逻辑**:
1. `HistoryManager.__init__(history_path, retention_days)`:
   - 历史记录文件: `DATA_DIR/.history.json`
   - 默认保留 30 天

2. `filter_seen(papers, weekend_mode)`:
   - 将论文分为 (new, seen) 两组
   - 按 arxiv_id 去重（无法提取时用 title fallback）
   - `weekend_mode=True` 时（周六/日），trending 论文可重推

3. `backfill(seen_papers, min_count)`:
   - 新论文不足 `min_count` 时，从已见论文中按 `score.total` 降序回填
   - 标记回填论文 `is_re_recommend=True`

4. `add_entries(papers, date)` / `prune()`:
   - 添加新记录，按 title/id 去重，保留最早 date
   - 删除超过 `retention_days` 的过期记录

### 3.4 Teaser 图获取 (`fetch_teasers.py`)

**文件**: [fetch_teasers.py](../scripts/fetch_teasers.py)

**功能**: 多源 fallback 获取论文 teaser 图，支持图片本地化。

**5 级 fallback**:
```
1. arXiv HTML figure 标签     ← 正则匹配 <figure> 内 <img>
2. 项目页面                   ← 从 abstract 提取项目 URL，搜索 og:image
3. arXiv PDF 缩略图           ← 固定路径 /arxiv/{id}.pdf.jpg
4. MinerU 云 API              ← 上传 PDF，解析返回的图表列表
5. pdfimages 本地提取          ← pdftoppm 首页渲染 / pdfimages 提取
```

**图片本地化**:
- `check_image_reachability(url)`: HTTP HEAD 请求检查可达性
- `localize_image(paper, assets_dir)`: 下载远程图片到 `assets/{paper_id}/teaser.png`
- 根据 `image_localization` 配置控制是否启用

### 3.5 论文解读生成 (`generate_interpretations.py`)

**文件**: [generate_interpretations.py](../scripts/generate_interpretations.py)

**功能**: 用 LLM 为论文生成 TLDR、评分理由、深度分析、中文翻译、分级。

**实现逻辑**:

**Step 1: TLDR + 评分理由**
- `generate_tldr_and_reasoning(title, abstract, keywords)`:
  - 调用 CHEAP_LLM
  - 输出: tldr、reasoning、keyword_scores（0-10）、has_real_world
  - 计算总分: `sum(keyword_scores)`

**Step 2: 深度分析**
- `generate_deep_analysis(title, abstract)`:
  - 仅对总分 >= 30 的论文执行
  - 调用 SMART_LLM
  - 输出: innovations、methodology、key_results、limitations

**Step 3: 中文翻译**
- `translate_title_abstract()` / `generate_tldr_cn()` / `translate_analysis()`

**Step 4: 论文分级**
- `grade_papers(papers, config)`:
  - `must_read`（必读）: score >= 40
  - `worth_reading`（值得看）: score >= 20
  - `skip`（可跳过）: score < 20

**Step 5: 链接回填**
- `backfill_interpretation_links(papers_path)`:
  - 检查 `resource/{paper_id}/README.md` 是否存在
  - 存在则设置 `paper["links"]["interpretation"]`

---

## 4. LLM 应用层

### 4.1 LLM 调用策略

| 阶段 | 模型 | 用途 | 触发条件 |
|------|------|------|---------|
| 论文评分 | CHEAP_LLM | 逐关键词评分 + TLDR + reasoning | 每篇新论文 |
| 深度分析 | SMART_LLM | PDF 深度分析 | 评分 >= 30 |
| 论文分类 | CHEAP_LLM | category/tags/modalities | arXiv API fallback 路径 |
| 中文翻译 | CHEAP_LLM | 标题/摘要/TLDR/分析翻译 | 每篇有评分的论文 |
| 相关性判断 | CHEAP_LLM | 论文是否与研究领域相关 | 关键词粗筛无法确定 |
| 负向过滤 | CHEAP_LLM | 是否命中负向关键词语义 | 有负向关键词配置时 |

### 4.2 LLM 调用方式

所有 LLM 调用统一使用火山引擎 Ark API（兼容 OpenAI 格式）:

```python
POST {API_BASE_URL}/chat/completions
Authorization: Bearer {API_KEY}
{
  "model": "{MODEL_NAME}",
  "messages": [{"role": "user", "content": "{prompt}"}],
  "max_tokens": 1024,
  "temperature": 0.1
}
```

- 使用标准库 `urllib.request`，不依赖 `openai` Python SDK
- `temperature: 0.1` 保证输出一致性
- JSON 输出通过正则 `\{[^{}]*"field_name"[^{}]*\}` 提取

### 4.3 关键词匹配 → LLM 替换原则

```
语义判断 → LLM（relevance、negative filter、classification）
结构识别 → 规则（URL 域名、图标检测、文件后缀）
高频低代价 → 规则（方法名停用词、机构关键词）
```

**已替换的语义类关键词匹配**:
- `relevance_filter.py`: CAD 相关性判断 → LLM 语义判断（关键词粗筛 + LLM 精筛）
- `sync.py`: 负向关键词过滤 → LLM 语义理解（避免误杀）
- `enrich_metadata.py`: `has_real_world` 关键词匹配 → LLM prompt 中判断

**保留的结构类关键词匹配**:
- `_is_icon_or_logo`: 图标图片过滤（文件名模式识别）
- `ACADEMIC_DOMAINS`: 学术 URL 判断（域名枚举）
- `RESOURCE_TYPE_RULES`: 资源类型判断（域名映射）
- `_METHOD_STOP`: 方法名停用词（频率过滤）
- `_AFFILIATION_KEYWORDS`: 机构关键词（PDF 文本模式识别）

---

## 5. 网站生成层

### 5.1 Astro 模板 (`templates/astro-site/`)

**文件**: [templates/astro-site/](../templates/astro-site/)

**功能**: 基于 Astro 框架的静态网站模板，生成中英双语的论文展示网站。

**页面**:

| 页面 | 路由 | 内容 |
|------|------|------|
| 首页 | `/{lang}/` | Hero 区域、精选论文 Top 6、数据集/工具预览 |
| 论文列表 | `/{lang}/papers` | FilterBar 筛选、PaperCard 网格 |
| 论文详情 | `/{lang}/papers/[id]` | 标题（双语）、TLDR、评分柱状图、深度分析 |
| 趋势分析 | `/{lang}/trends` | 关键词评分趋势、标签频率 Top 30、年份分布 |
| 数据集 | `/{lang}/datasets` | FilterBar 筛选、ResourceCard 网格 |
| 工具 | `/{lang}/tools` | FilterBar 筛选、ResourceCard 网格 |
| 资源 | `/{lang}/resources` | FilterBar 筛选、ResourceCard 网格 |

**组件**: PaperCard、ResourceCard、FilterBar

**数据加载** (`lib/data.ts`): 从 `data/` 目录读取 YAML 文件，TypeScript 类型定义

**国际化** (`lib/i18n.ts`): 约 50 个翻译 key，支持参数替换

### 5.2 网站生成流程

```
generate_site(config, output_dir)
  ├── 1. copy_template() → 复制 Astro 模板，替换 {{占位符}}
  ├── 2. 复制 data/ → output_dir/data/
  ├── 3. 复制 teaser 图 → output_dir/public/assets/papers/
  ├── 4. 复制 resource/ → output_dir/resource/
  ├── 5. 复制 awesome.yaml → output_dir/
  └── 6. build_site() → npm install && npm run build → dist/
```

---

## 6. 配置与工具层

### 6.1 配置系统

**文件**: [awesome.yaml](../awesome.yaml)

**配置结构**:

```yaml
project:              # 项目元信息
  name, description, github_url, site_url

research:             # 研究方向配置
  keywords, negative_keywords, arxiv_categories
  date_from, daily_search_days

  sources:              # 数据源开关
    arxiv, huggingface_daily, huggingface_trending

  auto_discover:        # GitHub 自动发现
    enabled, min_stars, max_sources

  scoring:              # 评分参数
    base_score, weight_coefficient, max_score_per_keyword
    filter_min_score, author_bonus

  deep_analysis:        # 深度分析
    enabled, min_score, pdf_parser, max_papers_per_run

  enrichment:           # 元数据富化
    enabled, max_concurrent, request_timeout
    extract_affiliations, extract_figures, extract_methods

  grading:              # 论文分级
    enabled, must_read_min_score, worth_reading_min_score

  history:              # 跨天去重
    enabled, retention_days, min_papers_per_run, weekend_mode

  image_localization:   # 图片本地化
    enabled, check_reachability, download_fallback

website:              # 网站配置
  sections, nav, footer
```

**本地覆盖**: `awesome.local.yaml` 通过 `deep_merge()` 深度合并，已在 `.gitignore` 中排除。

### 6.2 配置桥接 (`config_bridge.py`)

**文件**: [config_bridge.py](../scripts/config_bridge.py)

**功能**: 将 `awesome.yaml` 转换为 `arxiv-daily-researcher` 的 `config.json` 和 `.env`。

**映射关系**:

| awesome.yaml | researcher config.json |
|-------------|----------------------|
| `research.daily_search_days` | `search_settings.search_days` |
| `research.arxiv_categories` | `target_domains.domains` |
| `research.keywords` | `keywords.primary_keywords.keywords` |
| `project.name` | `keywords.research_context` |
| `research.scoring.*` | `scoring_settings.*` |
| `research.deep_analysis.pdf_parser` | `pdf_parser.mode` |

### 6.3 站点初始化 (`init_site.py`)

**文件**: [init_site.py](../scripts/init_site.py)

**功能**: 创建下游 `awesome-*-hub` 站点仓库的目录结构和初始文件。

**创建内容**: awesome.yaml、`.github/workflows/daily-update.yml`、`.gitignore`、`README.md`

### 6.4 URL 分类工具 (`url_classify.py`)

**文件**: [url_classify.py](../scripts/url_classify.py)

**功能**: 判断 URL 是否为学术论文链接，检测资源类型。

- `is_academic_url(url)`: 匹配 16 个学术域名
- `detect_resource_type(url)`: 按域名规则判断资源类型
- `entry_is_paper(entry)`: 根据 abstract 或学术 URL 判断是否为论文

---

## 7. 完整 Pipeline

### 7.1 build.py 全量构建

```
build.py main()
  ├── Phase 1: 数据发现
  │   ├── Step 1: 自动发现上游 awesome 项目
  │   │     ├── discover_sources.py (GitHub API 搜索)
  │   │     └── ingest_source.py (多格式解析)
  │   ├── Step 2: arXiv 搜索 + 评分 + 深度分析
  │   │     ├── 首选: ResearcherAdapter
  │   │     └── fallback: sync.py (arXiv API + LLM 分类)
  │   ├── Step 2.1: HuggingFace 数据源 (hf_source.py)
  │   ├── Step 2.5: 分离非论文资源 (url_classify.py)
  │   └── Step 2.6: 过滤不相关论文 (relevance_filter.py)
  │
  ├── Phase 2: 数据处理
  │   ├── Step 3: 获取 teaser 图 (fetch_teasers.py, 5 级 fallback)
  │   ├── Step 3.1: 元数据富化 (enrich_metadata.py, 4 级 fallback)
  │   └── Step 4: 生成解读 + 分级 (generate_interpretations.py)
  │
  └── Phase 3: 网站生成
        ├── Step 5: 生成 Astro 网站 (generate_site)
        ├── Step 8: 生成 README (generate_readme_with_table)
        └── Step 9: npm build (build_site)
```

### 7.2 update.py 每日增量更新

```
update.py main()
  ├── Phase 1: 论文搜索
  │   ├── Step 1: 论文发现（ResearcherAdapter / arXiv API / HF）
  │   ├── Step 1.1: 跨天去重 (HistoryManager.filter_seen + backfill)
  │   └── Step 2: 去重合并 (ResearcherAdapter.deduplicate)
  │
  ├── Phase 2: 数据处理
  │   ├── Step 2.1: 记录历史 (HistoryManager.add_entries + prune)
  │   ├── Step 2.2: 元数据富化 (enrich_metadata.py)
  │   └── Step 3: 获取 teaser 图 (fetch_teasers.py)
  │
  └── Phase 3: 网站生成
        └── Step 4: 重新构建 (generate_site + build_site)
```

### 7.3 数据流

```
awesome.yaml
    │
    ├── config_bridge → researcher config → ResearcherAdapter
    │                                             │
    │                                             ▼
    └── sync.search_arxiv → classify_paper → paper_to_yaml
                                              │
                    deduplicate() ←───────────┘
                              │
                              ▼
                        papers.yaml
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
       fetch_teasers   enrich_metadata   generate_interpretations
              │               │                │
              └───────────────┴────────────────┘
                              │
                        generate_site → build_site → dist/
```

### 7.4 产出物

| 产出物 | 路径 | 说明 |
|--------|------|------|
| papers.yaml | `.local/data/papers.yaml` | 论文数据（含评分/解读/分级/元数据） |
| resources.yaml | `.local/data/resources.yaml` | 非论文资源 |
| teaser 图片 | `.local/assets/papers/{id}/teaser.png` | 论文预览图 |
| 解读文件 | `.local/resource/{id}/README.md` | 论文解读（含中文翻译） |
| 历史记录 | `.local/data/.history.json` | 跨天去重记录 |
| 网站构建产物 | `.local/website/dist/` | 静态 HTML 页面 |

