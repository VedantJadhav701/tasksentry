"""Ollama integration helpers for tracked local model execution."""

from collections.abc import Callable
from typing import Any

from tasksentry.integrations.openai import TrackedOpenAIClient
from tasksentry.models.ollama import OllamaClient


def tracked_ollama_client(
    model: str = "llama3.2:1b",
    base_url: str = "http://localhost:11434/v1",
    api_key: str = "ollama",
    timeout_seconds: float = 120.0,
    transport: Callable[[str, dict[str, str], bytes, float], dict[str, Any]] | None = None,
) -> TrackedOpenAIClient:
    """Create a tracked client backed by an Ollama model instance."""
    ollama_model = OllamaClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    return TrackedOpenAIClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout_seconds,
        model_client=ollama_model,
    )
