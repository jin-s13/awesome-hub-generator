"""
generate_interpretations.py — Generate TLDR, reasoning, and deep analysis for papers.

Uses the LLM (ARK API) to:
1. Generate TLDR (one-sentence summary)
2. Generate reasoning (why this paper scored well/poorly)
3. Generate deep analysis (innovations, methodology, limitations) — uses SMART_LLM

Papers are processed in batch, only those missing interpretation fields.
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger("generate_interpretations")

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

# Load .env file if present
_env_path = ROOT / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _val = _val.strip("\"'")
                os.environ.setdefault(_key.strip(), _val)

# LLM config
API_KEY = os.environ.get("ARK_API_KEY", "")
API_BASE_URL = os.environ.get("ARK_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
MODEL_NAME = os.environ.get("ARK_MODEL_NAME", "deepseek-v4-flash-260425")
SMART_MODEL = os.environ.get("SMART_MODEL_NAME", MODEL_NAME)


def _get_ark_client():
    """Get Ark client."""
    from volcenginesdkarkruntime import Ark

    if not API_KEY:
        logger.warning("ARK_API_KEY not set, skipping LLM calls")
        return None
    return Ark(base_url=API_BASE_URL, api_key=API_KEY)


def _llm_chat(messages: List[Dict], model: str = "", max_tokens: int = 1024) -> str:
    """Call LLM."""
    client = _get_ark_client()
    if not client:
        return ""

    model = model or MODEL_NAME

    try:
        response = client.responses.create(
            model=model,
            input=messages,
            temperature=0.1,
            max_output_tokens=max_tokens,
        )
        for output in response.output:
            if output.type == "message":
                for content in output.content:
                    if content.type == "output_text":
                        return content.text
        return ""
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        return ""


def _extract_json(text: str) -> Optional[Dict]:
    """Extract JSON from LLM response."""
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def generate_tldr_and_reasoning(title: str, abstract: str, keywords: List[str]) -> Dict:
    """
    Generate TLDR and reasoning for a paper.

    Returns: {"tldr": str, "reasoning": str, "keyword_scores": dict}
    """
    kw_list = ", ".join(keywords[:20])
    prompt = f"""You are a research paper reviewer. Analyze this paper and return a JSON object:

{{
  "tldr": "One-sentence summary of the paper (max 30 words)",
  "reasoning": "Brief explanation of the paper's strengths and weaknesses (2-3 sentences)",
  "keyword_scores": {{
    "keyword1": score1,
    "keyword2": score2
  }}
}}

Score each keyword 0-10 based on relevance to the paper.
Keywords to score: {kw_list}

Title: {title}
Abstract: {abstract[:1500]}

Return ONLY valid JSON, no other text."""

    raw = _llm_chat([{"role": "user", "content": prompt}], max_tokens=1024)
    if not raw:
        return {"tldr": "", "reasoning": "", "keyword_scores": {}}

    result = _extract_json(raw)
    if result:
        return {
            "tldr": result.get("tldr", ""),
            "reasoning": result.get("reasoning", ""),
            "keyword_scores": result.get("keyword_scores", {}),
        }
    return {"tldr": "", "reasoning": "", "keyword_scores": {}}


def generate_deep_analysis(title: str, abstract: str) -> Dict:
    """
    Generate deep analysis for a paper using SMART_LLM.

    Returns: {"innovations": [...], "methodology": str, "key_results": str, "limitations": [...]}
    """
    prompt = f"""You are a senior researcher. Analyze this paper in depth and return a JSON object:

{{
  "innovations": ["Innovation 1", "Innovation 2", ...],
  "methodology": "Description of the methodology (2-3 sentences)",
  "key_results": "Key experimental results (1-2 sentences)",
  "limitations": ["Limitation 1", "Limitation 2", ...]
}}

Title: {title}
Abstract: {abstract[:2000]}

Return ONLY valid JSON, no other text."""

    raw = _llm_chat([{"role": "user", "content": prompt}], model=SMART_MODEL, max_tokens=2048)
    if not raw:
        return {}

    result = _extract_json(raw)
    if result:
        return {
            "innovations": result.get("innovations", []),
            "methodology": result.get("methodology", ""),
            "key_results": result.get("key_results", ""),
            "limitations": result.get("limitations", []),
        }
    return {}


def needs_interpretation(paper: Dict) -> bool:
    """Check if a paper needs interpretation."""
    return not paper.get("tldr") or not paper.get("reasoning")


def main():
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    papers_path = DATA_DIR / "papers.yaml"
    if not papers_path.exists():
        logger.error(f"Papers file not found: {papers_path}")
        return

    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    if not isinstance(papers, list):
        logger.error("Invalid papers.yaml format")
        return

    # Get keywords from config
    config_path = ROOT / "awesome.yaml"
    keywords = []
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        keywords = config.get("research", {}).get("keywords", [])

    # Find papers needing interpretation
    to_process = [p for p in papers if needs_interpretation(p)]
    if not to_process:
        logger.info("All papers already have interpretations")
        return

    logger.info(f"Generating interpretations for {len(to_process)} papers...")

    updated = 0
    for i, paper in enumerate(to_process):
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        if not title or not abstract:
            continue

        logger.info(f"  [{i+1}/{len(to_process)}] {title[:60]}...")

        # Step 1: TLDR + reasoning
        result = generate_tldr_and_reasoning(title, abstract, keywords)
        if result.get("tldr"):
            paper["tldr"] = result["tldr"]
        if result.get("reasoning"):
            paper["reasoning"] = result["reasoning"]
        if result.get("keyword_scores"):
            if "score" not in paper:
                paper["score"] = {}
            paper["score"]["keyword_scores"] = result["keyword_scores"]
            # Calculate total score
            scores = result["keyword_scores"].values()
            if scores:
                paper["score"]["total"] = round(sum(scores), 1)

        # Step 2: Deep analysis (only for papers with good scores)
        total_score = paper.get("score", {}).get("total", 0)
        if total_score >= 30 and not paper.get("analysis"):
            logger.debug(f"    Generating deep analysis...")
            analysis = generate_deep_analysis(title, abstract)
            if analysis:
                paper["analysis"] = analysis

        updated += 1
        time.sleep(0.5)  # Rate limit

    # Save
    if updated > 0:
        papers_path.write_text(
            yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        logger.info(f"Updated {updated} papers with interpretations")

    logger.info(f"Done: {updated} papers interpreted")


if __name__ == "__main__":
    main()
