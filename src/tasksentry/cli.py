"""TaskSentry Command Line Interface."""

import argparse
import json
import os
import sys
from typing import Any

from tasksentry.config import load_config
from tasksentry.core.task import AgentTask
from tasksentry.storage.sqlite import SQLiteReceiptStore


def _load_yaml(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")
    try:
        import yaml  # type: ignore[import-untyped]

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to parse YAML task contracts.") from exc


def cmd_demo(args: argparse.Namespace) -> int:
    """Run an offline demo task and print receipt."""
    print("Running TaskSentry offline demo...")
    cfg = load_config()
    store = SQLiteReceiptStore(cfg.database_path)

    task = AgentTask(
        goal="Demonstrate offline autonomous task execution under budget governance",
        max_llm_calls=5,
        max_tool_calls=10,
        max_tokens=20000,
        max_cost_usd=0.25,
        max_wall_time_seconds=60,
        success_criteria=[
            {
                "id": "verify_offline_result",
                "verifier": "numeric_range",
                "config": {"value": 1, "min": 0},
            }
        ],
        milestones=[
            {
                "id": "demo_milestone",
                "done_when": {"verifier": "numeric_range", "config": {"value": 1, "min": 0}},
            }
        ],
        store=store,
    )

    receipt = task.run(agent="fake-coding-agent", max_steps=5)
    print("\n=== Task Sentry Receipt ===")
    print(f"Task ID:   {receipt.task_id}")
    print(f"Status:    {receipt.status}")
    print(f"Success:   {receipt.success}")
    print(f"Tokens:    {receipt.tokens}")
    print(f"Cost:      ${receipt.cost_usd:.4f}")
    print(f"Duration:  {receipt.wall_time_seconds:.2f}s")
    print(f"Saved to:  {cfg.database_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run a task contract defined in a YAML file."""
    if not args.task:
        print("Error: --task <path> is required.", file=sys.stderr)
        return 1

    cfg = load_config()
    store = SQLiteReceiptStore(cfg.database_path)
    data = _load_yaml(args.task)

    goal = data.get("goal", "Default Task Goal")
    budget_cfg = data.get("budget", {})
    criteria = data.get("success_criteria", [])
    milestones = data.get("milestones", [])

    task = AgentTask(
        goal=goal,
        max_llm_calls=budget_cfg.get("max_llm_calls"),
        max_tool_calls=budget_cfg.get("max_tool_calls"),
        max_tokens=budget_cfg.get("max_tokens"),
        max_cost_usd=budget_cfg.get("max_cost_usd"),
        max_wall_time_seconds=budget_cfg.get("max_wall_time_seconds"),
        success_criteria=criteria,
        milestones=milestones,
        store=store,
    )

    agent_name = args.agent or "fake-coding-agent"
    print(f"Running task '{task.contract.task_id}' with agent '{agent_name}'...")
    receipt = task.run(agent=agent_name)

    print(json.dumps(receipt.model_dump(), indent=2))
    return 0 if receipt.success else 1


def cmd_tasks(args: argparse.Namespace) -> int:
    """List recorded tasks from the SQLite store."""
    cfg = load_config()
    store = SQLiteReceiptStore(cfg.database_path)
    receipts = store.list_tasks(status=args.status, limit=args.limit)

    if not receipts:
        print("No tasks found.")
        return 0

    print(f"{'TASK ID':<20} {'STATUS':<12} {'SUCCESS':<8} {'TOKENS':<8} {'COST':<8}")
    print("-" * 60)
    for r in receipts:
        cost_str = f"${r.cost_usd:.4f}"
        print(f"{r.task_id:<20} {r.status:<12} {r.success!s:<8} {r.tokens:<8} {cost_str:<8}")
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    """Show details of a specific task."""
    cfg = load_config()
    store = SQLiteReceiptStore(cfg.database_path)
    record = store.get_record(args.task_id)

    if not record:
        print(f"Task '{args.task_id}' not found.", file=sys.stderr)
        return 1

    print(json.dumps(record, indent=2, default=str))
    return 0


def cmd_receipt(args: argparse.Namespace) -> int:
    """Print the receipt JSON of a specific task."""
    cfg = load_config()
    store = SQLiteReceiptStore(cfg.database_path)
    receipt = store.get(args.task_id)

    if not receipt:
        print(f"Receipt for task '{args.task_id}' not found.", file=sys.stderr)
        return 1

    print(json.dumps(receipt.model_dump(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tasksentry",
        description="TaskSentry: A budget-native agent harness and control plane.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # demo
    subparsers.add_parser("demo", help="Run an offline demo task under budget control")

    # run
    p_run = subparsers.add_parser("run", help="Run a task from a YAML contract")
    p_run.add_argument("--task", "-t", required=True, help="Path to YAML task contract")
    p_run.add_argument("--agent", "-a", default="fake-coding-agent", help="Agent identifier")

    # tasks
    p_tasks = subparsers.add_parser("tasks", help="List stored task receipts")
    p_tasks.add_argument("--status", "-s", default=None, help="Filter by status")
    p_tasks.add_argument("--limit", "-l", type=int, default=50, help="Max tasks to list")

    # task
    p_task = subparsers.add_parser("task", help="View full task details")
    p_task.add_argument("task_id", help="Task ID to inspect")

    # receipt
    p_rec = subparsers.add_parser("receipt", help="Print task receipt")
    p_rec.add_argument("task_id", help="Task ID to retrieve receipt for")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0

    if not args.command:
        parser.print_help()
        return 0

    handler_map = {
        "demo": cmd_demo,
        "run": cmd_run,
        "tasks": cmd_tasks,
        "task": cmd_task,
        "receipt": cmd_receipt,
    }

    handler = handler_map.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
