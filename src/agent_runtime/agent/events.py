"""Events emitted while the agent loop runs.

The loop is a generator of these, which is what makes it a *visible*
runtime rather than a black box: the API layer turns the same stream into
Server-Sent Events, and tests can assert on it directly instead of
scraping the final answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_runtime.usage import TokenUsage


@dataclass(slots=True)
class RunStarted:
    run_id: str
    max_steps: int


@dataclass(slots=True)
class StepStarted:
    run_id: str
    step: int


@dataclass(slots=True)
class ModelToken:
    """One streamed token/fragment of the assistant's current turn."""

    run_id: str
    step: int
    text: str


@dataclass(slots=True)
class ToolCallRequested:
    run_id: str
    step: int
    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCallResult:
    run_id: str
    step: int
    call_id: str
    tool_name: str
    content: str
    is_error: bool
    duration_s: float


@dataclass(slots=True)
class UsageUpdated:
    """Token spend for the model call that just finished, plus the run total.

    Emitted after every model turn, so a client can show a live, running
    cost for the message it is watching instead of waiting for the end.
    """

    run_id: str
    step: int
    model: str
    step_usage: TokenUsage
    run_usage: TokenUsage


@dataclass(slots=True)
class FinalAnswer:
    run_id: str
    step: int
    content: str


@dataclass(slots=True)
class RunFailed:
    run_id: str
    step: int
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
