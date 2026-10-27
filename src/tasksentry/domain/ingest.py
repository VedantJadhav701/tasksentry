"""Deterministic adapters for common customer dataset formats."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO

from pydantic import BaseModel, ConfigDict, Field

InputFormat = Literal["json", "jsonl", "csv", "chatml"]


class IngestError(ValueError):
    """Raised when strict ingestion encounters invalid input."""


class FormatRecognition(BaseModel):
    """Auditable result of format detection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: InputFormat
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    recognizer: Literal["deterministic", "optional"] = "deterministic"


class IngestIssue(BaseModel):
    """A malformed row that can be reviewed without losing valid rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row: int = Field(ge=1)
    message: str
    raw: str = ""


class IngestResult(BaseModel):
    """Raw records plus format evidence, deduplication count, and row errors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recognition: FormatRecognition
    records: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[IngestIssue] = Field(default_factory=list)
    duplicates_removed: int = Field(default=0, ge=0)


class Recognizer(Protocol):
    """Optional recognizer protocol; callers must explicitly enable it."""

    def recognize(self, sample: str) -> FormatRecognition | None:
        """Suggest a format without changing any record or policy fields."""


def _read_text(source: str | Path | TextIO) -> tuple[str, str | None]:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8"), source.name
    if hasattr(source, "read"):
        return str(source.read()), getattr(source, "name", None)
    if "\n" not in source and "\r" not in source:
        try:
            path = Path(source)
            if path.is_file():
                return path.read_text(encoding="utf-8"), path.name
        except OSError:
            pass
    return source, None


def _looks_like_chatml(value: Any) -> bool:
    if isinstance(value, dict):
        messages = value.get("messages")
        return isinstance(messages, list) and all(isinstance(item, dict) for item in messages)
    return (
        isinstance(value, list) and bool(value) and all(_looks_like_chatml(item) for item in value)
    )


def _deterministic_recognize(text: str, filename: str | None = None) -> FormatRecognition:
    stripped = text.lstrip("\ufeff \t\r\n")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        if _looks_like_chatml(parsed):
            return FormatRecognition(
                format="chatml", confidence=0.99, reason="JSON object(s) contain messages lists."
            )
        if isinstance(parsed, (dict, list)):
            return FormatRecognition(format="json", confidence=0.99, reason="Input is valid JSON.")

    nonempty = [line for line in text.splitlines() if line.strip()]
    if len(nonempty) >= 2:
        valid_json_lines = 0
        for line in nonempty:
            try:
                value = json.loads(line)
                valid_json_lines += isinstance(value, dict)
            except json.JSONDecodeError:
                continue
        if valid_json_lines == len(nonempty):
            chatml = all(_looks_like_chatml(json.loads(line)) for line in nonempty)
            return FormatRecognition(
                format="chatml" if chatml else "jsonl",
                confidence=0.98 if chatml else 0.95,
                reason="Every non-empty line is a JSON object."
                + (" Each object contains messages." if chatml else ""),
            )

    first_line = next((line for line in text.splitlines() if line.strip()), "")
    if "," in first_line:
        try:
            dialect = csv.Sniffer().sniff(first_line)
            if dialect.delimiter == "," and len(next(csv.reader([first_line]), [])) >= 2:
                return FormatRecognition(
                    format="csv",
                    confidence=0.8,
                    reason="The first row has a comma-delimited header.",
                )
        except csv.Error:
            pass
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv":
        return FormatRecognition(format="csv", confidence=0.6, reason="File extension is .csv.")
    if suffix == ".jsonl":
        return FormatRecognition(format="jsonl", confidence=0.6, reason="File extension is .jsonl.")
    return FormatRecognition(
        format="json", confidence=0.2, reason="No deterministic format signature was found."
    )


def recognize_format(
    source: str | Path | TextIO,
    *,
    recognizer: Recognizer | None = None,
    allow_optional: bool = False,
) -> FormatRecognition:
    """Recognize input format deterministically, optionally consulting an explicit recognizer."""
    text, filename = _read_text(source)
    result = _deterministic_recognize(text, filename)
    if result.confidence >= 0.6 or recognizer is None or not allow_optional:
        return result
    proposed = recognizer.recognize(text[:12000])
    if proposed is None:
        return result
    return proposed.model_copy(update={"recognizer": "optional"})


def _as_record(value: Any, row: int, raw: str, issues: list[IngestIssue]) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    issues.append(IngestIssue(row=row, message="record must be a JSON object", raw=raw[:1000]))
    return None


def _parse_text(
    text: str, fmt: InputFormat, *, strict: bool
) -> tuple[list[dict[str, Any]], list[IngestIssue]]:
    issues: list[IngestIssue] = []
    records: list[dict[str, Any]] = []

    def invalid(row: int, message: str, raw: str) -> None:
        issue = IngestIssue(row=row, message=message, raw=raw[:1000])
        if strict:
            raise IngestError(f"row {row}: {message}")
        issues.append(issue)

    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not any(name.strip() for name in reader.fieldnames):
            invalid(1, "CSV input has no header", text[:1000])
            return records, issues
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                invalid(row_number, "CSV row has more fields than its header", str(row))
                continue
            records.append({str(k): v for k, v in row.items() if k is not None})
        return records, issues

    if fmt == "jsonl" or fmt == "chatml":
        lines = [line for line in text.splitlines() if line.strip()]
        if fmt == "chatml" and len(lines) == 1:
            try:
                parsed = json.loads(lines[0])
                values: Sequence[Any] = parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError as exc:
                invalid(1, f"invalid JSON: {exc.msg}", lines[0])
                return records, issues
            for row_number, value in enumerate(values, start=1):
                record = _as_record(value, row_number, json.dumps(value), issues)
                if record is not None:
                    records.append(record)
            return records, issues
        for row_number, line in enumerate(lines, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                invalid(row_number, f"invalid JSON: {exc.msg}", line)
                continue
            record = _as_record(value, row_number, line, issues)
            if record is not None:
                records.append(record)
        return records, issues

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        invalid(1, f"invalid JSON: {exc.msg}", text)
        return records, issues
    values = parsed if isinstance(parsed, list) else [parsed]
    for row_number, value in enumerate(values, start=1):
        record = _as_record(value, row_number, json.dumps(value), issues)
        if record is not None:
            records.append(record)
    return records, issues


def _record_key(record: Mapping[str, Any]) -> str:
    for name in ("id", "record_id", "ticket_id", "case_id"):
        value = record.get(name)
        if value not in (None, ""):
            return f"id:{value}"
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return "hash:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def deduplicate_records(records: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Stable first-wins deduplication by record ID, then canonical content hash."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    removed = 0
    for record in records:
        key = _record_key(record)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        unique.append(dict(record))
    return unique, removed


def ingest(
    source: str | Path | TextIO,
    *,
    format: InputFormat | None = None,
    strict: bool = False,
    deduplicate: bool = True,
    recognizer: Recognizer | None = None,
    allow_optional_recognizer: bool = False,
) -> IngestResult:
    """Read JSON, JSONL, CSV, or ChatML records without executing any content."""
    text, filename = _read_text(source)
    recognition = (
        FormatRecognition(format=format, confidence=1.0, reason="Format supplied by caller.")
        if format is not None
        else _deterministic_recognize(text, filename)
    )
    if format is None and recognition.confidence < 0.6 and recognizer is not None:
        proposed = recognizer.recognize(text[:12000]) if allow_optional_recognizer else None
        if proposed is not None:
            recognition = proposed.model_copy(update={"recognizer": "optional"})
    records, issues = _parse_text(text, recognition.format, strict=strict)
    if deduplicate:
        records, duplicates_removed = deduplicate_records(records)
    else:
        duplicates_removed = 0
    return IngestResult(
        recognition=recognition,
        records=records,
        issues=issues,
        duplicates_removed=duplicates_removed,
    )
