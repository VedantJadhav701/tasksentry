"""Unit tests for OllamaClient and health checking with mock transports."""

import json
from typing import Any

import pytest

from tasksentry.exceptions import ModelError, ModelNotFoundError
from tasksentry.models.ollama import OllamaClient, check_ollama_health


def test_ollama_client_request_formatting() -> None:
    captured: dict[str, Any] = {}

    def mock_transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body.decode("utf-8"))
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Ollama response text",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 18,
            },
            "model": "llama3.2:1b",
        }

    client = OllamaClient(
        model="llama3.2:1b",
        base_url="http://localhost:11434/v1",
        transport=mock_transport,
    )

    resp = client.complete(messages=[{"role": "user", "content": "Hello Ollama"}])
    assert resp.content == "Ollama response text"
    assert resp.input_tokens == 42
    assert resp.output_tokens == 18
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["body"]["model"] == "llama3.2:1b"
    assert resp.raw_response.get("latency_seconds") is not None


def test_ollama_client_tool_call_formatting() -> None:
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
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"query": "terms"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        }

    client = OllamaClient(transport=mock_transport)
    resp = client.complete(
        messages=[{"role": "user", "content": "lookup query"}],
        tools=[{"name": "lookup", "description": "Lookup tool", "parameters": {}}],
    )
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "lookup"
    assert resp.finish_reason == "tool_calls"


def test_ollama_client_model_not_found() -> None:
    def mock_transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> dict[str, Any]:
        raise ModelError("HTTP 404: model 'unknown:model' not found")

    client = OllamaClient(model="unknown:model", transport=mock_transport)
    with pytest.raises(ModelNotFoundError):
        client.complete([{"role": "user", "content": "test"}])


def test_ollama_client_connection_error() -> None:
    def mock_transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> dict[str, Any]:
        raise ModelError("Network connection refused")

    client = OllamaClient(transport=mock_transport)
    with pytest.raises(ModelError):
        client.complete([{"role": "user", "content": "test"}])


def test_check_ollama_health_success() -> None:
    def mock_health_transport(url: str, timeout: float) -> dict[str, Any]:
        return {"data": [{"id": "llama3.2:1b"}, {"id": "qwen2.5:3b"}]}

    res = check_ollama_health(model="llama3.2:1b", transport=mock_health_transport)
    assert res["reachable"] is True
    assert res["available"] is True
    assert "llama3.2:1b" in res["available_models"]


def test_check_ollama_health_model_missing() -> None:
    def mock_health_transport(url: str, timeout: float) -> dict[str, Any]:
        return {"data": [{"id": "gemma2:2b"}]}

    res = check_ollama_health(model="llama3.2:1b", transport=mock_health_transport)
    assert res["reachable"] is True
    assert res["available"] is False


def test_check_ollama_health_unreachable() -> None:
    def mock_health_transport(url: str, timeout: float) -> dict[str, Any]:
        raise RuntimeError("Connection refused")

    res = check_ollama_health(transport=mock_health_transport)
    assert res["reachable"] is False
    assert res["available"] is False
