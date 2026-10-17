"""FastAPI dependency wiring.

Everything long-lived (settings, the workspace, the tool registry, the
session store) is built once in `create_app` and stashed on `app.state`;
these dependencies just fetch it back out per request. The `AgentLoop`
itself is cheap, so it is built fresh per call — which is what lets each
request pick its own model.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, Query, Request, status

from agent_runtime.auth import EVERYONE, Principal
from agent_runtime.config import Settings
from agent_runtime.files.directories import DirectoryPolicy, DirectorySelectionDisabled
from agent_runtime.files.workspace import Workspace, WorkspaceError
from agent_runtime.mcp_client import McpManager
from agent_runtime.runtime import AgentFactory
from agent_runtime.sessions import ConversationStore
from agent_runtime.storage import DatabaseStore
from agent_runtime.storage.users import UserStore
from agent_runtime.tools.registry import ToolRegistry


def get_settings(request: Request) -> Settings:
    """Return the settings the app was built with."""
    return request.app.state.settings  # type: ignore[no-any-return]


def get_workspace(request: Request) -> Workspace:
    """Return the agent's workspace."""
    return request.app.state.workspace  # type: ignore[no-any-return]


def get_directory_policy(request: Request) -> DirectoryPolicy:
    """Return the rules for which directories a client may choose."""
    return request.app.state.directories  # type: ignore[no-any-return]


def get_request_workspace(
    workspace: str | None = Query(
        default=None,
        description="Absolute directory to work in instead of the server's workspace.",
    ),
    policy: DirectoryPolicy = Depends(get_directory_policy),
) -> Workspace:
    """Return the workspace a request named in `?workspace=`, or the default one."""
    return workspace_or_http_error(policy, workspace)


def workspace_or_http_error(policy: DirectoryPolicy, requested: str | None) -> Workspace:
    """`policy.workspace_for(requested)`, with refusals turned into 400/403."""
    try:
        return policy.workspace_for(requested)
    except DirectorySelectionDisabled as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except WorkspaceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def get_tools(request: Request) -> ToolRegistry:
    """Return the tool registry shared by every run."""
    return request.app.state.tools  # type: ignore[no-any-return]


def get_session_store(request: Request) -> ConversationStore:
    """Return the conversation store."""
    return request.app.state.sessions  # type: ignore[no-any-return]


def get_history_store(store: ConversationStore = Depends(get_session_store)) -> DatabaseStore:
    """Return the database store, or 501 when sessions only live in memory."""
    if not isinstance(store, DatabaseStore):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Session history needs a database; set DATABASE_URL on the server.",
        )
    return store


def get_mcp(request: Request) -> McpManager | None:
    """Return the MCP connection manager; None when MCP_ENABLED is off."""
    return request.app.state.mcp  # type: ignore[no-any-return]


def get_all_tools(
    tools: ToolRegistry = Depends(get_tools), mcp: McpManager | None = Depends(get_mcp)
) -> ToolRegistry:
    """The built-in tools plus those of every connected MCP server."""
    return ToolRegistry([*tools, *mcp.tools()]) if mcp is not None else tools


def get_agent_factory(
    settings: Settings = Depends(get_settings),
    tools: ToolRegistry = Depends(get_tools),
    mcp: McpManager | None = Depends(get_mcp),
) -> AgentFactory:
    """Return a factory for this request's agent loop (tests override this)."""
    return AgentFactory(settings=settings, tools=tools, mcp=mcp)


def get_user_store(
    settings: Settings = Depends(get_settings),
    store: ConversationStore = Depends(get_session_store),
) -> UserStore | None:
    """The account store when sign-in is on (a database, and `AUTH_ENABLED`)."""
    if settings.auth_enabled and isinstance(store, DatabaseStore):
        return store.users
    return None


def bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    """The token from `Authorization: Bearer <token>`, if one was sent."""
    if authorization and authorization[:7].lower() == "bearer ":
        return authorization[7:].strip() or None
    return None


async def require_api_key(
    settings: Settings = Depends(get_settings),
    users: UserStore | None = Depends(get_user_store),
    token: str | None = Depends(bearer_token),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    """Who is calling, or 401.

    A signed-in user's token gives access to their own sessions; the
    server's `API_KEY` gives access to everything. With neither sign-in nor
    `API_KEY` configured the server is open (local development).
    """
    if users is not None and token is not None:
        user = await users.user_for_token(token)
        if user is not None:
            return Principal(user_id=user.id, username=user.username, is_admin=user.is_admin)
    if settings.api_key is not None:
        expected = settings.api_key.get_secret_value().encode()
        if x_api_key is not None and secrets.compare_digest(x_api_key.encode(), expected):
            return EVERYONE
    elif users is None:
        return EVERYONE
    detail = "Sign in to continue." if users is not None else "Invalid or missing API key"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
