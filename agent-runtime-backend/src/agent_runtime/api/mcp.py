"""Managing MCP servers: add, edit, test, enable or disable, import, remove.

    GET    /v1/mcp/servers                   every server, its status and tools
    POST   /v1/mcp/servers                   add one
    PUT    /v1/mcp/servers/{name}            replace its config
    PATCH  /v1/mcp/servers/{name}            enable or disable it
    DELETE /v1/mcp/servers/{name}            remove it
    POST   /v1/mcp/servers/{name}/reconnect  drop and reopen its connection
    POST   /v1/mcp/test                      try a config without saving it
    POST   /v1/mcp/import                    add servers from Claude/VS Code JSON

Everyone who may use the API may look. Changing anything (or testing, which
starts the server) is for admins when sign-in is on: a local (stdio) server
runs a program on this machine.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from agent_runtime.api.deps import get_mcp, require_api_key
from agent_runtime.api.schemas import (
    McpImportRequest,
    McpImportResponse,
    McpServerCreate,
    McpServerPatch,
    McpServersResponse,
    McpServerView,
    McpTestRequest,
    McpTestView,
)
from agent_runtime.auth import Principal
from agent_runtime.mcp_client import McpConfigError, McpManager, McpServerConfig, parse_import

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])

# How long saving waits for the server to come up, so the answer usually
# shows "connected" or the error; slower servers report "connecting".
_SETTLE_S = 15.0


def _manager(mcp: McpManager | None = Depends(get_mcp)) -> McpManager:
    if mcp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP is turned off on this server (MCP_ENABLED=false).",
        )
    return mcp


def _can_manage(principal: Principal) -> bool:
    return principal.user_id is None or principal.is_admin


def _require_manager(principal: Principal = Depends(require_api_key)) -> Principal:
    if not _can_manage(principal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can change MCP servers.",
        )
    return principal


def _check_allowed(mcp: McpManager, config: McpServerConfig) -> None:
    if config.type == "stdio" and not mcp.allow_stdio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Local (stdio) MCP servers are turned off on this server; use http or sse.",
        )


async def _view(mcp: McpManager, name: str, *, wait: bool) -> McpServerView:
    state = await mcp.wait_settled(name, _SETTLE_S) if wait else mcp.state(name)
    state = state or mcp.state(name)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No server {name!r}")
    return McpServerView.from_state(state)


def _existing(mcp: McpManager, name: str) -> McpServerConfig:
    config = mcp.store.get(name)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No server {name!r}")
    return config


@router.get("/servers", response_model=McpServersResponse)
async def list_servers(
    mcp: McpManager = Depends(_manager), principal: Principal = Depends(require_api_key)
) -> McpServersResponse:
    """Every configured server, its connection status and its tools."""
    try:
        states = mcp.states()
    except McpConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return McpServersResponse(
        servers=[McpServerView.from_state(state) for state in states],
        can_manage=_can_manage(principal),
        allow_stdio=mcp.allow_stdio,
    )


@router.post("/servers", response_model=McpServerView, status_code=status.HTTP_201_CREATED)
async def create_server(
    body: McpServerCreate,
    mcp: McpManager = Depends(_manager),
    _: Principal = Depends(_require_manager),
) -> McpServerView:
    """Add a server and, if it is enabled, connect it."""
    if mcp.store.get(body.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"A server named {body.name!r} exists."
        )
    _check_allowed(mcp, body.config)
    await mcp.store.put(body.name, body.config)
    await mcp.apply(body.name)
    return await _view(mcp, body.name, wait=True)


@router.put("/servers/{name}", response_model=McpServerView)
async def update_server(
    name: str,
    config: McpServerConfig,
    mcp: McpManager = Depends(_manager),
    _: Principal = Depends(_require_manager),
) -> McpServerView:
    """Replace a server's config (masked secrets keep their stored values) and reconnect."""
    merged = config.merged_secrets(_existing(mcp, name))
    _check_allowed(mcp, merged)
    await mcp.store.put(name, merged)
    await mcp.apply(name)
    return await _view(mcp, name, wait=True)


@router.patch("/servers/{name}", response_model=McpServerView)
async def set_enabled(
    name: str,
    body: McpServerPatch,
    mcp: McpManager = Depends(_manager),
    _: Principal = Depends(_require_manager),
) -> McpServerView:
    """Enable (and connect) or disable (and disconnect) a server."""
    config = _existing(mcp, name)
    if body.enabled:
        _check_allowed(mcp, config)
    await mcp.store.put(name, config.model_copy(update={"enabled": body.enabled}))
    await mcp.apply(name)
    return await _view(mcp, name, wait=body.enabled)


@router.delete("/servers/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    name: str, mcp: McpManager = Depends(_manager), _: Principal = Depends(_require_manager)
) -> Response:
    """Disconnect and forget a server."""
    if not await mcp.store.delete(name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No server {name!r}")
    await mcp.apply(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/servers/{name}/reconnect", response_model=McpServerView)
async def reconnect_server(
    name: str, mcp: McpManager = Depends(_manager), _: Principal = Depends(_require_manager)
) -> McpServerView:
    """Drop the connection and open a fresh one (e.g. after the server restarted)."""
    _existing(mcp, name)
    await mcp.apply(name)
    return await _view(mcp, name, wait=True)


@router.post("/test", response_model=McpTestView)
async def try_server(
    body: McpTestRequest,
    mcp: McpManager = Depends(_manager),
    _: Principal = Depends(_require_manager),
) -> McpTestView:
    """Connect once with `config`, list its tools, and disconnect. Nothing is saved."""
    previous = mcp.store.get(body.name) if body.name else None
    config = body.config.merged_secrets(previous)
    _check_allowed(mcp, config)
    result = await mcp.test(config)
    return McpTestView.from_result(result, body.name or "server")


@router.post("/import", response_model=McpImportResponse)
async def import_servers(
    body: McpImportRequest,
    mcp: McpManager = Depends(_manager),
    _: Principal = Depends(_require_manager),
) -> McpImportResponse:
    """Add the servers in pasted JSON (`{"mcpServers": {...}}`) and connect them."""
    try:
        servers = parse_import(body.json_text)
    except McpConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    for config in servers.values():
        _check_allowed(mcp, config)

    added: list[str] = []
    replaced: list[str] = []
    skipped: list[str] = []
    for name, config in servers.items():
        exists = mcp.store.get(name) is not None
        if exists and not body.overwrite:
            skipped.append(name)
            continue
        await mcp.store.put(name, config)
        await mcp.apply(name)
        (replaced if exists else added).append(name)
    return McpImportResponse(added=added, replaced=replaced, skipped=skipped)


__all__ = ["router"]
