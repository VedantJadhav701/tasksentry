"""Example: Local Dashboard demonstration and programmatic health check.

This script runs 100% offline, initializes sample task receipts,
and queries the dashboard's internal API to verify functionality.

Expected output:
    Seeding database with sample receipts...
    Querying GET /api/health: status='ok'
    Querying GET /api/tasks: 2 tasks found
    Querying GET /api/metrics: success_rate=1.0
    Dashboard API verified successfully!

Exit condition:
    Exits with code 0 on verified dashboard responses.
"""

import contextlib
import os
import sys
import tempfile

from fastapi.testclient import TestClient

from tasksentry.core.receipt import TaskReceipt
from tasksentry.dashboard.app import app
from tasksentry.storage.sqlite import SQLiteReceiptStore


def main() -> int:
    print("Seeding database with sample receipts...")
    tmp_db = os.path.join(tempfile.gettempdir(), "tasksentry_demo_dash.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)

    os.environ["TASKSENTRY_DATABASE_PATH"] = tmp_db
    store = SQLiteReceiptStore(tmp_db)

    # Seed 2 sample tasks
    r1 = TaskReceipt(task_id="demo-task-1", status="completed", success=True, tokens=150)
    r2 = TaskReceipt(task_id="demo-task-2", status="completed", success=True, tokens=300)
    store.save(r1)
    store.save(r2)

    # Use FastAPI test client to verify endpoints
    client = TestClient(app)

    health = client.get("/api/health")
    print(f"Querying GET /api/health: status={health.json().get('status')!r}")
    assert health.status_code == 200

    tasks_res = client.get("/api/tasks")
    print(f"Querying GET /api/tasks: {len(tasks_res.json())} tasks found")
    assert tasks_res.status_code == 200

    metrics_res = client.get("/api/metrics")
    print(f"Querying GET /api/metrics: success_rate={metrics_res.json().get('success_rate')}")
    assert metrics_res.status_code == 200

    print("Dashboard API verified successfully!")
    print("\nTo launch the live interactive dashboard UI, run:")
    print("    tasksentry dashboard --port 8321")

    # Cleanup
    if os.path.exists(tmp_db):
        with contextlib.suppress(OSError):
            os.remove(tmp_db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
