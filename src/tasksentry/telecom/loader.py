"""Dataset loader and indexer for 5G RAN ticket logs."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from tasksentry.telecom.models import TelecomTicket

DEFAULT_DATASET_PATH = "ran_5g_logs_resolution_sft_chatml_train.jsonl"


def iter_tickets(path: str = DEFAULT_DATASET_PATH) -> Iterator[TelecomTicket]:
    """Stream tickets from the JSONL dataset one by one."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found at: {path}")

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            data = json.loads(line_str)
            yield TelecomTicket.from_dict(data)


def load_tickets(path: str = DEFAULT_DATASET_PATH, limit: int | None = None) -> list[TelecomTicket]:
    """Load tickets up to an optional limit."""
    tickets: list[TelecomTicket] = []
    for t in iter_tickets(path):
        tickets.append(t)
        if limit is not None and len(tickets) >= limit:
            break
    return tickets


def get_ticket_by_id(ticket_id: str, path: str = DEFAULT_DATASET_PATH) -> TelecomTicket | None:
    """Retrieve a single ticket by its ID (e.g. 'tsd_000001')."""
    target = ticket_id.lower().strip()
    for t in iter_tickets(path):
        if t.id.lower() == target or target in t.metadata.ticket_id.lower():
            return t
    return None


def filter_tickets(
    path: str = DEFAULT_DATASET_PATH,
    category: str | None = None,
    failure_type: str | None = None,
    datacenter: str | None = None,
    limit: int = 20,
) -> list[TelecomTicket]:
    """Filter tickets by failure category, datacenter, or failure type."""
    results: list[TelecomTicket] = []
    for t in iter_tickets(path):
        if category and category.lower() not in t.sop.problem_category.lower():
            continue
        if failure_type and failure_type.lower() not in t.metadata.failure_type.lower():
            continue
        if datacenter and datacenter.lower() not in t.metadata.datacenter.lower():
            continue
        results.append(t)
        if len(results) >= limit:
            break
    return results


class TelecomDatasetLoader:
    """Convenience loader class for 5G RAN tickets."""

    def __init__(self, path: str = DEFAULT_DATASET_PATH) -> None:
        self.path = path

    def iter_all(self) -> Iterator[TelecomTicket]:
        return iter_tickets(self.path)

    def load(self, limit: int | None = None) -> list[TelecomTicket]:
        return load_tickets(self.path, limit=limit)

    def get(self, ticket_id: str) -> TelecomTicket | None:
        return get_ticket_by_id(ticket_id, self.path)

    def filter(
        self,
        category: str | None = None,
        failure_type: str | None = None,
        datacenter: str | None = None,
        limit: int = 20,
    ) -> list[TelecomTicket]:
        return filter_tickets(
            self.path,
            category=category,
            failure_type=failure_type,
            datacenter=datacenter,
            limit=limit,
        )
