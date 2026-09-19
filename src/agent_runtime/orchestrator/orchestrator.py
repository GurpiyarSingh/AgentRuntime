"""The orchestrator: route a turn to an agent, run it, report how it went.

Today there is one specialist (email) and the orchestrator is a thin,
honest layer: pick an agent, build its loop, stream its events. That
thinness is the point — the seam for a second agent already exists, so
adding one means registering a spec rather than reworking the runtime.

The event stream stays flat on purpose:

    AgentSelected -> (the agent's own RunStarted..FinalAnswer) -> AgentCompleted

so a multi-agent turn later is simply more of these blocks back to back,
and no client has to learn a new shape to read it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from agent_runtime.agent.events import AgentEvent, FinalAnswer, RunFailed, StepStarted, UsageUpdated
from agent_runtime.agent.loop import AgentLoop
from agent_runtime.agent.messages import Message
from agent_runtime.agent.openai import OpenAIModel
from agent_runtime.agent.protocols import ChatModel
from agent_runtime.agents.base import AgentSpec
from agent_runtime.agents.registry import AgentRegistry
from agent_runtime.config import Settings
from agent_runtime.orchestrator.events import AgentCompleted, AgentSelected, OrchestratorEvent
from agent_runtime.orchestrator.router import AgentRouter
from agent_runtime.usage import TokenUsage

logger = logging.getLogger(__name__)

RuntimeEvent = AgentEvent | OrchestratorEvent
ModelFactory = Callable[[AgentSpec], ChatModel]


@dataclass(slots=True)
class OrchestratedResult:
    """The outcome of one orchestrated turn."""

    run_id: str
    agent: str
    model: str
    status: str
    answer: str
    steps_used: int
    usage: TokenUsage = field(default_factory=TokenUsage)
    error: str | None = None
    messages: list[Message] = field(default_factory=list)


class Orchestrator:
    """Routes a request to a specialist agent and runs it."""

    def __init__(
        self,
        settings: Settings,
        agents: AgentRegistry,
        model_id: str | None = None,
        router: AgentRouter | None = None,
        model_factory: ModelFactory | None = None,
        routing_model: ChatModel | None = None,
    ) -> None:
        self._settings = settings
        self._agents = agents
        self._model_id = model_id
        self._model_factory = model_factory or self._default_model_factory
        self._router = router or AgentRouter(
            agents, model=routing_model, model_provider=self._routing_model
        )

    # -- construction helpers -------------------------------------------------

    def _default_model_factory(self, spec: AgentSpec) -> ChatModel:
        return OpenAIModel(self._settings, spec.tools, model_id=spec.model_id or self._model_id)

    def _routing_model(self) -> ChatModel | None:
        """A tool-free model for routing.

        Called lazily by the router, and only when there is a genuine
        choice to make — with one agent registered, or an agent named
        explicitly, no model is ever constructed.
        """
        if len(self._agents) < 2:
            return None
        return OpenAIModel(self._settings, tools=None, model_id=self._model_id)

    def loop_for(self, spec: AgentSpec) -> AgentLoop:
        """The `AgentLoop` that runs one agent, with its prompt and its tools."""
        return AgentLoop(
            settings=self._settings,
            tools=spec.tools,
            model=self._model_factory(spec),
            system_prompt=spec.system_prompt,
        )

    # -- running --------------------------------------------------------------

    async def run(
        self,
        user_input: str,
        agent: str | None = None,
        run_id: str | None = None,
        transcript: list[Message] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Route, then run, yielding every event from both layers.

        An unknown explicit `agent` raises `UnknownAgentError` before any
        model call happens, so a bad name costs nothing.
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        decision = await self._router.route(user_input, requested=agent)
        spec = decision.agent

        yield AgentSelected(
            run_id=run_id,
            agent=spec.name,
            label=spec.label,
            reason=decision.reason,
            routed_by=decision.routed_by,
            available=self._agents.names(),
        )

        loop = self.loop_for(spec)
        steps_used = 0
        usage = TokenUsage()
        status = "failed"

        async for event in loop.run(user_input, run_id=run_id, transcript=transcript):
            if isinstance(event, StepStarted):
                steps_used = event.step
            elif isinstance(event, UsageUpdated):
                usage = event.run_usage
            elif isinstance(event, FinalAnswer):
                status = "completed"
                steps_used = event.step
            elif isinstance(event, RunFailed):
                status = "failed"
            yield event

        yield AgentCompleted(
            run_id=run_id,
            agent=spec.name,
            status="completed" if status == "completed" else "failed",
            steps_used=steps_used,
            usage=usage,
        )

    async def run_to_completion(
        self,
        user_input: str,
        agent: str | None = None,
        run_id: str | None = None,
        transcript: list[Message] | None = None,
    ) -> OrchestratedResult:
        """Drain the stream and return just the outcome."""
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        messages: list[Message] = transcript if transcript is not None else []
        selected = self._agents.default.name
        answer = ""
        error: str | None = None
        steps_used = 0
        usage = TokenUsage()
        status = "failed"
        model = ""

        async for event in self.run(user_input, agent=agent, run_id=run_id, transcript=messages):
            if isinstance(event, AgentSelected):
                selected = event.agent
            elif isinstance(event, UsageUpdated):
                usage = event.run_usage
                model = event.model
            elif isinstance(event, FinalAnswer):
                answer = event.content
            elif isinstance(event, RunFailed):
                error = event.reason
            elif isinstance(event, AgentCompleted):
                status = event.status
                steps_used = event.steps_used

        return OrchestratedResult(
            run_id=run_id,
            agent=selected,
            model=model,
            status=status,
            answer=answer,
            steps_used=steps_used,
            usage=usage,
            error=error,
            messages=messages,
        )


__all__ = ["ModelFactory", "OrchestratedResult", "Orchestrator", "RuntimeEvent"]
