"""What a specialist agent *is*, independent of how it runs.

An `AgentSpec` is data: a name, what it's for, the instructions it works
under, and the tools it may call. The orchestrator turns a spec into a
running `AgentLoop`; the API turns the same spec into a directory entry
for the UI. Adding an agent to this runtime means adding one of these —
no changes to the loop, the routing, or the transport layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """One specialist agent's identity, instructions and capabilities."""

    name: str
    label: str
    description: str
    system_prompt: str
    tools: ToolRegistry
    # Whether this agent can actually do its job right now, and a short
    # note explaining any caveat. Set when the agent is built, because
    # that is where its dependencies (a transport, an API client) are
    # known. The UI shows this, so an unconfigured agent says so instead
    # of failing at the first tool call.
    ready: bool = True
    status: str = ""
    # When set, this agent always runs on a specific model regardless of
    # what the caller picked — useful later for a cheap triage agent next
    # to an expensive drafting one.
    model_id: str | None = None

    @property
    def tool_names(self) -> list[str]:
        return self.tools.names()

    def routing_line(self) -> str:
        """One line describing this agent, for the router's prompt."""
        return f"- {self.name}: {self.description}"


__all__ = ["AgentSpec"]
