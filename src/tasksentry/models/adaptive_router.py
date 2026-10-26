"""Router that learns from outcomes: semantic rules + Thompson-sampling exploration.

Hard semantic signals (replanning, verification failure, reasoning keywords) still
force the reasoning lane. For ordinary 'routine' prompts, a cost-aware bandit may
explore/exploit between lanes. Call feedback() after each completion.
"""

from __future__ import annotations

from typing import Any

from tasksentry.math.bandit import ThompsonSelector, lane_reward
from tasksentry.models.router import SemanticModelRouter


class AdaptiveModelRouter(SemanticModelRouter):
    def __init__(
        self, *args: Any, seed: int | None = None, discount: float = 0.99, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.selector = ThompsonSelector(
            [self.routine_model, self.reasoning_model], seed=seed, discount=discount
        )

    def classify_route(
        self, messages: list[dict[str, Any]], context: dict[str, Any] | None = None
    ) -> tuple[str, str]:
        model, reason = super().classify_route(messages, context=context)
        if model == self.routine_model and reason.startswith("routine"):
            pick = self.selector.select()
            if pick != model:
                return pick, "bandit: learned lane preference"
        return model, reason

    def feedback(
        self, model: str, success: bool, latency_s: float = 0.0, cost_usd: float = 0.0
    ) -> None:
        if model in self.selector.params:
            self.selector.update(model, lane_reward(success, latency_s, cost_usd))
