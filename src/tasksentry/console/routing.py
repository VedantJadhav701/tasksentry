"""Auditable semantic routing decisions, signals telemetry, and router comparison playground."""

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.models.base import ModelClient, ModelResponse
from tasksentry.models.router import SemanticModelRouter


class RoutingDecision(BaseModel):
    """Auditable record of a single semantic routing decision."""

    model_config = ConfigDict(extra="ignore")

    step: int
    selected_model: str
    lane: str  # "routine" or "reasoning"
    reason: str
    signals: dict[str, Any] = Field(default_factory=dict)
    fallback_model: str = ""
    latency_ms: float = 0.0
    tokens: dict[str, int] = Field(default_factory=lambda: {"input": 0, "output": 0})
    timestamp: float = Field(default_factory=time.time)


class RouterAuditLog:
    """In-memory store of routing telemetry per task."""

    def __init__(self) -> None:
        self._decisions: dict[str, list[RoutingDecision]] = {}

    def record(self, task_id: str, decision: RoutingDecision) -> None:
        self._decisions.setdefault(task_id, []).append(decision)

    def get_task_decisions(self, task_id: str) -> list[RoutingDecision]:
        return list(self._decisions.get(task_id, []))

    def clear(self) -> None:
        self._decisions.clear()


default_audit_log = RouterAuditLog()


class RouterPlayground:
    """Interactive comparison engine evaluating prompts across routine and reasoning lanes."""

    def __init__(
        self,
        router: SemanticModelRouter | None = None,
        mock_mode: bool = False,
    ) -> None:
        self.router = router or SemanticModelRouter()
        self.mock_mode = mock_mode

    def compare(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
        routine_model: str | None = None,
        reasoning_model: str | None = None,
    ) -> dict[str, Any]:
        """Execute prompt against routine lane, reasoning lane, and semantic router decision."""
        ctx = context or {}
        r_mod = routine_model or self.router.routine_model
        re_mod = reasoning_model or self.router.reasoning_model

        messages = [{"role": "user", "content": prompt}]

        # 1. Inspect classification signals
        selected_mod, reason = self.router.classify_route(messages, context=ctx)
        lane = "reasoning" if selected_mod == re_mod else "routine"

        # Signal diagnostics
        complexity = (
            "hard"
            if any(
                k in prompt.lower()
                for k in ["root cause", "investigate", "architecture", "diagnose", "plan"]
            )
            else "standard"
        )
        signals = {
            "complexity": complexity,
            "stagnant_steps": ctx.get("stagnant_steps", 0),
            "open_failures": 1 if ctx.get("verification_failed") else 0,
            "has_replanning": bool(ctx.get("is_replanning")),
        }

        if self.mock_mode:
            # Deterministic offline evaluation
            return {
                "prompt": prompt,
                "lane_selected": lane,
                "selected_model": selected_mod,
                "reason": reason,
                "signals": signals,
                "fallback_model": r_mod if selected_mod == re_mod else re_mod,
                "routine_lane": {
                    "model": r_mod,
                    "content": f"[Mock Routine {r_mod}] Executed prompt.",
                    "latency_ms": 12.5,
                    "tokens": {"input": len(prompt.split()), "output": 8},
                },
                "reasoning_lane": {
                    "model": re_mod,
                    "content": f"[Mock Reasoning {re_mod}] Analyzed problem: {prompt}",
                    "latency_ms": 28.0,
                    "tokens": {"input": len(prompt.split()), "output": 15},
                },
                "routed_response": {
                    "model": selected_mod,
                    "content": f"[Routed: {selected_mod}] Handled via {lane} lane: {reason}",
                    "latency_ms": 18.0,
                    "tokens": {"input": len(prompt.split()), "output": 12},
                },
            }

        # Live execution via client
        def _timed_complete(client: ModelClient, mod: str) -> tuple[ModelResponse, float]:
            t0 = time.perf_counter()
            call_kwargs: dict[str, Any] = {}
            if "qwen3" in mod:
                call_kwargs["options"] = {"num_ctx": 4096}
            res = client.complete(messages, model=mod, **call_kwargs)
            lat = round((time.perf_counter() - t0) * 1000, 2)
            return res, lat

        routine_client = self.router._get_client(r_mod)
        reasoning_client = self.router._get_client(re_mod)

        # Execute routine model
        try:
            r_resp, r_lat = _timed_complete(routine_client, r_mod)
            r_data = {
                "model": r_mod,
                "content": r_resp.content,
                "latency_ms": r_lat,
                "tokens": {"input": r_resp.input_tokens, "output": r_resp.output_tokens},
            }
        except Exception as exc:
            r_data = {"model": r_mod, "error": str(exc), "latency_ms": 0.0, "tokens": {}}

        # Execute reasoning model
        try:
            re_resp, re_lat = _timed_complete(reasoning_client, re_mod)
            re_data = {
                "model": re_mod,
                "content": re_resp.content,
                "latency_ms": re_lat,
                "tokens": {"input": re_resp.input_tokens, "output": re_resp.output_tokens},
            }
        except Exception as exc:
            re_data = {"model": re_mod, "error": str(exc), "latency_ms": 0.0, "tokens": {}}

        # Routed outcome corresponds to whichever was selected
        routed_data = re_data if selected_mod == re_mod else r_data

        return {
            "prompt": prompt,
            "lane_selected": lane,
            "selected_model": selected_mod,
            "reason": reason,
            "signals": signals,
            "fallback_model": r_mod if selected_mod == re_mod else re_mod,
            "routine_lane": r_data,
            "reasoning_lane": re_data,
            "routed_response": routed_data,
        }
