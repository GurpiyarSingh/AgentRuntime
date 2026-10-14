"""FastAPI dependency wiring.

Everything long-lived (settings, the workspace, the tool registry, the
session store) is built once in `create_app` and stashed on `app.state`;
these dependencies just fetch it back out per request. The `AgentLoop`
itself is cheap, so it is built fresh per call — which is what lets each
request pick its own model.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, Request, status

from agent_runtime.config import Settings
from agent_runtime.files.workspace import Workspace
from agent_runtime.runtime import AgentFactory
from agent_runtime.sessions import SessionStore
from agent_runtime.tools.registry import ToolRegistry


def get_settings(request: Request) -> Settings:
    """Return the settings the app was built with."""
    return request.app.state.settings  # type: ignore[no-any-return]


def get_workspace(request: Request) -> Workspace:
    """Return the agent's workspace."""
    return request.app.state.workspace  # type: ignore[no-any-return]


def get_tools(request: Request) -> ToolRegistry:
    """Return the tool registry shared by every run."""
    return request.app.state.tools  # type: ignore[no-any-return]


def get_session_store(request: Request) -> SessionStore:
    """Return the conversation store."""
    return request.app.state.sessions  # type: ignore[no-any-return]


def get_agent_factory(
    settings: Settings = Depends(get_settings),
    tools: ToolRegistry = Depends(get_tools),
) -> AgentFactory:
    """Return a factory for this request's agent loop (tests override this)."""
    return AgentFactory(settings=settings, tools=tools)


async def require_api_key(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """No-op when `API_KEY` is unset (open, for local dev); enforced otherwise."""
    if settings.api_key is None:
        return
    expected = settings.api_key.get_secret_value().encode()
    if x_api_key is None or not secrets.compare_digest(x_api_key.encode(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key"
        )
