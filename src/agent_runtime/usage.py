"""Token accounting for a model call, a step, or a whole run.

Every model turn reports how many tokens it consumed; multiplied by the
selected model's prices (`agent_runtime.models`) that becomes a dollar
figure. `TokenUsage` values add together, so the same type describes one
call, one step, and the cumulative total for a run.

`cost_usd` is `None` — not `0.0` — when the model has no known price, so
"free" and "we don't know" never look the same on screen.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent_runtime.models import ModelPricing


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Tokens in, tokens out, and what that cost."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None

    @classmethod
    def from_counts(
        cls,
        input_tokens: int,
        output_tokens: int,
        pricing: ModelPricing | None = None,
        total_tokens: int | None = None,
    ) -> TokenUsage:
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=(
                total_tokens if total_tokens is not None else input_tokens + output_tokens
            ),
            cost_usd=pricing.cost_usd(input_tokens, output_tokens) if pricing else None,
        )

    @classmethod
    def from_metadata(
        cls, metadata: Mapping[str, Any] | None, pricing: ModelPricing | None = None
    ) -> TokenUsage | None:
        """Build from LangChain's `usage_metadata`, or `None` if it's absent.

        Providers occasionally omit usage (or a test double never sets it),
        and an absent count is reported as absent rather than as zero.
        """
        if not metadata:
            return None
        input_tokens = int(metadata.get("input_tokens", 0) or 0)
        output_tokens = int(metadata.get("output_tokens", 0) or 0)
        total = metadata.get("total_tokens")
        return cls.from_counts(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            pricing=pricing,
            total_tokens=int(total) if total else None,
        )

    def __add__(self, other: TokenUsage) -> TokenUsage:
        if self.cost_usd is None and other.cost_usd is None:
            cost: float | None = None
        else:
            cost = round((self.cost_usd or 0.0) + (other.cost_usd or 0.0), 6)
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cost_usd=cost,
        )

    @property
    def is_empty(self) -> bool:
        return self.total_tokens == 0 and not self.cost_usd


__all__ = ["TokenUsage"]
