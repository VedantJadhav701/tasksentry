"""In-memory receipt store implementation for transient execution and tests."""

import threading
import time
from typing import Any

from tasksentry.core.contract import TaskContract
from tasksentry.core.receipt import TaskReceipt
from tasksentry.exceptions import StorageTaskNotFoundError
from tasksentry.storage.receipts import ReceiptStore


class InMemoryReceiptStore(ReceiptStore):
    """In-memory thread-safe receipt store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, Any]] = {}

    def save(
        self,
        receipt: TaskReceipt,
        contract: TaskContract | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        record = {
            "task_id": receipt.task_id,
            "receipt": receipt,
            "contract": contract.model_dump() if contract else None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._store[receipt.task_id] = record

    def get(self, task_id: str) -> TaskReceipt | None:
        with self._lock:
            record = self._store.get(task_id)
            if record is None:
                return None
            return record["receipt"]  # type: ignore[no-any-return]

    def get_record(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._store.get(task_id)
            if record is None:
                return None
            return dict(record)

    def list_tasks(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TaskReceipt]:
        with self._lock:
            results = list(self._store.values())

        if status is not None:
            results = [r for r in results if r["receipt"].status == status]

        # Sort descending by created_at
        results.sort(key=lambda r: float(r["created_at"]), reverse=True)
        paginated = results[offset : offset + limit]
        return [r["receipt"] for r in paginated]

    def update(self, receipt: TaskReceipt) -> None:
        with self._lock:
            if receipt.task_id not in self._store:
                raise StorageTaskNotFoundError(f"Task '{receipt.task_id}' not found in store.")
            record = self._store[receipt.task_id]
            record["receipt"] = receipt
            record["updated_at"] = time.time()

    def delete(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._store:
                del self._store[task_id]
                return True
            return False
