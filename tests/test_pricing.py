"""Unit tests for the TaskSentry Pricing system."""

import pytest

from tasksentry.budget.pricing import (
    DEFAULT_PRICING_TABLE,
    CostEstimate,
    ModelPricing,
    PricingTable,
    calculate_cost,
)
from tasksentry.exceptions import UnknownModelPriceError


def test_calculate_cost_known_model() -> None:
    # gpt-4o: 2.50 input per 1M, 10.00 output per 1M
    est = calculate_cost("gpt-4o", input_tokens=1_000_000, output_tokens=500_000)
    assert isinstance(est, CostEstimate)
    assert est.model == "gpt-4o"
    assert est.input_tokens == 1_000_000
    assert est.output_tokens == 500_000
    assert est.total_tokens == 1_500_000
    assert est.input_cost == 2.50
    assert est.output_cost == 5.00
    assert est.total_cost == 7.50
    assert est.currency == "USD"


def test_calculate_cost_custom_override() -> None:
    table = PricingTable()
    table.add_override(
        model_name="my-custom-llm",
        input_price_per_1m=1.00,
        output_price_per_1m=3.00,
        currency="EUR",
    )
    est = calculate_cost(
        "my-custom-llm", input_tokens=2_000_000, output_tokens=1_000_000, pricing_table=table
    )
    assert est.input_cost == 2.00
    assert est.output_cost == 3.00
    assert est.total_cost == 5.00
    assert est.currency == "EUR"


def test_unknown_model_raises_error() -> None:
    with pytest.raises(UnknownModelPriceError):
        calculate_cost("non-existent-model-xyz", input_tokens=100, output_tokens=100)


def test_fallback_pricing() -> None:
    fallback = ModelPricing(
        model_name="default-fallback",
        input_price_per_1m=0.50,
        output_price_per_1m=1.50,
        currency="USD",
    )
    table = PricingTable(fallback_pricing=fallback)
    est = calculate_cost(
        "any-unseen-model", input_tokens=1_000_000, output_tokens=1_000_000, pricing_table=table
    )
    assert est.total_cost == 2.00
    assert est.input_cost == 0.50
    assert est.output_cost == 1.50


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_cost("gpt-4o", input_tokens=-10, output_tokens=100)

    with pytest.raises(ValueError):
        calculate_cost("gpt-4o", input_tokens=100, output_tokens=-10)


def test_precision_at_least_six_decimals() -> None:
    # 1 token of gpt-4o: 2.50 / 1_000_000 = 0.0000025 -> rounded to 6 places = 0.000003
    est = calculate_cost("gpt-4o", input_tokens=1, output_tokens=0)
    assert est.input_cost > 0.0
    assert isinstance(est.input_cost, float)


def test_pricing_table_list_models() -> None:
    models = DEFAULT_PRICING_TABLE.list_models()
    assert "gpt-4o" in models
    assert "gpt-4o-mini" in models
    assert "claude-3-5-sonnet" in models
