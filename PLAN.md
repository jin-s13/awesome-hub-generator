# awesome-hub-generator — 方案与计划

> 最后更新: 2026-06-15

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
├── data/papers.yaml            ← 自动生成的论文数据
├── src/                        ← Astro 网站源码（从模板生成）
├── .github/workflows/          ← 自动部署工作流
└── README.md
```

---

## 2. 系统架构

### 2.1 整体流程

```
                    ┌─────────────────────┐
                    │   awesome.yaml      │
                    │  (研究方向配置)      │
                    └────────┬────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                              ▼
    ┌──────────────────┐          ┌──────────────────┐
    │  全量构建 (build) │          │ 每日更新 (update) │
    │                  │          │                  │
    │ ① GitHub API 搜索 │          │ ① arxiv-daily-   │
    │   已有 awesome 项目│          │   researcher 运行 │
    │ ② 自动吸纳数据     │          │ ② 解析新论文      │
    │   (clone + 解析)   │          │ ③ 去重合并到 YAML │
    │ ③ arXiv 补充搜索   │          │ ④ 重新构建网站    │
    │   (去重)           │          │ ⑤ 部署到 Pages   │
    │ ④ LLM 分类打标签   │          │                  │
    │ ⑤ 生成 YAML 数据   │          │                  │
    │ ⑥ 从模板生成网站   │          │                  │
    │ ⑦ npm build       │          │                  │
    │ ⑧ 部署到 Pages    │          │                  │
    └────────┬─────────┘          └────────┬─────────┘
             │                             │
             └──────────────┬──────────────┘
                            ▼
                  ┌──────────────────┐
                  │  GitHub Pages    │
                  │  (静态网站)       │
                  └──────────────────┘
```

### 2.2 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| 配置 | `awesome.yaml` | 研究方向、关键词、arXiv 分类、网站信息 |
| GitHub 发现 | `scripts/discover_sources.py` | 自动搜索 GitHub 已有 awesome 项目并吸纳数据 |
| arXiv 搜索 | `scripts/sync.py` | arXiv API 搜索 + LLM 分类 + YAML 输出 |
| 全量构建 | `scripts/build.py` | 从零构建完整网站 |
| 每日更新 | `scripts/update.py` | 增量更新论文并重新构建 |
| 网站模板 | `templates/astro-site/` | Astro 静态网站模板（含 `{{占位符}}`） |
| 论文引擎 | `arxiv-daily-researcher/` | git submodule，论文发现与深度分析 |
| 全量构建工作流 | `.github/workflows/full-build.yml` | 手动触发全量构建 |
| 每日更新工作流 | `.github/workflows/daily-update.yml` | 定时触发增量更新 |

### 2.3 数据格式

论文数据存储在 `data/papers.yaml`，每条记录：

```yaml
- id: deepcad-2021
  title: "DeepCAD: A Deep Generative Network for Computer-Aided Design Models"
  year: 2021
  venue: "ICCV"
  category: "Generation"           # LLM 分类结果
  tags: ["CAD Sequence", "Deep Generative Model", "Parametric CAD"]
  representations: ["CAD Sequence", "Parametric CAD"]
  input_modalities: ["Latent"]
  output_modalities: ["CAD Sequence", "CAD Model"]
  links:
    paper: "https://arxiv.org/abs/2105.09492"
    code: "https://github.com/ChrisWu1997/DeepCAD"
  preview: "/assets/placeholder.svg"
  sources:
    - repo: "arxiv"
      category: "Generation"
```

---

## 3. 自动发现上游 Awesome 项目

### 3.1 设计思路

全量构建时，系统自动在 GitHub 上搜索该研究方向已有的 awesome 项目，直接 clone 并吸纳其数据，避免从零开始。

```
build.py 全量构建
    │
    ├── Phase 1: 自动发现上游 awesome 项目
    │     │
    │     ├── 1a. GitHub API 搜索（无需 Token，用量很小）
    │     │     ├── 按 topic 搜索: topic:awesome + topic:CAD
    │     │     ├── 按 README 内容搜索: "awesome" + "CAD" in:readme
    │     │     └── 按仓库名搜索: awesome-CAD in:name
    │     │
    │     ├── 1b. 过滤候选
    │     │     ├── min_stars >= 5
    │     │     ├── README 包含论文/工具列表（检测 Markdown 表格或列表）
    │     │     ├── 非 Fork、非 Archived
    │     │     └── 排除自己（避免循环引用）
    │     │
    │     ├── 1c. 按 stars 排序，取 Top 10
    │     │
    │     └── 1d. 自动采纳（无需用户确认）
    │           └── 进入 Phase 2
    │
    ├── Phase 2: 吸纳数据
    │     │
    │     ├── 2a. 抓取 README（git clone 或 raw 文件）
    │     ├── 2b. 自动检测格式
    │     │     ├── 📊 Markdown 表格 → MarkdownTableParser
    │     │     ├── 📋 Markdown 列表 → MarkdownListParser
    │     │     ├── 📁 YAML 文件 → YamlParser
    │     │     └── 📄 JSON 文件 → JsonParser
    │     ├── 2c. 解析为统一格式
    │     └── 2d. 去重合并到 data/papers.yaml
    │
    ├── Phase 3: arXiv 补充搜索
    │     ├── 搜索 arXiv 历史论文
    │     ├── 与已有数据去重
    │     └── LLM 分类后追加
    │
    └── Phase 4: 生成网站
```

### 3.2 GitHub Search API 策略

| 认证状态 | 频率限制 | 每页结果 | 总结果上限 | 是否够用 |
|---------|---------|---------|-----------|---------|
| 未认证（无 Token） | 10 次/分钟 | 5 条 | 前 100 条 | ✅ 够用 |
| 已认证（有 Token） | 30 次/分钟 | 100 条 | 前 1000 条 | ✅ 更好 |

我们的场景：3-5 个关键词 × 3 种搜索策略 = 9-15 次请求，未认证的 10 次/分钟完全够用。

GitHub Token 为可选项，通过环境变量 `GITHUB_TOKEN` 注入（和 API Key 一样走 Secrets），不配也能工作。

### 3.3 搜索策略详解

```python
def discover_awesome_sources(keywords):
    """
    自动发现 GitHub 上的 awesome 项目
    使用 GitHub Search API，无需额外爬虫
    """
    sources = set()
    
    # 策略 1: 按 topic 搜索
    # 很多 awesome 项目会打 awesome 和 领域 两个 topic
    for kw in keywords:
        query = f"topic:awesome topic:{kw}"
        results = github_api.search_repos(query, sort="stars", order="desc")
        sources.update(results)
    
    # 策略 2: 按 README 内容搜索
    query = ' '.join(f'"{kw}"' for kw in keywords)
    query = f'"awesome" "{query}" in:readme'
    results = github_api.search_repos(query, sort="stars", order="desc")
    sources.update(results)
    
    # 策略 3: 按仓库名搜索
    for kw in keywords:
        query = f"awesome-{kw} in:name"
        results = github_api.search_repos(query, sort="stars", order="desc")
        sources.update(results)
    
    # 过滤
    filtered = [
        s for s in sources
        if s.stars >= 5
        and not s.archived
        and not s.fork
        and has_paper_list(s.readme)
    ]
    
    return sorted(filtered, key=lambda s: s.stars, reverse=True)[:10]
```

### 3.4 格式自动检测与解析

```python
class FormatDetector:
    """自动检测上游仓库的数据格式"""
    
    @staticmethod
    def detect(readme_content: str, repo_files: List[str]) -> str:
        """检测 README 的格式类型"""
        
        # 1. 检查是否有 YAML/JSON 数据文件
        if any(f.endswith(('.yaml', '.yml')) for f in repo_files):
            return "yaml"
        if any(f.endswith('.json') for f in repo_files):
            return "json"
        
        # 2. 检查 README 中是否有 Markdown 表格
        table_rows = re.findall(r'^\|.+\|.+\|.+$', readme_content, re.MULTILINE)
        if len(table_rows) > 5:
            return "markdown_table"
        
        # 3. 检查是否有 Markdown 列表
        list_items = re.findall(r'^\s*-\s+\[.+\]\(.+\)', readme_content, re.MULTILINE)
        if len(list_items) > 5:
            return "markdown_list"
        
        return "unknown"
```

#### 支持的格式与解析器

| 格式 | 覆盖率 | 解析器 | 说明 |
|------|--------|--------|------|
| Markdown 表格 | ~90% | `MarkdownTableParser` | 大多数 awesome 项目使用 |
| Markdown 列表 | ~8% | `MarkdownListParser` | 少数项目使用 |
| YAML 文件 | ~1% | `YamlParser` | 结构化数据，解析最简单 |
| JSON 文件 | ~1% | `JsonParser` | 同上 |

#### Markdown 表格解析器

支持多种常见的 awesome 表格列名自动映射：

```python
COLUMN_MAP = {
    "title": ["title", "paper", "name"],
    "venue": ["venue", "conference", "journal", "publication"],
    "year": ["year", "date"],
    "links": ["links", "link", "code", "github", "resources"],
}
```

### 3.5 配置示例

```yaml
# awesome.yaml — 用户只需填这个
project:
  name: "Awesome CAD Hub"
  description: "A curated hub for CAD papers..."

research:
  keywords: ["CAD", "B-Rep", "parametric CAD"]
  arxiv_categories: ["cs.CV", "cs.GR"]
  date_from: "2020-01-01"

  # 自动发现配置
  auto_discover:
    enabled: true
    min_stars: 5           # 最少 star 数
    max_sources: 10        # 最多吸纳几个上游源
```

### 3.6 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 是否需要爬虫工具 | ❌ 不需要 | GitHub Search API 完全够用，AgentReach 等工具不适合批处理场景 |
| 是否要求用户配 Token | ❌ 不要求 | 未认证 10次/分钟，我们的场景完全够用 |
| 自动采纳还是用户确认 | ✅ 自动采纳 | 用户不需要知道有哪些上游源 |
| 是否配置已知源 | ❌ 不配置 | 假设用户完全不知道有哪些上游源 |
| 解析器优先级 | 表格 → 列表 → YAML/JSON | 覆盖 90%+ 的 awesome 项目 |

### 3.7 风险与应对

| 风险 | 应对 |
|------|------|
| 搜到不相关的仓库 | `min_stars` 过滤 + `has_paper_list()` 检测 README 是否包含论文列表 |
| 仓库格式无法解析 | 报错跳过该仓库，不影响整体流程 |
| 数据过时 | 以 arXiv 最新搜索为准，上游数据仅作为基础 |
| GitHub API 限流 | 未认证 10次/分钟够用；配 Token 后 30次/分钟更充裕 |

### 4.1 API Key 管理

**核心原则：Key 永不进代码仓库。**

| 场景 | 存储位置 | 安全机制 |
|------|---------|---------|
| GitHub Actions | GitHub Secrets（AES-256 加密） | 运行时注入环境变量，不出现在日志中 |
| 本地开发 | `.env` 文件 | 已在 `.gitignore` 中，git 不会跟踪 |

### 4.2 环境变量

```bash
# .env.example — 用户复制为 .env 后填写
ARK_API_KEY=sk-your-key-here           # 火山引擎 API Key
ARK_API_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL_NAME=deepseek-v4-flash-260425
```

在 GitHub Actions 中，用户需配置以下 Secrets：

| Secret 名称 | 说明 |
|-------------|------|
| `ARK_API_KEY` | 火山引擎 API Key |
| `ARK_API_BASE_URL` | API 地址（可选，有默认值） |
| `ARK_MODEL_NAME` | 模型名（可选，有默认值） |

---

## 5. 实现计划

### Phase 1: 核心框架 ✅ (已完成)

- [x] 项目目录结构
- [x] `awesome.yaml` 配置模板
- [x] Astro 网站模板（含占位符渲染）
- [x] `scripts/sync.py` — arXiv 搜索 + LLM 分类 + YAML 输出
- [x] `scripts/build.py` — 全量构建入口
- [x] `scripts/update.py` — 每日更新入口
- [x] GitHub Actions 工作流（full-build + daily-update）
- [x] `arxiv-daily-researcher` git submodule
- [x] README 和文档

### Phase 2: 自动发现与吸纳 ✅ (已完成)

- [x] `scripts/discover_sources.py` — GitHub API 搜索 + 过滤 + 排序
- [x] `scripts/ingest_source.py` — 格式检测 + 多格式解析器（表格/列表/YAML/JSON）
- [x] 集成到 `scripts/build.py` 全量构建流程
- [ ] 用 `awesome-cad-hub` 配置跑通全量构建
- [ ] 验证 LLM 分类质量
- [ ] 验证每日更新流程
- [ ] 验证 GitHub Pages 部署

### Phase 3: 开源准备（待完成）

- [ ] 完善 CONTRIBUTING.md
- [ ] 添加 LICENSE 文件
- [ ] 添加示例站点截图
- [ ] 发布到 GitHub

---

## 6. 使用指南

### 6.1 用户流程

```
1. Fork awesome-hub-generator
2. 编辑 awesome.yaml（填研究方向）
3. 在 GitHub Secrets 配置 ARK_API_KEY
4. 手动触发 Full build 工作流
5. 得到自动生成的 awesome 页面
6. 之后每天自动更新
```

### 6.2 配置示例（CAD 方向）

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
    - "CAD generation"
    - "text-to-CAD"
  arxiv_categories:
    - "cs.CV"
    - "cs.GR"
    - "cs.LG"
  date_from: "2020-01-01"
```

---

## 7. 技术选型

| 技术 | 用途 | 选择理由 |
|------|------|---------|
| Python 3.11 | 脚本语言 | 生态丰富，arXiv API 友好 |
| Astro 4 | 静态网站生成 | 高性能，组件化，当前项目已在用 |
| arXiv API | 论文搜索 | 免费，无需 API Key |
| volcengine-python-sdk | LLM 调用 | 火山引擎 DeepSeek，原生 SDK 支持 responses API |
| arxiv-daily-researcher | 论文发现引擎 | 成熟的开源工具，两种模式都支持 |
| GitHub Actions | CI/CD | 免费，与 GitHub Pages 深度集成 |
| GitHub Pages | 网站托管 | 免费静态托管 |

---

## 8. 附录

### 8.1 相关开源项目调研

见 [调研笔记](./docs/research-notes.md)（待创建）。

### 8.2 关键词参考

不同研究方向的 arXiv 分类参考：

| 研究方向 | 推荐 arXiv 分类 |
|---------|----------------|
| CAD / 3D 视觉 | cs.CV, cs.GR, cs.LG |
| NLP / LLM | cs.CL, cs.AI, cs.LG |
| 机器人 | cs.RO, cs.CV, cs.AI |
| 计算机图形学 | cs.GR, cs.CV |
| 机器学习理论 | cs.LG, stat.ML, cs.AI |
