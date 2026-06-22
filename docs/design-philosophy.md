# 设计哲学：从 Agent Skill 到 Fixed Workflow

> 本文档解释 awesome-hub-generator 与 dailypaper-skills 的设计理念差异，
> 以及如何以 Fixed Workflow + Agent Embedding 的方式吸收 dailypaper-skills 的能力。

---

## 1. 两种设计哲学对比

### dailypaper-skills: Agent Skill 模式

```
用户说 "今日论文推荐"
    │
    ▼
Claude Code 读取 SKILL.md
    │
    ▼
Agent 自主决策执行流程：
  ├── 决定先跑 fetch_and_score.py
  ├── 检查输出，如果失败则排查
  ├── 决定跑 enrich_papers.py
  ├── 检查富化结果
  ├── 自主生成点评（LLM 对话）
  ├── 自主生成笔记（LLM 对话）
  └── 最终告知用户结果
```

**特点**：
- 编排由 AI Agent 自主完成
- 错误处理靠 Agent 的对话式排查
- 灵活性高，能处理各种边界情况
- 但不可自动化（必须依赖 Claude Code 环境）
- 不可复现（每次结果可能不同）
- Token 消耗高（编排本身消耗上下文）

### awesome-hub-generator: Fixed Workflow 模式

```
定时触发 / 手动触发
    │
    ▼
Python 脚本按固定顺序执行：
  ├── Step 1: 论文发现（多源）       ← 纯 API 调用 + LLM 评分
  ├── Step 2: 元数据富化             ← 纯 HTML 解析
  ├── Step 3: teaser 图获取          ← 纯 HTTP 请求
  ├── Step 4: 解读生成 + 分级        ← LLM 调用 + 规则映射
  ├── Step 5: 网站构建               ← 纯构建
  └── Step 6: 部署                   ← GitHub Actions
```

**特点**：
- 编排由 Python 脚本固定控制
- 错误处理靠 try/except + fallback 链 + 重试机制
- 可完全自动化（GitHub Actions 定时触发）
- 可复现（相同输入产生相同输出）
- 零 Token 消耗在编排上

---

## 2. 核心原则：Fixed Workflow + Agent Embedding

我们的设计原则是：

> **编排用固定代码，推理用 LLM。**
> 能用规则解决的问题不用 LLM，必须用 LLM 的地方封装成独立模块。

### 决策树

```
遇到一个功能需求
    │
    ├── 能否用规则/API/计算解决？
    │     ├── 是 → 纯 Python 脚本（零 Token）
    │     │    例：API 调用、HTML 解析、字符串匹配、文件读写
    │     │
    │     └── 否 → 需要 LLM 推理？
    │           ├── 是 → 封装为 LLM 调用模块
    │           │    例：论文评分、深度分析、分类
    │           │
    │           └── 否 → 需要 Agent 自主决策？
    │                 ├── 极少情况 → 嵌入 Agent 子任务
    │                 │    例：复杂错误恢复、非常规格式解析
    │                 │
    │                 └── 绝大多数情况 → 重新思考设计
    │                      编排不应该依赖 Agent 自主决策
    │
    ▼
最终：Fixed Workflow 控制流程，LLM 作为计算资源被调用
```

---

## 3. 功能分类映射

以下是将 dailypaper-skills 的缺失功能按实现方式分类：

### 3.1 纯固定流程（零 Token 消耗）

这些功能直接用 Python 脚本实现，不涉及任何 LLM 调用：

| 功能 | 实现方式 | 对应文件 |
|------|---------|---------|
| HF Daily/Trending 数据源 | HTTP API 调用 + JSON 解析 | [hf_source.py](../scripts/hf_source.py) |
| arXiv HTML 元数据提取 | HTML 解析（正则） | [enrich_metadata.py](../scripts/enrich_metadata.py) |
| 图片可达性检查 | HTTP HEAD 请求 | [fetch_teasers.py](../scripts/fetch_teasers.py) |
| 图片本地化 | HTTP 下载 + 文件复制 | [fetch_teasers.py](../scripts/fetch_teasers.py) |
| PDF 图片提取 | pdfimages 命令调用 | [fetch_teasers.py](../scripts/fetch_teasers.py) |
| 跨天去重历史记录 | JSON 文件读写 + 日期比较 | [history_manager.py](../scripts/history_manager.py) |
| 历史记录裁剪 | 日期过滤 + 文件重写 | [history_manager.py](../scripts/history_manager.py) |
| 论文数不足回填 | 从历史记录按分数降序选取 | [history_manager.py](../scripts/history_manager.py) |
| 配置本地覆盖 | YAML 深度合并 | [config_bridge.py](../scripts/config_bridge.py) |
| 周末策略 | 检测日期 + 条件分支 | [history_manager.py](../scripts/history_manager.py) |

以下功能来自 gap-analysis 规划，尚未实现：

| 功能 | 实现方式 | 优先级 |
|------|---------|--------|
| PDF 机构提取 | pdftotext + 5 种规则策略 | P2 |
| 幂等设计 | 写入前比较文件内容 | P2 |
| Zotero 集成 | SQLite 数据库查询 | P2 |
| 后台守护进程 | 断点续传、rate limit | P2 |

### 3.2 LLM 调用模块（封装在固定流程中）

这些功能需要 LLM 推理，但**调用由固定流程控制**，LLM 作为计算资源被调用：

| 功能 | 实现方式 | 说明 |
|------|---------|------|
| 论文评分 | 调用 CHEAP_LLM 逐关键词评分 | 已有（researcher 子模块） |
| 深度分析 | 调用 SMART_LLM 分析 PDF | 已有（researcher 子模块） |
| TLDR 生成 | 调用 CHEAP_LLM 生成一句话摘要 | 已有（researcher 子模块） |
| 论文分级 | 基于 LLM 评分结果映射为三级 | [generate_interpretations.py](../scripts/generate_interpretations.py) |

### 3.3 Agent 嵌入（极少情况）

以下场景可能需要嵌入 Agent 子任务，但**编排仍由固定流程控制**：

| 场景 | 说明 | 触发条件 |
|------|------|---------|
| 复杂错误恢复 | 多次重试失败后，让 Agent 分析日志并决策 | 固定重试 N 次后仍失败 |
| 非常规格式解析 | 遇到无法解析的论文格式 | 规则解析器返回低置信度时 |
| 需要人类判断 | 边界情况需要人工确认 | Agent 整理信息后暂停等待 |

**实现方式**：固定流程中预留 Agent 调用点，通过 subprocess 调用 LLM 或外部 Agent 工具，获取结果后继续执行。

```
Fixed Workflow
    │
    ├── Step 1: 纯脚本处理 ─────────────── 99% 的情况
    ├── Step 2: 纯脚本处理
    ├── Step 3: LLM 调用（封装模块）─────── 作为计算资源
    ├── Step 4: 纯脚本处理
    ├── Step 5: [可选] Agent 嵌入 ──────── 极少数边界情况
    │              │
    │              ├── 调用 LLM 分析错误日志
    │              ├── 生成修复方案
    │              └── 返回结果继续流程
    └── Step 6: 纯脚本处理
```

---

## 4. 具体实现示例

### 示例 1：HF 数据源（纯固定流程）

```python
# scripts/hf_source.py
# 纯 API 调用，零 Token 消耗
# 使用标准库 urllib.request，不引入 requests 依赖

import json
import urllib.request
from datetime import datetime, timedelta

HF_DAILY_URL = "https://huggingface.co/api/daily_papers"
HF_TRENDING_URL = "https://huggingface.co/api/daily_papers?sort=trending&limit=50"

def fetch_hf_daily_papers(start_date=None, end_date=None):
    """按日期范围抓取 HF Daily Papers"""
    today = datetime.now().strftime("%Y-%m-%d")
    start = start_date or today
    end = end_date or start

    papers = []
    current = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while current <= end_dt:
        date_str = current.strftime("%Y-%m-%d")
        url = f"{HF_DAILY_URL}?date={date_str}&limit=100"
        req = urllib.request.Request(url, headers={"User-Agent": "awesome-hub-generator/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data:
                    paper_data = item.get("paper", {})
                    papers.append({
                        "arxiv_id": paper_data.get("id", ""),
                        "title": paper_data.get("title", ""),
                        "abstract": paper_data.get("summary", ""),
                        "authors": _parse_authors(paper_data.get("authors", [])),
                        "source": "huggingface-daily",
                    })
        except Exception:
            pass
        current += timedelta(days=1)
    return papers

def fetch_hf_trending_papers():
    """抓取 HF Trending Papers（全局，不依赖日期）"""
    req = urllib.request.Request(HF_TRENDING_URL, headers={"User-Agent": "awesome-hub-generator/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            papers = []
            for item in data:
                paper_data = item.get("paper", {})
                papers.append({
                    "arxiv_id": paper_data.get("id", ""),
                    "title": paper_data.get("title", ""),
                    "abstract": paper_data.get("summary", ""),
                    "authors": _parse_authors(paper_data.get("authors", [])),
                    "source": "huggingface-trending",
                })
            return papers
    except Exception:
        return []
```

### 示例 2：论文分级（规则映射）

```python
# 在 generate_interpretations.py 中

def grade_papers(papers: list[dict], config: dict) -> list[dict]:
    """
    根据评分将论文分为三级。
    不额外调用 LLM，直接基于已有评分结果映射。
    """
    grading = config.get("research", {}).get("grading", {})
    must_read_min = grading.get("must_read_min_score", 40)
    worth_reading_min = grading.get("worth_reading_min_score", 20)

    for paper in papers:
        score = paper.get("score", {}).get("total", 0)
        if score >= must_read_min:
            paper["grade"] = "must_read"       # 🔴 必读
        elif score >= worth_reading_min:
            paper["grade"] = "worth_reading"   # 🟡 值得看
        else:
            paper["grade"] = "skip"            # ⚪ 可跳过
    return papers
```

### 示例 3：配置本地覆盖（深度合并）

```python
# 在 config_bridge.py 中

def deep_merge(base: dict, override: dict) -> dict:
    """递归深度合并两个字典"""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def load_config_with_overrides(config_path: str = "awesome.yaml") -> dict:
    """加载 awesome.yaml，支持 awesome.local.yaml 覆盖"""
    import yaml
    path = Path(config_path)
    if not path.is_absolute():
        path = SITE_DIR / config_path
    config = yaml.safe_load(path.read_text(encoding="utf-8"))

    local_path = path.with_name("awesome.local.yaml")
    if local_path.exists():
        local_config = yaml.safe_load(local_path.read_text(encoding="utf-8"))
        config = deep_merge(config, local_config)
    return config
```

---

## 5. 实际架构

### build.py 全量构建流程

```
build.py main()
    │
    ├── Step 1:  自动发现上游 awesome 项目       ← discover_and_ingest()
    ├── Step 2:  arXiv 搜索 + 评分 + 深度分析    ← ResearcherAdapter / sync.py
    ├── Step 2.1: HuggingFace 数据源             ← hf_source.fetch_all_hf_papers()
    ├── Step 2.5: 分离非论文资源                  ← split_papers_resources()
    ├── Step 2.6: 过滤不相关论文                  ← filter_irrelevant_papers()
    ├── Step 3:  获取 teaser 图                  ← fetch_teasers.main()
    ├── Step 3.1: 元数据富化                     ← enrich_metadata.enrich_papers()
    ├── Step 4:  生成解读 + 分级                 ← generate_interpretations.main()
    ├── Step 5:  生成 Astro 网站                  ← generate_site()
    ├── Step 8:  生成 README                      ← generate_readme_with_table()
    └── Step 9:  npm build                        ← build_site()
```

### update.py 每日更新流程

```
update.py main()
    │
    ├── Step 1:  论文发现（多源）                 ← ResearcherAdapter / arXiv API
    ├── Step 1.1: HuggingFace 数据源             ← hf_source.fetch_all_hf_papers()
    ├── Step 1.2: 跨天去重历史记录               ← HistoryManager.filter_seen() + backfill()
    ├── Step 2:  去重合并到 papers.yaml           ← ResearcherAdapter.deduplicate()
    ├── Step 2.1: 记录到历史记录                  ← HistoryManager.add_entries() + prune()
    ├── Step 2.2: 元数据富化                     ← enrich_metadata.enrich_papers()
    ├── Step 3:  获取 teaser 图                  ← fetch_teasers.main()
    └── Step 4:  重新构建网站                     ← generate_site() + build_site()
```

### 新增模块

| 文件 | 职责 | 类型 |
|------|------|------|
| [hf_source.py](../scripts/hf_source.py) | HuggingFace Daily + Trending 数据源 | 纯 API 调用 |
| [enrich_metadata.py](../scripts/enrich_metadata.py) | arXiv HTML 元数据富化 | 纯 HTML 解析 |
| [history_manager.py](../scripts/history_manager.py) | 跨天去重历史记录管理 | 纯文件读写 |

### 配置本地覆盖

| 文件 | 机制 |
|------|------|
| [config_bridge.py](../scripts/config_bridge.py) | `deep_merge()` + `load_config_with_overrides()` |
| [build.py](../scripts/build.py) | `load_config()` 中检查 `awesome.local.yaml` |
| [update.py](../scripts/update.py) | `load_config()` 中检查 `awesome.local.yaml` |

---

## 6. 总结

| 设计原则 | 说明 |
|---------|------|
| **编排固定化** | 流程顺序由 Python 脚本控制，不依赖 Agent 自主决策 |
| **LLM 作为计算资源** | LLM 调用被封装在固定步骤中，像调用函数一样调用 LLM |
| **规则优先** | 能用规则解决的问题不用 LLM，降低成本和不确定性 |
| **Agent 仅用于边界** | Agent 嵌入仅用于极少数复杂错误恢复场景 |
| **可自动化** | 整个流程可在 GitHub Actions 中定时运行，无需人工介入 |
| **可测试** | 每个步骤都是独立模块，可单独编写单元测试 |
