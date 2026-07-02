# awesome-hub-generator

<p align="center">
  <a href="https://github.com/sindresorhus/awesome"><img alt="Awesome" src="https://awesome.re/badge.svg"></a>
  <a href="https://jin-s13.github.io/awesome-world-model-hub/zh"><img alt="World Model Hub" src="https://img.shields.io/badge/world%20model-web%20hub-2563eb?style=flat-square"></a>
  <a href="https://github.com/jin-s13/awesome-world-model-hub"><img alt="Generated Hub" src="https://img.shields.io/badge/generated%20hub-example-16a34a?style=flat-square"></a>
</p>

**awesome-hub-generator** turns a research direction into a living awesome hub:
papers, datasets, GitHub projects, citation signals, bilingual summaries,
deep-reading notes, trend pages, and GitHub Pages deployment.

It is built for research areas that move too fast for a hand-maintained list.
Give it a topic, seed sources, and model keys; it will discover papers from
arXiv, Hugging Face, upstream awesome lists, GitHub projects, OpenAlex, and
configured seed graphs, then publish a browsable static website plus
machine-readable metadata.

> 中文入口：这是一个用于自动生成研究型 awesome hub 的工具。它负责发现论文、评分排序、补全 TLDR/深度分析、抓取 teaser、生成网站，并支持每日增量更新。

## Generated Hubs

| Hub | Web UI | Repository | What it demonstrates |
| --- | --- | --- | --- |
| Awesome World Model Hub | [中文站点](https://jin-s13.github.io/awesome-world-model-hub/zh) / [English](https://jin-s13.github.io/awesome-world-model-hub/en) | [jin-s13/awesome-world-model-hub](https://github.com/jin-s13/awesome-world-model-hub) | Papers, datasets, projects, citation ranking, literature analysis, daily GitHub Actions updates |
| Awesome AI4CAD Hub | [English site](https://jin-s13.github.io/awesome-AI4CAD-hub/en) | [jin-s13/awesome-AI4CAD-hub](https://github.com/jin-s13/awesome-AI4CAD-hub) | Domain-specific discovery from arXiv, upstream awesome lists, GitHub project mining, and AI-for-CAD taxonomy |

These hubs are normal downstream repositories, not submodules. The generator
owns the tooling and templates; each hub owns its data, assets, website, and
deployment history.

## What It Builds

| Surface | Output |
| --- | --- |
| Paper index | Searchable cards with scores, TLDRs, tags, links, and teaser images |
| Paper detail pages | Score breakdown, reasoning, keyword relevance, deep analysis, and related resources |
| Research analysis | Topic-level synthesis, shared patterns, differences, trend evolution, and representative papers |
| Dataset index | Dataset and benchmark entries discovered from papers, Hugging Face, and upstream awesome sources |
| Project index | Relevant GitHub projects with stars, tags, source repos, and paper links when available |
| Trends | Keyword trends, year distributions, score patterns, and taxonomy slices |
| Metadata | Structured `data/`, `assets/`, and `resource/` files for downstream reuse |
| Deployment | GitHub Actions workflow template for daily refresh and GitHub Pages deployment |

## Why This Exists

Traditional awesome lists are beautiful but static. Research discovery needs a
slightly different shape:

- **Read-first ranking**: prioritize papers by topical fit, recency, citation
  signal, reproducibility, methodology evidence, and configured research intent.
- **LLM-assisted summaries**: generate TLDRs for every paper and deeper analysis
  for stronger candidates.
- **Source fusion**: combine arXiv, upstream awesome repos, Hugging Face datasets,
  OpenAlex, Semantic Scholar expansion, GitHub project discovery, and manual
  overrides.
- **Bilingual sites**: publish English and Chinese reading surfaces from the same
  metadata.
- **Daily updates**: keep the hub alive without turning every refresh into a
  manual curation session.

## Quick Start

### 1. Create a local hub

```bash
uv run python scripts/init_hub.py --name awesome-cad-hub --title "Awesome CAD Hub"
```

This creates `.local/awesome-cad-hub/` with:

```text
awesome.yaml
data/
assets/
resource/
website/
```

### 2. Configure the research direction

Edit `.local/awesome-cad-hub/awesome.yaml`:

```yaml
project:
  name: "Awesome CAD Hub"
  description: "A curated hub for CAD papers, datasets, projects, and Neural CAD research."
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

### 3. Configure model and data keys

For local runs, create `.env` in the hub or generator workspace:

```bash
cp .env.example .env
```

Common keys:

| Name | Required | Purpose |
| --- | --- | --- |
| `ARK_API_KEY` | Yes for LLM runs | Scoring, TLDRs, translation, deep analysis |
| `ARK_API_BASE_URL` | Optional | OpenAI-compatible `/responses` endpoint |
| `ARK_MODEL_NAME` | Optional | Fast scoring model |
| `SMART_MODEL_NAME` | Optional | Deep analysis and synthesis model |
| `MINERU_API_KEY` | Optional | PDF parsing and figure/table extraction |
| `OPENALEX_API_KEY` | Optional | Citation metadata |
| `OPENALEX_MAILTO` | Optional | OpenAlex polite pool email |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional | Reference expansion |
| `GH_TOKEN` | Optional local | GitHub discovery rate limits |
| `GH_DISCOVERY_TOKEN` | Optional Actions | GitHub discovery token for workflows |

### 4. Build the first version

```bash
uv run python scripts/build.py --hub awesome-cad-hub
```

The first build discovers papers, filters relevance, scores papers, fetches
teasers, generates interpretations, builds analysis pages, and renders an Astro
website. Existing metadata and LLM cache entries are reused on reruns.

### 5. Preview locally

```bash
uv run python scripts/serve_hub.py --hub awesome-cad-hub --port 4327
```

`serve_hub.py` pulls the hub checkout first when it is clean, then starts the
Astro dev server. Dirty checkouts are not pulled, so local edits are not
overwritten.

## Managing Multiple Local Hubs

Generated hubs live under `.local/` as ordinary git checkouts. They are managed
through `hubs.yaml` and `scripts/hubctl.py`.

```bash
uv run python scripts/hubctl.py list
uv run python scripts/hubctl.py status
uv run python scripts/hubctl.py pull
uv run python scripts/hubctl.py push awesome-world-model-hub
uv run python scripts/hubctl.py serve awesome-world-model-hub --port 4327
uv run python scripts/hubctl.py update awesome-world-model-hub --search-days 14 --skip-build
```

The default `hubs.yaml` registers:

- `.local/awesome-world-model-hub`
- `.local/awesome-ai4cad-hub`

This keeps hub repositories easy to operate from the generator workspace without
using git submodules or submodule pointer commits.

## Deploy a Hub Repository

When you want a public website, create a standalone downstream repository:

```bash
uv run python scripts/init_site.py --name awesome-cad-hub --title "Awesome CAD Hub"
```

Then push that repository to GitHub and configure:

| Setting | Value |
| --- | --- |
| Repository variable | `GENERATOR_REPO=jin-s13/awesome-hub-generator` |
| Required secret | `ARK_API_KEY` |
| Optional secrets | `ARK_API_BASE_URL`, `ARK_MODEL_NAME`, `SMART_MODEL_NAME`, `MINERU_API_KEY`, `OPENALEX_API_KEY`, `OPENALEX_MAILTO`, `SEMANTIC_SCHOLAR_API_KEY`, `GH_DISCOVERY_TOKEN` |
| Optional variables | `ARK_TIMEOUT_SECONDS`, `ARK_SURVEY_TIMEOUT_SECONDS`, `SEMANTIC_SCHOLAR_REQUEST_INTERVAL_SECONDS` |

The workflow template in `templates/workflows/daily-update.yml` runs daily at
UTC 00:00, refreshes metadata, rebuilds the site, deploys `gh-pages`, and commits
updated hub data back to `main`.

Downstream users should read structured metadata from the hub repository's
`main` branch:

```text
data/
assets/
resource/
```

The `gh-pages` branch is only the built static website.

## Repository Layout

```text
awesome-hub-generator/
├── scripts/
│   ├── build.py                         # Full build pipeline
│   ├── update.py                        # Daily update pipeline
│   ├── hubctl.py                        # Manage local hub checkouts
│   ├── serve_hub.py                     # Pull and run a local Astro dev server
│   ├── paper_sources.py                 # Source aggregation
│   ├── ingest_source.py                 # Markdown/YAML upstream awesome parsing
│   ├── paper_rank.py                    # Explainable read-first ranking
│   ├── fetch_teasers.py                 # Teaser image and PDF figure recovery
│   ├── refresh_interpretations_parallel.py
│   └── literature_survey.py             # Topic synthesis and research analysis
├── templates/
│   ├── astro-site/                      # Static website template
│   └── workflows/daily-update.yml       # GitHub Actions template
├── awesome.yaml.example                 # Hub config template
├── hubs.yaml                            # Local managed hub registry
└── .local/                              # Ignored local hub checkouts
```

## Pipeline Overview

```text
awesome.yaml
    |
    v
Source discovery
    |-- arXiv
    |-- Hugging Face
    |-- upstream awesome repos
    |-- GitHub projects
    |-- OpenAlex / Semantic Scholar signals
    v
Candidate pool -> relevance filtering -> dedupe
    v
Paper ranking + TLDR + deep analysis
    v
Teaser recovery + dataset/project sync
    v
Literature analysis + trend pages
    v
Astro website + structured metadata
```

## Configuration Highlights

### Source Discovery

```yaml
research:
  sources:
    arxiv: true
    huggingface: true
    upstream_awesome: true
    huggingface_datasets: true

  upstream_awesome:
    repos:
      - BunnySoCrazy/Awesome-Neural-CAD
    auto_discover: true

  auto_discover:
    enabled: true
    max_sources: 10
```

### Ranking

```yaml
research:
  ranking:
    enabled: true
    weights:
      topical_relevance: 0.25
      citation_impact: 0.15
      graph_prestige: 0.15
      citation_velocity: 0.10
      methodology_quality: 0.15
      reproducibility: 0.15
      recency: 0.05
```

### Teaser Recovery

```yaml
research:
  teasers:
    workers: 4
    retry_fallbacks: true
```

Fallback teaser SVGs are treated as unresolved. The fetcher retries arXiv HTML,
project pages, direct PDFs, CVF/NeurIPS landing-page PDF derivation, MinerU, and
local PDF rendering. Remaining fallbacks produce explicit warning logs so they
can be investigated later.

## Development

Run focused tests:

```bash
uv run pytest tests/test_hubctl.py tests/test_serve_hub.py
uv run pytest tests/test_paper_sources.py tests/test_fetch_teasers.py
```

Check all tests:

```bash
uv run pytest
```

## Design Principles

- The generator is a tool, not a concrete hub.
- Generated hubs are independent repositories, not submodules.
- Metadata should stay machine-readable and easy to reuse.
- Warnings should expose unresolved data quality issues instead of hiding them.
- Daily automation should be recoverable, incremental, and safe to rerun.

## License

MIT
