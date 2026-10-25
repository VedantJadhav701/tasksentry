"""Unit tests verifying documentation existence, links, and example scripts validity."""

import ast
from pathlib import Path


def test_core_documentation_files_exist() -> None:
    repo_root = Path(__file__).parent.parent
    core_files = [
        "README.md",
        "LICENSE",
        "NOTICE",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "RELEASE.md",
        ".env.example",
        "Makefile",
        "docker-compose.yml",
    ]
    for filename in core_files:
        path = repo_root / filename
        assert path.is_file(), f"Core root file '{filename}' is missing"


def test_docs_directory_completeness() -> None:
    repo_root = Path(__file__).parent.parent
    docs_dir = repo_root / "docs"
    expected_docs = [
        "architecture.md",
        "mathematics.md",
        "quickstart.md",
        "benchmark.md",
        "ollama.md",
        "configuration.md",
        "cli.md",
        "dashboard.md",
        "security.md",
        "roadmap.md",
        "release.md",
    ]
    for doc in expected_docs:
        doc_path = docs_dir / doc
        assert doc_path.is_file(), f"Documentation file 'docs/{doc}' is missing"
        assert doc_path.stat().st_size > 100, f"Documentation file 'docs/{doc}' is too short"


def test_example_scripts_syntax() -> None:
    repo_root = Path(__file__).parent.parent
    examples_dir = repo_root / "examples"
    expected_examples = [
        "wrap_existing_agent.py",
        "coding_agent_demo.py",
        "research_agent_demo.py",
        "dashboard_demo.py",
        "ollama_benchmark_demo.py",
    ]
    for example in expected_examples:
        ex_path = examples_dir / example
        assert ex_path.is_file(), f"Example script 'examples/{example}' is missing"

        # Verify syntactically valid Python code
        with open(ex_path, encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, filename=str(ex_path))
        assert isinstance(tree, ast.Module), f"Example '{example}' failed to parse into AST"
