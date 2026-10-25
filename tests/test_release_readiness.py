"""Unit tests verifying release readiness, version consistency, and CLI demo execution."""

import os
import tomllib
from pathlib import Path

from tasksentry.cli import main
from tasksentry.version import __version__


def test_release_version_consistency() -> None:
    repo_root = Path(__file__).parent.parent

    # 1. Check pyproject.toml version
    with open(repo_root / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["version"] == __version__

    # 2. Check CHANGELOG.md contains release section
    changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    expected_header = f"## [{__version__}]"
    assert expected_header in changelog, f"Missing header {expected_header} in CHANGELOG.md"


def test_cli_demo_execution_readiness(tmp_path: Path, monkeypatch: object) -> None:
    demo_db = str(tmp_path / "test_demo.db")
    import pytest

    if isinstance(monkeypatch, pytest.MonkeyPatch):
        monkeypatch.setenv("TASKSENTRY_DATABASE_PATH", demo_db)

    # Executing 'tasksentry demo' directly via main() must succeed with exit code 0
    exit_code = main(["demo"])
    assert exit_code == 0
    assert os.path.isfile(demo_db), "Demo must persist a receipt into the database"
