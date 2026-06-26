#!/usr/bin/env python3
"""Build a read-first deep research queue.

The queue is intentionally local and deterministic. It creates a manifest and
per-paper research stubs that later LLM/PDF/code readers can fill in.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _load_papers(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return data if isinstance(data, list) else []


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _score(paper: Dict[str, Any]) -> float:
    score = paper.get("score") if isinstance(paper.get("score"), dict) else {}
    value = score.get("read_first_score", score.get("total", 0))
    return float(value or 0)


def _component_summary(paper: Dict[str, Any]) -> List[str]:
    score = paper.get("score") if isinstance(paper.get("score"), dict) else {}
    components = score.get("components") if isinstance(score.get("components"), dict) else {}
    lines = []
    for key, component in sorted(
        components.items(),
        key=lambda item: float(item[1].get("value", 0) if isinstance(item[1], dict) else 0),
        reverse=True,
    ):
        if not isinstance(component, dict):
            continue
        explanation = component.get("explanation") or ""
        lines.append(f"- {key}: {component.get('value', 0)} - {explanation}")
    return lines


def _run_id(workflow: str, generated_at: str, paper_ids: List[str]) -> str:
    digest = hashlib.sha256(f"{workflow}\0{generated_at}\0{','.join(paper_ids)}".encode()).hexdigest()[:16]
    return f"{workflow}:{digest}"


def _artifact_path(resource_dir: Path, paper_id: str) -> Path:
    return resource_dir / paper_id / "research.md"


def _write_report(path: Path, paper: Dict[str, Any], generated_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    lines = [
        f"# {paper.get('title', paper.get('id', 'Untitled paper'))}",
        "",
        f"- Status: planned",
        f"- Generated at: {generated_at}",
        f"- Read-first score: {_score(paper):.1f}",
        f"- Paper: {links.get('paper', '')}",
        f"- Code: {links.get('code', links.get('github', ''))}",
        "",
        "## Score Signals",
        "",
        *(_component_summary(paper) or ["- No score components recorded yet."]),
        "",
        "## Research Questions",
        "",
        "- What is the core technical contribution?",
        "- What evidence supports the main claims?",
        "- What are the strongest limitations and reproduction risks?",
        "- Which datasets, baselines, code, or project artifacts should be inspected next?",
        "",
        "## Claim Extraction",
        "",
        "- Main claims: extract only claims supported by the paper text.",
        "- Methodology details: identify model design, data, training or evaluation setup, datasets, baselines, metrics, and compute assumptions when available.",
        "- Experimental results: separate measured results from motivation, speculation, or future work.",
        "- Limitations: preserve stated limitations and add observed reproduction risks as unverified notes.",
        "- Related-work connections: record explicit links to prior work, competing approaches, or benchmarks.",
        "",
        "## Evidence and Verification",
        "",
        "- source locations: attach section, page, figure, table, equation, repository path, or dataset card locations for every important finding.",
        "- Availability checks: verify paper, PDF, code, datasets, baselines, metrics, checkpoints, and artifacts before describing them as available.",
        "- Evidence status: mark each claim as verified, partially verified, unverified, or blocked.",
        "- Cross-checks: compare claims against abstracts, experiments, linked code, and benchmark descriptions.",
        "",
        "## Notes",
        "",
        "This file is a planned deep-research stub generated from local metadata. It has not yet verified full text, code, or citation claims.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _relative_resource_path(resource_dir: Path, artifact: Path) -> str:
    try:
        rel = artifact.relative_to(resource_dir)
        return f"resource/{rel.as_posix()}"
    except ValueError:
        return artifact.as_posix()


def build_deep_research_queue(
    data_dir: Path,
    config: Dict[str, Any],
    *,
    resource_dir: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> int:
    """Create deep-research manifest and report stubs for high-ranked papers."""
    research = config.get("research", {}) if isinstance(config, dict) else {}
    queue_config = research.get("deep_research", {})
    if not isinstance(queue_config, dict):
        queue_config = {}
    if queue_config.get("enabled", True) is False:
        return 0

    papers_path = data_dir / "papers.yaml"
    papers = _load_papers(papers_path)
    if not papers:
        return 0

    generated_at = generated_at or _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    resource_dir = resource_dir or Path(os.environ.get("HUB_RESOURCE_DIR", str(data_dir.parent / "resource")))
    threshold = float(queue_config.get("min_read_first_score", queue_config.get("min_score", 70)))
    max_papers = int(queue_config.get("max_papers_per_run", 10))

    candidates = [paper for paper in papers if _score(paper) >= threshold]
    candidates.sort(key=lambda paper: (-_score(paper), -(paper.get("year") or 0), paper.get("title") or ""))
    selected = candidates[:max_papers]
    if not selected:
        return 0

    run_papers = []
    artifacts = []
    for index, paper in enumerate(selected, start=1):
        paper_id = str(paper.get("id") or f"paper-{index}")
        report_path = _artifact_path(resource_dir, paper_id)
        _write_report(report_path, paper, generated_at)
        rel_path = _relative_resource_path(resource_dir, report_path)
        paper["deep_research"] = {
            "status": "planned",
            "run_status": "planned",
            "report": rel_path,
            "queued_at": generated_at,
        }
        run_papers.append(
            {
                "id": paper_id,
                "title": paper.get("title", ""),
                "rank": index,
                "score": _score(paper),
                "year": paper.get("year"),
                "url": (paper.get("links") or {}).get("paper") if isinstance(paper.get("links"), dict) else "",
                "verification": {
                    "state": "not_checked",
                    "summary": "Queued from local metadata; full text and code have not been verified.",
                },
            }
        )
        artifacts.append(
            {
                "kind": "report",
                "path": rel_path,
                "label": f"Deep research stub: {paper.get('title', paper_id)}",
                "role": "planned deep research brief",
                "primary": index == 1,
                "format": "markdown",
            }
        )

    run = {
        "run_id": _run_id("deep_research", generated_at, [paper["id"] for paper in run_papers]),
        "workflow": "deep_research",
        "generated_at": generated_at,
        "status": "planned",
        "research_jobs": [
            "reading_paper_content",
            "extracting_research_entities",
            "ranking_evidence",
            "verifying_claims",
            "synthesizing_artifacts",
        ],
        "sources": [
            {"id": "papers-yaml", "kind": "fixture", "path": "data/papers.yaml", "fields": ["score", "links", "analysis"]},
        ],
        "papers": run_papers,
        "artifacts": artifacts,
        "next_actions": [
            {
                "id": "verify-full-text",
                "title": "Fetch and inspect full text for queued papers",
                "priority": "high",
                "artifact_pointers": [artifact["path"] for artifact in artifacts],
            }
        ],
        "verification": {
            "state": "not_checked",
            "summary": "Queue generated from local metadata only.",
            "caveats": ["No full-text, code, citation, or claim verification has run yet."],
        },
    }
    manifest = {
        "schema_version": "awesome-hub.researchRuns.v1",
        "generated_at": generated_at,
        "runs": [run],
    }
    _write_yaml(data_dir / "research_runs.yaml", manifest)
    _write_yaml(papers_path, papers)
    return len(selected)
