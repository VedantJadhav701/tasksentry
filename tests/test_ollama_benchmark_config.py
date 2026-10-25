"""Unit tests for Ollama model configuration and role assignment."""

import os

import pytest
import yaml  # type: ignore[import-untyped]

from tasksentry.models.ollama import OllamaClient


def test_benchmark_models_yaml_structure() -> None:
    cfg_file = "configs/benchmark_models.yaml"
    assert os.path.isfile(cfg_file)

    with open(cfg_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "routine_models" in data
    assert "llama3.2:1b" in data["routine_models"]
    assert "gemma2:2b" in data["routine_models"]
    assert "qwen2.5:3b" in data["routine_models"]

    assert "reasoning_models" in data
    assert "qwen3:4b-instruct-2507-q4_K_M" in data["reasoning_models"]

    assert "optional_models" in data
    assert "ornith:latest" in data["optional_models"]


def test_ollama_client_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.50:11434/v1")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")

    client = OllamaClient()
    assert client.base_url == "http://192.168.1.50:11434/v1"
    assert client.model == "qwen2.5:3b"
