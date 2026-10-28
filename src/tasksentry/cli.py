"""TaskSentry Command Line Interface."""

import argparse
import json
import os
import sys
from pathlib import Path
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
    """Start the local TaskSentry dashboard / console application."""
    from tasksentry.console.app import run_console

    print(f"Starting TaskSentry Console on http://{args.host}:{args.port}")
    run_console(host=args.host, port=args.port)
    return 0


def cmd_console(args: argparse.Namespace) -> int:
    """Start the chat-first TaskSentry Console application."""
    from tasksentry.console.app import run_console

    print(f"Starting TaskSentry Console on http://{args.host}:{args.port}")
    run_console(host=args.host, port=args.port)
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


def cmd_telecom(args: argparse.Namespace) -> int:
    """Run Telecom 5G RAN ticket troubleshooting and automated command execution."""
    from tasksentry.telecom.loader import filter_tickets, get_ticket_by_id
    from tasksentry.telecom.runner import TelecomBatchRunner

    dataset_path = getattr(args, "dataset", "ran_5g_logs_resolution_sft_chatml_train.jsonl")
    if not os.path.exists(dataset_path):
        print(f"Error: Dataset file not found at {dataset_path}")
        return 1

    model_name = getattr(args, "model", "telco:latest")
    use_llm = getattr(args, "llm", False)
    runner = TelecomBatchRunner(
        dataset_path=dataset_path,
        brain_model=model_name,
        enable_llm_reasoning=use_llm,
    )

    if getattr(args, "list_tickets", False):
        cat = getattr(args, "category", None)
        tickets = filter_tickets(path=dataset_path, category=cat, limit=getattr(args, "limit", 15))
        print("==================================================")
        print(f" TELECOM 5G RAN TICKETS ({len(tickets)} shown)")
        print("==================================================")
        for t in tickets:
            print(
                f"[{t.id}] DU-{t.metadata.du_id} Cell-{t.metadata.cell_id} | "
                f"{t.metadata.datacenter} | {t.metadata.failure_type}"
            )
            print(f"   Category: {t.sop.problem_category}")
        return 0

    single_ticket_id = getattr(args, "ticket", None)
    if single_ticket_id:
        target_ticket = get_ticket_by_id(single_ticket_id, path=dataset_path)
        if not target_ticket:
            print(f"Error: Ticket '{single_ticket_id}' not found in dataset.")
            return 1

        m = target_ticket.metadata
        print("==================================================")
        print(f" TELECOM TICKET RESOLUTION: {target_ticket.id}")
        print("==================================================")
        print(f"Category:      {target_ticket.sop.problem_category}")
        print(f"Target gNB:    {m.gnb_id} (DU: {m.du_id})")
        print(f"Cluster:       {m.prefecture} ({m.datacenter})")
        print(f"Failure Alert: {m.failure_type} (OperStatus: {m.oper_status})")
        print("Executing Macro-Graph SOP and automated diagnostics...\n")

        res = runner.run_ticket(
            target_ticket,
            enable_llm_reasoning=getattr(args, "llm", False),
        )
        print("Resolution Result:")
        print(f"  * Status:           {res.status.upper()}")
        print(f"  * RCA Driver:       {res.rca_driver}")
        print(f"  * Escalation Team:  {res.escalation_team or 'None (Resolved In-SOP)'}")
        print(f"  * SOP Compliance:   {int(res.compliance_score * 100)}%")
        print(f"  * Execution Time:   {res.wall_time_seconds}s")
        print(f"  * Audit Receipt:    {res.audit_receipt_hash}\n")

        if res.llm_analysis:
            print(f"Telco Brain Reasoning ({res.brain_model}):")
            print(f"  {res.llm_analysis}\n")

        print("Step-by-Step SOP Execution Trace:")
        for s in res.steps_executed:
            print(f"  [{s.status}] Step {s.step_number}: {s.title}")
            print(f"        Cmd: {s.command_executed}")
            if s.subissue_detected:
                print(f"        Subissue: {s.subissue_detected}")
            if s.escalate_to:
                print(f"        Escalate: {s.escalate_to}")

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(res.model_dump(), f, indent=2)
            print(f"\nSaved execution trace to {args.output}")

        return 0

    batch_count = getattr(args, "batch", 10)
    print("==================================================")
    print(f" TELECOM 5G RAN BATCH EVALUATION ({batch_count} tickets)")
    print("==================================================")
    report = runner.run_file(path=dataset_path, limit=batch_count, output_report_path=args.output)
    print(f"Total Tickets:            {report.total_tickets}")
    print(f"Resolved Tickets:         {report.resolved_count}")
    print(f"Escalated Tickets:        {report.escalated_count}")
    print(f"Average Compliance Score: {int(report.average_compliance_score * 100)}%")
    print(f"MTTR per Ticket:          {report.mean_time_to_resolve_seconds:.2f}s")
    if args.output:
        print(f"Saved batch report to:    {args.output}")

    return 0


def _write_domain_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def cmd_domain_ingest(args: argparse.Namespace) -> int:
    from tasksentry.domain.ingest import ingest
    from tasksentry.domain.redact import TenantRedactor

    result = ingest(args.input, strict=args.strict, deduplicate=True)
    redactor = TenantRedactor(args.tenant, redact_ips=args.redact_ips)
    records = [redactor.redact_record(record) for record in result.records]
    output = Path(args.out)
    if output.suffix.lower() == ".jsonl":
        records_path = output
        report_path = output.with_name(output.stem + "-report.json")
    else:
        output.mkdir(parents=True, exist_ok=True)
        records_path = output / "records.jsonl"
        report_path = output / "ingest-report.json"
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        "".join(json.dumps(record, sort_keys=True, default=str) + "\n" for record in records),
        encoding="utf-8",
    )
    _write_domain_json(
        report_path,
        {
            "tenant_id": args.tenant,
            "recognition": result.recognition.model_dump(mode="json"),
            "records": len(records),
            "issues": [issue.model_dump(mode="json") for issue in result.issues],
            "duplicates_removed": result.duplicates_removed,
            "redaction_stats": redactor.stats.__dict__,
            "records_path": str(records_path),
        },
    )
    print(json.dumps({"records": len(records), "out": str(records_path)}, sort_keys=True))
    return 0


def cmd_domain_catalog(args: argparse.Namespace) -> int:
    from tasksentry.domain.catalog import CommandCatalog, draft_from_sop
    from tasksentry.domain.schema import SopDoc

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    sop = SopDoc.model_validate(data)
    if sop.tenant_id != args.tenant:
        raise ValueError("SOP tenant_id does not match --tenant")
    draft = draft_from_sop(sop, version=args.version)
    output = Path(args.out)
    if args.approve:
        catalog = CommandCatalog(
            tenant_id=draft.tenant_id,
            version=draft.version,
            commands=draft.commands,
        )
        catalog.validate_links()
        _write_domain_json(output, catalog.model_dump(mode="json"))
    else:
        _write_domain_json(output, draft.model_dump(mode="json"))
    print(json.dumps({"approved": args.approve, "out": str(output)}, sort_keys=True))
    return 0


def cmd_domain_export(args: argparse.Namespace) -> int:
    from tasksentry.domain.datasets import export_datasets
    from tasksentry.domain.schema import Trajectory

    lines = Path(args.input).read_text(encoding="utf-8").splitlines()
    trajectories = [Trajectory.model_validate(json.loads(line)) for line in lines if line.strip()]
    selected = [trajectory for trajectory in trajectories if trajectory.tenant_id == args.tenant]
    report = export_datasets(selected, args.out, catalog_version=args.catalog_version)
    print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    return 0


def cmd_domain_eval(args: argparse.Namespace) -> int:
    from tasksentry.domain.replay import (
        EvalReport,
        compare_baseline,
        evaluate_replay,
        write_eval_report,
    )
    from tasksentry.domain.schema import Trajectory

    lines = Path(args.input).read_text(encoding="utf-8").splitlines()
    trajectories = [Trajectory.model_validate(json.loads(line)) for line in lines if line.strip()]
    selected = [
        trajectory
        for trajectory in trajectories
        if trajectory.tenant_id == args.tenant
        and (not args.split or trajectory.context.get("split") in (None, args.split))
    ]
    report = evaluate_replay(
        selected,
        tenant_id=args.tenant,
        split=args.split,
        model_name=args.model,
    )
    json_path, markdown_path = write_eval_report(report, args.out)
    result: dict[str, Any] = {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "samples": report.samples,
    }
    if args.baseline:
        baseline_data = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        decision = compare_baseline(
            report,
            EvalReport.model_validate(baseline_data),
            tolerance=args.tolerance,
        )
        result["regression"] = decision.model_dump(mode="json")
        print(json.dumps(result, sort_keys=True))
        return 0 if decision.passed else 1
    print(json.dumps(result, sort_keys=True))
    return 0


def cmd_domain(args: argparse.Namespace) -> int:
    """Ingest domain data, draft catalogs, or export DSLM datasets."""
    handlers = {
        "ingest": cmd_domain_ingest,
        "catalog": cmd_domain_catalog,
        "export": cmd_domain_export,
        "eval": cmd_domain_eval,
    }
    handler = handlers.get(args.domain_command)
    if handler is None:
        print("A domain subcommand is required: ingest, catalog, export, or eval.", file=sys.stderr)
        return 2
    return handler(args)


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

    # console
    p_console = subparsers.add_parser("console", help="Start chat-first local TaskSentry Console")
    p_console.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    p_console.add_argument("--port", type=int, default=8321, help="Bind port (default 8321)")

    # benchmark-report
    p_brep = subparsers.add_parser("benchmark-report", help="Inspect saved benchmark report")
    p_brep.add_argument("--run", "-r", required=True, help="Benchmark run ID or filename")

    # telecom
    p_tel = subparsers.add_parser("telecom", help="Telecom 5G RAN SOP ticket resolution")
    p_tel.add_argument("--ticket", "-t", default=None, help="Ticket ID (e.g. tsd_000001)")
    p_tel.add_argument("--batch", "-b", type=int, default=10, help="Batch ticket count")
    p_tel.add_argument("--category", "-c", default=None, help="Filter by failure category")
    p_tel.add_argument(
        "--dataset",
        default="ran_5g_logs_resolution_sft_chatml_train.jsonl",
        help="Dataset file",
    )
    p_tel.add_argument("--output", "-o", default=None, help="Output path for JSON report")
    p_tel.add_argument("--llm", action="store_true", help="Enable telco brain reasoning")
    p_tel.add_argument("--model", "-m", default="telco:latest", help="Brain model")
    p_tel.add_argument("--list-tickets", action="store_true", help="List tickets in dataset")
    p_tel.add_argument("--limit", type=int, default=15, help="Limit when listing tickets")

    # domain DSLM data workflow
    p_domain = subparsers.add_parser("domain", help="Domain data and DSLM workflow")
    domain_sub = p_domain.add_subparsers(dest="domain_command")
    p_d_ingest = domain_sub.add_parser(
        "ingest", help="Recognize, redact, and ingest domain records"
    )
    p_d_ingest.add_argument("--input", "-i", required=True)
    p_d_ingest.add_argument("--tenant", required=True)
    p_d_ingest.add_argument("--out", "-o", required=True)
    p_d_ingest.add_argument("--redact-ips", action="store_true")
    p_d_ingest.add_argument("--strict", action="store_true")

    p_d_catalog = domain_sub.add_parser("catalog", help="Draft a typed command catalog from an SOP")
    p_d_catalog.add_argument("--input", "-i", required=True)
    p_d_catalog.add_argument("--tenant", required=True, help="Expected tenant ID")
    p_d_catalog.add_argument("--out", "-o", required=True)
    p_d_catalog.add_argument("--version", default="draft-1")
    p_d_catalog.add_argument("--approve", action="store_true", help="Explicitly approve the draft")

    p_d_export = domain_sub.add_parser("export", help="Export deterministic DSLM datasets")
    p_d_export.add_argument("--input", "-i", required=True, help="Canonical trajectory JSONL")
    p_d_export.add_argument("--tenant", required=True)
    p_d_export.add_argument("--out", "-o", required=True, help="Output directory")
    p_d_export.add_argument("--catalog-version", default="unknown")

    p_d_eval = domain_sub.add_parser("eval", help="Replay-evaluate a domain trajectory JSONL")
    p_d_eval.add_argument("--input", "-i", required=True)
    p_d_eval.add_argument("--tenant", required=True)
    p_d_eval.add_argument("--split", default="test")
    p_d_eval.add_argument("--out", "-o", required=True)
    p_d_eval.add_argument("--model", default="harness-only")
    p_d_eval.add_argument("--baseline", default=None)
    p_d_eval.add_argument("--tolerance", type=float, default=0.02)

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
        "console": cmd_console,
        "benchmark-report": cmd_benchmark_report,
        "telecom": cmd_telecom,
        "domain": cmd_domain,
    }

    handler = handler_map.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
