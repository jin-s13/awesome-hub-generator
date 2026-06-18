"""
generate_interpretations.py — Generate TLDR, reasoning, and deep analysis for papers.

Uses the LLM (ARK API) to:
1. Generate TLDR (one-sentence summary)
2. Generate reasoning (why this paper scored well/poorly)
3. Generate deep analysis (innovations, methodology, limitations) — uses SMART_LLM
4. Generate Chinese translations (title_cn, abstract_cn, tldr_cn, analysis_cn)

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


def translate_title_abstract(title: str, abstract: str) -> Dict:
    """
    Translate paper title and abstract to Chinese.

    Returns: {"title_cn": str, "abstract_cn": str}
    """
    if not title and not abstract:
        return {"title_cn": "", "abstract_cn": ""}

    prompt = f"""You are a professional academic translator. Translate the following paper title and abstract from English to Chinese.

Requirements:
1. Keep academic terminology accurate
2. Make the translation fluent and natural in Chinese
3. Keep proper nouns (model names, dataset names, etc.) in English on first occurrence, optionally annotating with Chinese

Title: {title}

Abstract: {abstract[:2000]}

Return ONLY valid JSON, no other text:
{{
  "title_cn": "Chinese translation of the title",
  "abstract_cn": "Chinese translation of the abstract"
}}"""

    raw = _llm_chat([{"role": "user", "content": prompt}], max_tokens=2048)
    if not raw:
        return {"title_cn": "", "abstract_cn": ""}

    result = _extract_json(raw)
    if result:
        return {
            "title_cn": result.get("title_cn", ""),
            "abstract_cn": result.get("abstract_cn", ""),
        }
    return {"title_cn": "", "abstract_cn": ""}


def generate_tldr_cn(title: str, abstract: str, tldr_en: str) -> str:
    """
    Generate a Chinese TLDR (one-sentence summary) based on the English TLDR and paper content.

    Returns: Chinese TLDR string, or empty string on failure.
    """
    if not tldr_en:
        return ""

    prompt = f"""You are a research paper summarizer. Based on the paper's English TLDR and content, generate a concise one-sentence summary in Chinese (max 50 Chinese characters).

English TLDR: {tldr_en}

Title: {title}
Abstract: {abstract[:1000]}

Return ONLY the Chinese summary, no JSON, no explanation, no English."""
    raw = _llm_chat([{"role": "user", "content": prompt}], max_tokens=256)
    return raw.strip() if raw else ""


def translate_analysis(analysis: Dict) -> Dict:
    """
    Translate analysis fields (innovations, methodology, key_results, limitations, tech_stack)
    to Chinese.

    Returns: dict with Chinese translations, preserving the same structure.
    """
    if not analysis:
        return {}

    innovations = analysis.get("innovations", [])
    methodology = analysis.get("methodology", "")
    key_results = analysis.get("key_results", "")
    limitations = analysis.get("limitations", [])
    tech_stack = analysis.get("tech_stack", [])

    innovations_str = "\n".join(f"- {i}" for i in innovations) if innovations else "None"
    limitations_str = "\n".join(f"- {l}" for l in limitations) if limitations else "None"
    tech_stack_str = ", ".join(tech_stack) if tech_stack else "None"

    prompt = f"""You are a professional academic translator. Translate the following research paper analysis from English to Chinese.

Requirements:
1. Keep academic terminology accurate
2. Make the translation fluent and natural in Chinese
3. Keep proper nouns (model names, dataset names, technology names) in English

Innovations:
{innovations_str}

Methodology:
{methodology}

Key Results:
{key_results}

Limitations:
{limitations_str}

Tech Stack:
{tech_stack_str}

Return ONLY valid JSON, no other text:
{{
  "innovations": ["translated innovation 1", "translated innovation 2"],
  "methodology": "translated methodology",
  "key_results": "translated key results",
  "limitations": ["translated limitation 1", "translated limitation 2"],
  "tech_stack": ["tech1", "tech2"]
}}"""

    raw = _llm_chat([{"role": "user", "content": prompt}], max_tokens=2048)
    if not raw:
        return {}

    result = _extract_json(raw)
    if result:
        return {
            "innovations": result.get("innovations", []),
            "methodology": result.get("methodology", ""),
            "key_results": result.get("key_results", ""),
            "limitations": result.get("limitations", []),
            "tech_stack": result.get("tech_stack", []),
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
    else:
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

    # =====================================================================
    # Step 3: Generate Chinese translations for papers missing Chinese fields
    # =====================================================================
    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    if not isinstance(papers, list):
        return

    papers_needing_cn = [
        p for p in papers
        if p.get("title") and (not p.get("title_cn") or not p.get("abstract_cn"))
    ]
    if not papers_needing_cn:
        logger.info("All papers already have Chinese translations")
    else:
        logger.info(f"Generating Chinese translations for {len(papers_needing_cn)} papers...")

        cn_updated = 0
        for i, paper in enumerate(papers_needing_cn):
            title = paper.get("title", "")
            abstract = paper.get("abstract", "")
            if not title or not abstract:
                continue

            logger.info(f"  [CN {i+1}/{len(papers_needing_cn)}] {title[:60]}...")

            # Translate title and abstract
            trans_result = translate_title_abstract(title, abstract)
            if trans_result.get("title_cn"):
                paper["title_cn"] = trans_result["title_cn"]
            if trans_result.get("abstract_cn"):
                paper["abstract_cn"] = trans_result["abstract_cn"]

            # Generate Chinese TLDR if English TLDR exists
            tldr_en = paper.get("tldr", "")
            if tldr_en and not paper.get("tldr_cn"):
                tldr_cn = generate_tldr_cn(title, abstract, tldr_en)
                if tldr_cn:
                    paper["tldr_cn"] = tldr_cn

            # Translate analysis if it exists and no Chinese analysis yet
            analysis = paper.get("analysis")
            if analysis and not paper.get("analysis_cn"):
                analysis_cn = translate_analysis(analysis)
                if analysis_cn:
                    paper["analysis_cn"] = analysis_cn

            cn_updated += 1
            time.sleep(0.5)  # Rate limit

        if cn_updated > 0:
            papers_path.write_text(
                yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
                encoding="utf-8",
            )
            logger.info(f"Updated {cn_updated} papers with Chinese translations")

        logger.info(f"Done: {cn_updated} papers with Chinese translations")


if __name__ == "__main__":
    main()
