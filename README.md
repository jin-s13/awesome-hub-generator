# awesome-hub-generator

> 告诉它你的研究方向，它自动帮你建一个 awesome 页面，每天更新。

**awesome-hub-generator** 是一个端到端的 awesome 页面生成器。你只需要配置研究方向关键词，它就会：

1. **全量构建**：从 arXiv 搜索历史论文，LLM 自动分类打标签，生成完整的 Astro 网站
2. **每日更新**：定时检查 arXiv 新论文，筛选相关论文，自动追加到页面中
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
  keywords:
    - "CAD"
    - "B-Rep"
    - "parametric CAD"
    - "text-to-CAD"
  arxiv_categories:
    - "cs.CV"
    - "cs.GR"
    - "cs.LG"
  date_from: "2020-01-01"
```

### 3. 配置 API Key (GitHub Secrets)

在 GitHub 仓库的 **Settings → Secrets and variables → Actions** 中添加：

| Secret | 说明 | 示例值 |
|--------|------|--------|
| `CHEAP_LLM__API_KEY` | LLM API Key | `sk-xxxxx` |
| `CHEAP_LLM__BASE_URL` | API 地址 | `https://ark.cn-beijing.volces.com/api/v3` |
| `CHEAP_LLM__MODEL_NAME` | 模型名 | `deepseek-v4-flash` |

> 支持火山引擎 DeepSeek、OpenAI、OpenRouter 等任意兼容 OpenAI 格式的 API。

### 4. 全量构建

在 GitHub 仓库的 **Actions → Full build → Run workflow** 中手动触发。

首次构建会搜索 arXiv 历史论文，LLM 分类后生成完整的 Astro 网站并部署到 GitHub Pages。

### 5. 每日自动更新

`daily-update.yml` 工作流默认每天 UTC 0:00（北京时间 8:00）自动运行，检查 arXiv 新论文，有新增则自动更新网站。

## 项目结构

```
awesome-hub-generator/
├── awesome.yaml                 # ← 核心配置文件（你只需改这个）
├── arxiv-daily-researcher/      # git submodule: 论文发现引擎
├── scripts/
│   ├── build.py                 # 全量构建入口
│   ├── update.py                # 每日更新入口
│   └── sync.py                  # arXiv 适配器（搜索 + LLM 分类 + YAML 输出）
├── templates/
│   └── astro-site/              # Astro 网站模板
├── .github/workflows/
│   ├── full-build.yml           # 全量构建工作流
│   └── daily-update.yml         # 每日更新工作流
└── output/website/              # 生成的网站（自动创建）
    ├── data/papers.yaml         # 论文数据
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
    ┌──────────────────┐          ┌──────────────────┐
    │  全量构建 (build) │          │ 每日更新 (update) │
    │                  │          │                  │
    │  arXiv API 搜索   │          │  arxiv-daily-    │
    │  LLM 分类打标签    │          │  researcher 运行  │
    │  生成 YAML 数据   │          │  解析新论文        │
    │  生成 Astro 网站  │          │  去重合并到 YAML   │
    │  npm build 构建   │          │  重新构建网站      │
    └────────┬─────────┘          └────────┬─────────┘
             │                             │
             └──────────────┬──────────────┘
                            ▼
                  ┌──────────────────┐
                  │  GitHub Pages    │
                  │  (静态网站)       │
                  └──────────────────┘
```

## 自定义

### 修改网站外观

编辑 `templates/astro-site/public/styles/global.css` 中的 CSS 变量。

### 添加 datasets 和 tools

除了自动生成的论文，你还可以在 `data/datasets.yaml` 和 `data/tools.yaml` 中手动维护数据集和工具列表。

## 许可证

AGPL-3.0
