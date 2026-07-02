# Changelog

## Unreleased

### Added
- Added asynchronous literature survey jobs via `data/survey_jobs.yaml` and `scripts/survey_worker.py`, so full hub generation can queue slow LLM survey synthesis instead of blocking the build.
- Added tests for arXiv retry behavior, Hugging Face source limits, LLM parallelism, survey job processing, and source discovery controls.

### Changed
- Improved paper relevance filtering: LLM `relevant=false` classifications now reject off-topic papers, while empty or failed LLM responses remain unknown so later runs can retry.
- Parallelized LLM classification and semantic relevance filtering to improve full-generation throughput.
- Made teaser fetching configurable from hub config, including worker count and fallback retry behavior.
- Tightened default source behavior for new hubs: non-CAD hubs no longer inherit CAD-specific seed discovery defaults.

### Fixed
- Added arXiv 429 retry/backoff handling and more bounded Hugging Face/GitHub source collection to reduce long or stuck full builds.
- Preserved discovered GitHub projects while limiting how many repository READMEs are fetched for paper ingestion.
