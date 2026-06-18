# awesome-hub-generator — 方案与计划

> 最后更新: 2026-06-16 (Phase 1-5 全部完成)

---

## 1. 项目定位

**awesome-hub-generator** 是一个端到端的 awesome 页面生成器。用户只需配置研究方向关键词，系统自动完成：

1. **全量构建**：从 arXiv 搜索历史论文，LLM 自动分类打标签，生成完整的 Astro 静态网站
2. **每日更新**：定时检查 arXiv 新论文，筛选相关论文，自动追加到页面中
3. **自动部署**：通过 GitHub Actions 构建并部署到 GitHub Pages

### 两个项目的关系

```
awesome-hub-generator/          ← 通用生成器工具（本仓库）
├── awesome.yaml                ← 配置文件（用户修改）
├── arxiv-daily-researcher/     ← git submodule: 论文发现引擎
├── scripts/                    ← 构建脚本
├── templates/astro-site/       ← Astro 网站模板
└── .github/workflows/          ← CI/CD 工作流

        ↓ 运行后产出 ↓

awesome-cad-hub/                ← 具体 awesome 站点（产物仓库）
├── awesome.yaml                ← CAD 方向的配置
├── data/papers.yaml            ← 自动生成的论文数据（含评分/深度分析）
├── src/                        ← Astro 网站源码（从模板生成）
├── .github/workflows/          ← 自动部署工作流
└── README.md
```

---

## 2. 最终形态架构

### 2.1 设计原则

1. **arxiv-daily-researcher 作为核心论文引擎**，直接 Python import 调用，而非子进程
2. **双 LLM 策略**：CHEAP_LLM 评分筛选 + SMART_LLM 深度分析，而非每篇都调 SMART_LLM
3. **配置统一**：awesome.yaml 作为唯一用户配置入口，自动生成 researcher 的 config.json
4. **数据富化**：papers.yaml 保留评分、TLDR、深度分析等结构化信息
5. **网站增强**：展示评分徽章、TLDR、深度分析摘要、关键词趋势

### 2.2 整体流程

```
                    ┌─────────────────────┐
                    │   awesome.yaml      │
                    │  (用户唯一配置)      │
                    └────────┬────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                              ▼
    ┌──────────────────────┐      ┌──────────────────────┐
    │  全量构建 (build.py)  │      │ 每日更新 (update.py)  │
    │                      │      │                      │
    │ Phase 1: 自动发现     │      │ Step 1: 调用          │
    │   GitHub awesome 项目 │      │   arxiv-daily-        │
    │   并吸纳数据          │      │   researcher 的        │
    │                      │      │   DailyResearchPipeline│
    │ Phase 2: arXiv 搜索   │      │   (Python import)     │
    │   通过 researcher 的   │      │                      │
    │   DailyResearchPipeline│      │ Step 2: 适配层转换    │
    │   (Python import)     │      │   → papers.yaml       │
    │                      │      │                      │
    │ Phase 3: 适配层转换    │      │ Step 3: 重新构建网站   │
    │   → papers.yaml       │      │                      │
    │                      │      │                      │
    │ Phase 4: 生成 Astro   │      │                      │
    │   网站 + npm build    │      │                      │
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

### 2.3 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| 配置 | `awesome.yaml` | 研究方向、关键词、arXiv 分类、网站信息（**用户唯一入口**） |
| 配置生成器 | `scripts/config_bridge.py` | 将 awesome.yaml 转为 researcher 的 config.json + .env |
| GitHub 发现 | `scripts/discover_sources.py` | 自动搜索 GitHub 已有 awesome 项目并吸纳数据 |
| arXiv 搜索 | `scripts/sync.py` | **降级为 fallback**：仅当 researcher 不可用时使用 |
| 适配层 | `scripts/researcher_adapter.py` | **核心新增**：封装 researcher 调用 + 结果转换 |
| 全量构建 | `scripts/build.py` | 从零构建完整网站（集成 researcher） |
| 每日更新 | `scripts/update.py` | 增量更新论文并重新构建（集成 researcher） |
| 网站模板 | `templates/astro-site/` | Astro 静态网站模板（含 `{{占位符}}`） |
| 论文引擎 | `arxiv-daily-researcher/` | git submodule，论文发现与深度分析 |
| 全量构建工作流 | `.github/workflows/full-build.yml` | 手动触发全量构建 |
| 每日更新工作流 | `.github/workflows/daily-update.yml` | 定时触发增量更新 |

---

## 3. 配置统一方案

### 3.1 设计目标

- **awesome.yaml 是用户唯一需要编辑的配置文件**
- 自动生成 `arxiv-daily-researcher/configs/config.json` 和 `.env`
- 用户无需了解 researcher 的内部配置结构

### 3.2 awesome.yaml（增强版）

```yaml
# =============================================================================
# awesome-hub-generator 配置文件
# 用户只需编辑此文件，其余自动生成
# =============================================================================

project:
  name: "Awesome CAD Hub"
  description: "A curated hub for CAD papers, datasets, tools, and Neural CAD research."
  github_url: "https://github.com/your-username/awesome-cad-hub"
  site_url: "https://your-username.github.io/awesome-cad-hub"

research:
  # === 搜索关键词（支持引号包裹短语） ===
  keywords:
    - "CAD"
    - "B-Rep"
    - "parametric CAD"
    - "CAD generation"
    - "CAD reconstruction"
    - "text-to-CAD"
    - "CAD program"

  # === 负向关键词（命中直接排除） ===
  negative_keywords:
    - "medical imaging"
    - "weather forecast"
    - "protein folding"
    - "drug discovery"

  # === 领域加分词（额外加权） ===
  domain_boost_keywords:
    - "neural CAD"
    - "generative CAD"
    - "point cloud"
    - "mesh"

  # === arXiv 分类过滤 ===
  arxiv_categories:
    - "cs.CV"
    - "cs.GR"
    - "cs.LG"
    - "cs.AI"

  # === 全量构建的起始日期 ===
  date_from: "2020-01-01"

  # === 每日搜索的天数范围 ===
  daily_search_days: 3

  # === 自动发现 GitHub 已有 awesome 项目 ===
  auto_discover:
    enabled: true
    min_stars: 5
    max_sources: 10

  # === 评分配置 ===
  scoring:
    base_score: 1.5            # 基础分
    weight_coefficient: 2.5    # 权重系数
    max_score_per_keyword: 10  # 每个关键词最高分
    author_bonus:              # 专家作者加分
      enabled: true
      bonus_points: 5.0
      expert_authors: []

  # === 深度分析配置 ===
  deep_analysis:
    enabled: true               # 是否对高分论文做 PDF 深度分析
    min_score: 30               # 最低评分门槛
    pdf_parser: "pymupdf"       # pymupdf（本地）或 mineru（云端）
    max_papers_per_run: 10      # 每次运行最多分析多少篇

  # === 关键词趋势追踪 ===
  keyword_tracking:
    enabled: true
    report_frequency: "weekly"  # daily / weekly / monthly / always

website:
  sections:
    papers: true
    datasets: true
    tools: true
  nav:
    - label: "Home"
      href: "/"
    - label: "Papers"
      href: "/papers"
    - label: "Trends"
      href: "/trends"
    - label: "Datasets"
      href: "/datasets"
    - label: "Tools"
      href: "/tools"
  footer: |
    Built with <a href="https://github.com/your-username/awesome-hub-generator">awesome-hub-generator</a>.
```

### 3.3 配置桥接器（config_bridge.py）

```python
"""
config_bridge.py — 配置桥接器

将 awesome.yaml 转换为 arxiv-daily-researcher 所需的：
1. configs/config.json（搜索、评分、报告配置）
2. .env（LLM API Key 等敏感信息）
"""

def awesome_to_researcher_config(awesome_config: dict) -> dict:
    """将 awesome.yaml 配置转为 researcher 的 config.json 格式"""
    research = awesome_config.get("research", {})
    scoring = research.get("scoring", {})
    
    return {
        "search_settings": {
            "search_days": research.get("daily_search_days", 3),
            "max_results": 100,
        },
        "target_domains": {
            "domains": research.get("arxiv_categories", ["cs.CV", "cs.LG"]),
        },
        "keywords": {
            "primary_keywords": {
                "weight": 1.0,
                "keywords": research.get("keywords", []),
            },
            "negative_keywords": research.get("negative_keywords", []),
            "domain_boost_keywords": research.get("domain_boost_keywords", []),
            "research_context": f"研究方向: {awesome_config['project']['name']}",
        },
        "scoring_settings": {
            "keyword_relevance_score": {
                "max_score_per_keyword": scoring.get("max_score_per_keyword", 10),
            },
            "author_bonus": scoring.get("author_bonus", {"enabled": False}),
            "passing_score_formula": {
                "base_score": scoring.get("base_score", 1.5),
                "weight_coefficient": scoring.get("weight_coefficient", 2.5),
            },
            "include_all_in_report": True,
        },
        # ... 更多映射
    }
```

---

## 4. 适配层设计（researcher_adapter.py）

### 4.1 设计目标

- 直接 Python import 调用 `DailyResearchPipeline`，而非 subprocess
- 获取结构化的 `RunResult`，而非解析 markdown 报告
- 将 researcher 的输出转换为 `papers.yaml` 格式
- 保留评分、TLDR、深度分析等富信息

### 4.2 接口设计

```python
"""
researcher_adapter.py — arxiv-daily-researcher 适配层

职责：
1. 配置同步：确保 researcher 的 config.json 与 awesome.yaml 一致
2. 调用执行：直接 import 调用 DailyResearchPipeline
3. 结果转换：将 RunResult 转为 papers.yaml 格式
4. 历史管理：维护论文去重状态
"""

class ResearcherAdapter:
    """
    arxiv-daily-researcher 适配器。
    
    封装 researcher 的调用细节，对外提供简洁接口。
    """
    
    def __init__(self, awesome_config: dict):
        self.config = awesome_config
        self.researcher_dir = ROOT / "arxiv-daily-researcher"
    
    def sync_config(self) -> None:
        """将 awesome.yaml 同步到 researcher 的 config.json 和 .env"""
        # 1. 生成 config.json
        researcher_config = awesome_to_researcher_config(self.config)
        config_path = self.researcher_dir / "configs" / "config.json"
        config_path.write_text(json.dumps(researcher_config, indent=2))
        
        # 2. 生成 .env（从当前环境变量）
        env_path = self.researcher_dir / ".env"
        env_vars = {
            "CHEAP_LLM__API_KEY": os.environ.get("ARK_API_KEY", ""),
            "CHEAP_LLM__BASE_URL": os.environ.get("ARK_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            "CHEAP_LLM__MODEL_NAME": os.environ.get("ARK_MODEL_NAME", "deepseek-v4-flash-260425"),
            "SMART_LLM__API_KEY": os.environ.get("ARK_API_KEY", ""),
            "SMART_LLM__BASE_URL": os.environ.get("ARK_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            "SMART_LLM__MODEL_NAME": os.environ.get("SMART_MODEL_NAME", "deepseek-v4-flash-260425"),
        }
        # ... 写入 .env
    
    def run_daily_research(self) -> RunResult:
        """运行每日研究模式，返回结构化结果"""
        # 先同步配置
        self.sync_config()
        
        # 直接 import 调用（而非 subprocess）
        sys.path.insert(0, str(self.researcher_dir / "src"))
        from config import settings
        from modes.daily_research import DailyResearchPipeline
        
        # 重新加载配置
        settings.load_from_search_config()
        
        # 执行 pipeline
        pipeline = DailyResearchPipeline()
        result = pipeline.run()
        return result
    
    def convert_to_papers_yaml(self, result: RunResult) -> List[dict]:
        """将 RunResult 转换为 papers.yaml 格式"""
        papers = []
        for source, scored_list in result.scored_papers_by_source.items():
            for scored in scored_list:
                paper = scored["paper_metadata"]
                score_resp = scored["score_response"]
                
                entry = {
                    "id": slugify(f"{paper.title[:60]}-{paper.published_date.year}"),
                    "title": paper.title,
                    "year": paper.published_date.year,
                    "venue": infer_venue(paper.categories),
                    "category": "Others",  # 后续可用 LLM 再分类
                    "tags": score_resp.extracted_keywords[:8],
                    "links": {
                        "paper": paper.url,
                        "pdf": paper.pdf_url,
                    },
                    "score": {
                        "total": score_resp.total_score,
                        "keyword_scores": score_resp.keyword_scores,
                        "author_bonus": score_resp.author_bonus,
                        "passing_score": score_resp.passing_score,
                        "is_qualified": score_resp.is_qualified,
                    },
                    "tldr": score_resp.tldr,
                    "reasoning": score_resp.reasoning,
                    "preview": "/assets/placeholder.svg",
                    "sources": [{"repo": source, "category": "arxiv"}],
                }
                
                # 如果有深度分析结果
                analysis = result.analyses_by_source.get(source, [])
                for a in analysis:
                    if a.get("paper_id") == paper.paper_id:
                        entry["analysis"] = a["analysis"]
                        break
                
                papers.append(entry)
        
        return papers
```

### 4.3 调用关系

```
update.py / build.py
    │
    ├── config_bridge.sync_config()
    │     └── 写入 arxiv-daily-researcher/configs/config.json
    │     └── 写入 arxiv-daily-researcher/.env
    │
    ├── ResearcherAdapter.run_daily_research()
    │     └── import DailyResearchPipeline
    │     └── pipeline.run()
    │     └── 返回 RunResult（结构化数据）
    │
    ├── ResearcherAdapter.convert_to_papers_yaml()
    │     └── 将 RunResult 转为 List[dict]
    │     └── 保留 score / tldr / analysis 字段
    │
    ├── sync_papers()  # 去重合并到 papers.yaml
    │
    └── build_site()   # 重新生成网站
```

---

## 5. 增强数据模型

### 5.1 papers.yaml（增强版）

```yaml
- id: pi0-2025
  title: "Pi0: A Vision-Language-Action Flow Model"
  year: 2025
  venue: "arXiv"
  category: "Generation"            # LLM 分类
  tags: ["VLA", "Flow Matching", "Robot Foundation Model", "Imitation Learning"]
  representations: ["Action Sequence"]
  input_modalities: ["Image", "Text", "Robot State"]
  output_modalities: ["Action", "Robot Control"]
  links:
    paper: "https://arxiv.org/abs/2504.12345"
    code: "https://github.com/example/pi0"
    project: "https://pi0.example.com"
  preview: "/assets/papers/pi0-2025/teaser.png"
  
  # === 新增：评分信息 ===
  score:
    total: 85.5
    keyword_scores:
      "world model": 9.0
      "diffusion model": 8.0
      "embodied ai": 9.5
    author_bonus: 0.0
    passing_score: 20.0
    is_qualified: true
  
  # === 新增：一句话摘要 ===
  tldr: "提出了一种基于流匹配的视觉-语言-动作基础模型，在多个机器人操作任务上达到 SOTA。"
  
  # === 新增：评分理由 ===
  reasoning: "论文核心方法涉及流匹配（与扩散模型相关），面向具身 AI 和机器人操作，与关键词高度相关。"
  
  # === 新增：深度分析 ===
  analysis:
    innovations:
      - "首次将流匹配应用于 VLA 基础模型训练"
      - "提出跨本体动作表示方法"
    methodology: "基于预训练 VLM，使用流匹配目标在机器人数据集上微调..."
    key_results: "在 7 个基准上平均提升 15.3%"
    limitations:
      - "仅在仿真环境中验证"
      - "需要大规模计算资源"
    tech_stack: ["Flow Matching", "VLM", "Diffusion Transformer"]
  
  sources:
    - repo: "arxiv"
      category: "Generation"
```

### 5.2 字段说明

| 字段 | 来源 | 用途 |
|------|------|------|
| `score` | researcher CHEAP_LLM 评分 | 网站排序、筛选、展示评分徽章 |
| `tldr` | researcher CHEAP_LLM 评分 | 论文卡片展示一句话摘要 |
| `reasoning` | researcher CHEAP_LLM 评分 | 详情页展示评分依据 |
| `analysis` | researcher SMART_LLM 深度分析 | 详情页展示完整分析 |
| `preview` | 多路图片获取（arXiv HTML/项目主页/PDF） | 卡片展示论文 teaser 图 |

---

## 6. 网站展示增强

### 6.1 论文卡片增强

当前卡片：
```
┌──────────────────────────────┐
│  [placeholder]               │
│  Pi0: A VLA Flow Model       │
│  arXiv 2025                  │
│  Tags: VLA, Flow Matching    │
└──────────────────────────────┘
```

增强后卡片：
```
┌──────────────────────────────┐
│  [论文 teaser 图]      ⭐85  │
│  Pi0: A VLA Flow Model       │
│  arXiv 2025                  │
│  "提出了一种基于流匹配的      │
│    VLA 基础模型..."           │
│  Tags: VLA, Flow Matching    │
│  🔥 必读                     │
└──────────────────────────────┘
```

### 6.2 论文详情页（新增）

点击卡片后展示详情页：

```
┌─────────────────────────────────────────┐
│  Pi0: A Vision-Language-Action Flow ... │
│  ⭐ 85.5 · arXiv 2025 · 🔥 必读         │
│  [teaser 图]                            │
│                                         │
│  TLDR                                    │
│  提出了一种基于流匹配的 VLA 基础模型...  │
│                                         │
│  📊 评分详情                             │
│  world model        ██████████ 9.0      │
│  diffusion model    ████████░░ 8.0      │
│  embodied ai        ██████████ 9.5      │
│                                         │
│  🔬 深度分析                             │
│  ## 创新点                               │
│  - 首次将流匹配应用于 VLA 基础模型训练    │
│  - 提出跨本体动作表示方法                 │
│  ## 方法                                 │
│  ...                                     │
│  ## 局限性                               │
│  - 仅在仿真环境中验证                     │
│                                         │
│  📁 资源                                 │
│  [PDF] [Code] [Project Page]             │
└─────────────────────────────────────────┘
```

### 6.3 关键词趋势页（新增）

```
┌─────────────────────────────────────────┐
│  📈 关键词趋势                           │
│                                         │
│  过去 30 天出现频率 Top 15               │
│                                         │
│  world model        ████████████ 25     │
│  diffusion model    ██████████ 20       │
│  VLA                ████████ 16         │
│  flow matching      ██████ 12           │
│  ...                                     │
│                                         │
│  趋势热图（按周）                         │
│  ┌────┬────┬────┬────┬────┐             │
│  │ ██ │ ██ │ ██ │ ██ │ ██ │ world model│
│  │ ██ │ ██ │ ██ │ ██ │ ██ │ diffusion  │
│  │ ██ │ ██ │ ██ │ ██ │ ██ │ VLA        │
│  └────┴────┴────┴────┴────┘             │
│  W1   W2   W3   W4   W5                │
└─────────────────────────────────────────┘
```

---

## 7. 工作流改造

### 7.1 全量构建（build.py）

```
build.py 全量构建
    │
    ├── Phase 1: 自动发现上游 awesome 项目
    │     └── 同现有逻辑（不变）
    │
    ├── Phase 2: arXiv 搜索 + 评分 + 深度分析
    │     ├── 2a. config_bridge.sync_config()
    │     │     └── awesome.yaml → researcher config.json + .env
    │     ├── 2b. ResearcherAdapter.run_daily_research()
    │     │     └── import DailyResearchPipeline
    │     │     └── 设置 search_days 为 date_from 至今
    │     │     └── 返回 RunResult
    │     ├── 2c. ResearcherAdapter.convert_to_papers_yaml()
    │     │     └── RunResult → List[dict]
    │     └── 2d. sync_papers() 去重合并到 papers.yaml
    │
    ├── Phase 3: 生成 Astro 网站
    │     └── 同现有逻辑（模板渲染 + npm build）
    │
    └── Phase 4: 部署到 GitHub Pages
          └── 同现有逻辑
```

### 7.2 每日更新（update.py）

```
update.py 每日更新
    │
    ├── Step 1: config_bridge.sync_config()
    │
    ├── Step 2: ResearcherAdapter.run_daily_research()
    │     ├── 搜索最近 N 天（daily_search_days）
    │     ├── CHEAP_LLM 评分筛选
    │     ├── SMART_LLM 深度分析（高分论文）
    │     └── 返回 RunResult
    │
    ├── Step 3: 转换为 papers.yaml 并去重合并
    │
    ├── Step 4: 关键词趋势处理
    │     └── 读取 researcher 的 keywords.db
    │     └── 生成趋势数据供网站展示
    │
    └── Step 5: 重新构建网站 + 部署
```

### 7.3 Fallback 策略

当 `arxiv-daily-researcher` 不可用时（如 submodule 未初始化），自动降级到现有的 `sync.py`：

```python
def run_paper_discovery(config):
    """运行论文发现，优先使用 researcher，失败时降级"""
    try:
        adapter = ResearcherAdapter(config)
        result = adapter.run_daily_research()
        return adapter.convert_to_papers_yaml(result)
    except (ImportError, FileNotFoundError) as e:
        logger.warning(f"researcher 不可用 ({e})，降级到 sync.py")
        from sync import search_arxiv
        papers = search_arxiv(...)
        return papers
```

---

## 8. GitHub Actions 环境变量

### 8.1 统一环境变量

用户只需配置一套环境变量，脚本自动分发给 researcher：

```bash
# .env.example — 用户唯一需要配置的
ARK_API_KEY=sk-your-key-here
ARK_API_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL_NAME=deepseek-v4-flash-260425     # 用于 CHEAP_LLM（评分）
SMART_MODEL_NAME=deepseek-v4-flash-260425   # 用于 SMART_LLM（深度分析，可选）
```

### 8.2 GitHub Secrets

| Secret 名称 | 对应 researcher 变量 | 说明 |
|-------------|---------------------|------|
| `ARK_API_KEY` | `CHEAP_LLM__API_KEY` + `SMART_LLM__API_KEY` | 共用同一个 Key |
| `ARK_API_BASE_URL` | `CHEAP_LLM__BASE_URL` + `SMART_LLM__BASE_URL` | API 地址 |
| `ARK_MODEL_NAME` | `CHEAP_LLM__MODEL_NAME` | 评分用模型 |
| `SMART_MODEL_NAME` | `SMART_LLM__MODEL_NAME` | 深度分析用模型（默认同 ARK_MODEL_NAME） |

---

## 9. 实现计划

### Phase 1: 配置桥接 ✅

- [x] 设计 `awesome.yaml` 增强版（含评分/负向关键词/深度分析配置）
- [x] 实现 `scripts/config_bridge.py`
  - [x] `awesome_to_researcher_config()` — 配置映射
  - [x] `generate_env_file()` — .env 自动生成
  - [x] `sync_config()` — 一键同步

### Phase 2: 适配层 ✅

- [x] 实现 `scripts/researcher_adapter.py`
  - [x] `ResearcherAdapter.sync_config()` — 配置同步
  - [x] `ResearcherAdapter.run_daily_research()` — Python import 调用
  - [x] `ResearcherAdapter.convert_to_papers_yaml()` — 结果转换
  - [x] `ResearcherAdapter.deduplicate()` — 去重合并

### Phase 3: 改造构建流程 ✅

- [x] 改造 `scripts/build.py`
  - [x] Phase 2 替换为 researcher 调用（含 fallback）
  - [x] 保留上游 awesome 项目吸纳逻辑
  - [x] 保留 fallback 到 sync.py
- [x] 改造 `scripts/update.py`
  - [x] 替换 subprocess 调用为 Python import
  - [x] 替换 markdown 解析为结构化数据
  - [x] 集成 fallback 机制

### Phase 4: 网站增强 ✅

- [x] 论文卡片展示评分徽章和 TLDR
- [x] 论文详情页（含深度分析）
- [x] 关键词趋势页
- [x] 论文 teaser 图自动获取（`scripts/fetch_teasers.py`）

### Phase 5: 验证与优化 ✅

- [x] 43 个单元测试全部通过
- [x] Astro 构建验证（25 页面生成成功）
- [x] Fallback 机制验证
- [x] 数据模型升级验证（ScoreInfo / AnalysisInfo 类型）

---

## 10. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| researcher 的 API 变化 | 适配层失效 | 锁定 submodule 版本，适配层加测试 |
| 双 LLM 调用增加成本 | 运行成本上升 | CHEAP_LLM 用低成本模型（如 deepseek-flash），仅高分论文调 SMART_LLM |
| researcher 的 config.json 格式变化 | 配置同步失败 | config_bridge 加 schema 校验 |
| GitHub Actions 运行超时 | 构建失败 | 限制深度分析数量（max_papers_per_run），增加超时时间 |
| 用户只有一个 API Key | 无法区分 CHEAP/SMART | 默认共用同一个 Key，仅区分 model_name |

---

## 11. 附录

### 11.1 与 dailypaper-skills 的对比借鉴

| 特性 | dailypaper-skills | 我们的方案 |
|------|-------------------|-----------|
| 运行环境 | Claude Code Skills | Python 脚本 + GitHub Actions |
| 输出目标 | Obsidian 笔记 | Astro 静态网站 |
| 评分机制 | 关键词命中（标题+3，摘要+1） | LLM 逐关键词评分（0-10）× 权重 |
| 图片获取 | arXiv HTML → 项目主页 → PDF | 同左（后续实现） |
| 概念库 | Obsidian [[双向链接]] | 关键词趋势追踪 + 标签系统 |
| 去重 | .history.json 30 天 | researcher 内置历史 + 标题/ID 去重 |

### 11.2 技术选型

| 技术 | 用途 | 选择理由 |
|------|------|---------|
| Python 3.11 | 脚本语言 | 生态丰富，与 researcher 一致 |
| Astro 4 | 静态网站生成 | 高性能，组件化 |
| arxiv-daily-researcher | 论文发现引擎 | 成熟开源，双 LLM 策略，深度分析 |
| GitHub Actions | CI/CD | 免费，与 GitHub Pages 集成 |
| GitHub Pages | 网站托管 | 免费静态托管 |
| volcengine-python-sdk | LLM 调用 | 火山引擎 DeepSeek |
