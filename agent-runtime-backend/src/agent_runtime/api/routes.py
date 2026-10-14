"""HTTP and SSE endpoints exposing the agent loop."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from agent_runtime.agent.events import FinalAnswer, RunFailed
from agent_runtime.agent.loop import AgentLoop
from agent_runtime.agent.messages import Message
from agent_runtime.agent.openai import ModelConfigurationError
from agent_runtime.agent.outcome import RunOutcome
from agent_runtime.api.deps import (
    get_agent_factory,
    get_session_store,
    get_settings,
    get_tools,
    get_workspace,
    require_api_key,
)
from agent_runtime.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    ModelsResponse,
    ModelView,
    ToolsResponse,
    ToolView,
    WorkspaceStatus,
)
from agent_runtime.config import Settings
from agent_runtime.files.workspace import Workspace
from agent_runtime.models import (
    UnknownModelError,
    available_models,
    pricing_for,
    resolve_model_id,
)
from agent_runtime.runtime import AgentFactory
from agent_runtime.sessions import SessionStore
from agent_runtime.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass(frozen=True, slots=True)
class _Turn:
    """Everything one chat request runs with, prepared before any model call."""

    agent: AgentLoop
    model_id: str
    session_id: str
    run_id: str
    history_len: int
    transcript: list[Message]


async def _start_turn(
    body: ChatRequest, build_agent: AgentFactory, sessions: SessionStore, settings: Settings
) -> _Turn:
    """Validate the request and load its session, failing fast before any spend.

    Raises:
        HTTPException: 400 for a model outside the catalog, 503 when the
            server has no model credentials.
    """
    try:
        model_id = resolve_model_id(body.model, settings.openai_model)
        agent = build_agent(model_id)
    except UnknownModelError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ModelConfigurationError as exc:
        logger.error("model is not configured: %s", exc)
        detail = "The model provider is not configured." if settings.is_prod else str(exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc

    session_id = body.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    history = await sessions.get_history(session_id)
    return _Turn(
        agent=agent,
        model_id=model_id,
        session_id=session_id,
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        history_len=len(history),
        transcript=history,  # Already a copy; the loop extends it in place.
    )


@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health(
    settings: Settings = Depends(get_settings),
    tools: ToolRegistry = Depends(get_tools),
    workspace: Workspace = Depends(get_workspace),
) -> HealthResponse:
    """Report liveness and how this server is configured (no secrets)."""
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
        model=settings.openai_model,
        tools=tools.names(),
        workspace=WorkspaceStatus(
            read_only=settings.workspace_read_only,
            path=None if settings.is_prod else str(workspace.root),
        ),
    )


@router.get("/v1/models", response_model=ModelsResponse, tags=["meta"])
async def models(settings: Settings = Depends(get_settings)) -> ModelsResponse:
    """List the models a caller may select, with the prices used to cost runs."""
    overrides = settings.pricing_overrides
    views = []
    for info in available_models():
        pricing = pricing_for(info.id, overrides) or info.pricing
        views.append(ModelView.from_info(info, pricing.input_usd_per_1m, pricing.output_usd_per_1m))
    return ModelsResponse(default=settings.openai_model, models=views)


@router.get("/v1/tools", response_model=ToolsResponse, tags=["meta"])
async def list_tools(tools: ToolRegistry = Depends(get_tools)) -> ToolsResponse:
    """List every tool the agent can call, with the JSON schema the model sees."""
    return ToolsResponse(tools=[ToolView.from_tool(tool) for tool in tools])


@router.post(
    "/v1/chat",
    response_model=ChatResponse,
    tags=["agent"],
    dependencies=[Depends(require_api_key)],
)
async def chat(
    body: ChatRequest,
    build_agent: AgentFactory = Depends(get_agent_factory),
    sessions: SessionStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """Run the agent to completion and return its answer.

    Use `/v1/chat/stream` instead to observe each step as it happens
    (model tokens, tool calls, tool results) rather than waiting for the
    whole run.
    """
    turn = await _start_turn(body, build_agent, sessions, settings)
    outcome = RunOutcome()
    async for event in turn.agent.run(body.message, turn.transcript, run_id=turn.run_id):
        outcome.observe(event)
    await sessions.append(turn.session_id, turn.transcript[turn.history_len :])

    if not outcome.succeeded:
        logger.warning("run failed", extra={"run_id": turn.run_id, "reason": outcome.error})
    return ChatResponse.from_outcome(
        outcome,
        run_id=turn.run_id,
        session_id=turn.session_id,
        model=turn.model_id,
        hide_error_detail=settings.is_prod,
    )


@router.post("/v1/chat/stream", tags=["agent"], dependencies=[Depends(require_api_key)])
async def chat_stream(
    body: ChatRequest,
    build_agent: AgentFactory = Depends(get_agent_factory),
    sessions: SessionStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings),
) -> EventSourceResponse:
    """Stream every agent-loop event as Server-Sent Events.

    Event names: `run_started`, `step_started`, `model_token`,
    `tool_call_requested`, `tool_call_result`, `usage_updated`, and finally
    `final_answer` or `run_failed`, after which the stream ends.
    """
    turn = await _start_turn(body, build_agent, sessions, settings)

    async def event_source() -> AsyncIterator[dict[str, str]]:
        finished = False
        try:
            async for event in turn.agent.run(body.message, turn.transcript, run_id=turn.run_id):
                payload = asdict(event)
                payload["session_id"] = turn.session_id
                payload["model"] = payload.get("model") or turn.model_id
                yield {"event": _event_name(event), "data": json.dumps(payload)}
                finished = isinstance(event, FinalAnswer | RunFailed)
        finally:
            # A client that disconnects mid-run can cut a turn off between a
            # tool request and its result, and the model rejects a transcript
            # like that on every later message. Only whole turns are kept.
            if finished:
                await sessions.append(turn.session_id, turn.transcript[turn.history_len :])

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
