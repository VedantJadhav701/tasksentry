"""Unit tests for Server-Sent Events (SSE) and stream event formatting."""

import asyncio

import pytest

from tasksentry.console.runs import ConsoleRun, RunEvent
from tasksentry.console.sockets import sse_event_stream


def test_run_event_to_dict() -> None:
    evt = RunEvent(event_type="test_event", data={"foo": "bar"}, task_id="t1")
    d = evt.to_dict()
    assert d["type"] == "test_event"
    assert d["task_id"] == "t1"
    assert d["data"] == {"foo": "bar"}
    assert "timestamp" in d


def test_console_run_subscribe_and_emit() -> None:
    run = ConsoleRun("t1", "Goal")
    q = run.subscribe()

    run.emit("planner_started", {"goal": "Goal"})
    evt = q.get_nowait()
    assert evt is not None
    assert evt.event_type == "planner_started"
    assert evt.data["goal"] == "Goal"


def test_console_run_unsubscribe() -> None:
    run = ConsoleRun("t1", "Goal")
    q = run.subscribe()
    assert len(run._subscribers) == 1
    run.unsubscribe(q)
    assert len(run._subscribers) == 0


def test_console_run_events_history_replayed_to_new_sub() -> None:
    run = ConsoleRun("t1", "Goal")
    run.emit("event1", {"val": 1})
    run.emit("event2", {"val": 2})

    q = run.subscribe()
    e1 = q.get_nowait()
    e2 = q.get_nowait()
    assert e1 is not None and e1.event_type == "event1"
    assert e2 is not None and e2.event_type == "event2"


@pytest.mark.asyncio
async def test_sse_event_stream_yields_proper_format() -> None:
    run = ConsoleRun("t1", "Goal")

    async def _produce_events() -> None:
        await asyncio.sleep(0.02)
        run.emit("model_selected", {"selected_model": "qwen2.5:3b"})
        await asyncio.sleep(0.02)
        # Terminate stream
        for sub in list(run._subscribers):
            sub.put_nowait(None)

    task = asyncio.create_task(_produce_events())

    collected: list[str] = []
    async for chunk in sse_event_stream(run):
        collected.append(chunk)

    await task

    assert len(collected) >= 2
    assert any("model_selected" in c for c in collected)
    assert any("stream_end" in c for c in collected)
    assert all(c.startswith("data: ") and c.endswith("\n\n") for c in collected)
