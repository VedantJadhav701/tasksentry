"""Ollama client integrating local models via Ollama's OpenAI-compatible endpoint."""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from tasksentry.exceptions import ModelError, ModelNotFoundError
from tasksentry.models.base import ModelClient, ModelResponse
from tasksentry.models.openai_compat import OpenAICompatibleClient


def check_ollama_health(
    base_url: str = "http://localhost:11434/v1",
    model: str = "llama3.2:1b",
    timeout: float = 5.0,
    transport: Callable[[str, float], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check connectivity to Ollama server and verify if the requested model is loaded."""
    eff_base = os.environ.get("OLLAMA_BASE_URL", base_url).rstrip("/")
    eff_model = os.environ.get("OLLAMA_MODEL", model)

    start_time = time.perf_counter()
    endpoint = f"{eff_base}/models"

    if transport is not None:
        try:
            data = transport(endpoint, timeout)
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            models_list = [
                m.get("id") or m.get("name") for m in data.get("data", data.get("models", []))
            ]
            available = any(eff_model == m or eff_model in str(m) for m in models_list)
            return {
                "base_url": eff_base,
                "model": eff_model,
                "reachable": True,
                "available": available,
                "latency_ms": round(latency_ms, 2),
                "available_models": models_list,
                "message": (
                    f"Model '{eff_model}' found."
                    if available
                    else f"Server reachable, but model '{eff_model}' not found in {models_list}."
                ),
            }
        except Exception as exc:
            return {
                "base_url": eff_base,
                "model": eff_model,
                "reachable": False,
                "available": False,
                "latency_ms": 0.0,
                "available_models": [],
                "message": f"Connection failed: {exc}",
            }

    # Default urllib network probe
    try:
        req = urllib.request.Request(endpoint, headers={"User-Agent": "TaskSentry/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            models_list = [
                m.get("id") or m.get("name") for m in raw.get("data", raw.get("models", []))
            ]
            available = any(eff_model == m or eff_model in str(m) for m in models_list)
            return {
                "base_url": eff_base,
                "model": eff_model,
                "reachable": True,
                "available": available,
                "latency_ms": round(latency_ms, 2),
                "available_models": models_list,
                "message": (
                    f"Model '{eff_model}' is available."
                    if available
                    else f"Ollama reachable, but '{eff_model}' not installed."
                ),
            }
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return {
            "base_url": eff_base,
            "model": eff_model,
            "reachable": True,
            "available": False,
            "latency_ms": round(latency_ms, 2),
            "available_models": [],
            "message": f"Ollama server returned HTTP {exc.code}: {exc.reason}",
        }
    except Exception as exc:
        return {
            "base_url": eff_base,
            "model": eff_model,
            "reachable": False,
            "available": False,
            "latency_ms": 0.0,
            "available_models": [],
            "message": f"Could not reach Ollama at {eff_base}: {exc}",
        }


class OllamaClient(ModelClient):
    """Client for local Ollama models via OpenAI-compatible endpoints."""

    def __init__(
        self,
        model: str = "llama3.2:1b",
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        timeout_seconds: float = 120.0,
        transport: Callable[[str, dict[str, str], bytes, float], dict[str, Any]] | None = None,
    ) -> None:
        self.model = os.environ.get("OLLAMA_MODEL", model)
        self.base_url = os.environ.get("OLLAMA_BASE_URL", base_url).rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._underlying = OpenAICompatibleClient(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            timeout=self.timeout_seconds,
            transport=transport,
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Issue completion request to Ollama and measure latency."""
        start = time.perf_counter()
        try:
            resp = self._underlying.complete(
                messages=messages,
                tools=tools,
                model=kwargs.pop("model", self.model),
                timeout=kwargs.pop("timeout", self.timeout_seconds),
                **kwargs,
            )
        except ModelError as exc:
            msg = str(exc).lower()
            if "not found" in msg or "404" in msg:
                raise ModelNotFoundError(
                    f"Model '{self.model}' not found on Ollama server at {self.base_url}."
                ) from exc
            raise

        elapsed = time.perf_counter() - start
        raw = dict(resp.raw_response)
        raw["latency_seconds"] = round(elapsed, 4)

        return ModelResponse(
            content=resp.content,
            tool_calls=resp.tool_calls,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            model=resp.model or self.model,
            finish_reason=resp.finish_reason,
            raw_response=raw,
        )
