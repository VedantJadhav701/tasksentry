"""Unit tests for InMemoryReceiptStore."""

import pytest

from tasksentry.core.contract import SuccessCriterion, TaskContract
from tasksentry.core.receipt import TaskReceipt
from tasksentry.exceptions import StorageTaskNotFoundError
from tasksentry.storage.memory import InMemoryReceiptStore


def test_in_memory_store_save_and_get() -> None:
    store = InMemoryReceiptStore()
    contract = TaskContract(
        task_id="t1",
        goal="Goal 1",
        success_criteria=[
            SuccessCriterion(id="c1", verifier="numeric_range", config={"value": 1, "min": 0})
        ],
    )
    receipt = TaskReceipt(task_id="t1", status="completed", tokens=500, cost_usd=0.02)

    store.save(receipt, contract=contract, metadata={"author": "alice"})

    retrieved = store.get("t1")
    assert retrieved is not None
    assert retrieved.task_id == "t1"
    assert retrieved.tokens == 500
    assert retrieved.cost_usd == 0.02

    record = store.get_record("t1")
    assert record is not None
    assert record["metadata"] == {"author": "alice"}
    assert record["contract"]["goal"] == "Goal 1"


def test_in_memory_store_list_and_filter() -> None:
    store = InMemoryReceiptStore()
    store.save(TaskReceipt(task_id="task_ok_1", status="completed"))
    store.save(TaskReceipt(task_id="task_ok_2", status="completed"))
    store.save(TaskReceipt(task_id="task_fail", status="failed"))

    all_tasks = store.list_tasks()
    assert len(all_tasks) == 3

    completed = store.list_tasks(status="completed")
    assert len(completed) == 2
    assert all(t.status == "completed" for t in completed)

    failed = store.list_tasks(status="failed")
    assert len(failed) == 1
    assert failed[0].task_id == "task_fail"


def test_in_memory_store_update_and_delete() -> None:
    store = InMemoryReceiptStore()
    r = TaskReceipt(task_id="t_up", status="running", tokens=100)
    store.save(r)

    updated = TaskReceipt(task_id="t_up", status="completed", tokens=350)
    store.update(updated)

    res = store.get("t_up")
    assert res is not None
    assert res.status == "completed"
    assert res.tokens == 350

    assert store.delete("t_up") is True
    assert store.get("t_up") is None
    assert store.delete("t_up") is False


def test_in_memory_store_update_missing() -> None:
    store = InMemoryReceiptStore()
    with pytest.raises(StorageTaskNotFoundError):
        store.update(TaskReceipt(task_id="missing", status="completed"))
