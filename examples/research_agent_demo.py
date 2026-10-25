"""Example: Research agent with milestone tracking and proxy information gain.

Runs 100% offline using deterministic mock data.

Expected output:
    Research task started: Extracting system metrics.
    Research task completed with status: 'completed', success=True

Exit condition:
    Exits with code 0 on verified task completion.
"""

import sys
from typing import Any

from pydantic import BaseModel

from tasksentry import AgentTask
from tasksentry.tools.registry import Tool, ToolRegistry


class SearchInput(BaseModel):
    query: str


class SummarizeInput(BaseModel):
    data: str


def search_docs(query: str) -> dict[str, Any]:
    """Search knowledge base."""
    return {"new_world": {"facts_found": 1}, "finding": "Memory utilization peaked at 42%"}


def compile_report(data: str) -> dict[str, Any]:
    """Compile finalized report."""
    return {"new_world": {"report_verified": 1}, "report": f"Report compiled: {data}"}


def main() -> int:
    print("Research task started: Extracting system metrics.")

    reg = ToolRegistry()
    reg.register(
        Tool(name="search_docs", input_model=SearchInput, callable=search_docs, risk="read")
    )
    reg.register(
        Tool(
            name="compile_report", input_model=SummarizeInput, callable=compile_report, risk="read"
        )
    )

    milestone_1 = {
        "id": "retrieved_system_stats",
        "done_when": {"verifier": "numeric_range", "config": {"key": "facts_found", "min": 1}},
    }

    criterion = {
        "id": "report_ready",
        "verifier": "numeric_range",
        "config": {"key": "report_verified", "min": 1},
    }

    actions = [
        {"type": "tool_call", "tool": "search_docs", "arguments": {"query": "memory stats"}},
        {"type": "tool_call", "tool": "compile_report", "arguments": {"data": "Peak memory 42%"}},
        {"type": "complete_task"},
    ]

    task = AgentTask(
        goal="Extract memory stats and compile report",
        registry=reg,
        milestones=[milestone_1],
        success_criteria=[criterion],
        max_tool_calls=4,
    )

    receipt = task.run(actions)
    print(f"Research task completed with status: {receipt.status!r}, success={receipt.success}")
    assert receipt.success is True, "Research task was expected to complete successfully"
    return 0


if __name__ == "__main__":
    sys.exit(main())
