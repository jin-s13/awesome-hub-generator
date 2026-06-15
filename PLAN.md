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
    │ ① arXiv API 搜索  │          │ ① arxiv-daily-   │
    │   历史论文         │          │   researcher 运行 │
    │ ② LLM 分类打标签   │          │ ② 解析新论文      │
    │ ③ 生成 YAML 数据   │          │ ③ 去重合并到 YAML │
    │ ④ 从模板生成网站   │          │ ④ 重新构建网站    │
    │ ⑤ npm build       │          │ ⑤ 部署到 Pages   │
    │ ⑥ 部署到 Pages    │          │                  │
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

## 3. 安全方案

### 3.1 API Key 管理

**核心原则：Key 永不进代码仓库。**

| 场景 | 存储位置 | 安全机制 |
|------|---------|---------|
| GitHub Actions | GitHub Secrets（AES-256 加密） | 运行时注入环境变量，不出现在日志中 |
| 本地开发 | `.env` 文件 | 已在 `.gitignore` 中，git 不会跟踪 |

### 3.2 环境变量

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

## 4. 实现计划

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

### Phase 2: 集成与测试（待完成）

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

## 5. 使用指南

### 5.1 用户流程

```
1. Fork awesome-hub-generator
2. 编辑 awesome.yaml（填研究方向）
3. 在 GitHub Secrets 配置 ARK_API_KEY
4. 手动触发 Full build 工作流
5. 得到自动生成的 awesome 页面
6. 之后每天自动更新
```

### 5.2 配置示例（CAD 方向）

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

## 6. 技术选型

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

## 7. 附录

### 7.1 相关开源项目调研

见 [调研笔记](./docs/research-notes.md)（待创建）。

### 7.2 关键词参考

不同研究方向的 arXiv 分类参考：

| 研究方向 | 推荐 arXiv 分类 |
|---------|----------------|
| CAD / 3D 视觉 | cs.CV, cs.GR, cs.LG |
| NLP / LLM | cs.CL, cs.AI, cs.LG |
| 机器人 | cs.RO, cs.CV, cs.AI |
| 计算机图形学 | cs.GR, cs.CV |
| 机器学习理论 | cs.LG, stat.ML, cs.AI |
