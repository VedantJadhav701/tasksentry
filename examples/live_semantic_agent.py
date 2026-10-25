"""End-to-End Live Autonomous Agent with Semantic Model Routing and Real Ollama LLMs.

Demonstrates:
1. Connecting to local Ollama (127.0.0.1:11434).
2. Semantic model routing:
   - Routine lane: Fast lightweight models (e.g. qwen2.5:3b, llama3.2:1b).
   - Reasoning lane: Deep reasoning models (e.g. qwen3:4b-instruct-2507-q4_K_M, ornith:latest).
3. Autonomous execution of LLMAgent under TaskSentry budget governance & tool execution.
4. Final receipt verification and audit trail.
"""

import sys

import tasksentry.tools.builtin  # noqa: F401 - registers built-in tools
from tasksentry.core.task import AgentTask
from tasksentry.harness.agent import LLMAgent
from tasksentry.models.ollama import check_ollama_health
from tasksentry.models.router import SemanticModelRouter
from tasksentry.tools.registry import default_registry


def main() -> int:
    print("==================================================")
    print(" TASK SENTRY: LIVE SEMANTIC AGENT WITH OLLAMA")
    print("==================================================")

    # 1. Check local Ollama health
    print("\n[Step 1] Checking local Ollama health...")
    health = check_ollama_health()
    if not health.get("reachable"):
        print("[ERROR] Local Ollama is not reachable on http://127.0.0.1:11434.")
        print("Please ensure Ollama is running (`ollama serve`).")
        return 1

    available_models = health.get("available_models", [])
    print(f"  * Ollama status: Reachable ({health.get('latency_ms', 0):.1f}ms latency)")
    print(f"  * Available models ({len(available_models)}): {', '.join(available_models[:6])}")

    # 2. Configure Semantic Router
    routine_model = "qwen2.5:3b" if "qwen2.5:3b" in available_models else "llama3.2:1b"
    reasoning_model = (
        "qwen3:4b-instruct-2507-q4_K_M"
        if "qwen3:4b-instruct-2507-q4_K_M" in available_models
        else "ornith:latest"
        if "ornith:latest" in available_models
        else routine_model
    )

    print("\n[Step 2] Initializing Semantic Model Router...")
    print(f"  * Routine lane  -> {routine_model} (fast tool invocation & arguments)")
    print(f"  * Reasoning lane -> {reasoning_model} (planning, failure analysis, replanning)")

    router = SemanticModelRouter(
        routine_model=routine_model,
        reasoning_model=reasoning_model,
        fallback_models=[m for m in available_models if m not in (routine_model, reasoning_model)],
    )

    # 3. Demonstrate Semantic Classification
    print("\n[Step 3] Testing dynamic routing classification:")
    test_routine = [{"role": "user", "content": "List the files in the directory"}]
    test_reasoning = [
        {
            "role": "user",
            "content": "Investigate root cause of failure and plan architectural refactoring",
        }
    ]

    r_mod, r_reason = router.classify_route(test_routine)
    print(f"  - Routine query:   -> routed to '{r_mod}' ({r_reason})")
    re_mod, re_reason = router.classify_route(test_reasoning)
    print(f"  - Reasoning query: -> routed to '{re_mod}' ({re_reason})")

    # 4. Set up live governed task
    print("\n[Step 4] Running live autonomous task under TaskSentry budget...")
    task = AgentTask(
        goal="List files in the current repository workspace and verify pyproject.toml exists",
        max_llm_calls=5,
        max_tool_calls=5,
        max_tokens=10000,
        max_cost_usd=0.25,
        max_wall_time_seconds=60,
        success_criteria=[
            {
                "id": "pyproject_exists",
                "verifier": "file_exists",
                "config": {"path": "pyproject.toml"},
            }
        ],
    )

    agent = LLMAgent(
        model_client=router,
        registry=default_registry,
        system_prompt=(
            "You are an autonomous agent governed by TaskSentry.\n"
            "Goal: check directory contents and read pyproject.toml if present.\n"
            "Use available tools. When complete, output: COMPLETE: <summary>\n"
        ),
    )

    receipt = task.run(agent=agent, max_steps=4)

    # 5. Display Receipt
    print("\n==================================================")
    print(" TASK RECEIPT SUMMARY")
    print("==================================================")
    print(f"Task ID:    {receipt.task_id}")
    print(f"Status:     {receipt.status}")
    print(f"Success:    {receipt.success}")
    print(f"Tokens:     {receipt.tokens}")
    print(f"Cost:       ${receipt.cost_usd:.4f}")
    print(f"Duration:   {receipt.wall_time_seconds:.2f}s")
    print(f"Tool Calls: {receipt.tool_calls}")
    print("==================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
