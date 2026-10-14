"""Folding a run's event stream into its final outcome.

Every front end that waits for a whole run (the `/v1/chat` endpoint, the
CLI's `ask` command) needs the same summary: the answer or the failure,
the tool calls made, the steps and tokens spent. `RunOutcome` is that
summary, built by feeding it each event as it is observed, so all front
ends report a run identically and none re-implements the bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_runtime.agent.events import (
    AgentEvent,
    FinalAnswer,
    RunFailed,
    StepStarted,
    ToolCallRequested,
    ToolCallResult,
    UsageUpdated,
)
from agent_runtime.usage import TokenUsage


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """One tool call made during a run, with its arguments and result."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    content: str
    is_error: bool
    duration_s: float
    image_count: int


@dataclass(slots=True)
class RunOutcome:
    """The running summary of one run; complete once a terminal event is seen."""

    answer: str = ""
    error: str | None = None
    steps_used: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    _pending_args: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    @property
    def succeeded(self) -> bool:
        """True when the run ended in a final answer rather than a failure."""
        return self.error is None

    def observe(self, event: AgentEvent) -> None:
        """Update the summary with one event from `AgentLoop.run`."""
        if isinstance(event, StepStarted):
            self.steps_used = event.step
        elif isinstance(event, ToolCallRequested):
            # Arguments arrive with the request, results later; pair them by id.
            self._pending_args[event.call_id] = event.arguments
        elif isinstance(event, ToolCallResult):
            self.tool_calls.append(
                ToolCallRecord(
                    call_id=event.call_id,
                    tool_name=event.tool_name,
                    arguments=self._pending_args.pop(event.call_id, {}),
                    content=event.content,
                    is_error=event.is_error,
                    duration_s=event.duration_s,
                    image_count=event.image_count,
                )
            )
        elif isinstance(event, UsageUpdated):
            self.usage = event.run_usage
        elif isinstance(event, FinalAnswer):
            self.answer = event.content
            self.steps_used = event.step
        elif isinstance(event, RunFailed):
            self.error = event.reason


__all__ = ["RunOutcome", "ToolCallRecord"]
