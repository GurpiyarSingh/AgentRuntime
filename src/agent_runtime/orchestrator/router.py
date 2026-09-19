"""Choosing which agent handles a turn.

Routing is deliberately cheap. An explicit choice from the caller wins
outright, and while only one agent is registered the router answers
without calling a model at all — you do not pay for a classification
whose answer is already known. The model is consulted only once there is
a genuine choice to make, which is the point at which a second agent
starts earning its keep.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from agent_runtime.agent.messages import Message, SystemMessage, UserMessage
from agent_runtime.agent.protocols import ChatModel
from agent_runtime.agents.base import AgentSpec
from agent_runtime.agents.registry import AgentRegistry
from agent_runtime.orchestrator.events import RoutedBy

logger = logging.getLogger(__name__)

ROUTER_PROMPT = (
    "You route a user's request to exactly one specialist agent.\n"
    "Reply with the agent's name and nothing else — no punctuation, no explanation.\n"
    "If more than one could fit, choose the one whose description matches the "
    "user's end goal. If none clearly fit, reply with the first agent listed."
)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Which agent runs, and why — carried through to the event stream."""

    agent: AgentSpec
    reason: str
    routed_by: RoutedBy


class AgentRouter:
    """Picks an `AgentSpec` for a request.

    The routing model is supplied as a provider rather than an instance so
    that nothing is constructed for requests that never need routing — an
    explicit agent, or a runtime with only one registered.
    """

    def __init__(
        self,
        agents: AgentRegistry,
        model: ChatModel | None = None,
        model_provider: Callable[[], ChatModel | None] | None = None,
    ) -> None:
        self._agents = agents
        self._model = model
        self._model_provider = model_provider
        self._resolved = model is not None

    def _routing_model(self) -> ChatModel | None:
        """The model used to choose an agent, built at most once, on demand."""
        if not self._resolved:
            self._model = self._model_provider() if self._model_provider else None
            self._resolved = True
        return self._model

    async def route(self, user_input: str, requested: str | None = None) -> RoutingDecision:
        """Choose an agent. Raises `UnknownAgentError` for a bad explicit name."""
        if requested:
            agent = self._agents.get(requested)
            return RoutingDecision(
                agent=agent, reason="Requested by the caller.", routed_by="explicit"
            )

        if len(self._agents) == 1:
            agent = self._agents.default
            return RoutingDecision(
                agent=agent,
                reason="Only one agent is registered, so no routing call was needed.",
                routed_by="only-agent",
            )

        model = self._routing_model()
        if model is None:
            agent = self._agents.default
            return RoutingDecision(
                agent=agent,
                reason="No routing model is configured; used the default agent.",
                routed_by="fallback",
            )

        return await self._route_with_model(model, user_input)

    async def _route_with_model(self, model: ChatModel, user_input: str) -> RoutingDecision:
        catalog = "\n".join(spec.routing_line() for spec in self._agents.specs())
        messages: list[Message] = [
            SystemMessage(content=f"{ROUTER_PROMPT}\n\nAgents:\n{catalog}"),
            UserMessage(content=user_input),
        ]
        try:
            answer = await model.invoke(messages)
        except Exception as exc:
            logger.warning("router model call failed; using default agent: %s", exc)
            return RoutingDecision(
                agent=self._agents.default,
                reason=f"Routing call failed ({type(exc).__name__}); used the default agent.",
                routed_by="fallback",
            )

        choice = answer.content.strip().strip(".").splitlines()[0].strip() if answer.content else ""
        if choice in self._agents:
            return RoutingDecision(
                agent=self._agents.get(choice),
                reason="Chosen by the routing model.",
                routed_by="model",
            )

        logger.warning("router returned unusable choice %r; using default agent", choice)
        return RoutingDecision(
            agent=self._agents.default,
            reason=f"Routing model answered {choice!r}, which is not an agent; used the default.",
            routed_by="fallback",
        )


__all__ = ["ROUTER_PROMPT", "AgentRouter", "RoutingDecision"]
