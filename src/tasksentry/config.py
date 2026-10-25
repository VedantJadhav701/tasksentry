"""Configuration management for TaskSentry.

Loads settings with the following precedence:
1. Explicit function overrides.
2. Environment variables prefixed with TASKSENTRY_.
3. Configuration file (tasksentry.yaml or tasksentry.yml).
4. Default fallback values.

Never stores or hardcodes API keys.
"""

import contextlib
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskSentryConfig(BaseModel):
    """Runtime configuration settings for TaskSentry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pricing_table_path: str | None = None
    database_path: str = Field(default="tasksentry.db")
    dashboard_host: str = Field(default="127.0.0.1")
    dashboard_port: int = Field(default=8080, ge=1, le=65535)
    console_host: str = Field(default="127.0.0.1")
    console_port: int = Field(default=8321, ge=1, le=65535)
    default_policy: str = Field(default="default")
    model_registry_path: str | None = None
    tool_registry_path: str | None = None
    log_level: str = Field(default="INFO")
    otel_enabled: bool = Field(default=False)
    ollama_base_url: str = Field(default="http://localhost:11434/v1")


def _load_yaml_file(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        import yaml  # type: ignore[import-untyped]

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except ImportError:
        return {}


def load_config(
    config_path: str | None = None,
    **overrides: Any,
) -> TaskSentryConfig:
    """Load configuration from file, environment variables, and explicit overrides."""
    file_data: dict[str, Any] = {}
    if config_path:
        file_data = _load_yaml_file(config_path)
    else:
        for candidate in ("tasksentry.yaml", "tasksentry.yml"):
            if os.path.isfile(candidate):
                file_data = _load_yaml_file(candidate)
                break

    # Environment variables prefixed with TASKSENTRY_
    env_data: dict[str, Any] = {}
    mapping = {
        "TASKSENTRY_PRICING_TABLE_PATH": "pricing_table_path",
        "TASKSENTRY_DATABASE_PATH": "database_path",
        "TASKSENTRY_DASHBOARD_HOST": "dashboard_host",
        "TASKSENTRY_DASHBOARD_PORT": "dashboard_port",
        "TASKSENTRY_DEFAULT_POLICY": "default_policy",
        "TASKSENTRY_MODEL_REGISTRY_PATH": "model_registry_path",
        "TASKSENTRY_TOOL_REGISTRY_PATH": "tool_registry_path",
        "TASKSENTRY_LOG_LEVEL": "log_level",
        "TASKSENTRY_OTEL_ENABLED": "otel_enabled",
        "TASKSENTRY_OLLAMA_BASE_URL": "ollama_base_url",
    }
    for env_var, field_name in mapping.items():
        if env_var in os.environ:
            val = os.environ[env_var]
            if field_name == "dashboard_port":
                with contextlib.suppress(ValueError):
                    env_data[field_name] = int(val)
            elif field_name == "otel_enabled":
                env_data[field_name] = val.lower() in ("1", "true", "yes", "on")
            else:
                env_data[field_name] = val

    merged: dict[str, Any] = {}
    # 1. file data
    merged.update({k: v for k, v in file_data.items() if v is not None})
    # 2. env vars
    merged.update({k: v for k, v in env_data.items() if v is not None})
    # 3. explicit overrides
    merged.update({k: v for k, v in overrides.items() if v is not None})

    return TaskSentryConfig(**merged)
