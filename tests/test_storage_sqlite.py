"""Unit tests for SQLiteReceiptStore."""

import os
import threading

import pytest

from tasksentry.core.contract import SuccessCriterion, TaskContract
from tasksentry.core.receipt import TaskReceipt
from tasksentry.exceptions import StorageTaskNotFoundError
from tasksentry.storage.sqlite import SQLiteReceiptStore


def test_sqlite_store_lifecycle(tmp_path: os.PathLike[str]) -> None:
    db_file = os.path.join(str(tmp_path), "test.db")
    store = SQLiteReceiptStore(db_file)

    contract = TaskContract(
        task_id="t_sqlite_1",
        goal="Test SQLite Persistence",
        success_criteria=[
            SuccessCriterion(id="c1", verifier="numeric_range", config={"value": 1, "min": 0})
        ],
    )
    receipt = TaskReceipt(
        task_id="t_sqlite_1",
        status="completed",
        tokens=1200,
        cost_usd=0.05,
    )

    store.save(receipt, contract=contract, metadata={"env": "test"})

    fetched = store.get("t_sqlite_1")
    assert fetched is not None
    assert fetched.task_id == "t_sqlite_1"
    assert fetched.tokens == 1200
    assert fetched.cost_usd == 0.05

    record = store.get_record("t_sqlite_1")
    assert record is not None
    assert record["status"] == "completed"
    assert record["metadata"]["env"] == "test"
    assert record["contract"]["goal"] == "Test SQLite Persistence"


def test_sqlite_store_list_and_filter(tmp_path: os.PathLike[str]) -> None:
    db_file = os.path.join(str(tmp_path), "filter.db")
    store = SQLiteReceiptStore(db_file)

    store.save(TaskReceipt(task_id="t1", status="completed"))
    store.save(TaskReceipt(task_id="t2", status="completed"))
    store.save(TaskReceipt(task_id="t3", status="failed"))

    all_tasks = store.list_tasks()
    assert len(all_tasks) == 3

    completed = store.list_tasks(status="completed")
    assert len(completed) == 2

    failed = store.list_tasks(status="failed")
    assert len(failed) == 1
    assert failed[0].task_id == "t3"


def test_sqlite_store_update_and_delete(tmp_path: os.PathLike[str]) -> None:
    db_file = os.path.join(str(tmp_path), "up_del.db")
    store = SQLiteReceiptStore(db_file)

    store.save(TaskReceipt(task_id="t_mod", status="running", tokens=100))

    store.update(TaskReceipt(task_id="t_mod", status="stopped", tokens=250))
    updated = store.get("t_mod")
    assert updated is not None
    assert updated.status == "stopped"
    assert updated.tokens == 250

    assert store.delete("t_mod") is True
    assert store.get("t_mod") is None
    assert store.delete("t_mod") is False


def test_sqlite_store_update_missing(tmp_path: os.PathLike[str]) -> None:
    db_file = os.path.join(str(tmp_path), "missing.db")
    store = SQLiteReceiptStore(db_file)
    with pytest.raises(StorageTaskNotFoundError):
        store.update(TaskReceipt(task_id="does_not_exist", status="completed"))


def test_sqlite_store_concurrent_writes(tmp_path: os.PathLike[str]) -> None:
    db_file = os.path.join(str(tmp_path), "concurrent.db")
    store = SQLiteReceiptStore(db_file)

    def worker(idx: int) -> None:
        r = TaskReceipt(task_id=f"concurrent_task_{idx}", tokens=idx * 10)
        store.save(r)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    tasks = store.list_tasks(limit=100)
    assert len(tasks) == 10
