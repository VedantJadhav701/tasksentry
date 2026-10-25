"""Example: Wrapping an existing agent loop with TaskSentry budget tracking.

This example runs 100% offline with zero external dependencies or API keys.

Expected output:
    [Step 1] Agent generated 240 tokens.
    [Step 2] Agent generated 310 tokens.
    Budget remaining: 1450 tokens, $0.0160 USD
    Final TaskReceipt: status='completed', success=True, total_tokens=550

Exit condition:
    Exits with code 0 upon obtaining receipt.
"""

import sys

from tasksentry import budget


def simulate_existing_agent_step(step_idx: int) -> dict[str, int | str]:
    """Simulate an existing agent framework (e.g. LangGraph or CrewAI) step."""
    tokens = 240 if step_idx == 1 else 310
    return {"step": step_idx, "tokens": tokens, "output": f"Result for step {step_idx}"}


def main() -> int:
    print("Starting wrap_existing_agent example...")

    # Wrap the arbitrary agent loop inside a TaskSentry budget context
    with budget(max_tokens=2000, max_cost_usd=0.02, max_tool_calls=5) as b:
        for step in range(1, 3):
            result = simulate_existing_agent_step(step)
            print(f"[Step {step}] Agent generated {result['tokens']} tokens.")

            # Record usage into ambient meter
            b.record_usage(
                input_tokens=int(result["tokens"]) // 2,
                output_tokens=int(result["tokens"]) // 2,
                cost_usd=0.002,
            )
            b.record_tool_call("simulate_step")

        remaining = b.remaining_budget()
        print(
            f"Budget remaining: {remaining['remaining_tokens']} tokens, "
            f"${remaining['remaining_cost_usd']:.4f} USD"
        )

    receipt = b.receipt()
    print(
        f"Final TaskReceipt: status={receipt.status!r}, success={receipt.success}, "
        f"tokens={receipt.tokens}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
