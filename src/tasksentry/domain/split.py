"""Leakage-resistant deterministic dataset splitting."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.domain.ingest import deduplicate_records


class SplitError(ValueError):
    """Raised when records cannot be safely split."""


class SplitResult(BaseModel):
    """Time-ordered split output and reproducibility metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["time", "time_customer"]
    train: list[dict[str, Any]] = Field(default_factory=list)
    val: list[dict[str, Any]] = Field(default_factory=list)
    test: list[dict[str, Any]] = Field(default_factory=list)
    duplicates_removed: int = Field(default=0, ge=0)
    timestamp_field: str

    @property
    def validation(self) -> list[dict[str, Any]]:
        """Alias used by callers that prefer the full word."""
        return self.val


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value)
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise SplitError(f"invalid timestamp {value!r}") from exc
    raise SplitError(f"timestamp must be ISO text, datetime, or epoch number; got {value!r}")


def _time_field(record: Mapping[str, Any], requested: str | None) -> str:
    candidates = (requested,) if requested else ("created_at", "timestamp", "created", "updated_at")
    for field in candidates:
        if field and record.get(field) not in (None, ""):
            return field
    raise SplitError("every record needs a timestamp for time-based splitting")


def _customer(record: Mapping[str, Any]) -> str | None:
    for field in ("customer_id", "customer", "account_id", "tenant_customer_id"):
        value = record.get(field)
        if isinstance(value, Mapping):
            value = value.get("id") or value.get("customer_id")
        if value not in (None, ""):
            return str(value)
    return None


def _cut(groups: list[list[dict[str, Any]]], target: float, start: int, end: int) -> int:
    """Pick the group boundary nearest a target record count."""
    if end - start <= 1:
        return end
    cumulative = sum(len(group) for group in groups[:start])
    candidates: list[tuple[float, int]] = []
    for index in range(start, end):
        cumulative += len(groups[index])
        candidates.append((abs(cumulative - target), index + 1))
    return min(candidates, key=lambda item: (item[0], item[1]))[1]


def split_records(
    records: Sequence[Mapping[str, Any]],
    *,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    timestamp_field: str | None = None,
    by_customer: bool = True,
    method: str = "time",
) -> SplitResult:
    """Split records chronologically, grouping customers when customer IDs exist.

    ``method="random"`` is intentionally rejected.  A random split can leak a
    customer's future incident or the same ticket family into evaluation.
    """
    if method != "time":
        raise SplitError("only deterministic time-based splitting is supported")
    if not 0.0 < train_ratio < 1.0 or not 0.0 <= val_ratio < 1.0:
        raise SplitError("train_ratio must be in (0, 1) and val_ratio must be in [0, 1)")
    if train_ratio + val_ratio >= 1.0:
        raise SplitError("train_ratio + val_ratio must be less than 1")

    unique, duplicates_removed = deduplicate_records(records)
    if not unique:
        return SplitResult(
            method="time",
            train=[],
            val=[],
            test=[],
            duplicates_removed=duplicates_removed,
            timestamp_field=timestamp_field or "created_at",
        )

    selected_field = timestamp_field or _time_field(unique[0], None)
    timed: list[tuple[datetime, int, dict[str, Any]]] = []
    for index, record in enumerate(unique):
        field = _time_field(record, selected_field)
        if field != selected_field:
            raise SplitError(f"record {index + 1} is missing timestamp field {selected_field!r}")
        timed.append((_parse_time(record[field]), index, dict(record)))
    timed.sort(key=lambda item: (item[0], item[1]))

    grouped: list[list[dict[str, Any]]]
    use_customers = by_customer and any(_customer(record) is not None for _, _, record in timed)
    if use_customers:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for _, index, record in timed:
            customer = _customer(record) or f"__record_{index}"
            buckets[customer].append(record)
        grouped = sorted(
            buckets.values(),
            key=lambda group: (_parse_time(group[0][selected_field]), str(_customer(group[0]))),
        )
    else:
        grouped = [[record] for _, _, record in timed]

    total = len(unique)
    first_cut = _cut(grouped, total * train_ratio, 0, len(grouped))
    second_cut = _cut(grouped, total * (train_ratio + val_ratio), first_cut, len(grouped))
    train = [record for group in grouped[:first_cut] for record in group]
    val = [record for group in grouped[first_cut:second_cut] for record in group]
    test = [record for group in grouped[second_cut:] for record in group]
    return SplitResult(
        method="time_customer" if use_customers else "time",
        train=train,
        val=val,
        test=test,
        duplicates_removed=duplicates_removed,
        timestamp_field=selected_field,
    )
