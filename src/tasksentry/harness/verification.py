"""Deterministic verifiers and verification gates for success criteria and milestones."""

import json
import os
import re
import subprocess
import sys
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.core.contract import Milestone, SuccessCriterion, VerifierSpec


class VerificationResult(BaseModel):
    """Outcome of a single verification check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_id: str
    verifier: str
    passed: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


def verify_command_exit_code(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Run a command and verify expected return exit code."""
    command = config.get("command")
    if not command:
        return False, "Missing 'command' in config", {}

    expected_exit = config.get("expected_exit_code", 0)
    timeout = float(config.get("timeout_seconds", 10.0))
    cwd = config.get("cwd")

    try:
        use_shell = isinstance(command, str)
        proc = subprocess.run(
            command,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
        passed = proc.returncode == expected_exit
        msg = (
            f"Command exited with {proc.returncode} (expected {expected_exit})"
            if passed
            else f"Command failed: expected exit {expected_exit}, got {proc.returncode}"
        )
        return (
            passed,
            msg,
            {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            },
        )
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s", {"timeout": timeout}
    except Exception as exc:
        return False, f"Error executing command: {exc}", {"error": str(exc)}


def verify_pytest(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Run pytest suite in subprocess and verify zero exit code."""
    target = config.get("target", "tests")
    extra_args = config.get("extra_args", ["-q"])
    timeout = float(config.get("timeout_seconds", 30.0))
    cwd = config.get("cwd")

    cmd = [sys.executable, "-m", "pytest", target, *extra_args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
        passed = proc.returncode == 0
        msg = "Pytest suite passed" if passed else f"Pytest failed with exit code {proc.returncode}"
        return (
            passed,
            msg,
            {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            },
        )
    except subprocess.TimeoutExpired:
        return False, f"Pytest execution timed out after {timeout}s", {"timeout": timeout}
    except Exception as exc:
        return False, f"Error executing pytest: {exc}", {"error": str(exc)}


def verify_json_schema(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify JSON structure against required fields and schema properties."""
    data = config.get("data")
    file_path = config.get("file_path")

    if file_path:
        if not os.path.exists(file_path):
            return False, f"JSON file does not exist: {file_path}", {}
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            return False, f"Failed to parse JSON file {file_path}: {exc}", {"error": str(exc)}
    elif isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception as exc:
            return False, f"Failed to parse JSON string: {exc}", {"error": str(exc)}

    if data is None:
        return False, "No JSON data or file_path provided", {}

    required = config.get("required") or (
        config.get("schema", {}).get("required") if isinstance(config.get("schema"), dict) else None
    )
    if required and isinstance(data, dict):
        missing = [k for k in required if k not in data]
        if missing:
            return False, f"Missing required keys in JSON: {missing}", {"missing": missing}

    return True, "JSON schema validation passed", {"data": data}


def verify_file_exists(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify that a specified file exists and satisfies minimum size."""
    path = config.get("path")
    if not path:
        return False, "Missing 'path' parameter", {}

    exists = os.path.exists(path)
    if not exists:
        return False, f"File does not exist: {path}", {"path": path}

    min_bytes = config.get("min_bytes")
    if min_bytes is not None:
        size = os.path.getsize(path)
        if size < min_bytes:
            return (
                False,
                f"File {path} size {size}B < required {min_bytes}B",
                {"size": size, "min_bytes": min_bytes},
            )

    return True, f"File exists: {path}", {"path": path}


def verify_git_diff_nonempty(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify that working git diff is non-empty."""
    if context and "git_diff" in context:
        diff_str = str(context["git_diff"]).strip()
        passed = len(diff_str) > 0
        return (
            passed,
            ("Git diff is non-empty" if passed else "Git diff is empty"),
            {"diff": diff_str},
        )

    cwd = config.get("cwd")
    try:
        proc = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True,
            text=True,
            timeout=10.0,
            cwd=cwd,
            check=False,
        )
        passed = bool(proc.stdout.strip())
        return (
            passed,
            ("Git diff is non-empty" if passed else "Git diff is empty"),
            {"stdout": proc.stdout},
        )
    except Exception as exc:
        return False, f"Error inspecting git diff: {exc}", {"error": str(exc)}


def verify_regex_match(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify regex pattern match against string or file contents."""
    pattern = config.get("pattern")
    if not pattern:
        return False, "Missing 'pattern' parameter", {}

    text = config.get("text")
    file_path = config.get("file_path")

    if file_path:
        if not os.path.exists(file_path):
            return False, f"File {file_path} not found for regex match", {}
        with open(file_path, encoding="utf-8") as f:
            text = f.read()
    elif text is None and context:
        text = context.get("output") or context.get("text", "")

    if text is None:
        return False, "No text available for regex matching", {}

    match = re.search(pattern, str(text))
    passed = match is not None
    msg = (
        f"Pattern {pattern!r} matched"
        if passed
        else f"Pattern {pattern!r} not found in target text"
    )
    return passed, msg, {"pattern": pattern, "matched": passed}


def verify_numeric_range(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify that a numeric metric falls within [min, max] range."""
    val = config.get("value")
    key = config.get("key")
    if val is None and key and context:
        val = context.get(key)

    if val is None:
        return False, f"No numeric value found (key={key!r})", {}

    try:
        numeric = float(val)
    except (ValueError, TypeError):
        return False, f"Value {val!r} is not numeric", {}

    min_val = config.get("min")
    max_val = config.get("max")

    if min_val is not None and numeric < float(min_val):
        return False, f"Value {numeric} < minimum {min_val}", {"value": numeric, "min": min_val}
    if max_val is not None and numeric > float(max_val):
        return False, f"Value {numeric} > maximum {max_val}", {"value": numeric, "max": max_val}

    return (
        True,
        f"Numeric value {numeric} satisfies range [{min_val}, {max_val}]",
        {"value": numeric},
    )


def verify_python_assert(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Run user assertions strictly in an isolated subprocess with timeout."""
    code = config.get("code")
    module_path = config.get("module_path")
    timeout = float(config.get("timeout_seconds", 5.0))

    if not code and not module_path:
        return False, "Missing 'code' or 'module_path' for python_assert", {}

    cmd = [sys.executable, "-c", code] if code else [sys.executable, str(module_path)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        passed = proc.returncode == 0
        msg = (
            "python_assert passed successfully"
            if passed
            else f"python_assert assertion failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
        return (
            passed,
            msg,
            {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            },
        )
    except subprocess.TimeoutExpired:
        return False, f"python_assert timed out after {timeout}s", {"timeout": timeout}
    except Exception as exc:
        return False, f"python_assert error: {exc}", {"error": str(exc)}


def verify_artifact_exists(
    config: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify existence of an artifact file or canonical state artifact entry."""
    path = config.get("path")
    artifact_id = config.get("artifact_id")

    if path and os.path.exists(path):
        return True, f"Artifact file exists: {path}", {"path": path}

    if artifact_id and context:
        artifacts = context.get("artifacts") or context.get("world", {}).get("artifacts") or []
        if artifact_id in artifacts:
            return True, f"Artifact {artifact_id!r} verified in state", {"artifact_id": artifact_id}

    return False, f"Artifact not found (path={path!r}, artifact_id={artifact_id!r})", {}


VERIFIER_DISPATCH = {
    "command_exit_code": verify_command_exit_code,
    "pytest": verify_pytest,
    "json_schema": verify_json_schema,
    "file_exists": verify_file_exists,
    "git_diff_nonempty": verify_git_diff_nonempty,
    "regex_match": verify_regex_match,
    "numeric_range": verify_numeric_range,
    "python_assert": verify_python_assert,
    "artifact_exists": verify_artifact_exists,
}


class VerificationGate:
    """Evaluates task verification specs, success criteria, and milestones."""

    def __init__(self, custom_verifiers: dict[str, Any] | None = None) -> None:
        self.verifiers = dict(VERIFIER_DISPATCH)
        if custom_verifiers:
            self.verifiers.update(custom_verifiers)

    def verify(
        self,
        spec: VerifierSpec,
        criterion_id: str = "check",
        context: dict[str, Any] | None = None,
    ) -> VerificationResult:
        """Execute a verifier specification."""
        verifier_fn = self.verifiers.get(spec.verifier)
        if verifier_fn is None:
            return VerificationResult(
                criterion_id=criterion_id,
                verifier=spec.verifier,
                passed=False,
                message=f"Unknown verifier {spec.verifier!r}",
                details={"verifier": spec.verifier},
            )

        passed, msg, details = verifier_fn(spec.config, context or {})
        return VerificationResult(
            criterion_id=criterion_id,
            verifier=spec.verifier,
            passed=passed,
            message=msg,
            details=details,
        )

    def verify_criterion(
        self,
        criterion: SuccessCriterion,
        context: dict[str, Any] | None = None,
    ) -> VerificationResult:
        """Verify an objective success criterion."""
        return self.verify(criterion.spec, criterion_id=criterion.id, context=context)

    def verify_milestone(
        self,
        milestone: Milestone,
        context: dict[str, Any] | None = None,
    ) -> VerificationResult:
        """Verify whether a milestone's done_when gate passes."""
        return self.verify(milestone.done_when, criterion_id=milestone.id, context=context)

    def verify_criteria(
        self,
        criteria: list[SuccessCriterion],
        context: dict[str, Any] | None = None,
    ) -> list[VerificationResult]:
        """Evaluate a list of success criteria."""
        return [self.verify_criterion(c, context=context) for c in criteria]

    def all_required_passed(
        self,
        criteria: list[SuccessCriterion],
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, list[VerificationResult]]:
        """Verify all required criteria pass. Returns (all_passed, results)."""
        results = self.verify_criteria(criteria, context=context)
        passed_by_id = {r.criterion_id: r.passed for r in results}
        all_passed = all(passed_by_id.get(c.id, False) for c in criteria if c.required)
        return all_passed, results
