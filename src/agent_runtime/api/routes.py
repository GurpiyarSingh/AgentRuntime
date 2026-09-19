"""HTTP and SSE endpoints exposing the orchestrator and its agents."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from agent_runtime.agent.events import (
    FinalAnswer,
    RunFailed,
    ToolCallRequested,
    ToolCallResult,
    UsageUpdated,
)
from agent_runtime.agents.registry import AgentRegistry, UnknownAgentError
from agent_runtime.api.deps import (
    OrchestratorFactory,
    get_agents,
    get_orchestrator,
    get_session_store,
    get_settings,
    require_api_key,
)
from agent_runtime.api.schemas import (
    AgentsResponse,
    AgentView,
    ChatRequest,
    ChatResponse,
    EmailStatus,
    HealthResponse,
    ModelsResponse,
    ModelView,
    ToolCallView,
    UsageView,
    YouTubeStatus,
)
from agent_runtime.config import Settings
from agent_runtime.models import (
    UnknownModelError,
    available_models,
    pricing_for,
    resolve_model_id,
)
from agent_runtime.orchestrator.events import AgentCompleted, AgentSelected
from agent_runtime.sessions import SessionStore
from agent_runtime.usage import TokenUsage

logger = logging.getLogger(__name__)

router = APIRouter()


def _email_status(settings: Settings) -> EmailStatus:
    return EmailStatus(
        dry_run=not settings.can_send_email,
        sender=settings.email_from or None,
        max_recipients=settings.email_max_recipients,
        allowed_domains=sorted(settings.allowed_email_domains),
    )


def _youtube_status(settings: Settings) -> YouTubeStatus:
    return YouTubeStatus(
        configured=settings.can_search_youtube, max_results=settings.youtube_max_results
    )


def _resolve_model(settings: Settings, requested: str | None) -> str:
    """Validate the caller's model choice, or reject the request with a 400."""
    try:
        return resolve_model_id(requested, settings.openai_model)
    except UnknownModelError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _check_agent(agents: AgentRegistry, requested: str | None) -> None:
    """Reject an unknown agent name before any model call is made."""
    if requested is None:
        return
    try:
        agents.get(requested)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health(
    settings: Settings = Depends(get_settings), agents: AgentRegistry = Depends(get_agents)
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
        model=settings.openai_model,
        agents=agents.names(),
        email=_email_status(settings),
        youtube=_youtube_status(settings),
    )


@router.get("/v1/models", response_model=ModelsResponse, tags=["meta"])
async def models(settings: Settings = Depends(get_settings)) -> ModelsResponse:
    """The models a caller may select, and the prices used to cost their runs.

    This is what the UI's model dropdown is built from, so the choices on
    screen can never include something the server would reject.
    """
    overrides = settings.pricing_overrides
    views = []
    for info in available_models():
        pricing = pricing_for(info.id, overrides) or info.pricing
        views.append(ModelView.from_info(info, pricing.input_usd_per_1m, pricing.output_usd_per_1m))
    return ModelsResponse(default=settings.openai_model, models=views)


@router.get("/v1/agents", response_model=AgentsResponse, tags=["meta"])
async def list_agents(agents: AgentRegistry = Depends(get_agents)) -> AgentsResponse:
    """Every specialist the orchestrator can route to, with its tools.

    The UI agent picker is built from this, and it is also the honest
    answer to what this runtime can actually do right now.
    """
    return AgentsResponse(
        default=agents.default.name,
        agents=[AgentView.from_spec(spec) for spec in agents.specs()],
    )


@router.post(
    "/v1/chat",
    response_model=ChatResponse,
    tags=["agent"],
    dependencies=[Depends(require_api_key)],
)
async def chat(
    body: ChatRequest,
    build_orchestrator: OrchestratorFactory = Depends(get_orchestrator),
    sessions: SessionStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings),
    agents: AgentRegistry = Depends(get_agents),
) -> ChatResponse:
    """Route the request to an agent, run it to completion, return the answer.

    Use `/v1/chat/stream` instead to observe each step as it happens
    (routing, model tokens, tool calls, tool results) rather than waiting
    for the whole run.
    """
    _check_agent(agents, body.agent)
    model_id = _resolve_model(settings, body.model)
    orchestrator = build_orchestrator(model_id)

    session_id = body.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    history = await sessions.get_history(session_id)

    transcript = list(history)
    pending_args: dict[str, dict[str, Any]] = {}
    tool_calls: list[ToolCallView] = []
    selected = agents.default.name
    steps_used = 0
    answer = ""
    usage = TokenUsage()
    failure: str | None = None

    async for event in orchestrator.run(
        body.message, agent=body.agent, run_id=run_id, transcript=transcript
    ):
        if isinstance(event, AgentSelected):
            selected = event.agent
        elif isinstance(event, ToolCallRequested):
            pending_args[event.call_id] = event.arguments
        elif isinstance(event, ToolCallResult):
            tool_calls.append(
                ToolCallView(
                    call_id=event.call_id,
                    tool_name=event.tool_name,
                    arguments=pending_args.pop(event.call_id, {}),
                    content=event.content,
                    is_error=event.is_error,
                    duration_s=event.duration_s,
                )
            )
        elif isinstance(event, UsageUpdated):
            usage = event.run_usage
        elif isinstance(event, FinalAnswer):
            answer = event.content
        elif isinstance(event, RunFailed):
            failure = event.reason
        elif isinstance(event, AgentCompleted):
            steps_used = event.steps_used

    await sessions.append(session_id, transcript[len(history) :])

    if failure is not None:
        # Don't hand provider internals (model names, quota details, stack
        # context) to callers in production.
        logger.warning("run failed", extra={"run_id": run_id, "reason": failure})
        detail = failure if not settings.is_prod else "The agent run did not complete."
        return ChatResponse(
            run_id=run_id,
            session_id=session_id,
            status="failed",
            answer="",
            agent=selected,
            model=model_id,
            steps_used=steps_used,
            # A failed run still burned tokens; report them rather than
            # letting the caller think it was free.
            usage=UsageView.from_usage(usage),
            tool_calls=tool_calls,
            error=detail,
        )

    return ChatResponse(
        run_id=run_id,
        session_id=session_id,
        status="completed",
        answer=answer,
        agent=selected,
        model=model_id,
        steps_used=steps_used,
        usage=UsageView.from_usage(usage),
        tool_calls=tool_calls,
    )


@router.post("/v1/chat/stream", tags=["agent"], dependencies=[Depends(require_api_key)])
async def chat_stream(
    body: ChatRequest,
    build_orchestrator: OrchestratorFactory = Depends(get_orchestrator),
    sessions: SessionStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings),
    agents: AgentRegistry = Depends(get_agents),
) -> EventSourceResponse:
    """Stream every routing and agent-loop event as Server-Sent Events.

    Event names: `agent_selected`, `run_started`, `step_started`,
    `model_token`, `tool_call_requested`, `tool_call_result`,
    `usage_updated`, `final_answer` / `run_failed`, `agent_completed`.
    The stream ends after `agent_completed`.
    """
    _check_agent(agents, body.agent)
    model_id = _resolve_model(settings, body.model)
    orchestrator = build_orchestrator(model_id)

    session_id = body.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    history = await sessions.get_history(session_id)
    transcript = list(history)

    async def event_source() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in orchestrator.run(
                body.message, agent=body.agent, run_id=run_id, transcript=transcript
            ):
                name = _event_name(event)
                payload = asdict(event)
                payload["session_id"] = session_id
                payload["model"] = payload.get("model") or model_id
                yield {"event": name, "data": json.dumps(payload)}
        finally:
            await sessions.append(session_id, transcript[len(history) :])

    return EventSourceResponse(event_source())


def _event_name(event: object) -> str:
    """CamelCase event class name -> snake_case SSE event name."""
    name = type(event).__name__
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


__all__ = ["router"]
