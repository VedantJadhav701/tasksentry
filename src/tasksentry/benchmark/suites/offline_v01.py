"""Offline deterministic benchmark suite v0.1 for CI and regression tracking."""

from tasksentry.benchmark.tasks import BenchmarkTask
from tasksentry.core.contract import (
    BudgetLimits,
    Milestone,
    SuccessCriterion,
    VerifierSpec,
)


def get_offline_v01_tasks() -> list[BenchmarkTask]:
    """Return the complete set of 26 offline regression benchmark tasks across 10 families."""
    tasks: list[BenchmarkTask] = []

    # 1. Code repair (3 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="cr_syntax_error",
            family="Code repair",
            goal="Fix syntax error in mathematical formula parser",
            success_criteria=[
                SuccessCriterion(
                    id="tests_pass",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1, "max": 1},
                )
            ],
            milestones=[
                Milestone(
                    id="syntax_validated",
                    done_when=VerifierSpec(verifier="numeric_range", config={"value": 1, "min": 1}),
                )
            ],
            available_tools=["read_file", "write_file", "run_tests"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=10),
            fake_actions=[
                {"tool": "read_file", "arguments": {"path": "src/parser.py"}},
                {"tool": "write_file", "arguments": {"path": "src/parser.py", "content": "valid"}},
                {"tool": "run_tests", "arguments": {"test_name": "test_parser"}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="cr_type_mismatch",
            family="Code repair",
            goal="Resolve type mismatch in currency converter",
            success_criteria=[
                SuccessCriterion(
                    id="types_clean",
                    verifier="numeric_range",
                    config={"value": 0, "min": 0, "max": 0},
                )
            ],
            available_tools=["read_file", "write_file", "typecheck"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=10),
            fake_actions=[
                {"tool": "read_file", "arguments": {"path": "src/currency.py"}},
                {
                    "tool": "write_file",
                    "arguments": {"path": "src/currency.py", "content": "fixed"},
                },
                {"tool": "typecheck", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="cr_boundary_condition",
            family="Code repair",
            goal="Correct off-by-one error in sliding window algorithm",
            success_criteria=[
                SuccessCriterion(
                    id="boundary_tests_pass",
                    verifier="numeric_range",
                    config={"value": 100, "min": 100},
                )
            ],
            available_tools=["read_file", "write_file", "run_tests"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=10),
            fake_actions=[
                {"tool": "read_file", "arguments": {"path": "src/window.py"}},
                {"tool": "write_file", "arguments": {"path": "src/window.py", "content": "fixed"}},
                {"tool": "run_tests", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    # 2. Repository analysis (3 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="ra_dependency_graph",
            family="Repository analysis",
            goal="Analyze modular dependency structure and verify acyclic graph",
            success_criteria=[
                SuccessCriterion(
                    id="graph_acyclic",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["list_dir", "read_file", "build_graph"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=10),
            fake_actions=[
                {"tool": "list_dir", "arguments": {"path": "src"}},
                {"tool": "build_graph", "arguments": {"root": "src"}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="ra_code_churn",
            family="Repository analysis",
            goal="Determine hot spots with top modification frequencies",
            success_criteria=[
                SuccessCriterion(
                    id="churn_analyzed",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["git_log", "read_file"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=8),
            fake_actions=[
                {"tool": "git_log", "arguments": {"max_commits": 50}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="ra_dead_code",
            family="Repository analysis",
            goal="Detect and report unreachable helper routines",
            success_criteria=[
                SuccessCriterion(
                    id="dead_code_cleared",
                    verifier="numeric_range",
                    config={"value": 0, "max": 0},
                )
            ],
            available_tools=["read_file", "find_references", "write_file"],
            budget_limits=BudgetLimits(max_llm_calls=6, max_tool_calls=12),
            fake_actions=[
                {"tool": "find_references", "arguments": {"symbol": "old_helper"}},
                {"tool": "write_file", "arguments": {"path": "src/util.py", "content": "pruned"}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    # 3. RAG-style research (3 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="rag_keyword_lookup",
            family="RAG-style research",
            goal="Search knowledge base for retry backoff configuration",
            success_criteria=[
                SuccessCriterion(
                    id="config_found",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["search_kb", "read_file"],
            budget_limits=BudgetLimits(max_llm_calls=4, max_tool_calls=6),
            fake_actions=[
                {"tool": "search_kb", "arguments": {"query": "retry backoff"}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="rag_multi_doc_summarize",
            family="RAG-style research",
            goal="Synthesize pricing policy from provider docs",
            success_criteria=[
                SuccessCriterion(
                    id="synthesis_done",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["read_file", "synthesize"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=8),
            fake_actions=[
                {"tool": "read_file", "arguments": {"path": "docs/provider_a.md"}},
                {"tool": "read_file", "arguments": {"path": "docs/provider_b.md"}},
                {"tool": "synthesize", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="rag_entity_extraction",
            family="RAG-style research",
            goal="Extract API key references and check vault compliance",
            success_criteria=[
                SuccessCriterion(
                    id="compliance_verified",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["scan_secrets", "verify_vault"],
            budget_limits=BudgetLimits(max_llm_calls=4, max_tool_calls=6),
            fake_actions=[
                {"tool": "scan_secrets", "arguments": {}},
                {"tool": "verify_vault", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    # 4. Multi-step API workflow (3 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="api_auth_fetch",
            family="Multi-step API workflow",
            goal="Authenticate session then fetch protected resource",
            success_criteria=[
                SuccessCriterion(
                    id="resource_fetched",
                    verifier="numeric_range",
                    config={"value": 200, "min": 200, "max": 200},
                )
            ],
            available_tools=["auth_login", "fetch_data"],
            budget_limits=BudgetLimits(max_llm_calls=4, max_tool_calls=6),
            fake_actions=[
                {"tool": "auth_login", "arguments": {"user": "admin"}},
                {"tool": "fetch_data", "arguments": {"endpoint": "/api/metrics"}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="api_paginated_fetch",
            family="Multi-step API workflow",
            goal="Traverse paginated catalog and aggregate records",
            success_criteria=[
                SuccessCriterion(
                    id="all_pages_fetched",
                    verifier="numeric_range",
                    config={"value": 3, "min": 3},
                )
            ],
            available_tools=["fetch_page"],
            budget_limits=BudgetLimits(max_llm_calls=6, max_tool_calls=10),
            fake_actions=[
                {"tool": "fetch_page", "arguments": {"page": 1}},
                {"tool": "fetch_page", "arguments": {"page": 2}},
                {"tool": "fetch_page", "arguments": {"page": 3}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="api_post_verify",
            family="Multi-step API workflow",
            goal="Create cluster resource and verify healthy status",
            success_criteria=[
                SuccessCriterion(
                    id="cluster_healthy",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["create_node", "check_health"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=8),
            fake_actions=[
                {"tool": "create_node", "arguments": {"name": "node-1"}},
                {"tool": "check_health", "arguments": {"name": "node-1"}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True},
        )
    )

    # 5. Injected transient tool failures (3 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="transient_http_503",
            family="Injected transient tool failures",
            goal="Handle temporary 503 gateway unavailable with backoff",
            success_criteria=[
                SuccessCriterion(
                    id="api_recovered",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["call_remote_service"],
            budget_limits=BudgetLimits(max_llm_calls=6, max_tool_calls=10),
            injected_failures={
                "call_remote_service": {"transient_count": 2, "error": "503 Unavailable"}
            },
            fake_actions=[
                {"tool": "call_remote_service", "arguments": {"retry": 1}},
                {"tool": "call_remote_service", "arguments": {"retry": 2}},
                {"tool": "call_remote_service", "arguments": {"retry": 3}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True, "requires_retry": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="transient_lock_timeout",
            family="Injected transient tool failures",
            goal="Recover from database lock contention on write",
            success_criteria=[
                SuccessCriterion(
                    id="write_committed",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["acquire_lock_and_write"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=8),
            injected_failures={
                "acquire_lock_and_write": {"transient_count": 1, "error": "LockTimeout"}
            },
            fake_actions=[
                {"tool": "acquire_lock_and_write", "arguments": {"attempt": 1}},
                {"tool": "acquire_lock_and_write", "arguments": {"attempt": 2}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True, "requires_retry": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="transient_socket_reset",
            family="Injected transient tool failures",
            goal="Survive network connection reset by peer",
            success_criteria=[
                SuccessCriterion(
                    id="connection_established",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["connect_stream"],
            budget_limits=BudgetLimits(max_llm_calls=4, max_tool_calls=6),
            injected_failures={
                "connect_stream": {"transient_count": 1, "error": "ConnectionReset"}
            },
            fake_actions=[
                {"tool": "connect_stream", "arguments": {}},
                {"tool": "connect_stream", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"success": True, "requires_retry": True},
        )
    )

    # 6. Duplicate-call traps (3 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="dup_search_loop",
            family="Duplicate-call traps",
            goal="Avoid infinite repeated keyword search loop",
            success_criteria=[
                SuccessCriterion(
                    id="search_resolved",
                    verifier="numeric_range",
                    config={"key": "search_resolved", "min": 1},
                )
            ],
            available_tools=["search_tool", "fallback_tool"],
            budget_limits=BudgetLimits(max_llm_calls=8, max_tool_calls=8),
            loop_trigger_step=3,
            fake_actions=[
                {"tool": "search_tool", "arguments": {"query": "static"}},
                {"tool": "search_tool", "arguments": {"query": "static"}},
                {"tool": "search_tool", "arguments": {"query": "static"}},
                {"tool": "fallback_tool", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"case_detects_loop": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="dup_status_poll",
            family="Duplicate-call traps",
            goal="Intervene when agent loops on polling unchanging build status",
            success_criteria=[
                SuccessCriterion(
                    id="status_verified",
                    verifier="numeric_range",
                    config={"key": "status_verified", "min": 1},
                )
            ],
            available_tools=["poll_status", "rebuild"],
            budget_limits=BudgetLimits(max_llm_calls=8, max_tool_calls=8),
            loop_trigger_step=3,
            fake_actions=[
                {"tool": "poll_status", "arguments": {}},
                {"tool": "poll_status", "arguments": {}},
                {"tool": "poll_status", "arguments": {}},
                {"tool": "rebuild", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"case_detects_loop": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="dup_read_stagnant",
            family="Duplicate-call traps",
            goal="Block repetitive file reading with no state progression",
            success_criteria=[
                SuccessCriterion(
                    id="read_succeeded",
                    verifier="numeric_range",
                    config={"key": "read_succeeded", "min": 1},
                )
            ],
            available_tools=["read_file", "edit_file"],
            budget_limits=BudgetLimits(max_llm_calls=8, max_tool_calls=8),
            loop_trigger_step=3,
            fake_actions=[
                {"tool": "read_file", "arguments": {"file": "log.txt"}},
                {"tool": "read_file", "arguments": {"file": "log.txt"}},
                {"tool": "read_file", "arguments": {"file": "log.txt"}},
                {"tool": "edit_file", "arguments": {"file": "log.txt"}},
                {"type": "complete_task"},
            ],
            expected_outcome={"case_detects_loop": True},
        )
    )

    # 7. Context-bloat traps (2 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="bloat_huge_payload",
            family="Context-bloat traps",
            goal="Compact context after fetching a large 100k JSON payload",
            success_criteria=[
                SuccessCriterion(
                    id="payload_digested",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["dump_large_json", "extract_summary"],
            budget_limits=BudgetLimits(max_llm_calls=4, max_tokens=15000),
            fake_actions=[
                {"tool": "dump_large_json", "arguments": {}},
                {"tool": "extract_summary", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"requires_compression": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="bloat_repetitive_logs",
            family="Context-bloat traps",
            goal="Filter redundant trace lines before answering prompt",
            success_criteria=[
                SuccessCriterion(
                    id="logs_filtered",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["fetch_raw_logs", "filter_errors"],
            budget_limits=BudgetLimits(max_llm_calls=4, max_tokens=20000),
            fake_actions=[
                {"tool": "fetch_raw_logs", "arguments": {}},
                {"tool": "filter_errors", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"requires_compression": True},
        )
    )

    # 8. Premature-completion traps (2 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="premature_claim_early",
            family="Premature-completion traps",
            goal="Reject model completion declaration when unit tests are failing",
            success_criteria=[
                SuccessCriterion(
                    id="unit_tests_pass",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["apply_fix", "run_unit_tests"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=8),
            premature_claim_step=1,
            fake_actions=[
                {"type": "complete_task"},  # Premature claim!
                {"tool": "apply_fix", "arguments": {}},
                {"tool": "run_unit_tests", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"case_rejects_premature": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="premature_skipped_milestone",
            family="Premature-completion traps",
            goal="Ensure task is not marked done before milestone 2 is satisfied",
            success_criteria=[
                SuccessCriterion(
                    id="final_gate",
                    verifier="numeric_range",
                    config={"value": 2, "min": 2},
                )
            ],
            milestones=[
                Milestone(
                    id="m1_ready",
                    done_when=VerifierSpec(verifier="numeric_range", config={"value": 1, "min": 1}),
                ),
                Milestone(
                    id="m2_deployed",
                    done_when=VerifierSpec(verifier="numeric_range", config={"value": 2, "min": 2}),
                ),
            ],
            available_tools=["step_one", "step_two"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=8),
            premature_claim_step=1,
            fake_actions=[
                {"tool": "step_one", "arguments": {}},
                {"type": "complete_task"},  # Premature claim before step two!
                {"tool": "step_two", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"case_rejects_premature": True},
        )
    )

    # 9. Budget-constrained planning (2 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="budget_tight_cost",
            family="Budget-constrained planning",
            goal="Execute search and verify result strictly within $0.05 limit",
            success_criteria=[
                SuccessCriterion(
                    id="tight_goal_met",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["quick_probe"],
            budget_limits=BudgetLimits(max_cost_usd=0.05, max_llm_calls=3, max_tool_calls=4),
            fake_actions=[
                {"tool": "quick_probe", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"budget_compliant": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="budget_token_cap",
            family="Budget-constrained planning",
            goal="Operate under hard 5,000 token budget cap without exceeding",
            success_criteria=[
                SuccessCriterion(
                    id="token_goal_met",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["concise_tool"],
            budget_limits=BudgetLimits(max_tokens=5000, max_llm_calls=4),
            fake_actions=[
                {"tool": "concise_tool", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"budget_compliant": True},
        )
    )

    # 10. Recovery-from-failure tasks (2 tasks)
    tasks.append(
        BenchmarkTask(
            task_id="recovery_persistent_failure",
            family="Recovery-from-failure tasks",
            goal="Switch to backup tool after primary fails 3 times",
            success_criteria=[
                SuccessCriterion(
                    id="recovery_completed",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["primary_broken_tool", "backup_working_tool"],
            budget_limits=BudgetLimits(max_llm_calls=8, max_tool_calls=10),
            injected_failures={"primary_broken_tool": {"permanent": True}},
            fake_actions=[
                {"tool": "primary_broken_tool", "arguments": {}},
                {"tool": "primary_broken_tool", "arguments": {}},
                {"tool": "primary_broken_tool", "arguments": {}},
                {"tool": "backup_working_tool", "arguments": {}},
                {"type": "complete_task"},
            ],
            expected_outcome={"triggers_replan": True},
        )
    )

    tasks.append(
        BenchmarkTask(
            task_id="recovery_invalid_arguments",
            family="Recovery-from-failure tasks",
            goal="Correct schema argument type upon governor rejection",
            success_criteria=[
                SuccessCriterion(
                    id="schema_satisfied",
                    verifier="numeric_range",
                    config={"value": 1, "min": 1},
                )
            ],
            available_tools=["strict_tool"],
            budget_limits=BudgetLimits(max_llm_calls=5, max_tool_calls=6),
            fake_actions=[
                {"tool": "strict_tool", "arguments": {"count": "not_an_int"}},
                {"tool": "strict_tool", "arguments": {"count": 42}},
                {"type": "complete_task"},
            ],
            expected_outcome={"recovers_from_schema_error": True},
        )
    )

    return tasks
