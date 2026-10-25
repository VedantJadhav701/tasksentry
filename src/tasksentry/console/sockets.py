"""Server-Sent Events (SSE) and WebSocket streaming infrastructure for the TaskSentry Console."""

import asyncio
import json
import queue
from collections.abc import AsyncIterator

from fastapi import WebSocket, WebSocketDisconnect

from tasksentry.console.runs import ConsoleRun


async def sse_event_stream(run: ConsoleRun) -> AsyncIterator[str]:
    """Asynchronous generator yielding Server-Sent Events from the run's event queue."""
    q = run.subscribe()

    try:
        while True:
            # Non-blocking pull with small sleep to allow cooperative concurrency
            try:
                event = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            if event is None:
                # Stream terminated
                yield f"data: {json.dumps({'type': 'stream_end', 'task_id': run.task_id})}\n\n"
                break

            payload = json.dumps(event.to_dict())
            yield f"data: {payload}\n\n"
    finally:
        run.unsubscribe(q)


async def handle_websocket_stream(websocket: WebSocket, run: ConsoleRun) -> None:
    """Handle bi-directional WebSocket connection for streaming task execution."""
    await websocket.accept()
    q = run.subscribe()

    try:
        while True:
            try:
                event = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            if event is None:
                await websocket.send_json({"type": "stream_end", "task_id": run.task_id})
                break

            await websocket.send_json(event.to_dict())
    except WebSocketDisconnect:
        pass
    finally:
        run.unsubscribe(q)
