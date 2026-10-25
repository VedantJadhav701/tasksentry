"""Example: Ollama Benchmark Track Demonstration.

Demonstrates how to probe local Ollama health and run benchmarks.
- If Ollama is running on http://127.0.0.1:11434, queries models.
- If Ollama is not running, prints setup instructions and runs the offline fallback.

Expected output:
    Checking local Ollama daemon status...
    [If running]: Connected to Ollama! Models found: [...]
    [If offline]: Ollama daemon is not running on http://127.0.0.1:11434.
                  To run live models: 'ollama serve' and 'ollama pull llama3.2:1b'.
                  Executing offline fallback suite to demonstrate benchmark execution...
    Offline benchmark smoke test completed successfully.

Exit condition:
    Exits with code 0.
"""

import sys

from tasksentry.benchmark.runner import run_benchmark_suite
from tasksentry.models.ollama import check_ollama_health


def main() -> int:
    print("Checking local Ollama daemon status at http://127.0.0.1:11434...")
    health = check_ollama_health("http://127.0.0.1:11434")

    if health.get("reachable") and health.get("available_models"):
        models = health.get("available_models", [])
        print(f"Connected to Ollama! Found {len(models)} models:")
        for m in models:
            print(f"  - {m}")
        print("\nTo run the live real-model benchmark:")
        print("    tasksentry benchmark --suite ollama-v0.1 --routine-model llama3.2:1b")
    else:
        print("Note: Ollama daemon is currently offline or has no downloaded models.")
        print("To run local models:")
        print("  1. Download and start Ollama: https://ollama.com")
        print("  2. Pull a recommended model:  ollama pull llama3.2:1b")
        print("  3. Run:                       tasksentry benchmark --suite ollama-v0.1")
        print("\nExecuting offline regression track to verify benchmark harness...")

    # Run offline suite to demonstrate runner behavior
    data = run_benchmark_suite(suite_name="offline-v0.1", seed=42)
    aggregates = data.get("aggregates", {})
    case_stats = aggregates.get("tasksentry_case", {})
    print("\nBenchmark results (offline-v0.1):")
    print(f"  - Success rate: {case_stats.get('task_success_rate', 0.0) * 100:.1f}%")
    print(f"  - Tokens/success: {case_stats.get('tokens_per_successful_task', 0.0):.1f}")
    print(f"  - Tool calls/task: {case_stats.get('tool_calls_per_task', 0.0):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
