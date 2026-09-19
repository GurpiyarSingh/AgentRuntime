from __future__ import annotations

import pytest

from agent_runtime.config import Settings
from agent_runtime.models import (
    DEFAULT_MODEL_ID,
    MODEL_CATALOG,
    ModelPricing,
    UnknownModelError,
    available_models,
    parse_pricing_overrides,
    pricing_for,
    resolve_model_id,
)
from agent_runtime.usage import TokenUsage


def test_catalog_offers_both_models() -> None:
    ids = [model.id for model in available_models()]
    assert ids == ["gpt-4o", "gpt-5.2"]
    assert DEFAULT_MODEL_ID in MODEL_CATALOG


def test_resolve_model_id_falls_back_to_default() -> None:
    assert resolve_model_id(None, "gpt-5.2") == "gpt-5.2"
    assert resolve_model_id("  gpt-4o  ") == "gpt-4o"


def test_resolve_model_id_rejects_unknown_model() -> None:
    with pytest.raises(UnknownModelError) as excinfo:
        resolve_model_id("gpt-9000")
    assert "gpt-4o" in str(excinfo.value)  # the error names what is available


def test_cost_is_priced_per_million_tokens() -> None:
    pricing = ModelPricing(input_usd_per_1m=2.50, output_usd_per_1m=10.00)
    # 1M input + 1M output at those rates.
    assert pricing.cost_usd(1_000_000, 1_000_000) == 12.50
    assert pricing.cost_usd(1_000, 500) == round(0.0025 + 0.005, 6)
    assert pricing.cost_usd(0, 0) == 0.0


def test_pricing_overrides_win_over_catalog() -> None:
    overrides = parse_pricing_overrides(
        '{"gpt-4o": {"input_usd_per_1m": 1.0, "output_usd_per_1m": 2.0}}'
    )
    assert pricing_for("gpt-4o", overrides) == ModelPricing(1.0, 2.0)
    # Untouched models keep their catalog prices.
    assert pricing_for("gpt-5.2", overrides) == MODEL_CATALOG["gpt-5.2"].pricing


def test_pricing_overrides_reject_malformed_input() -> None:
    assert parse_pricing_overrides(None) == {}
    assert parse_pricing_overrides("   ") == {}
    with pytest.raises(ValueError):
        parse_pricing_overrides("not json")
    with pytest.raises(ValueError):
        parse_pricing_overrides('{"gpt-4o": {"input_usd_per_1m": 1.0}}')


def test_settings_reject_unknown_default_model() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, openai_model="gpt-9000")  # type: ignore[call-arg]


def test_usage_adds_up_and_keeps_unpriced_distinct_from_free() -> None:
    priced = TokenUsage.from_counts(100, 50, ModelPricing(2.50, 10.00))
    assert priced.total_tokens == 150
    assert priced.cost_usd == round(100 * 2.5 / 1e6 + 50 * 10 / 1e6, 6)

    total = priced + priced
    assert (total.input_tokens, total.output_tokens, total.total_tokens) == (200, 100, 300)
    assert total.cost_usd == round(priced.cost_usd * 2, 6)

    unpriced = TokenUsage.from_counts(10, 5, None)
    assert unpriced.cost_usd is None  # not 0.0 — the price simply isn't known
    assert (unpriced + unpriced).cost_usd is None
    # A mix keeps whatever cost is actually known.
    assert (priced + unpriced).cost_usd == priced.cost_usd


def test_usage_from_provider_metadata() -> None:
    assert TokenUsage.from_metadata(None) is None
    assert TokenUsage.from_metadata({}) is None
    parsed = TokenUsage.from_metadata(
        {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
        ModelPricing(2.50, 10.00),
    )
    assert parsed is not None
    assert (parsed.input_tokens, parsed.output_tokens, parsed.total_tokens) == (12, 3, 15)
    assert parsed.cost_usd is not None
