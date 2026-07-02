#!/usr/bin/env python3
"""Unified paper source aggregation.

This module keeps source-specific adapters thin and returns one normalized
collection that callers can feed into the candidate pool or directly merge into
papers.yaml. Network failures are recorded per source and do not abort the run.
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


SOURCE_NAMES = ("arxiv", "huggingface", "awesome", "alphaxiv")


def _research(config: Dict[str, Any]) -> Dict[str, Any]:
    return config.get("research", {}) if isinstance(config, dict) else {}


def _sources(config: Dict[str, Any]) -> Dict[str, Any]:
    sources = _research(config).get("sources", {})
    return sources if isinstance(sources, dict) else {}


def _source_summary(enabled: bool, count: int = 0, error: str = "") -> Dict[str, Any]:
    result = {"enabled": bool(enabled), "count": int(count)}
    if error:
        result["error"] = error
    return result


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def _paper_key(paper: Dict[str, Any]) -> str:
    arxiv_id = str(paper.get("arxiv_id") or "").strip()
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    paper_url = str(links.get("paper") or "")
    arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/([^?#/]+)", paper_url)
    if arxiv_match:
        return f"arxiv:{arxiv_match.group(1).replace('.pdf', '')}"
    doi = str(paper.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    title = re.sub(r"\s+", " ", str(paper.get("title") or "").strip().lower())
    return f"title:{title}"


def _merge_sources(existing: List[Dict[str, Any]], incoming: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = list(existing)
    seen = {(item.get("repo"), item.get("category")) for item in merged if isinstance(item, dict)}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        key = (item.get("repo"), item.get("category"))
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def _merge_paper(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if key == "sources":
            merged["sources"] = _merge_sources(merged.get("sources") or [], value if isinstance(value, list) else [])
        elif key == "links" and isinstance(value, dict):
            links = dict(merged.get("links") or {})
            links.update({k: v for k, v in value.items() if v})
            merged["links"] = links
        elif key == "score" and isinstance(value, dict):
            score = dict(merged.get("score") or {})
            score.update(value)
            merged["score"] = score
        elif key == "preview" and merged.get("preview") in (None, "", "/assets/placeholder.svg"):
            merged["preview"] = value
        elif key == "authors" and isinstance(value, list) and not merged.get("authors"):
            merged["authors"] = value
        elif not merged.get(key):
            merged[key] = value
    return merged


def merge_papers(papers: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge papers by arXiv ID, DOI, paper URL, or normalized title."""
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for paper in papers:
        if not isinstance(paper, dict) or not paper.get("title"):
            continue
        key = _paper_key(paper)
        if key not in merged:
            merged[key] = dict(paper)
            order.append(key)
        else:
            merged[key] = _merge_paper(merged[key], paper)
    return [merged[key] for key in order]


def github_source_to_project(source: Any) -> Dict[str, Any]:
    """Convert a discovered GitHub repository into a project/resource entry."""
    full_name = str(getattr(source, "full_name", "") or "").strip()
    repo_name = full_name.split("/")[-1] if full_name else "GitHub project"
    description = str(getattr(source, "description", "") or "").strip()
    topics = [str(topic) for topic in (getattr(source, "topics", []) or []) if str(topic).strip()]
    stars = int(getattr(source, "stars", 0) or 0)
    html_url = str(getattr(source, "html_url", "") or "").strip()
    return {
        "id": f"github-{_slug(full_name)}",
        "name": repo_name,
        "type": "GitHub",
        "category": "GitHub project",
        "description": description or f"GitHub project related to {full_name}.",
        "tags": topics,
        "stars": stars,
        "links": {"github": html_url} if html_url else {},
        "sources": [{"repo": full_name, "category": "github_project"}] if full_name else [],
    }


def _project_key(project: Dict[str, Any]) -> str:
    links = project.get("links") if isinstance(project.get("links"), dict) else {}
    github = str(links.get("github") or links.get("repo") or "").rstrip("/").lower()
    if github:
        return f"github:{github}"
    return f"name:{str(project.get('name') or '').strip().lower()}"


def merge_projects(existing: Iterable[Dict[str, Any]], incoming: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge GitHub project entries while preserving manually maintained fields."""
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for project in [*existing, *incoming]:
        if not isinstance(project, dict) or not project.get("name"):
            continue
        key = _project_key(project)
        if key not in merged:
            merged[key] = dict(project)
            order.append(key)
            continue
        current = merged[key]
        for field, value in project.items():
            if value in (None, "", [], {}):
                continue
            if field == "links" and isinstance(value, dict):
                links = dict(current.get("links") or {})
                links.update({k: v for k, v in value.items() if v})
                current["links"] = links
            elif field == "sources" and isinstance(value, list):
                current["sources"] = _merge_sources(current.get("sources") or [], value)
            elif field == "tags" and isinstance(value, list):
                current["tags"] = sorted({*current.get("tags", []), *value})
            elif field == "stars" and isinstance(value, int):
                current["stars"] = max(int(current.get("stars") or 0), value)
            elif not current.get(field):
                current[field] = value
    return sorted(
        [merged[key] for key in order],
        key=lambda item: (-(int(item.get("stars") or 0)), str(item.get("name") or "").lower()),
    )


def save_projects_yaml(data_dir: Path, projects: Iterable[Dict[str, Any]]) -> int:
    """Merge projects into data/projects.yaml and return the resulting count."""
    import yaml

    path = data_dir / "projects.yaml"
    existing: List[Dict[str, Any]] = []
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        existing = data if isinstance(data, list) else []
    merged = merge_projects(existing, projects)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(merged, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return len(merged)


def fetch_arxiv_source(config: Dict[str, Any], search_days: Optional[int] = None, max_results: int = 500) -> List[Dict[str, Any]]:
    """Fetch papers from arXiv using the existing sync adapter."""
    from scripts.sync import search_arxiv

    research = _research(config)
    keywords = research.get("keywords", [])
    categories = research.get("arxiv_categories", [])
    if search_days:
        date_from = (_dt.datetime.now() - _dt.timedelta(days=search_days)).strftime("%Y%m%d")
        date_to = _dt.datetime.now().strftime("%Y%m%d")
    else:
        date_from = research.get("date_from", "")
        date_to = research.get("date_to", "")
    return search_arxiv(keywords, categories, date_from, date_to, max_results=max_results)


def fetch_huggingface_source(config: Dict[str, Any], search_days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch papers from Hugging Face Daily/Trending through the existing adapter."""
    from scripts.hf_source import fetch_all_hf_papers

    if not search_days:
        return fetch_all_hf_papers(config)
    hf_config = dict(config)
    hf_config.setdefault("research", {})["date_from"] = (
        _dt.datetime.now() - _dt.timedelta(days=search_days)
    ).strftime("%Y-%m-%d")
    return fetch_all_hf_papers(hf_config)


def fetch_awesome_bundle(config: Dict[str, Any]) -> Dict[str, Any]:
    """Discover upstream awesome repositories and return parsed papers plus repo projects."""
    from scripts.discover_sources import GitHubDiscoverer
    from scripts.ingest_source import FormatDetector, JsonParser, MarkdownListParser, MarkdownTableParser, YamlParser
    from scripts.url_classify import entry_is_paper

    research = _research(config)
    auto = research.get("auto_discover", {}) if isinstance(research.get("auto_discover", {}), dict) else {}
    upstream = research.get("upstream_awesome", {}) if isinstance(research.get("upstream_awesome", {}), dict) else {}
    keywords = research.get("keywords", [])
    configured_repos = [
        str(repo).strip()
        for repo in upstream.get("repos", [])
        if str(repo).strip() and "/" in str(repo)
    ]
    auto_enabled = bool(upstream.get("auto_discover", auto.get("enabled", True)))
    if not keywords and not configured_repos:
        return {"papers": [], "projects": []}

    runtime = config.get("_runtime", {}) if isinstance(config.get("_runtime", {}), dict) else {}
    cache_path = runtime.get("github_cache_path") or auto.get("cache_path")
    discoverer = GitHubDiscoverer(
        cache_path=Path(cache_path) if cache_path else None,
        search_interval_seconds=auto.get("search_interval_seconds"),
        core_interval_seconds=auto.get("core_interval_seconds"),
        max_rate_limit_sleep_seconds=auto.get("max_rate_limit_sleep_seconds"),
        request_timeout_seconds=auto.get("request_timeout_seconds"),
    )
    sources = [discoverer.source_from_repo(repo) for repo in configured_repos]
    if auto_enabled and keywords:
        discovered = discoverer.discover(
            keywords,
            min_stars=auto.get("min_stars", 5),
            max_sources=auto.get("max_sources", 10),
            query_expansion=auto.get("query_expansion", []),
            max_search_terms=auto.get("max_search_terms", 2),
        )
        seen = {source.full_name for source in sources}
        sources.extend(source for source in discovered if source.full_name not in seen)
    projects = [github_source_to_project(source) for source in sources]
    max_repos_to_fetch = auto.get("max_repos_to_fetch")
    if max_repos_to_fetch is not None:
        try:
            repo_limit = int(max_repos_to_fetch)
        except (TypeError, ValueError):
            repo_limit = 0
        if repo_limit > 0:
            sources = sources[:repo_limit]
    papers: List[Dict[str, Any]] = []
    for source in sources:
        readme = discoverer.fetch_readme(source)
        if not readme:
            continue
        repo_files = discoverer.list_repo_files(source)
        fmt = FormatDetector.detect(readme, repo_files)
        if fmt == "yaml":
            for file_path in [item for item in repo_files if item.endswith((".yaml", ".yml"))]:
                content = discoverer.fetch_file(source, file_path)
                if content:
                    papers.extend(YamlParser.parse(content, source.full_name))
        elif fmt == "json":
            for file_path in [item for item in repo_files if item.endswith(".json")]:
                content = discoverer.fetch_file(source, file_path)
                if content:
                    papers.extend(JsonParser.parse(content, source.full_name))
        elif fmt == "markdown_table":
            papers.extend(MarkdownTableParser.parse(readme, source.full_name))
        elif fmt in ("markdown_list", "html_list", "unknown"):
            papers.extend(MarkdownListParser.parse(readme, source.full_name))
    return {"papers": [paper for paper in papers if entry_is_paper(paper)], "projects": projects}


def fetch_awesome_source(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Discover and parse upstream awesome repositories without writing files."""
    return fetch_awesome_bundle(config)["papers"]


def fetch_alphaxiv_source(config: Dict[str, Any], query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Optional AlphaXiv enhancement hook.

    AlphaXiv support is deliberately non-fatal and disabled by default. The
    public Python project does not depend on AlphaXiv credentials; deployments
    may provide a compatible JSON endpoint through research.alphaxiv.endpoint.
    """
    alpha = _research(config).get("alphaxiv", {})
    if not isinstance(alpha, dict):
        alpha = {}
    endpoint = str(alpha.get("endpoint") or "").strip()
    if not endpoint:
        return []

    import json
    import urllib.request

    query_text = query or " ".join(str(item) for item in _research(config).get("keywords", []))
    url = endpoint
    separator = "&" if "?" in url else "?"
    url = f"{url}{separator}q={urllib.parse.quote_plus(query_text)}"
    req = urllib.request.Request(url, headers={"User-Agent": "awesome-hub-generator/1.0"})
    with urllib.request.urlopen(req, timeout=int(alpha.get("timeout", 30))) as response:
        payload = json.loads(response.read().decode("utf-8"))
    items = payload.get("papers", payload) if isinstance(payload, dict) else payload
    return items if isinstance(items, list) else []


def _run_source(name: str, enabled: bool, fetcher: Callable[[], List[Dict[str, Any]]]) -> Dict[str, Any]:
    if not enabled:
        return {"papers": [], "summary": _source_summary(False)}
    try:
        papers = fetcher()
        return {"papers": papers, "summary": _source_summary(True, len(papers))}
    except Exception as exc:
        return {"papers": [], "summary": _source_summary(True, 0, str(exc))}


def collect_paper_sources(
    config: Dict[str, Any],
    *,
    search_days: Optional[int] = None,
    max_results: int = 500,
) -> Dict[str, Any]:
    """Collect enabled paper sources and return merged papers plus source summaries."""
    sources = _sources(config)
    hf_enabled = bool(sources.get("huggingface_daily", False) or sources.get("huggingface_trending", False))
    awesome_enabled = bool(
        sources.get("upstream_awesome", _research(config).get("auto_discover", {}).get("enabled", False))
    )
    alpha_enabled = bool(sources.get("alphaxiv", False) or _research(config).get("alphaxiv", {}).get("enabled", False))

    source_runs = {
        "arxiv": _run_source("arxiv", sources.get("arxiv", True), lambda: fetch_arxiv_source(config, search_days, max_results)),
        "huggingface": _run_source("huggingface", hf_enabled, lambda: fetch_huggingface_source(config, search_days)),
        "alphaxiv": _run_source("alphaxiv", alpha_enabled, lambda: fetch_alphaxiv_source(config)),
    }
    projects: List[Dict[str, Any]] = []
    if awesome_enabled:
        try:
            awesome_bundle = fetch_awesome_bundle(config)
            awesome_papers = awesome_bundle.get("papers", [])
            projects = awesome_bundle.get("projects", [])
            source_runs["awesome"] = {
                "papers": awesome_papers,
                "summary": _source_summary(True, len(awesome_papers)),
            }
        except Exception as exc:
            source_runs["awesome"] = {"papers": [], "summary": _source_summary(True, 0, str(exc))}
    else:
        source_runs["awesome"] = {"papers": [], "summary": _source_summary(False)}
    papers: List[Dict[str, Any]] = []
    summaries: Dict[str, Any] = {}
    for name in SOURCE_NAMES:
        papers.extend(source_runs[name]["papers"])
        summaries[name] = source_runs[name]["summary"]
    return {
        "papers": merge_papers(papers),
        "sources": summaries,
        "projects": merge_projects([], projects),
    }
