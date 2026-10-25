"""SQLite persistent storage implementation for task receipts."""

import json
import sqlite3
import threading
from typing import Any

from tasksentry.core.contract import TaskContract
from tasksentry.core.receipt import TaskReceipt
from tasksentry.exceptions import StorageTaskNotFoundError
from tasksentry.storage.receipts import ReceiptStore


class SQLiteReceiptStore(ReceiptStore):
    """Thread-safe SQLite persistent store with transactional schema management."""

    def __init__(self, db_path: str = "tasksentry.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_receipts (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    llm_calls INTEGER NOT NULL,
                    tool_calls INTEGER NOT NULL,
                    wall_time_seconds REAL NOT NULL,
                    receipt_json TEXT NOT NULL,
                    contract_json TEXT,
                    metadata_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_receipts_status ON task_receipts(status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_receipts_created_at "
                "ON task_receipts(created_at);"
            )

    def save(
        self,
        receipt: TaskReceipt,
        contract: TaskContract | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        contract_json = json.dumps(contract.model_dump()) if contract else None
        metadata_json = json.dumps(metadata) if metadata else None
        receipt_json = json.dumps(receipt.model_dump())

        query = """
            INSERT INTO task_receipts (
                task_id, status, success, tokens, cost_usd, llm_calls, tool_calls,
                wall_time_seconds, receipt_json, contract_json, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(task_id) DO UPDATE SET
                status = excluded.status,
                success = excluded.success,
                tokens = excluded.tokens,
                cost_usd = excluded.cost_usd,
                llm_calls = excluded.llm_calls,
                tool_calls = excluded.tool_calls,
                wall_time_seconds = excluded.wall_time_seconds,
                receipt_json = excluded.receipt_json,
                contract_json = coalesce(excluded.contract_json, task_receipts.contract_json),
                metadata_json = coalesce(excluded.metadata_json, task_receipts.metadata_json),
                updated_at = CURRENT_TIMESTAMP;
        """
        params = (
            receipt.task_id,
            receipt.status,
            1 if receipt.success else 0,
            receipt.tokens,
            receipt.cost_usd,
            receipt.llm_calls,
            receipt.tool_calls,
            receipt.wall_time_seconds,
            receipt_json,
            contract_json,
            metadata_json,
        )

        with self._lock, self._get_connection() as conn:
            conn.execute(query, params)

    def get(self, task_id: str) -> TaskReceipt | None:
        query = "SELECT receipt_json FROM task_receipts WHERE task_id = ?;"
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(query, (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["receipt_json"])
            return TaskReceipt(**data)

    def get_record(self, task_id: str) -> dict[str, Any] | None:
        query = "SELECT * FROM task_receipts WHERE task_id = ?;"
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(query, (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "task_id": row["task_id"],
                "status": row["status"],
                "success": bool(row["success"]),
                "tokens": row["tokens"],
                "cost_usd": row["cost_usd"],
                "llm_calls": row["llm_calls"],
                "tool_calls": row["tool_calls"],
                "wall_time_seconds": row["wall_time_seconds"],
                "receipt": TaskReceipt(**json.loads(row["receipt_json"])),
                "contract": json.loads(row["contract_json"]) if row["contract_json"] else None,
                "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def list_tasks(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TaskReceipt]:
        if status is not None:
            query = """
                SELECT receipt_json FROM task_receipts
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?;
            """
            params: tuple[Any, ...] = (status, limit, offset)
        else:
            query = """
                SELECT receipt_json FROM task_receipts
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?;
            """
            params = (limit, offset)

        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [TaskReceipt(**json.loads(r["receipt_json"])) for r in rows]

    def update(self, receipt: TaskReceipt) -> None:
        receipt_json = json.dumps(receipt.model_dump())
        query = """
            UPDATE task_receipts SET
                status = ?,
                success = ?,
                tokens = ?,
                cost_usd = ?,
                llm_calls = ?,
                tool_calls = ?,
                wall_time_seconds = ?,
                receipt_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?;
        """
        params = (
            receipt.status,
            1 if receipt.success else 0,
            receipt.tokens,
            receipt.cost_usd,
            receipt.llm_calls,
            receipt.tool_calls,
            receipt.wall_time_seconds,
            receipt_json,
            receipt.task_id,
        )

        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(query, params)
            if cursor.rowcount == 0:
                raise StorageTaskNotFoundError(
                    f"Task '{receipt.task_id}' was not found in SQLite storage."
                )

    def delete(self, task_id: str) -> bool:
        query = "DELETE FROM task_receipts WHERE task_id = ?;"
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(query, (task_id,))
            return cursor.rowcount > 0
