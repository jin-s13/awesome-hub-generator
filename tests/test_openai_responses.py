"""Tests for the OpenAI-compatible Responses HTTP client."""

from __future__ import annotations

from scripts.llm_cache import LLMCallResult
from scripts.openai_responses import call_openai_responses, extract_response_text


def test_extract_response_text_from_output_items():
    data = {
        "output": [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "thinking"}],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "ok"},
                ],
            },
        ]
    }

    assert extract_response_text(data) == "ok"


def test_call_openai_responses_posts_standard_http_payload(monkeypatch):
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            seen["raised"] = True

        def json(self):
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "hello"},
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                },
            }

    def fake_post(url, *, headers, json, timeout):
        seen["url"] = url
        seen["headers"] = headers
        seen["json"] = json
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("scripts.openai_responses.requests.post", fake_post)

    result = call_openai_responses(
        api_key="secret",
        base_url="https://example.test/v1/",
        model="test-model",
        messages=[{"role": "user", "content": "Hi"}],
        max_tokens=64,
        temperature=0.2,
    )

    assert isinstance(result, LLMCallResult)
    assert result.text == "hello"
    assert result.total_tokens == 5
    assert seen["url"] == "https://example.test/v1/responses"
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["json"] == {
        "model": "test-model",
        "input": [{"role": "user", "content": "Hi"}],
        "max_output_tokens": 64,
        "temperature": 0.2,
    }
    assert seen["timeout"] == 60
    assert seen["raised"] is True
