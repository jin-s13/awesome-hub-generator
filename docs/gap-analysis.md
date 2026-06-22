# awesome-hub-generator 能力差距分析

> 目标：让 awesome-hub-generator 包含 dailypaper-skills 的完整能力（笔记功能除外）。
> 最后更新: 2026-06-22

---

## 目录

1. [吸收状态总览](#1-吸收状态总览)
2. [已吸收功能](#2-已吸收功能)
3. [部分吸收功能](#3-部分吸收功能)
4. [未吸收功能](#4-未吸收功能)
5. [明确不吸收的功能](#5-明确不吸收的功能)
6. [实现优先级建议](#6-实现优先级建议)

---

## 1. 吸收状态总览

| 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|
| daily-papers | fetch_and_score.py | 已吸收 | HF/arXiv 抓取已吸收，评分算法沿用 LLM 方案 |
| daily-papers | enrich_papers.py | 部分 | 元数据富化已吸收，需扩展 TeX source + PDF fallback |
| daily-papers | parse_arxiv.py | 已吸收 | arXiv XML 解析内联到 `sync.py` |
| daily-papers | extract_affiliations.py | 部分 | PDF 机构提取，作为元数据富化的最终 fallback |
| daily-papers | download_note_images.py | 不吸收 | Obsidian 专属功能 |
| daily-papers-review | update_history.py | 已吸收 | 被 `history_manager.py` 替代并增强 |
| daily-papers-notes | backfill_links.py | 不吸收 | Obsidian 专属功能 |
| paper-reader | paper_daemon.py | 待定 | 后台批量处理可集成，但不依赖 Zotero |
| paper-reader | zotero_helper.py | 不吸收 | 明确不做 |
| paper-reader | reorganize_notes.py | 不吸收 | Obsidian 专属功能 |
| _shared | user_config.py | 部分 | 配置管理思路类似但结构不同 |
| _shared | moc_builder.py | 不吸收 | Obsidian 专属功能 |

---

## 2. 已吸收功能

以下功能已实现，不再需要开发：

| 功能 | 对应文件 | 说明 |
|------|---------|------|
| arXiv API 论文搜索 | [sync.py](../scripts/sync.py) | 关键词分批搜索，XML 解析 |
| arXiv XML 解析 | [sync.py](../scripts/sync.py) | 内联在 `search_arxiv` 中 |
| HuggingFace Daily 数据源 | [hf_source.py](../scripts/hf_source.py) | 按日期范围抓取 |
| HuggingFace Trending 数据源 | [hf_source.py](../scripts/hf_source.py) | 全局 trending 抓取 |
| 多源合并去重 | [hf_source.py](../scripts/hf_source.py) | 同一 arxiv_id 合并 sources |
| arXiv HTML 元数据提取 | [enrich_metadata.py](../scripts/enrich_metadata.py) | 作者/机构/方法名/章节/图表 |
| 图片可达性检查 | [fetch_teasers.py](../scripts/fetch_teasers.py) | HTTP HEAD 检查 |
| 图片本地化 | [fetch_teasers.py](../scripts/fetch_teasers.py) | 下载远程图片到 assets |
| PDF 图片提取 | [fetch_teasers.py](../scripts/fetch_teasers.py) | pdfimages + pdftoppm fallback |
| 跨天去重历史记录 | [history_manager.py](../scripts/history_manager.py) | JSON 文件管理 |
| 历史记录裁剪 | [history_manager.py](../scripts/history_manager.py) | 过期自动删除 |
| 论文数不足回填 | [history_manager.py](../scripts/history_manager.py) | 从历史按 score 回填 |
| 周末策略 | [history_manager.py](../scripts/history_manager.py) | 周末放宽 trending 去重 |
| 配置本地覆盖 | [config_bridge.py](../scripts/config_bridge.py) | awesome.local.yaml 深度合并 |
| 论文分级 | [generate_interpretations.py](../scripts/generate_interpretations.py) | 必读/值得看/可跳过 |

---

## 3. 部分吸收功能

以下功能已实现但需要增强：

### 3.1 元数据富化（多级 fallback 链）

**参考**: `enrich_papers.py` + `extract_affiliations.py`

**当前实现**: `enrich_metadata.py` 从 arXiv HTML 和 abs 页面提取元数据（作者、机构、方法名、章节标题、图表标题）。

**需要扩展的 fallback 链**（按优先级排列）：

```
提取机构/作者
    │
    ├── 1. arXiv HTML 页面         ← 已实现（enrich_metadata.py）
    ├── 2. arXiv abs 页面 meta 标签 ← 已实现（enrich_metadata.py）
    ├── 3. TeX source 解析         ← 未实现（新增）
    └── 4. PDF 文本提取            ← 未实现（新增）
         └── 5 种策略：关键词匹配、编号脚注、版权行、全文扫描、位置启发式
```

**TeX source 解析**: 从 arXiv 获取 TeX 源文件（`https://arxiv.org/e-print/{arxiv_id}`），解析 `\author`、`\affiliation`、`\institute` 等 LaTeX 命令提取机构信息。这是比 PDF 更干净的来源。

**PDF 机构提取**: 作为最终 fallback，使用 `pdftotext` 提取文本后，用 5 种策略匹配机构名。

### 3.2 Trending 信息展示

**参考**: `fetch_and_score.py` 中的 trending upvotes

**当前实现**: `hf_source.py` 抓取了 trending 论文的 upvotes 信息，存储在 `paper["score"]["upvotes"]` 中。

**建议**: Trending 信息保留在前端展示（如论文卡片上显示 upvotes 数），但不影响评分。用户可以通过 upvotes 了解社区关注度。

---

## 4. 未吸收功能

### 4.1 幂等设计

**参考**: `moc_builder.py` 中的 `write_if_changed()`

- **功能**: 写入前比较文件内容，内容不变不重写，减少 git 变动
- **工作量**: 小（0.5 天）
- **建议**: 在 `build.py`/`update.py` 的 `save_yaml` 调用中应用

### 4.2 方法名提取增强

**参考**: `enrich_papers.py` 中的 `extract_method_names()`

- **功能**: 当前实现较简化（正则提取 CamelCase 词），可增加频率分析和停用词过滤
- **工作量**: 小（0.5 天）
- **建议**: 增强 `enrich_metadata.py` 中的 `_extract_method_names()` 函数

### 4.3 元数据 HTML 并发优化

**参考**: `enrich_papers.py` 中的 asyncio + Semaphore 模式

- **功能**: 当前用 `ThreadPoolExecutor`，可改为 asyncio 提升并发效率
- **工作量**: 小（0.5 天）
- **建议**: 优化 `enrich_metadata.py` 中的 `enrich_papers()` 函数

### 4.4 论文详情页链接回填

**参考**: `backfill_links.py`

- **功能**: 将生成的解读/笔记链接回填到论文卡片或 README 中
- **工作量**: 小（0.5 天）
- **建议**: 在 `generate_interpretations.py` 完成后，将解读链接回填到 `papers.yaml` 或 README

### 4.5 自动发现增强

**参考**: `discover_sources.py`

- **功能**: 当前 GitHub awesome 项目发现的正则过于简单（仅匹配 `- [name](url)` 格式）
- **工作量**: 中（1-2 天）
- **建议**: 增强解析逻辑，支持表格、HTML 列表等多种格式

### 4.6 后台批量处理

**参考**: `paper_daemon.py`

- **功能**: 从数据源获取论文列表，逐篇调用 LLM 处理，支持断点续传、rate limit
- **工作量**: 大（5-7 天）
- **说明**: 可以集成但不依赖 Zotero。数据源可以是 papers.yaml 或 arXiv API
- **建议**: 新建 `scripts/paper_daemon.py`，从 `papers.yaml` 读取待处理论文，逐篇调用 `generate_interpretations.py` 中的 LLM 函数

---

## 5. 明确不吸收的功能

以下功能与 awesome-hub-generator 的定位不符，明确不吸收：

| 功能 | 理由 |
|------|------|
| Obsidian 笔记保存 | awesome-hub-generator 生成 Astro 网站，不生成 Obsidian 笔记 |
| Obsidian 图片本地化 | 同上 |
| Obsidian 链接回填 | 同上 |
| Obsidian MOC 目录页 | 同上 |
| Obsidian 概念库管理 | 同上 |
| Agent 工作流（SKILL.md） | awesome-hub-generator 采用 Fixed Workflow 模式 |
| 毒舌点评（LLM 人设） | awesome-hub-generator 生成结构化分析，非人设点评 |
| 论文笔记模板 | 不生成笔记 |
| Zotero 集成 | 明确不做，不依赖 Zotero |
| 关键词评分算法 | 沿用现有 LLM 评分方案，不引入规则评分 |

---

## 6. 实现优先级建议

### P0 — 核心能力缺失（建议近期实现）

| # | 功能 | 工作量 | 影响面 | 说明 |
|---|------|--------|--------|------|
| 1 | 元数据富化 TeX source fallback | 中 | 大 | 从 TeX 源文件提取机构/作者，约 2-3 天 |
| 2 | 方法名提取增强 | 小 | 中 | 增加频率分析和停用词过滤，约 0.5 天 |
| 3 | 论文详情页链接回填 | 小 | 中 | 将解读链接回填到论文卡片，约 0.5 天 |
| 4 | 幂等设计 | 小 | 中 | 减少不必要的文件写入和 git 变动，约 0.5 天 |

### P1 — 重要增强（建议后续实现）

| # | 功能 | 工作量 | 影响面 | 说明 |
|---|------|--------|--------|------|
| 5 | 元数据富化 PDF fallback | 中 | 中 | PDF 文本提取机构，约 2-3 天 |
| 6 | 元数据 HTML 并发优化 | 小 | 中 | 改为 asyncio 提升效率，约 0.5 天 |
| 7 | 自动发现增强 | 中 | 中 | 改进 GitHub awesome 项目解析，约 1-2 天 |

### P2 — 锦上添花

| # | 功能 | 工作量 | 影响面 | 说明 |
|---|------|--------|--------|------|
| 8 | 后台批量处理 | 大 | 小 | 断点续传、rate limit，约 5-7 天 |

---

## 附录：参考文件映射

### dailypaper-skills 参考文件

| 文件 | 对应功能 | 建议集成方式 | 优先级 |
|------|---------|-------------|--------|
| `fetch_and_score.py` | HF 抓取、关键词评分 | 已吸收（hf_source.py），评分算法不跟进 | - |
| `enrich_papers.py` | arXiv HTML 元数据提取 | 已吸收（enrich_metadata.py），扩展 TeX + PDF fallback | P0 |
| `extract_affiliations.py` | PDF 机构提取 | 作为 enrich_metadata.py 的最终 fallback | P1 |
| `update_history.py` | 历史记录更新 | 已吸收（history_manager.py） | - |
| `paper_daemon.py` | 后台批量处理 | 新建 `scripts/paper_daemon.py`（不依赖 Zotero） | P2 |
| `user_config.py` | 配置加载与本地覆盖 | 已吸收（config_bridge.py） | - |
| `moc_builder.py` | 幂等写入 | 在 `build.py`/`update.py` 中应用 | P0 |

### awesome-hub-generator 现有对应文件

| 文件 | 当前能力 | 需要增强的方向 |
|------|---------|-------------|
| [hf_source.py](../scripts/hf_source.py) | HF Daily + Trending 抓取 | 无（已完成） |
| [enrich_metadata.py](../scripts/enrich_metadata.py) | arXiv HTML 元数据富化 | 扩展 TeX source + PDF fallback |
| [history_manager.py](../scripts/history_manager.py) | 跨天去重历史记录 | 无（已完成） |
| [build.py](../scripts/build.py) | 全量构建入口 | 应用幂等设计 |
| [update.py](../scripts/update.py) | 每日更新入口 | 应用幂等设计 |
