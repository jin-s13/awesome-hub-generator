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
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from scripts.llm_cache import (
        LLMCallResult,
        estimate_tokens_from_messages,
        estimate_tokens_from_text,
        get_default_cache,
        paper_identity_from,
        usage_from_provider,
    )
except ImportError:
    from llm_cache import (  # type: ignore
        LLMCallResult,
        estimate_tokens_from_messages,
        estimate_tokens_from_text,
        get_default_cache,
        paper_identity_from,
        usage_from_provider,
    )

logger = logging.getLogger("generate_interpretations")

ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = Path.cwd()
DATA_DIR = Path(os.environ.get("HUB_DATA_DIR", str(SITE_DIR / ".local/data")))

# Load .env file: check CWD first, then ROOT
for _env_path in [SITE_DIR / ".env", ROOT / ".env"]:
    if _env_path.exists():
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _key, _val = _line.split("=", 1)
                    _val = _val.strip("\"'")
                    os.environ.setdefault(_key.strip(), _val)
        break

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


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _llm_call_once(client: Any, messages: List[Dict], model: str, max_tokens: int) -> LLMCallResult:
    """Single LLM call attempt (retried by tenacity on transient failures)."""
    response = client.responses.create(
        model=model,
        input=messages,
        temperature=0.1,
        max_output_tokens=max_tokens,
    )
    text = ""
    for output in response.output:
        if output.type == "message":
            for content in output.content:
                if content.type == "output_text":
                    text = content.text
                    break
    usage = usage_from_provider(
        getattr(response, "usage", None),
        prompt_fallback=estimate_tokens_from_messages(messages),
        completion_fallback=estimate_tokens_from_text(text),
    )
    return LLMCallResult.from_text(text, usage)


def _llm_chat(
    messages: List[Dict],
    model: str = "",
    max_tokens: int = 1024,
    *,
    task_type: str = "interpretation",
    prompt_version: str = "v1",
    paper_identity: str = "",
    abstract: str = "",
    criteria: Any = None,
) -> str:
    """Call LLM with automatic retry on transient failures."""
    client = _get_ark_client()
    if not client:
        return ""

    model = model or MODEL_NAME

    try:
        result = get_default_cache().get_or_call_llm(
            task_type=task_type,
            model=model,
            prompt_version=prompt_version,
            paper_identity=paper_identity,
            abstract=abstract,
            criteria=criteria or {},
            messages=messages,
            call_func=lambda: _llm_call_once(client, messages, model, max_tokens),
        )
        return result.text
    except Exception as e:
        logger.warning(f"LLM call failed after retries: {e}")
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
  "has_real_world": true or false,
  "keyword_scores": {{
    "keyword1": score1,
    "keyword2": score2
  }}
}}

Score each keyword 0-10 based on relevance to the paper.
"has_real_world" should be true if the paper includes real-world experiments, benchmarks, datasets, or empirical evaluations.
Keywords to score: {kw_list}

Title: {title}
Abstract: {abstract[:1500]}

Return ONLY valid JSON, no other text."""

    raw = _llm_chat(
        [{"role": "user", "content": prompt}],
        max_tokens=1024,
        task_type="tldr_reasoning",
        prompt_version="tldr_reasoning_v1",
        paper_identity=paper_identity_from(title=title),
        abstract=abstract,
        criteria={"keywords": keywords[:20]},
    )
    if not raw:
        return {"tldr": "", "reasoning": "", "keyword_scores": {}}

    result = _extract_json(raw)
    if result:
        return {
            "tldr": result.get("tldr", ""),
            "reasoning": result.get("reasoning", ""),
            "has_real_world": result.get("has_real_world", False),
            "keyword_scores": result.get("keyword_scores", {}),
        }
    return {"tldr": "", "reasoning": "", "has_real_world": False, "keyword_scores": {}}


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

    raw = _llm_chat(
        [{"role": "user", "content": prompt}],
        model=SMART_MODEL,
        max_tokens=4096,
        task_type="deep_analysis",
        prompt_version="deep_analysis_v1",
        paper_identity=paper_identity_from(title=title),
        abstract=abstract,
    )
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

    raw = _llm_chat(
        [{"role": "user", "content": prompt}],
        max_tokens=4096,
        task_type="translate_title_abstract",
        prompt_version="translate_title_abstract_v1",
        paper_identity=paper_identity_from(title=title),
        abstract=abstract,
    )
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
    raw = _llm_chat(
        [{"role": "user", "content": prompt}],
        max_tokens=256,
        task_type="translate_tldr",
        prompt_version="translate_tldr_v1",
        paper_identity=paper_identity_from(title=title),
        abstract=abstract,
        criteria={"tldr_en": tldr_en},
    )
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

    raw = _llm_chat(
        [{"role": "user", "content": prompt}],
        max_tokens=2048,
        task_type="translate_analysis",
        prompt_version="translate_analysis_v1",
        paper_identity=paper_identity_from(title=methodology or key_results or "analysis"),
        criteria=analysis,
    )
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


def generate_chinese_fields(
    title: str,
    abstract: str,
    tldr_en: str = "",
    analysis: Optional[Dict] = None,
    requested_fields: Optional[List[str]] = None,
) -> Dict:
    """
    Generate all missing Chinese-facing paper fields in one LLM call.

    Returns any of: title_cn, abstract_cn, tldr_cn, analysis_cn.
    """
    if not title and not abstract:
        return {}

    requested = list(requested_fields) if requested_fields else ["title_cn", "abstract_cn"]
    if tldr_en and "tldr_cn" not in requested:
        requested.append("tldr_cn")
    if analysis and "analysis_cn" not in requested:
        requested.append("analysis_cn")

    requested = [f for f in requested if f in {"title_cn", "abstract_cn", "tldr_cn", "analysis_cn"}]
    if not requested:
        return {}

    analysis_payload = json.dumps(analysis or {}, ensure_ascii=False, indent=2)
    requested_schema = {
        "title_cn": "Chinese translation of the title",
        "abstract_cn": "Chinese translation of the abstract",
        "tldr_cn": "Concise Chinese one-sentence TLDR, max 50 Chinese characters",
        "analysis_cn": {
            "innovations": ["translated innovation 1"],
            "methodology": "translated methodology",
            "key_results": "translated key results",
            "limitations": ["translated limitation 1"],
            "tech_stack": ["tech1"],
        },
    }
    schema = {field: requested_schema[field] for field in requested}

    prompt = f"""You are a professional academic translator and research summarizer.

Generate the requested Chinese fields for this research paper in one JSON object.

Requirements:
1. Keep academic terminology accurate.
2. Keep model, dataset, benchmark, and method names in English when appropriate.
3. Return ONLY valid JSON with exactly the requested top-level keys.
4. Do not invent analysis fields when no English analysis is provided.

Requested JSON schema:
{json.dumps(schema, ensure_ascii=False, indent=2)}

Title:
{title}

Abstract:
{abstract[:2000]}

English TLDR:
{tldr_en or "N/A"}

English analysis JSON:
{analysis_payload if analysis else "N/A"}
"""

    raw = _llm_chat(
        [{"role": "user", "content": prompt}],
        max_tokens=4096,
        task_type="translate_chinese_fields",
        prompt_version="translate_chinese_fields_v1",
        paper_identity=paper_identity_from(title=title),
        abstract=abstract,
        criteria={
            "requested_fields": requested,
            "tldr_en": tldr_en,
            "analysis": analysis or {},
        },
    )
    if not raw:
        return {}

    result = _extract_json(raw)
    if not result:
        return {}

    output: Dict[str, Any] = {}
    for field in requested:
        value = result.get(field)
        if value:
            output[field] = value
    return output


def paper_needs_chinese_fields(paper: Dict) -> bool:
    """Return true when any Chinese-facing field can be backfilled."""
    if not paper.get("title"):
        return False
    if not paper.get("title_cn") or not paper.get("abstract_cn"):
        return True
    if paper.get("tldr") and not paper.get("tldr_cn"):
        return True
    if paper.get("analysis") and not paper.get("analysis_cn"):
        return True
    return False


def grade_papers(papers: List[Dict], config: dict) -> List[Dict]:
    """根据评分和配置对论文进行分级。

    分级规则:
      - "must_read" (必读): score.total >= grading.must_read_min_score (默认 40)
      - "worth_reading" (值得看): score.total >= grading.worth_reading_min_score (默认 20)
      - "skip" (可跳过): 低于 worth_reading_min_score

    在每篇论文中写入 paper["grade"] 字段。
    如果 grading.enabled=false，跳过不处理。
    """
    grading_config = config.get("research", {}).get("grading", {})
    if not grading_config.get("enabled", True):
        logger.info("论文分级已禁用，跳过")
        return papers

    must_read_min = grading_config.get("must_read_min_score", 40)
    worth_reading_min = grading_config.get("worth_reading_min_score", 20)

    counts = {"must_read": 0, "worth_reading": 0, "skip": 0}

    for paper in papers:
        total_score = paper.get("score", {}).get("total", 0)
        if total_score >= must_read_min:
            paper["grade"] = "must_read"
            counts["must_read"] += 1
        elif total_score >= worth_reading_min:
            paper["grade"] = "worth_reading"
            counts["worth_reading"] += 1
        else:
            paper["grade"] = "skip"
            counts["skip"] += 1

    logger.info(
        f"分级完成: {counts['must_read']} 篇必读, "
        f"{counts['worth_reading']} 篇值得看, "
        f"{counts['skip']} 篇可跳过"
    )
    return papers


def needs_interpretation(paper: Dict) -> bool:
    """Check if a paper needs interpretation."""
    return not paper.get("tldr") or not paper.get("reasoning")


def _extract_arxiv_id_from_links(links: Dict[str, str]) -> Optional[str]:
    """从 links 字典中提取 arXiv ID"""
    for v in (links or {}).values():
        m = re.search(r"arxiv\.org/(?:abs|html|pdf)/(\d+\.\d+)", str(v))
        if m:
            return m.group(1)
    return None


def _fill_missing_abstracts(papers: List[Dict], papers_path: Path) -> int:
    """对缺少 abstract 的论文，用 arXiv API 批量补充 abstract 和 authors"""
    import urllib.request

    ARXIV_API = "https://export.arxiv.org/api/query"

    id_to_paper: Dict[str, Dict] = {}
    for paper in papers:
        if paper.get("abstract"):
            continue
        arxiv_id = _extract_arxiv_id_from_links(paper.get("links", {}))
        if arxiv_id:
            id_to_paper[arxiv_id] = paper

    if not id_to_paper:
        return 0

    logger.info(f"Filling abstracts for {len(id_to_paper)} papers via arXiv API...")

    filled = 0
    BATCH = 30
    arxiv_ids = list(id_to_paper.keys())

    for i in range(0, len(arxiv_ids), BATCH):
        batch = arxiv_ids[i:i + BATCH]
        id_list = ",".join(batch)
        url = f"{ARXIV_API}?id_list={id_list}&max_results={len(batch)}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "awesome-hub-generator/1.0"})
            resp = urllib.request.urlopen(req, timeout=30)
            xml = resp.read().decode("utf-8")

            entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)
            for entry in entries:
                entry_id = re.search(r"<id>(.*?)</id>", entry, re.DOTALL)
                if not entry_id:
                    continue
                m = re.search(r"(\d+\.\d+)", entry_id.group(1))
                if not m:
                    continue
                aid = m.group(1)

                paper = id_to_paper.get(aid)
                if not paper:
                    continue

                summary = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
                if summary:
                    abstract = re.sub(r"\s+", " ", summary.group(1).strip())
                    abstract = re.sub(r"&[a-z]+;", "", abstract).strip()
                    if abstract:
                        paper["abstract"] = abstract
                        filled += 1

                if not paper.get("authors"):
                    names = re.findall(r"<name>(.*?)</name>", entry, re.DOTALL)
                    authors = [re.sub(r"\s+", " ", n).strip() for n in names if n.strip()]
                    if authors:
                        paper["authors"] = authors[:10]

            logger.info(f"  [{i + len(batch)}/{len(arxiv_ids)}] processed, {filled} abstracts filled")
            time.sleep(3)
        except Exception as e:
            logger.warning(f"  arXiv API batch {i} error: {e}")

    if filled > 0:
        papers_path.write_text(
            yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        logger.info(f"  Filled {filled} abstracts, saved to papers.yaml")

    return filled


def backfill_interpretation_links(papers_path: Path) -> int:
    """将论文解读链接回填到 papers.yaml 中。

    对于每篇论文，如果存在对应的解读文件（resource/{paper_id}/README.md），
    在 paper["links"]["interpretation"] 中设置链接。

    Returns:
        回填的论文数量
    """
    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    if not isinstance(papers, list):
        logger.error("Invalid papers.yaml format for backfill")
        return 0

    resource_dir = DATA_DIR.parent / "resource"
    backfilled = 0

    for paper in papers:
        paper_id = paper.get("id", "")
        if not paper_id:
            continue

        readme_path = resource_dir / paper_id / "README.md"
        if not readme_path.exists():
            continue

        # 确保 links 字典存在
        if "links" not in paper:
            paper["links"] = {}

        expected_link = f"/resource/{paper_id}/"
        current_link = paper["links"].get("interpretation", "")

        if current_link == expected_link:
            continue  # 已指向正确链接，跳过

        paper["links"]["interpretation"] = expected_link
        backfilled += 1

    if backfilled > 0:
        papers_path.write_text(
            yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )

    logger.info(f"回填了 {backfilled} 篇论文的解读链接")
    return backfilled


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

    # Get keywords from config (支持通过 HUB_CONFIG_PATH 环境变量指定配置文件)
    config_path = Path(os.environ.get("HUB_CONFIG_PATH", "")) if os.environ.get("HUB_CONFIG_PATH") else None
    if not config_path or not config_path.exists():
        config_path = SITE_DIR / "awesome.yaml"
    if not config_path.exists():
        config_path = ROOT / "awesome.yaml.example"
    config = {}
    keywords = []
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        keywords = config.get("research", {}).get("keywords", [])

    # 补充缺失的 abstract（用 arXiv API 批量拉取）
    _fill_missing_abstracts(papers, papers_path)

    # Find papers needing interpretation
    to_process = [p for p in papers if needs_interpretation(p)]
    if not to_process:
        logger.info("All papers already have interpretations")
    else:
        logger.info(f"Generating interpretations for {len(to_process)} papers...")

        updated = 0
        save_interval = 5
        since_last_save = 0

        for i, paper in enumerate(to_process):
            title = paper.get("title", "")
            abstract = paper.get("abstract", "")
            if not title or not abstract:
                continue

            logger.info(f"  [{i+1}/{len(to_process)}] {title[:60]}...")

            try:
                # Step 1: TLDR + reasoning
                result = generate_tldr_and_reasoning(title, abstract, keywords)
                if result.get("tldr"):
                    paper["tldr"] = result["tldr"]
                if result.get("reasoning"):
                    paper["reasoning"] = result["reasoning"]
                if "has_real_world" in result:
                    paper["has_real_world"] = result["has_real_world"]
                if result.get("keyword_scores"):
                    if "score" not in paper:
                        paper["score"] = {}
                    paper["score"]["keyword_scores"] = result["keyword_scores"]
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
                since_last_save += 1
            except Exception as e:
                logger.warning(f"    LLM error, skipping: {e}")

            time.sleep(0.5)  # Rate limit

            if since_last_save >= save_interval:
                papers_path.write_text(
                    yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
                    encoding="utf-8",
                )
                logger.info(f"  [checkpoint] saved {updated} interpretations so far...")
                since_last_save = 0

        # Save
        if updated > 0:
            papers_path.write_text(
                yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
                encoding="utf-8",
            )
            logger.info(f"Updated {updated} papers with interpretations")

        logger.info(f"Done: {updated} papers interpreted")

    # =====================================================================
    # Step 2.5: Grade papers
    # =====================================================================
    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    if isinstance(papers, list):
        grade_papers(papers, config)
        papers_path.write_text(
            yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )

    # =====================================================================
    # Step 3: Generate Chinese translations for papers missing Chinese fields
    # =====================================================================
    papers = yaml.safe_load(papers_path.read_text(encoding="utf-8"))
    if not isinstance(papers, list):
        return

    papers_needing_cn = [p for p in papers if paper_needs_chinese_fields(p)]
    if not papers_needing_cn:
        logger.info("All papers already have Chinese translations")
    else:
        logger.info(f"Generating Chinese translations for {len(papers_needing_cn)} papers...")

        cn_updated = 0
        cn_save_interval = 5
        cn_since_save = 0

        for i, paper in enumerate(papers_needing_cn):
            title = paper.get("title", "")
            abstract = paper.get("abstract", "")
            if not title or not abstract:
                continue

            logger.info(f"  [CN {i+1}/{len(papers_needing_cn)}] {title[:60]}...")

            try:
                tldr_en = paper.get("tldr", "")
                analysis = paper.get("analysis")
                requested_fields = []
                if not paper.get("title_cn"):
                    requested_fields.append("title_cn")
                if not paper.get("abstract_cn"):
                    requested_fields.append("abstract_cn")
                if tldr_en and not paper.get("tldr_cn"):
                    requested_fields.append("tldr_cn")
                if analysis and not paper.get("analysis_cn"):
                    requested_fields.append("analysis_cn")

                combined = generate_chinese_fields(
                    title=title,
                    abstract=abstract,
                    tldr_en=tldr_en if "tldr_cn" in requested_fields else "",
                    analysis=analysis if "analysis_cn" in requested_fields else None,
                    requested_fields=requested_fields,
                )

                if combined.get("title_cn"):
                    paper["title_cn"] = combined["title_cn"]
                if combined.get("abstract_cn"):
                    paper["abstract_cn"] = combined["abstract_cn"]
                if combined.get("tldr_cn"):
                    paper["tldr_cn"] = combined["tldr_cn"]
                if combined.get("analysis_cn"):
                    paper["analysis_cn"] = combined["analysis_cn"]

                # Fallbacks only run for malformed/partial combined responses.
                if ("title_cn" in requested_fields or "abstract_cn" in requested_fields) and (
                    not paper.get("title_cn") or not paper.get("abstract_cn")
                ):
                    trans_result = translate_title_abstract(title, abstract)
                    if trans_result.get("title_cn"):
                        paper["title_cn"] = trans_result["title_cn"]
                    if trans_result.get("abstract_cn"):
                        paper["abstract_cn"] = trans_result["abstract_cn"]

                if "tldr_cn" in requested_fields and not paper.get("tldr_cn"):
                    tldr_cn = generate_tldr_cn(title, abstract, tldr_en)
                    if tldr_cn:
                        paper["tldr_cn"] = tldr_cn

                if "analysis_cn" in requested_fields and not paper.get("analysis_cn"):
                    analysis_cn = translate_analysis(analysis)
                    if analysis_cn:
                        paper["analysis_cn"] = analysis_cn

                cn_updated += 1
                cn_since_save += 1
            except Exception as e:
                logger.warning(f"    CN translation error, skipping: {e}")

            time.sleep(0.5)  # Rate limit

            if cn_since_save >= cn_save_interval:
                papers_path.write_text(
                    yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
                    encoding="utf-8",
                )
                logger.info(f"  [checkpoint] saved {cn_updated} CN translations so far...")
                cn_since_save = 0

        if cn_updated > 0:
            papers_path.write_text(
                yaml.dump(papers, allow_unicode=True, sort_keys=False, default_flow_style=False),
                encoding="utf-8",
            )
            logger.info(f"Updated {cn_updated} papers with Chinese translations")

        logger.info(f"Done: {cn_updated} papers with Chinese translations")

    # =====================================================================
    # Step 4: Backfill interpretation links
    # =====================================================================
    backfill_interpretation_links(papers_path)

    try:
        llm_stats = get_default_cache().stats()
        for task, item in llm_stats.get("calls_by_task", {}).items():
            logger.info(
                "LLM %s: calls=%s cache_hits=%s tokens=%s",
                task,
                item.get("calls", 0),
                item.get("cache_hits", 0),
                item.get("total_tokens", 0),
            )
    except Exception as e:
        logger.debug("LLM stats unavailable: %s", e)


if __name__ == "__main__":
    main()
