"""Unit tests for configuration loading and precedence."""

import os

import pytest

from tasksentry.config import TaskSentryConfig, load_config


def test_default_config() -> None:
    cfg = load_config()
    assert isinstance(cfg, TaskSentryConfig)
    assert cfg.database_path == "tasksentry.db"
    assert cfg.dashboard_host == "127.0.0.1"
    assert cfg.dashboard_port == 8080
    assert cfg.log_level == "INFO"
    assert cfg.otel_enabled is False


def test_explicit_overrides() -> None:
    cfg = load_config(
        database_path="custom.db",
        dashboard_port=9090,
        otel_enabled=True,
    )
    assert cfg.database_path == "custom.db"
    assert cfg.dashboard_port == 9090
    assert cfg.otel_enabled is True


def test_env_var_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TASKSENTRY_DATABASE_PATH", "env_test.db")
    monkeypatch.setenv("TASKSENTRY_DASHBOARD_PORT", "9999")
    monkeypatch.setenv("TASKSENTRY_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TASKSENTRY_OTEL_ENABLED", "true")

    cfg = load_config()
    assert cfg.database_path == "env_test.db"
    assert cfg.dashboard_port == 9999
    assert cfg.log_level == "DEBUG"
    assert cfg.otel_enabled is True


def test_yaml_config_file_loading(tmp_path: os.PathLike[str]) -> None:
    yaml_file = os.path.join(str(tmp_path), "tasksentry.yaml")
    with open(yaml_file, "w", encoding="utf-8") as f:
        f.write(
            """
database_path: file_db.sqlite
dashboard_port: 8888
log_level: WARNING
"""
        )

    cfg = load_config(config_path=yaml_file)
    assert cfg.database_path == "file_db.sqlite"
    assert cfg.dashboard_port == 8888
    assert cfg.log_level == "WARNING"
