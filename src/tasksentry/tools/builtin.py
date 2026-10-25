"""Deterministic offline built-in tools for agent testing, benchmarking, and execution."""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from tasksentry.tools.registry import Tool, tool

_FAIL_TIMES_STATE: dict[str, int] = {}


def reset_fail_times() -> None:
    """Reset failure counters for fail_times."""
    _FAIL_TIMES_STATE.clear()


@tool(
    name="echo",
    description="Echoes back the provided text.",
    risk="read",
    idempotent=True,
    timeout_seconds=5.0,
)
def echo(text: str) -> str:
    """Return the input text unchanged."""
    return text


@tool(
    name="add",
    description="Adds two integers.",
    risk="read",
    idempotent=True,
    timeout_seconds=5.0,
)
def add(a: int, b: int) -> int:
    """Return the arithmetic sum of two integers."""
    return a + b


@tool(
    name="fail_always",
    description="Always raises a deterministic error.",
    risk="read",
    idempotent=True,
    timeout_seconds=5.0,
)
def fail_always(message: str = "Deterministic failure") -> None:
    """Deterministically raise a RuntimeError."""
    raise RuntimeError(message)


@tool(
    name="fail_times",
    description="Fails the first N calls, then succeeds.",
    risk="read",
    idempotent=False,
    timeout_seconds=5.0,
)
def fail_times(message: str = "Transient failure", n_failures: int = 1) -> str:
    """Fail the first n_failures times, then return 'success'."""
    current = _FAIL_TIMES_STATE.get(message, 0)
    if current < n_failures:
        _FAIL_TIMES_STATE[message] = current + 1
        raise RuntimeError(f"{message} (attempt {current + 1} of {n_failures})")
    return "success"


@tool(
    name="slow_tool",
    description="Sleeps for a specified duration and returns.",
    risk="read",
    idempotent=True,
    timeout_seconds=1.0,
)
def slow_tool(duration_seconds: float = 2.0) -> str:
    """Sleep for duration_seconds (useful for timeout verification)."""
    time.sleep(duration_seconds)
    return f"slept {duration_seconds}s"


@tool(
    name="read_text_file",
    description="Reads and returns the contents of a text file.",
    risk="read",
    idempotent=True,
    timeout_seconds=10.0,
)
def read_text_file(path: str) -> str:
    """Read full text content from path."""
    with open(path, encoding="utf-8") as f:
        return f.read()


@tool(
    name="write_text_file",
    description="Writes text content to a destination file path.",
    risk="write",
    idempotent=True,
    timeout_seconds=10.0,
)
def write_text_file(path: str, content: str) -> int:
    """Write text content to file, creating parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        return f.write(content)


@tool(
    name="list_directory",
    description="Lists entries inside a directory.",
    risk="read",
    idempotent=True,
    timeout_seconds=5.0,
)
def list_directory(path: str = ".") -> list[str]:
    """Return sorted filenames within directory."""
    return sorted(os.listdir(path))


@tool(
    name="run_command",
    description="Executes a system shell command safely offline.",
    risk="write",
    idempotent=False,
    timeout_seconds=30.0,
)
def run_command(command: str) -> dict[str, Any]:
    """Run command in a subprocess and return returncode, stdout, and stderr."""
    proc = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


@tool(
    name="json_validate",
    description="Validates a JSON string and checks required keys if specified.",
    risk="read",
    idempotent=True,
    timeout_seconds=5.0,
)
def json_validate(json_str: str, schema: dict[str, Any] | None = None) -> bool:
    """Verify that json_str is valid JSON and contains required properties."""
    parsed = json.loads(json_str)
    if schema and "required" in schema and isinstance(parsed, dict):
        required_keys = schema.get("required", [])
        for k in required_keys:
            if k not in parsed:
                return False
    return True


BUILTIN_TOOLS: list[Tool] = [
    echo,
    add,
    fail_always,
    fail_times,
    slow_tool,
    read_text_file,
    write_text_file,
    list_directory,
    run_command,
    json_validate,
]
