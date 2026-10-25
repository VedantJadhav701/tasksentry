"""Receipt storage protocols and common data structures."""

from typing import Any, Protocol, runtime_checkable

from tasksentry.core.contract import TaskContract
from tasksentry.core.receipt import TaskReceipt


@runtime_checkable
class ReceiptStore(Protocol):
    """Abstract persistent storage interface for task receipts and metadata."""

    def save(
        self,
        receipt: TaskReceipt,
        contract: TaskContract | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save a task receipt and optional task contract and metadata."""
        ...

    def get(self, task_id: str) -> TaskReceipt | None:
        """Retrieve a task receipt by ID or None if not found."""
        ...

    def get_record(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve the full stored record including timestamps and contract."""
        ...

    def list_tasks(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TaskReceipt]:
        """List receipts with optional status filtering and pagination."""
        ...

    def update(self, receipt: TaskReceipt) -> None:
        """Update an existing task receipt."""
        ...

    def delete(self, task_id: str) -> bool:
        """Delete a stored task receipt by ID. Return True if deleted."""
        ...
