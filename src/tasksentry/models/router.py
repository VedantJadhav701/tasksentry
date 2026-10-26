"""Semantic model router directing agent steps between fast routine and deep reasoning models."""

import logging
import re
import time
from typing import Any

from tasksentry.models.base import ModelClient, ModelResponse
from tasksentry.models.ollama import OllamaClient

logger = logging.getLogger(__name__)

REASONING_KEYWORDS = {
    "plan",
    "replan",
    "architecture",
    "investigate",
    "diagnose",
    "root cause",
    "why",
    "hypothesis",
    "recovering",
    "verification failed",
    "stagnant",
    "loop warning",
    "deadlock",
    "synthesize",
    "refactor",
}


class SemanticModelRouter(ModelClient):
    """Dynamically routes queries between fast routine models and deep reasoning models.

    Models:
    - Routine: Fast, low-latency models for tool execution, argument formatting, and status checks
      (e.g. qwen2.5:3b, llama3.2:1b, gemma2:2b).
    - Reasoning: High-capacity models for planning, failure diagnosis, replans, and complex logic
      (e.g. qwen3:4b-instruct-2507-q4_K_M, ornith:latest, beam:cloud).
    """

    def __init__(
        self,
        routine_model: str = "qwen2.5:3b",
        reasoning_model: str = "qwen3:4b-instruct-2507-q4_K_M",
        base_url: str = "http://127.0.0.1:11434",
        fallback_models: list[str] | None = None,
        clients: dict[str, ModelClient] | None = None,
    ) -> None:
        self.routine_model = routine_model
        self.reasoning_model = reasoning_model
        self.base_url = base_url
        self.fallback_models = fallback_models or ["beam:cloud", "qwen2.5:3b", "llama3.2:1b"]
        self._clients: dict[str, ModelClient] = clients or {}

    def _get_client(self, model_name: str) -> ModelClient:
        if model_name not in self._clients:
            # For Ollama models, use OllamaClient with safe context options
            self._clients[model_name] = OllamaClient(
                model=model_name,
                base_url=f"{self.base_url.rstrip('/')}/v1",
            )
        return self._clients[model_name]

    def classify_route(
        self,
        messages: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Classify messages into 'reasoning' or 'routine' with a human-readable rationale."""
        ctx = context or {}

        # 1. Explicit context flags take precedence
        if ctx.get("is_replanning") or ctx.get("is_recovering"):
            return self.reasoning_model, "context: active recovery/replanning phase"
        if ctx.get("verification_failed") or ctx.get("loop_warning"):
            return self.reasoning_model, "context: verification failure or loop warning"

        # 2. Inspect latest user/system message content
        text_content = ""
        for m in reversed(messages):
            c = m.get("content") or ""
            if isinstance(c, str):
                text_content += " " + c.lower()
            if len(text_content) > 1000:
                break

        words = set(re.findall(r"\b[a-z]{3,}\b", text_content))
        overlap = words.intersection(REASONING_KEYWORDS)
        crit_phrases = ["root cause", "verification failed", "loop warning"]
        if len(overlap) >= 2 or any(p in text_content for p in crit_phrases):
            return self.reasoning_model, f"semantic match: {list(overlap)[:3]}"

        # 3. Default to routine fast model for standard tool operations
        return self.routine_model, "routine tool execution"

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Route completion request semantically with automated fallback."""
        explicit_model = kwargs.pop("model", None)
        if explicit_model:
            target_model = explicit_model
            route_reason = "explicit model request"
        else:
            ctx = kwargs.get("context")
            target_model, route_reason = self.classify_route(messages, context=ctx)

        models_to_try = [target_model]
        # Build fallback chain excluding target
        for fb in self.fallback_models:
            if fb not in models_to_try:
                models_to_try.append(fb)
        if self.routine_model not in models_to_try:
            models_to_try.append(self.routine_model)

        last_error: Exception | None = None
        start_time = time.perf_counter()

        for mod in models_to_try:
            client = self._get_client(mod)
            try:
                # Add safe context options for qwen3 to avoid 38GB KV cache OOM
                call_kwargs = dict(kwargs)
                if "qwen3" in mod:
                    opts = dict(call_kwargs.get("options", {}))
                    opts.setdefault("num_ctx", 4096)
                    call_kwargs["options"] = opts

                resp = client.complete(messages, tools=tools, model=mod, **call_kwargs)
                raw = dict(resp.raw_response)
                raw["routed_model"] = mod
                raw["route_reason"] = route_reason
                raw["router_latency_seconds"] = round(time.perf_counter() - start_time, 4)

                return ModelResponse(
                    content=resp.content,
                    tool_calls=resp.tool_calls,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    model=mod,
                    finish_reason=resp.finish_reason,
                    raw_response=raw,
                )
            except Exception as exc:
                logger.warning(
                    "Model %s failed in semantic router: %s. Trying fallback...",
                    mod,
                    exc,
                )
                last_error = exc
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError("No models available in semantic router.")
