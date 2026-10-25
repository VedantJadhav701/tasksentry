"""Unit tests verifying packaging metadata, py.typed, and top-level SDK exports."""

import tomllib
from pathlib import Path

import tasksentry
from tasksentry.version import __version__


def test_package_version_consistency() -> None:
    assert __version__ == "0.1.0"
    assert tasksentry.__version__ == "0.1.0"


def test_pyproject_toml_structure() -> None:
    repo_root = Path(__file__).parent.parent
    pyproject_path = repo_root / "pyproject.toml"
    assert pyproject_path.is_file(), "pyproject.toml must exist"

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    assert project.get("name") == "tasksentry"
    assert project.get("version") == "0.1.0"
    assert project.get("readme") == "README.md"
    assert "dependencies" in project

    optional = project.get("optional-dependencies", {})
    for extra in ("dev", "dashboard", "ollama", "openai", "benchmark"):
        assert extra in optional, f"Optional dependency extra '{extra}' missing in pyproject.toml"

    urls = project.get("urls", {})
    for url_key in ("Homepage", "Repository", "Issues", "Changelog"):
        assert url_key in urls, f"URL '{url_key}' missing in pyproject.toml"


def test_py_typed_file_present() -> None:
    pkg_dir = Path(tasksentry.__file__).parent
    py_typed = pkg_dir / "py.typed"
    assert py_typed.is_file(), "src/tasksentry/py.typed must exist for PEP 561 compliance"


def test_public_sdk_surface_exports() -> None:
    expected_exports = [
        "AgentTask",
        "Budget",
        "BudgetPolicy",
        "TaskReceipt",
        "ToolGovernor",
        "ToolRegistry",
        "budget",
        "tool",
        "AgentRegistry",
        "ModelRegistry",
        "InMemoryReceiptStore",
        "SQLiteReceiptStore",
        "ReceiptStore",
    ]
    for symbol in expected_exports:
        assert hasattr(tasksentry, symbol), (
            f"Expected export '{symbol}' missing on top-level tasksentry"
        )
