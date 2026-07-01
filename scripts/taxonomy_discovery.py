#!/usr/bin/env python3
"""Build a reusable domain taxonomy and assign papers to taxonomy nodes.

The first implementation is deliberately deterministic for testability and
offline builds. LLM synthesis can layer on top of the same schema later.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "topic"


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _load_yaml(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return fallback if data is None else data


def _dump_yaml(path: Path, data: Any) -> None:
    path.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _node_from_config(item: Dict[str, Any]) -> Dict[str, Any]:
    node_id = str(item.get("id") or _slug(item.get("label", "")))
    label = str(item.get("label") or node_id.replace("_", " ").title())
    node = {
        "id": node_id,
        "label": label,
        "description": str(item.get("description") or ""),
        "keywords": list(item.get("keywords") or []),
    }
    if item.get("label_zh"):
        node["label_zh"] = str(item["label_zh"])
    if item.get("description_zh"):
        node["description_zh"] = str(item["description_zh"])
    children = item.get("children") if isinstance(item.get("children"), list) else []
    if children:
        node["children"] = [_node_from_config(child) for child in children if isinstance(child, dict)]
    return {key: value for key, value in node.items() if value not in ("", [], None)}


def _source_heading_node(heading: str) -> Dict[str, Any]:
    label = str(heading).strip()
    return {
        "id": _slug(label),
        "label": label,
        "description": f"Papers and resources related to {label}.",
        "keywords": [_norm(label)],
    }


def _flatten_nodes(nodes: Iterable[Dict[str, Any]], prefix: str = "") -> List[Tuple[str, Dict[str, Any]]]:
    flat: List[Tuple[str, Dict[str, Any]]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        path = f"{prefix}.{node_id}" if prefix else node_id
        flat.append((path, node))
        children = node.get("children") if isinstance(node.get("children"), list) else []
        flat.extend(_flatten_nodes(children, path))
    return flat


def _node_terms(path: str, node: Dict[str, Any]) -> List[str]:
    terms = [
        path.replace(".", " "),
        path.replace(".", " ").replace("_", " "),
        node.get("label", ""),
        node.get("description", ""),
    ]
    terms.extend(node.get("keywords") or [])
    seen: List[str] = []
    for term in terms:
        text = _norm(term)
        if text and text not in seen:
            seen.append(text)
    return seen


def _paper_text(paper: Dict[str, Any]) -> str:
    fields = [
        paper.get("title", ""),
        paper.get("abstract", ""),
        paper.get("tldr", ""),
        paper.get("reasoning", ""),
        " ".join(str(tag) for tag in paper.get("tags", []) if tag),
    ]
    analysis = paper.get("analysis") if isinstance(paper.get("analysis"), dict) else {}
    fields.extend(str(value) for value in analysis.values() if isinstance(value, str))
    return _norm(" ".join(fields))


def _score_node(paper_text: str, terms: List[str]) -> float:
    score = 0.0
    for term in terms:
        if not term:
            continue
        if term in paper_text:
            score += 5.0 + min(len(term.split()), 4)
            continue
        words = [word for word in term.split() if len(word) > 2]
        if words:
            matches = sum(1 for word in words if word in paper_text)
            score += matches / len(words)
    return score


def build_taxonomy(
    data_dir: Path,
    config: Dict[str, Any],
    *,
    generated_at: Optional[str] = None,
    use_llm: bool = True,
) -> int:
    """Generate data/taxonomy.yaml.

    The deterministic path combines configured nodes with source headings. It
    preserves order and de-duplicates by node id.
    """
    research = config.get("research", {}) if isinstance(config, dict) else {}
    settings = research.get("taxonomy_discovery", {}) if isinstance(research.get("taxonomy_discovery", {}), dict) else {}
    if settings.get("enabled") is False:
        return 0

    nodes: List[Dict[str, Any]] = []
    seen = set()

    for item in settings.get("nodes", []) or []:
        if not isinstance(item, dict):
            continue
        node = _node_from_config(item)
        if node["id"] not in seen:
            nodes.append(node)
            seen.add(node["id"])

    for heading in settings.get("source_headings", []) or []:
        node = _source_heading_node(str(heading))
        if node["id"] not in seen:
            nodes.append(node)
            seen.add(node["id"])

    if not nodes:
        taxonomy = research.get("taxonomy", {}) if isinstance(research.get("taxonomy", {}), dict) else {}
        for item in taxonomy.get("paper_types", []) or []:
            if isinstance(item, dict) and item.get("label"):
                node = _source_heading_node(str(item["label"]))
                node["description"] = str(item.get("description") or node["description"])
                if node["id"] not in seen:
                    nodes.append(node)
                    seen.add(node["id"])

    generated_at = generated_at or _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    data = {
        "schema_version": "awesome-hub.taxonomy.v1",
        "generated_at": generated_at,
        "mode": settings.get("update_mode", "propose"),
        "nodes": nodes,
    }
    _dump_yaml(data_dir / "taxonomy.yaml", data)
    return len(_flatten_nodes(nodes))


def assign_papers_to_taxonomy(
    data_dir: Path,
    config: Dict[str, Any],
    *,
    use_llm: bool = True,
) -> int:
    """Assign every paper in papers.yaml to taxonomy nodes."""
    taxonomy = _load_yaml(data_dir / "taxonomy.yaml", {})
    nodes = taxonomy.get("nodes", []) if isinstance(taxonomy, dict) else []
    flat_nodes = _flatten_nodes(nodes)
    if not flat_nodes:
        return 0

    papers = _load_yaml(data_dir / "papers.yaml", [])
    if not isinstance(papers, list):
        return 0

    node_terms = [(path, node, _node_terms(path, node)) for path, node in flat_nodes]
    assignments = []
    updated = 0

    for paper in papers:
        if not isinstance(paper, dict):
            continue
        text = _paper_text(paper)
        scored = [
            (path, _score_node(text, terms), terms)
            for path, _node, terms in node_terms
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        best_path, best_score, best_terms = scored[0]
        secondary = [path for path, score, _terms in scored[1:4] if score > 0]
        evidence_terms = [term for term in best_terms if term and term in text][:3]
        evidence = ", ".join(evidence_terms) or best_path.replace(".", " / ").replace("_", " ")
        confidence = min(0.95, round(0.35 + best_score / 20, 2)) if best_score > 0 else 0.25
        assignment = {
            "primary": best_path,
            "secondary": secondary,
            "confidence": confidence,
            "evidence": evidence,
        }
        paper["taxonomy"] = assignment
        assignments.append({"paper_id": paper.get("id", ""), **assignment})
        updated += 1

    _dump_yaml(data_dir / "papers.yaml", papers)
    _dump_yaml(
        data_dir / "paper_taxonomy.yaml",
        {
            "schema_version": "awesome-hub.paperTaxonomy.v1",
            "generated_at": _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "assignments": assignments,
        },
    )
    return updated
