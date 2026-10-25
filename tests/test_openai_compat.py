"""Unit tests for FakeModel and OpenAICompatibleClient."""

import json
from typing import Any

import pytest

from tasksentry.exceptions import ModelError
from tasksentry.models.fake_model import FakeModel
from tasksentry.models.openai_compat import (
    OpenAICompatibleClient,
    convert_tools_to_openai_format,
)


def test_fake_model_deterministic_output() -> None:
    model = FakeModel()
    resp1 = model.complete([{"role": "user", "content": "What is 2+2?"}])
    assert "2+2" in str(resp1.content)
    assert resp1.finish_reason == "stop"
    assert model.call_count == 1

    # Queued responses
    model.queue_response("Four")
    resp2 = model.complete([{"role": "user", "content": "Tell me again"}])
    assert resp2.content == "Four"
    assert model.call_count == 2


def test_convert_tools_to_openai_format() -> None:
    tools = [
        {
            "name": "lookup",
            "description": "Lookup information",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]
    formatted = convert_tools_to_openai_format(tools)
    assert len(formatted) == 1
    assert formatted[0]["type"] == "function"
    assert formatted[0]["function"]["name"] == "lookup"
    assert formatted[0]["function"]["description"] == "Lookup information"


def test_openai_compatible_client_mock_transport() -> None:
    captured: dict[str, Any] = {}

    def mock_transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body.decode("utf-8"))
        captured["timeout"] = timeout

        return {
            "id": "chatcmpl-test",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Paris is the capital of France.",
                        "tool_calls": [],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 8,
                "total_tokens": 23,
            },
            "model": "gpt-4o-mini",
        }

    client = OpenAICompatibleClient(
        base_url="https://api.example.com/v1",
        api_key="secret-key",
        model="gpt-4o-mini",
        transport=mock_transport,
    )

    resp = client.complete(
        messages=[{"role": "user", "content": "Capital of France?"}],
        tools=[{"name": "t1", "description": "tool1", "parameters": {}}],
    )

    assert resp.content == "Paris is the capital of France."
    assert resp.input_tokens == 15
    assert resp.output_tokens == 8
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert len(captured["body"]["tools"]) == 1


def test_openai_compatible_client_tool_call_response() -> None:
    def mock_transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "calculate",
                                    "arguments": '{"expr": "10 * 5"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    client = OpenAICompatibleClient(transport=mock_transport)
    resp = client.complete([{"role": "user", "content": "Calculate 10*5"}])

    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "calculate"
    assert resp.tool_calls[0]["arguments"] == {"expr": "10 * 5"}
    assert resp.finish_reason == "tool_calls"


def test_openai_compatible_client_error_handling() -> None:
    def error_transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> dict[str, Any]:
        raise RuntimeError("Simulated connection timeout")

    client = OpenAICompatibleClient(transport=error_transport)
    with pytest.raises(ModelError):
        client.complete([{"role": "user", "content": "hello"}])
