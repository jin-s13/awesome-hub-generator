"""OpenAI-compatible Responses API helpers."""

from __future__ import annotations

from typing import Any, Dict, List

import requests

try:
    from scripts.llm_cache import (
        LLMCallResult,
        estimate_tokens_from_messages,
        estimate_tokens_from_text,
        usage_from_provider,
    )
except ImportError:
    from llm_cache import (  # type: ignore
        LLMCallResult,
        estimate_tokens_from_messages,
        estimate_tokens_from_text,
        usage_from_provider,
    )


def extract_response_text(data: Dict[str, Any]) -> str:
    """Extract assistant text from an OpenAI-compatible Responses payload."""
    chunks: List[str] = []
    for output in data.get("output") or []:
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        for content in output.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text") or ""
                if text:
                    chunks.append(str(text))
    return "\n".join(chunks).strip()


def call_openai_responses(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: int,
    temperature: float = 0.1,
    timeout: int = 60,
) -> LLMCallResult:
    """Call an OpenAI-compatible HTTP /responses endpoint."""
    response = requests.post(
        f"{base_url.rstrip('/')}/responses",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json={
            "model": model,
            "input": messages,
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    text = extract_response_text(data)
    usage = usage_from_provider(
        data.get("usage"),
        prompt_fallback=estimate_tokens_from_messages(messages),
        completion_fallback=estimate_tokens_from_text(text),
    )
    return LLMCallResult.from_text(text, usage)
