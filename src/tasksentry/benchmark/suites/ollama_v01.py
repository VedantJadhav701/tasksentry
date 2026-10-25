"""Ollama local benchmark suite v0.1 targeting local LLM models."""

from tasksentry.benchmark.suites.offline_v01 import get_offline_v01_tasks
from tasksentry.benchmark.tasks import BenchmarkTask


def get_ollama_v01_tasks() -> list[BenchmarkTask]:
    """Return the suite of 26 benchmark tasks configured for local Ollama execution."""
    # Tasks share identical criteria, goals, and verifiers to maintain strict fairness
    return get_offline_v01_tasks()
