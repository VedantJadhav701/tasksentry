"""Unit tests for ReceiptStore protocol compliance and AgentTask store integration."""

from tasksentry.core.task import AgentTask
from tasksentry.storage.memory import InMemoryReceiptStore
from tasksentry.storage.receipts import ReceiptStore
from tasksentry.storage.sqlite import SQLiteReceiptStore


def test_receipt_store_protocol_compliance() -> None:
    mem = InMemoryReceiptStore()
    sqlite = SQLiteReceiptStore(":memory:")

    assert isinstance(mem, ReceiptStore)
    assert isinstance(sqlite, ReceiptStore)


def test_agent_task_saves_receipt_to_store() -> None:
    store = InMemoryReceiptStore()

    task = AgentTask(
        goal="Verify automatic storage save",
        max_llm_calls=5,
        success_criteria=[
            {
                "id": "c1",
                "verifier": "numeric_range",
                "config": {"value": 1, "min": 0},
            }
        ],
        store=store,
    )

    receipt = task.run(agent="fake-coding-agent", max_steps=2)

    saved_receipt = store.get(receipt.task_id)
    assert saved_receipt is not None
    assert saved_receipt.task_id == receipt.task_id
    assert saved_receipt.status == receipt.status

    record = store.get_record(receipt.task_id)
    assert record is not None
    assert record["contract"]["goal"] == "Verify automatic storage save"
