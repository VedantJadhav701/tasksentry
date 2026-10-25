"""TaskSentry Command Line Interface."""

import argparse
import json
import os
import sys
from typing import Any

from tasksentry.config import load_config
from tasksentry.core.task import AgentTask
from tasksentry.models.ollama import check_ollama_health
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
    """Run an offline or live demo task and print receipt."""
    cfg = load_config()
    store = SQLiteReceiptStore(cfg.database_path)

    if getattr(args, "live", False):
        import tasksentry.tools.builtin  # noqa: F401 - ensure builtins are registered
        from tasksentry.harness.agent import LLMAgent
        from tasksentry.models.router import SemanticModelRouter

        routine = getattr(args, "routine_model", None) or "qwen2.5:3b"
        reasoning = getattr(args, "reasoning_model", None) or "qwen3:4b-instruct-2507-q4_K_M"

        print("==================================================")
        print(" TASK SENTRY LIVE AGENT EXECUTION")
        print("==================================================")
        print("Routing configuration:")
        print(f"  * Fast routine model:   {routine}")
        print(f"  * Deep reasoning model: {reasoning}")
        print("Starting task under budget governance...\n")

        router = SemanticModelRouter(
            routine_model=routine,
            reasoning_model=reasoning,
        )
        task = AgentTask(
            goal="Inspect current project directory, list key files, and confirm repository status",
            max_llm_calls=5,
            max_tool_calls=5,
            max_tokens=15000,
            max_cost_usd=0.25,
            max_wall_time_seconds=60,
            success_criteria=[
                {
                    "id": "check_workspace_valid",
                    "verifier": "file_exists",
                    "config": {"path": "pyproject.toml"},
                }
            ],
            store=store,
        )
        agent = LLMAgent(model_client=router, registry=task.runtime.registry)
        receipt = task.run(agent=agent, max_steps=4)
    else:
        print("Running TaskSentry offline demo...")
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


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Run TaskSentryBench offline or Ollama local suite."""
    from tasksentry.benchmark.runner import run_benchmark_suite

    out_file = args.output
    if not out_file:
        out_file = (
            "reports/ollama-benchmark.json"
            if "ollama" in args.suite
            else "reports/offline-benchmark.json"
        )

    print(f"Executing TaskSentryBench: suite='{args.suite}', output='{out_file}'")
    run_benchmark_suite(
        suite_name=args.suite,
        routine_model=args.routine_model,
        reasoning_model=args.reasoning_model,
        seed=args.seed,
        output_path=out_file,
    )
    print(
        f"Benchmark finished. Reports written to {out_file} and {out_file.replace('.json', '.md')}"
    )
    return 0


def cmd_ollama_health(args: argparse.Namespace) -> int:
    """Check availability and latency of local Ollama server and models."""
    res = check_ollama_health(base_url=args.base_url, model=args.model)
    print("\n=== Ollama Health Status ===")
    print(f"Base URL:   {res['base_url']}")
    print(f"Reachable:  {'Yes' if res['reachable'] else 'No'}")
    print(f"Model:      {res['model']} ({'Available' if res['available'] else 'Not Found'})")
    print(f"Latency:    {res['latency_ms']} ms")
    print(f"Message:    {res['message']}")
    if res["available_models"]:
        print(f"Models:     {', '.join(res['available_models'])}")
    return 0 if res["reachable"] else 1


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Start the local TaskSentry dashboard FastAPI application."""
    from tasksentry.dashboard.app import run_dashboard

    print(f"Starting TaskSentry dashboard on http://{args.host}:{args.port}")
    run_dashboard(host=args.host, port=args.port)
    return 0


def cmd_benchmark_report(args: argparse.Namespace) -> int:
    """Print or inspect a saved benchmark report."""
    run_id = args.run
    reports_dir = "reports"
    candidates = [
        os.path.join(reports_dir, f"{run_id}.md"),
        os.path.join(reports_dir, f"{run_id}.json"),
        os.path.join(reports_dir, run_id),
    ]

    for p in candidates:
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                print(f.read())
            return 0

    print(f"Report '{run_id}' not found in {reports_dir}/.", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tasksentry",
        description="TaskSentry: A budget-native agent harness and control plane.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # demo
    p_demo = subparsers.add_parser("demo", help="Run a demo task under budget control")
    p_demo.add_argument(
        "--live",
        action="store_true",
        help="Run live using local Ollama LLMs and semantic model routing",
    )
    p_demo.add_argument(
        "--routine-model",
        default="qwen2.5:3b",
        help="Fast routine lane model (e.g. qwen2.5:3b, llama3.2:1b, gemma2:2b)",
    )
    p_demo.add_argument(
        "--reasoning-model",
        default="qwen3:4b-instruct-2507-q4_K_M",
        help="Deep reasoning lane model (e.g. qwen3:4b-instruct-2507-q4_K_M, ornith:latest)",
    )

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

    # benchmark
    p_bench = subparsers.add_parser("benchmark", help="Run TaskSentryBench evaluation suite")
    p_bench.add_argument(
        "--suite",
        "-s",
        default="offline-v0.1",
        choices=["offline-v0.1", "ollama-v0.1", "v0.1"],
        help="Benchmark suite",
    )
    p_bench.add_argument("--routine-model", default="llama3.2:1b", help="Routine lane model")
    p_bench.add_argument(
        "--reasoning-model", default="qwen3:4b-instruct-2507-q4_K_M", help="Reasoning lane model"
    )
    p_bench.add_argument("--seed", type=int, default=42, help="Random seed")
    p_bench.add_argument("--output", "-o", default=None, help="Destination report path")

    # ollama-health
    p_ohealth = subparsers.add_parser("ollama-health", help="Check local Ollama server health")
    p_ohealth.add_argument("--base-url", default="http://localhost:11434/v1", help="Ollama URL")
    p_ohealth.add_argument("--model", default="llama3.2:1b", help="Model name to check")

    # dashboard
    p_dash = subparsers.add_parser("dashboard", help="Start local dashboard server")
    p_dash.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    p_dash.add_argument("--port", type=int, default=8321, help="Bind port (default 8321)")

    # benchmark-report
    p_brep = subparsers.add_parser("benchmark-report", help="Inspect saved benchmark report")
    p_brep.add_argument("--run", "-r", required=True, help="Benchmark run ID or filename")

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
        "benchmark": cmd_benchmark,
        "ollama-health": cmd_ollama_health,
        "dashboard": cmd_dashboard,
        "benchmark-report": cmd_benchmark_report,
    }

    handler = handler_map.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
