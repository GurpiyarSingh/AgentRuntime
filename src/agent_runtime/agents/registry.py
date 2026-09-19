"""The set of agents this runtime knows how to run."""

from __future__ import annotations

from agent_runtime.agents.base import AgentSpec


class UnknownAgentError(ValueError):
    """Raised when something asks for an agent that isn't registered."""


class AgentRegistry:
    """Name -> `AgentSpec`, plus the default the router falls back to.

    Order matters: the first agent registered is the default, and the UI
    lists them in registration order.
    """

    def __init__(self, agents: list[AgentSpec] | None = None) -> None:
        self._agents: dict[str, AgentSpec] = {}
        for agent in agents or []:
            self.register(agent)

    def register(self, agent: AgentSpec) -> None:
        if agent.name in self._agents:
            raise ValueError(f"Agent {agent.name!r} is already registered")
        self._agents[agent.name] = agent

    def get(self, name: str) -> AgentSpec:
        try:
            return self._agents[name]
        except KeyError as exc:
            known = ", ".join(self._agents) or "none"
            raise UnknownAgentError(
                f"Unknown agent {name!r}. Registered agents: {known}."
            ) from exc

    @property
    def default(self) -> AgentSpec:
        if not self._agents:
            raise UnknownAgentError("No agents are registered.")
        return next(iter(self._agents.values()))

    def specs(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def names(self) -> list[str]:
        return list(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    def __len__(self) -> int:
        return len(self._agents)


__all__ = ["AgentRegistry", "UnknownAgentError"]
