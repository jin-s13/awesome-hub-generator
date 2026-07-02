#!/usr/bin/env python3
"""Dataset discovery and paper-to-dataset derivation helpers."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

logger = logging.getLogger("dataset_sources")

HF_DATASETS_URL = "https://huggingface.co/api/datasets"
USER_AGENT = "awesome-hub-generator/1.0"
REQUEST_TIMEOUT = 30


def _section_enabled(config: dict, section: str, default: bool = True) -> bool:
    sections = config.get("website", {}).get("sections", {})
    return bool(sections.get(section, default))


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return text.strip("-") or "dataset"


def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.warning("HF datasets HTTP %s: %s", e.code, url)
    except urllib.error.URLError as e:
        logger.warning("HF datasets URL error: %s - %s", url, e.reason)
    except json.JSONDecodeError as e:
        logger.warning("HF datasets JSON decode failed: %s - %s", url, e)
    return []


def _parse_year(value: Any) -> int | None:
    if not value:
        return None
    text = str(value)
    match = re.search(r"(19|20)\d{2}", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def _paper_link_from_card(card: dict) -> str:
    for key in ("paper", "paper_url", "arxiv", "arxiv_url", "paperswithcode_url"):
        value = card.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    citation = str(card.get("citation") or "")
    match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", citation, re.I)
    if match:
        return f"https://arxiv.org/abs/{match.group(1)}"
    return ""


def _hf_dataset_to_resource(item: dict) -> dict | None:
    repo_id = item.get("id") or item.get("repo_id") or item.get("name")
    if not repo_id:
        return None

    card = item.get("cardData") if isinstance(item.get("cardData"), dict) else {}
    description = (
        item.get("description")
        or card.get("description")
        or card.get("pretty_name")
        or f"Hugging Face dataset: {repo_id}"
    )
    tags = _as_list(item.get("tags") or card.get("tags"))
    year = _parse_year(item.get("lastModified") or item.get("createdAt") or card.get("date"))

    links = {"huggingface": f"https://huggingface.co/datasets/{repo_id}"}
    paper_link = _paper_link_from_card(card)
    if paper_link:
        links["paper"] = paper_link

    notes_parts = []
    for key in ("downloads", "likes"):
        if item.get(key) is not None:
            notes_parts.append(f"{key}={item[key]}")
    if card.get("license"):
        notes_parts.append(f"license={card['license']}")
    if item.get("paperswithcode_id"):
        notes_parts.append(f"paperswithcode={item['paperswithcode_id']}")

    resource = {
        "id": f"hf-{_slugify(str(repo_id))}",
        "name": str(repo_id),
        "description": str(description).strip(),
        "tags": tags,
        "links": links,
        "sources": [{"repo": "huggingface-datasets", "category": "dataset"}],
    }
    if year:
        resource["year"] = year
    if notes_parts:
        resource["notes"] = ", ".join(notes_parts)
    return resource


def fetch_hf_datasets(config: dict) -> List[dict]:
    """Search Hugging Face Datasets with configured research keywords."""
    if not _section_enabled(config, "datasets"):
        return []

    research = config.get("research", {})
    dataset_config = research.get("datasets", {})
    sources = research.get("sources", {})
    enabled = dataset_config.get("huggingface", sources.get("huggingface_datasets", True))
    if enabled is False:
        return []

    keywords = [str(item).strip() for item in research.get("keywords", []) if str(item).strip()]
    if not keywords:
        return []

    limit = int(dataset_config.get("huggingface_limit_per_keyword", 20))
    max_keywords = int(dataset_config.get("huggingface_max_keywords", 5))
    if max_keywords > 0:
        keywords = keywords[:max_keywords]
    fetched: List[dict] = []
    for keyword in keywords:
        params = urllib.parse.urlencode(
            {
                "search": keyword,
                "sort": dataset_config.get("huggingface_sort", "downloads"),
                "direction": dataset_config.get("huggingface_direction", "-1"),
                "limit": limit,
                "full": "true",
            }
        )
        data = _http_get_json(f"{HF_DATASETS_URL}?{params}")
        if isinstance(data, dict):
            data = data.get("datasets") or data.get("items") or []
        if not isinstance(data, list):
            continue
        for item in data:
            if isinstance(item, dict):
                resource = _hf_dataset_to_resource(item)
                if resource:
                    fetched.append(resource)

    merged, _ = merge_dataset_entries([], fetched)
    return merged


def _dataset_name_from_paper(title: str) -> str:
    title = (title or "").strip()
    if not title:
        return "Unnamed Dataset"
    for sep in (":", "：", " -- ", " - "):
        if sep in title:
            head = title.split(sep, 1)[0].strip()
            if 2 <= len(head) <= 80:
                return head
    return title[:120]


def _paper_types(paper: dict) -> List[str]:
    raw = paper.get("paper_type") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(item).lower() for item in raw if item]


def _paper_mentions_dataset(paper: dict) -> bool:
    tags = [str(tag).lower() for tag in (paper.get("tags") or [])]
    if "benchmark" in _paper_types(paper) or "dataset" in _paper_types(paper):
        return True
    if "benchmark" in tags or "dataset" in tags:
        return True
    links = paper.get("links") or {}
    if isinstance(links, dict) and any("dataset" in str(key).lower() for key in links):
        return True
    title = str(paper.get("title") or "").lower()
    if re.search(r"\b(dataset|datasets|benchmark|benchmarks|evaluation suite|leaderboard)\b", title):
        return True
    haystack = " ".join(
        str(paper.get(key) or "")
        for key in ("title", "abstract", "tldr", "reasoning")
    ).lower()
    dataset_release_patterns = (
        r"\b(introduce|introduces|present|presents|release|releases|propose|proposes|curate|curates|construct|constructs|collect|collects|build|builds|create|creates|provide|provides|contribute|contributes)\b.{0,100}\bdatasets?\b",
        r"\bdatasets?\b.{0,80}\b(contains|for evaluating|for evaluation|suite|leaderboard)\b",
        r"\bnew\s+datasets?\b",
    )
    return any(re.search(pattern, haystack) for pattern in dataset_release_patterns)


def derive_datasets_from_papers(papers: Iterable[dict]) -> List[dict]:
    derived: List[dict] = []
    for paper in papers:
        if not isinstance(paper, dict) or not _paper_mentions_dataset(paper):
            continue
        name = _dataset_name_from_paper(paper.get("title", ""))
        name_zh = _dataset_name_from_paper(paper.get("title_cn", ""))
        links = {k: v for k, v in (paper.get("links") or {}).items() if v}
        abstract = str(paper.get("abstract") or "")
        description = paper.get("tldr") or abstract[:240] + ("..." if len(abstract) > 240 else "")
        description_zh = paper.get("tldr_cn") or paper.get("abstract_cn")
        paper_url = links.get("paper") or ""
        item = {
            "id": f"paper-{paper.get('id') or _slugify(name)}",
            "name": name,
            "description": description or f"Derived from paper: {paper.get('title', name)}",
            "tags": paper.get("tags") or [],
            "links": links,
            "sources": [{"repo": "papers", "category": "dataset"}],
            "notes": f"Derived from paper: {paper.get('title', name)}",
            "related_papers": [
                {
                    "id": paper.get("id", ""),
                    "title": paper.get("title", ""),
                    "url": paper_url,
                }
            ],
        }
        if name_zh:
            item["name_zh"] = name_zh
        if description_zh:
            item["description_zh"] = description_zh
        if paper.get("title_cn"):
            item["notes_zh"] = f"派生自论文：{paper['title_cn']}"
            item["related_papers"][0]["title_zh"] = paper["title_cn"]
        if paper.get("year"):
            item["year"] = paper["year"]
        if paper.get("preview"):
            item["preview"] = paper["preview"]
        derived.append(item)
    return derived


def _entry_keys(item: dict) -> set[str]:
    keys = set()
    name = str(item.get("name") or "").strip().lower()
    if name:
        keys.add(f"name:{name}")
    links = item.get("links") or {}
    if isinstance(links, dict):
        for key in ("huggingface", "paper", "dataset", "code", "url"):
            value = str(links.get(key) or "").strip().lower().rstrip("/")
            if value:
                keys.add(f"url:{value}")
    if item.get("id"):
        keys.add(f"id:{str(item['id']).strip().lower()}")
    return keys


def merge_dataset_entries(existing: List[dict], incoming: List[dict]) -> Tuple[List[dict], int]:
    """Merge dataset resources, preserving existing/manual entries on conflict."""
    merged = [item for item in existing if isinstance(item, dict)]
    seen = set()
    for item in merged:
        seen.update(_entry_keys(item))

    added = 0
    for item in incoming:
        if not isinstance(item, dict):
            continue
        keys = _entry_keys(item)
        if keys and seen.intersection(keys):
            continue
        merged.append(item)
        seen.update(keys)
        added += 1
    return merged, added


def _name_aliases(name: str) -> set[str]:
    aliases = set()
    raw = str(name or "").strip()
    if not raw:
        return aliases
    aliases.add(raw.lower())
    short = raw.rsplit("/", 1)[-1]
    aliases.add(short.lower())
    aliases.add(short.replace("-", " ").replace("_", " ").lower())
    return {alias for alias in aliases if len(alias) >= 4}


def associate_datasets_with_papers(datasets: List[dict], papers: List[dict]) -> List[dict]:
    """Add deterministic paper links when dataset names are mentioned by papers."""
    result = []
    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        item = dict(dataset)
        links = dict(item.get("links") or {})
        related = list(item.get("related_papers") or [])
        related_keys = {entry.get("id") or entry.get("url") for entry in related if isinstance(entry, dict)}
        aliases = _name_aliases(item.get("name", ""))
        for paper in papers:
            if not isinstance(paper, dict):
                continue
            haystack = " ".join(
                str(paper.get(key) or "")
                for key in ("title", "abstract", "tldr", "reasoning")
            ).lower()
            if not any(alias in haystack for alias in aliases):
                continue
            paper_url = ""
            paper_links = paper.get("links") or {}
            if isinstance(paper_links, dict):
                paper_url = paper_links.get("paper") or ""
            related_key = paper.get("id") or paper_url
            for entry in related:
                if not isinstance(entry, dict):
                    continue
                entry_key = entry.get("id") or entry.get("url")
                if entry_key == related_key and paper.get("title_cn") and not entry.get("title_zh"):
                    entry["title_zh"] = paper["title_cn"]
            if related_key and related_key not in related_keys:
                related_entry = {
                    "id": paper.get("id", ""),
                    "title": paper.get("title", ""),
                    "url": paper_url,
                }
                if paper.get("title_cn"):
                    related_entry["title_zh"] = paper["title_cn"]
                related.append(related_entry)
                related_keys.add(related_key)
            if paper_url and not links.get("paper"):
                links["paper"] = paper_url
            paper_preview = str(paper.get("preview") or "")
            current_preview = str(item.get("preview") or "")
            if paper_preview and (not current_preview or current_preview.endswith("placeholder.svg")):
                item["preview"] = paper_preview
            if paper.get("title_cn") and not item.get("name_zh"):
                item["name_zh"] = _dataset_name_from_paper(paper["title_cn"])
            if paper.get("tldr_cn") and not item.get("description_zh"):
                item["description_zh"] = paper["tldr_cn"]
            elif paper.get("abstract_cn") and not item.get("description_zh"):
                item["description_zh"] = paper["abstract_cn"]
            if paper.get("title_cn") and not item.get("notes_zh") and item.get("id") == f"paper-{paper.get('id')}":
                item["notes_zh"] = f"派生自论文：{paper['title_cn']}"
        item["links"] = links
        if related:
            item["related_papers"] = related
        result.append(item)
    return result


def sync_datasets(data_dir: Path, config: dict) -> Dict[str, int]:
    """Sync datasets.yaml from HF datasets and paper-derived benchmark entries."""
    if not _section_enabled(config, "datasets"):
        return {"hf_datasets": 0, "derived_from_papers": 0, "total_added": 0}

    papers_path = data_dir / "papers.yaml"
    datasets_path = data_dir / "datasets.yaml"

    existing = []
    if datasets_path.exists():
        loaded = yaml.safe_load(datasets_path.read_text(encoding="utf-8")) or []
        existing = loaded if isinstance(loaded, list) else []

    papers = []
    if papers_path.exists():
        loaded = yaml.safe_load(papers_path.read_text(encoding="utf-8")) or []
        papers = loaded if isinstance(loaded, list) else []

    research = config.get("research", {})
    dataset_config = research.get("datasets", {})

    hf_items = fetch_hf_datasets(config)
    derived_items = []
    if dataset_config.get("derive_from_papers", True):
        derived_items = derive_datasets_from_papers(papers)

    incoming = associate_datasets_with_papers(hf_items + derived_items, papers)
    merged, added = merge_dataset_entries(existing, incoming)
    merged = associate_datasets_with_papers(merged, papers)

    datasets_path.parent.mkdir(parents=True, exist_ok=True)
    datasets_path.write_text(
        yaml.dump(merged, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    if added:
        logger.info("Synced datasets: +%d (%d total)", added, len(merged))
    return {
        "hf_datasets": len(hf_items),
        "derived_from_papers": len(derived_items),
        "total_added": added,
    }
