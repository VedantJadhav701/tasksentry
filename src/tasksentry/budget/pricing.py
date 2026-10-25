"""Configurable token pricing tables and cost estimation.

NOTE: Model pricing changes frequently across providers. Built-in prices
are heuristic defaults provided for convenience and testing, are user-configurable,
and may become outdated. For accurate production accounting, supply an updated
PricingTable or explicit overrides.
"""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tasksentry.exceptions import UnknownModelPriceError


class ModelPricing(BaseModel):
    """Pricing configuration for a single model.

    Prices are expressed per 1,000,000 (1M) tokens in the designated currency.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str
    input_price_per_1m: float = Field(ge=0.0)
    output_price_per_1m: float = Field(ge=0.0)
    currency: str = "USD"
    effective_date: str | None = None

    @field_validator("model_name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("model_name cannot be empty")
        return stripped


class CostEstimate(BaseModel):
    """Detailed breakdown of estimated cost for an LLM invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    input_cost: float = Field(ge=0.0)
    output_cost: float = Field(ge=0.0)
    total_cost: float = Field(ge=0.0)
    currency: str = "USD"

    @property
    def cost_usd(self) -> float:
        """Alias for total_cost when currency is USD."""
        return self.total_cost


class PricingTable:
    """Configurable table mapping model identifiers to pricing rules.

    Supports fallback pricing for unseen models and per-model user overrides.
    """

    def __init__(
        self,
        prices: dict[str, ModelPricing] | None = None,
        fallback_pricing: ModelPricing | None = None,
        default_currency: str = "USD",
    ) -> None:
        self._prices: dict[str, ModelPricing] = {}
        self.fallback_pricing = fallback_pricing
        self.default_currency = default_currency

        if prices:
            for key, val in prices.items():
                self._prices[key.lower()] = val

    def set_price(self, pricing: ModelPricing) -> None:
        """Register or override pricing for a model."""
        self._prices[pricing.model_name.lower()] = pricing

    def add_override(
        self,
        model_name: str,
        input_price_per_1m: float,
        output_price_per_1m: float,
        currency: str = "USD",
        effective_date: str | None = None,
    ) -> None:
        """Add or update pricing for a specific model."""
        pricing = ModelPricing(
            model_name=model_name,
            input_price_per_1m=input_price_per_1m,
            output_price_per_1m=output_price_per_1m,
            currency=currency,
            effective_date=effective_date,
        )
        self.set_price(pricing)

    def get_pricing(self, model: str) -> ModelPricing:
        """Retrieve pricing for ``model``, falling back if configured.

        Raises:
            UnknownModelPriceError: if model is not found and no fallback is set.
        """
        key = model.strip().lower()
        if key in self._prices:
            return self._prices[key]
        if self.fallback_pricing is not None:
            return self.fallback_pricing
        raise UnknownModelPriceError(
            f"Unknown model {model!r} with no fallback pricing configured in pricing table."
        )

    def list_models(self) -> list[str]:
        """List all configured model names."""
        return sorted(self._prices.keys())


# Default heuristic pricing table for common models (prices per 1M tokens in USD).
DEFAULT_PRICING_TABLE = PricingTable(
    prices={
        "gpt-4o": ModelPricing(
            model_name="gpt-4o",
            input_price_per_1m=2.50,
            output_price_per_1m=10.00,
            effective_date="2024-10-01",
        ),
        "gpt-4o-mini": ModelPricing(
            model_name="gpt-4o-mini",
            input_price_per_1m=0.15,
            output_price_per_1m=0.60,
            effective_date="2024-10-01",
        ),
        "claude-3-5-sonnet": ModelPricing(
            model_name="claude-3-5-sonnet",
            input_price_per_1m=3.00,
            output_price_per_1m=15.00,
            effective_date="2024-10-01",
        ),
        "claude-3-5-haiku": ModelPricing(
            model_name="claude-3-5-haiku",
            input_price_per_1m=0.80,
            output_price_per_1m=4.00,
            effective_date="2024-10-01",
        ),
        "mock-model": ModelPricing(
            model_name="mock-model",
            input_price_per_1m=1.00,
            output_price_per_1m=2.00,
            effective_date="2024-01-01",
        ),
    }
)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing_table: PricingTable | None = None,
) -> CostEstimate:
    """Calculate the estimated monetary cost of an LLM call.

    Args:
        model: model identifier.
        input_tokens: count of prompt/input tokens (must be non-negative).
        output_tokens: count of completion/output tokens (must be non-negative).
        pricing_table: optional custom pricing table (defaults to DEFAULT_PRICING_TABLE).

    Returns:
        CostEstimate with input_cost, output_cost, and total_cost rounded to at least
        6 decimal places.

    Raises:
        ValueError: if input_tokens or output_tokens is negative.
        UnknownModelPriceError: if model is unknown and no fallback pricing exists.
    """
    if input_tokens < 0:
        raise ValueError(f"input_tokens must be non-negative, got {input_tokens}")
    if output_tokens < 0:
        raise ValueError(f"output_tokens must be non-negative, got {output_tokens}")

    table = pricing_table or DEFAULT_PRICING_TABLE
    pricing = table.get_pricing(model)

    per_million = Decimal("1000000")
    in_tokens = Decimal(input_tokens)
    out_tokens = Decimal(output_tokens)
    in_price = Decimal(str(pricing.input_price_per_1m))
    out_price = Decimal(str(pricing.output_price_per_1m))

    input_cost_dec = (in_tokens * in_price) / per_million
    output_cost_dec = (out_tokens * out_price) / per_million
    total_cost_dec = input_cost_dec + output_cost_dec

    # Maintain precision with 6+ decimal places
    six_places = Decimal("0.000001")
    input_cost = float(input_cost_dec.quantize(six_places, rounding=ROUND_HALF_UP))
    output_cost = float(output_cost_dec.quantize(six_places, rounding=ROUND_HALF_UP))
    total_cost = float(total_cost_dec.quantize(six_places, rounding=ROUND_HALF_UP))

    return CostEstimate(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
        currency=pricing.currency,
    )
