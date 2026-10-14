"""Events emitted while the agent loop runs.

The loop is a generator of these, which is what makes it a *visible*
runtime rather than a black box: the API turns the same stream into
Server-Sent Events (the class name in snake_case is the SSE event name and
the fields are its JSON payload), and tests assert on it directly instead
of scraping the final answer. Field names are therefore part of the public
streaming API; rename them only as a breaking change.

Every event carries the `run_id` and the 1-based `step` it belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_runtime.usage import TokenUsage


@dataclass(frozen=True, slots=True)
class RunStarted:
    """A run began; always the first event."""

    run_id: str
    max_steps: int


@dataclass(frozen=True, slots=True)
class StepStarted:
    """A think/act iteration began."""

    run_id: str
    step: int


@dataclass(frozen=True, slots=True)
class ModelToken:
    """One streamed fragment of the assistant's current turn."""

    run_id: str
    step: int
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallRequested:
    """The model asked for a tool call; emitted before it runs."""

    run_id: str
    step: int
    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """A tool call finished, successfully or with an error the model will see."""

    run_id: str
    step: int
    call_id: str
    tool_name: str
    content: str
    is_error: bool
    duration_s: float
    image_count: int = 0
    """Images the tool attached for the model. They travel in the transcript,
    not in events, so a stream never carries megabytes of base64."""


@dataclass(frozen=True, slots=True)
class UsageUpdated:
    """Token spend for the model call that just finished, plus the run total.

    Emitted after every model turn that reported usage, so a client can
    show a live running cost instead of waiting for the end.
    """

    run_id: str
    step: int
    model: str
    step_usage: TokenUsage
    run_usage: TokenUsage


@dataclass(frozen=True, slots=True)
class FinalAnswer:
    """The model answered without calling tools; the run succeeded. Terminal."""

    run_id: str
    step: int
    content: str


@dataclass(frozen=True, slots=True)
class RunFailed:
    """The run ended without an answer (budget, provider or internal error). Terminal."""

    run_id: str
    step: int
    """The step in progress when it failed; 0 if it failed before the first."""
    reason: str


AgentEvent = (
    RunStarted
    | StepStarted
    | ModelToken
    | ToolCallRequested
    | ToolCallResult
    | UsageUpdated
    | FinalAnswer
    | RunFailed
)
"""Any event the loop can emit."""


__all__ = [
    "AgentEvent",
    "FinalAnswer",
    "ModelToken",
    "RunFailed",
    "RunStarted",
    "StepStarted",
    "ToolCallRequested",
    "ToolCallResult",
    "UsageUpdated",
]
