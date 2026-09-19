"""Events the orchestrator emits around a specialist agent's run.

These sit one level above `agent_runtime.agent.events`: those describe
what happened *inside* an agent, these describe which agent was chosen
and how it finished. A client can therefore show routing — "the email
agent took this" — without inspecting the loop's internals, and a future
multi-agent run is just more of these pairs in the same stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from agent_runtime.usage import TokenUsage

RoutedBy = Literal["explicit", "only-agent", "model", "fallback"]


@dataclass(slots=True)
class AgentSelected:
    """The orchestrator picked an agent to handle this turn."""

    run_id: str
    agent: str
    label: str
    reason: str
    routed_by: RoutedBy
    available: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentCompleted:
    """An agent finished its turn, successfully or not."""

    run_id: str
    agent: str
    status: Literal["completed", "failed"]
    steps_used: int
    usage: TokenUsage = field(default_factory=TokenUsage)


OrchestratorEvent = AgentSelected | AgentCompleted


__all__ = ["AgentCompleted", "AgentSelected", "OrchestratorEvent", "RoutedBy"]
