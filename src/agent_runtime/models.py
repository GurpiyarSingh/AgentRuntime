"""The catalog of selectable chat models, and what each one costs.

This is the single source of truth for "which models may a caller pick?"
— the UI dropdown, the `/v1/models` endpoint, request validation, and the
cost calculation all read from `MODEL_CATALOG`, so they can't drift apart.

Prices are **USD per 1,000,000 tokens** and are baked in as defaults only.
Provider pricing changes without warning, so any entry can be corrected at
runtime via the `MODEL_PRICING_JSON` environment variable (see
`agent_runtime.config.Settings.pricing_overrides`) without editing code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


class UnknownModelError(ValueError):
    """Raised when a caller asks for a model that isn't in the catalog."""


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Token prices for one model, in USD per 1M tokens."""

    input_usd_per_1m: float
    output_usd_per_1m: float

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Cost of a call with this many tokens, rounded to the nearest microdollar."""
        cost = (
            input_tokens * self.input_usd_per_1m + output_tokens * self.output_usd_per_1m
        ) / 1_000_000
        return round(cost, 6)


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """One selectable model: how to name it, how to describe it, what it costs."""

    id: str
    label: str
    description: str
    pricing: ModelPricing


# Keep insertion order meaningful: the UI renders the dropdown in this order.
MODEL_CATALOG: dict[str, ModelInfo] = {
    "gpt-4o": ModelInfo(
        id="gpt-4o",
        label="GPT-4o",
        description="Fast, widely available, and the cheapest of the two for most turns.",
        pricing=ModelPricing(input_usd_per_1m=2.50, output_usd_per_1m=10.00),
    ),
    "gpt-5.2": ModelInfo(
        id="gpt-5.2",
        label="GPT-5.2",
        description="Stronger reasoning; slower, and it spends more output tokens per answer.",
        # NOTE: placeholder rates — verify against OpenAI's pricing page and
        # correct with MODEL_PRICING_JSON rather than trusting these numbers.
        pricing=ModelPricing(input_usd_per_1m=1.25, output_usd_per_1m=10.00),
    ),
}

DEFAULT_MODEL_ID = "gpt-4o"


def available_models() -> list[ModelInfo]:
    """Every model a caller is allowed to select, in display order."""
    return list(MODEL_CATALOG.values())


def resolve_model_id(requested: str | None, default: str = DEFAULT_MODEL_ID) -> str:
    """Validate a caller-supplied model id, falling back to `default`.

    Raises `UnknownModelError` for anything outside the catalog, so a typo
    in an API request fails loudly instead of silently billing a different
    model than the caller asked for.
    """
    model_id = (requested or default).strip()
    if model_id not in MODEL_CATALOG:
        allowed = ", ".join(MODEL_CATALOG)
        raise UnknownModelError(f"Unknown model {model_id!r}. Available models: {allowed}.")
    return model_id


def pricing_for(
    model_id: str, overrides: dict[str, ModelPricing] | None = None
) -> ModelPricing | None:
    """Prices for `model_id`, preferring a runtime override; `None` if unpriced."""
    if overrides and model_id in overrides:
        return overrides[model_id]
    info = MODEL_CATALOG.get(model_id)
    return info.pricing if info else None


def parse_pricing_overrides(raw: str | None) -> dict[str, ModelPricing]:
    """Parse `MODEL_PRICING_JSON` into per-model prices.

    Expected shape (USD per 1M tokens), and unknown keys are allowed so a
    model can be repriced before it's added to the catalog:

        {"gpt-5.2": {"input_usd_per_1m": 1.25, "output_usd_per_1m": 10.0}}
    """
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MODEL_PRICING_JSON is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("MODEL_PRICING_JSON must be a JSON object keyed by model id")

    overrides: dict[str, ModelPricing] = {}
    for model_id, prices in data.items():
        if not isinstance(prices, dict):
            raise ValueError(f"MODEL_PRICING_JSON entry for {model_id!r} must be an object")
        try:
            overrides[model_id] = ModelPricing(
                input_usd_per_1m=float(prices["input_usd_per_1m"]),
                output_usd_per_1m=float(prices["output_usd_per_1m"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"MODEL_PRICING_JSON entry for {model_id!r} needs numeric "
                "'input_usd_per_1m' and 'output_usd_per_1m'"
            ) from exc
    return overrides


__all__ = [
    "DEFAULT_MODEL_ID",
    "MODEL_CATALOG",
    "ModelInfo",
    "ModelPricing",
    "UnknownModelError",
    "available_models",
    "parse_pricing_overrides",
    "pricing_for",
    "resolve_model_id",
]
