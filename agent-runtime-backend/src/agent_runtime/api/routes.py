"""HTTP and SSE endpoints exposing the agent loop."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from agent_runtime.agent.events import AgentEvent, FinalAnswer, RunFailed, event_name
from agent_runtime.agent.loop import AgentLoop
from agent_runtime.agent.messages import Message
from agent_runtime.agent.openai import ModelConfigurationError
from agent_runtime.agent.outcome import RunOutcome
from agent_runtime.api.deps import (
    get_agent_factory,
    get_directory_policy,
    get_session_store,
    get_settings,
    get_tools,
    get_workspace,
    require_api_key,
    workspace_or_http_error,
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
from agent_runtime.auth import Principal
from agent_runtime.config import Settings
from agent_runtime.files.directories import DirectoryPolicy
from agent_runtime.files.workspace import Workspace
from agent_runtime.models import (
    UnknownModelError,
    available_models,
    pricing_for,
    resolve_model_id,
)
from agent_runtime.runtime import AgentFactory
from agent_runtime.sessions import ConversationStore, RunContext, RunRecorder
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
    recorder: RunRecorder

    def payload(self, event: AgentEvent) -> dict[str, Any]:
        """An event as clients receive it: its fields plus session and model."""
        payload = asdict(event)
        payload["session_id"] = self.session_id
        payload["model"] = payload.get("model") or self.model_id
        return payload


async def _start_turn(
    body: ChatRequest,
    request: Request,
    build_agent: AgentFactory,
    sessions: ConversationStore,
    settings: Settings,
    directories: DirectoryPolicy,
    principal: Principal,
) -> _Turn:
    """Validate the request and load its session, failing fast before any spend.

    Raises:
        HTTPException: 400 for a model outside the catalog or a directory
            that can't be used, 403 when choosing a directory is disabled,
            503 when the server has no model credentials.
    """
    workspace = workspace_or_http_error(directories, body.workspace)
    try:
        model_id = resolve_model_id(body.model, settings.openai_model)
        # The shared tools already serve the default workspace.
        agent = build_agent(
            model_id, workspace=None if workspace is directories.default else workspace
        )
    except UnknownModelError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ModelConfigurationError as exc:
        logger.error("model is not configured: %s", exc)
        detail = "The model provider is not configured." if settings.is_prod else str(exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc

    session_id = body.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    if not await sessions.can_continue(session_id, principal):
        # Not "forbidden": whether someone else's session id exists is not ours to say.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such session.")
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    history = await sessions.get_history(session_id)
    recorder = await sessions.start_run(
        RunContext(
            session_id=session_id,
            run_id=run_id,
            user_message=body.message,
            model=model_id,
            workspace=str(workspace.root),
            client_host=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            user_id=principal.user_id,
        )
    )
    return _Turn(
        agent=agent,
        model_id=model_id,
        session_id=session_id,
        run_id=run_id,
        history_len=len(history),
        transcript=history,  # Already a copy; the loop extends it in place.
        recorder=recorder,
    )


@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health(
    settings: Settings = Depends(get_settings),
    tools: ToolRegistry = Depends(get_tools),
    workspace: Workspace = Depends(get_workspace),
    sessions: ConversationStore = Depends(get_session_store),
) -> HealthResponse:
    """Report liveness and how this server is configured (no secrets)."""
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
        model=settings.openai_model,
        tools=tools.names(),
        history=sessions.keeps_history,
        workspace=WorkspaceStatus(
            read_only=settings.workspace_read_only,
            path=None if settings.is_prod else str(workspace.root),
            selectable=settings.workspace_selectable,
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


@router.post("/v1/chat", response_model=ChatResponse, tags=["agent"])
async def chat(
    body: ChatRequest,
    request: Request,
    principal: Principal = Depends(require_api_key),
    build_agent: AgentFactory = Depends(get_agent_factory),
    sessions: ConversationStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings),
    directories: DirectoryPolicy = Depends(get_directory_policy),
) -> ChatResponse:
    """Run the agent to completion and return its answer.

    Use `/v1/chat/stream` instead to observe each step as it happens
    (model tokens, tool calls, tool results) rather than waiting for the
    whole run.
    """
    turn = await _start_turn(body, request, build_agent, sessions, settings, directories, principal)
    outcome = RunOutcome()
    try:
        async for event in turn.agent.run(body.message, turn.transcript, run_id=turn.run_id):
            outcome.observe(event)
            await turn.recorder.observe(event, turn.payload(event))
        await sessions.append(
            turn.session_id, turn.transcript[turn.history_len :], run_id=turn.run_id
        )
    finally:
        await asyncio.shield(turn.recorder.finish())

    if not outcome.succeeded:
        logger.warning("run failed", extra={"run_id": turn.run_id, "reason": outcome.error})
    return ChatResponse.from_outcome(
        outcome,
        run_id=turn.run_id,
        session_id=turn.session_id,
        model=turn.model_id,
        hide_error_detail=settings.is_prod,
    )


@router.post("/v1/chat/stream", tags=["agent"])
async def chat_stream(
    body: ChatRequest,
    request: Request,
    principal: Principal = Depends(require_api_key),
    build_agent: AgentFactory = Depends(get_agent_factory),
    sessions: ConversationStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings),
    directories: DirectoryPolicy = Depends(get_directory_policy),
) -> EventSourceResponse:
    """Stream every agent-loop event as Server-Sent Events.

    Event names: `run_started`, `step_started`, `model_token`,
    `tool_call_requested`, `tool_call_result`, `usage_updated`, and finally
    `final_answer` or `run_failed`, after which the stream ends.
    """
    turn = await _start_turn(body, request, build_agent, sessions, settings, directories, principal)

    async def save(finished: bool) -> None:
        # A client that disconnects mid-run can cut a turn off between a
        # tool request and its result, and the model rejects a transcript
        # like that on every later message. Only whole turns are kept; the
        # activity log still records how far the abandoned run got.
        if finished:
            await sessions.append(
                turn.session_id, turn.transcript[turn.history_len :], run_id=turn.run_id
            )
        await turn.recorder.finish()

    async def event_source() -> AsyncIterator[dict[str, str]]:
        finished = False
        try:
            async for event in turn.agent.run(body.message, turn.transcript, run_id=turn.run_id):
                payload = turn.payload(event)
                # Recorded (and the turn marked whole) before it is sent, so
                # a client that leaves on the last event loses nothing.
                await turn.recorder.observe(event, payload)
                finished = isinstance(event, FinalAnswer | RunFailed)
                yield {"event": event_name(event), "data": json.dumps(payload)}
        finally:
            # Shielded: on a disconnect this generator is being cancelled,
            # and the save must still complete.
            await asyncio.shield(save(finished))

    return EventSourceResponse(event_source())


__all__ = ["router"]
