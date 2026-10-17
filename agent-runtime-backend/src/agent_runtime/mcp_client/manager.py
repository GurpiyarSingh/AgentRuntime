"""Keeps every enabled MCP server connected, and hands their tools to the agent.

Each enabled server gets a background task that opens the connection,
publishes the server's tools, then waits until it is told to stop. The
transports hold anyio task groups, so a connection must be opened and
closed in the same task; that task is its owner. Tool calls from requests
go through the live session, which supports concurrent requests.

Connecting never blocks startup or a request: a slow server shows as
`connecting`, a broken one as `error` with a readable reason (including
what the server printed), and the agent simply sees the tools of the
servers that are `connected`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import IO, Any, Literal, TextIO, cast

import anyio
import mcp.types as types

from agent_runtime.mcp_client.client import Connection, McpTool, connect, describe_failure
from agent_runtime.mcp_client.config import McpConfigError, McpConfigStore, McpServerConfig
from agent_runtime.tools.base import ToolError

logger = logging.getLogger(__name__)

Status = Literal["disabled", "connecting", "connected", "error"]

_STOP_GRACE_S = 10.0


@dataclass(slots=True)
class ServerState:
    """One configured server and how its connection is doing."""

    name: str
    config: McpServerConfig
    status: Status = "disabled"
    error: str | None = None
    connection: Connection | None = None
    connected_at: datetime | None = None
    task: asyncio.Task[None] | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    settled: asyncio.Event = field(default_factory=asyncio.Event)
    """Set once the connection attempt has succeeded or failed."""

    @property
    def tools(self) -> list[types.Tool]:
        """The server's tools while connected; none otherwise."""
        return self.connection.tools if self.connection and self.status == "connected" else []


@dataclass(frozen=True, slots=True)
class TestResult:
    """What a trial connection found."""

    ok: bool
    duration_s: float
    error: str | None = None
    server_name: str | None = None
    server_version: str | None = None
    tools: list[types.Tool] = field(default_factory=list)


def _tail(errlog: IO[str]) -> str:
    """What a stdio server printed to stderr, if anything."""
    with contextlib.suppress(OSError, ValueError):
        errlog.flush()
        errlog.seek(0)
        return errlog.read()
    return ""


class McpManager:
    """The live connections to every configured MCP server."""

    def __init__(
        self,
        store: McpConfigStore,
        *,
        allow_stdio: bool = True,
        tool_timeout_s: float = 60.0,
        max_chars: int = 40_000,
    ) -> None:
        """Manage the servers in `store`.

        Args:
            store: Where the configurations live.
            allow_stdio: Whether local (stdio) servers may be started at all.
            tool_timeout_s: Longest wait for one remote tool call.
            max_chars: Most characters of a tool result handed to the model.
        """
        self.store = store
        self.allow_stdio = allow_stdio
        self._tool_timeout = timedelta(seconds=tool_timeout_s)
        self._max_chars = max_chars
        self._states: dict[str, ServerState] = {}
        self._lock = asyncio.Lock()

    # --- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        """Begin connecting every enabled server (returns without waiting)."""
        try:
            configs = self.store.load()
        except McpConfigError as exc:
            logger.error("can't read the MCP config file: %s", exc)
            return
        async with self._lock:
            for name, config in configs.items():
                self._states[name] = self._launch(name, config)

    async def close(self) -> None:
        """Disconnect every server."""
        async with self._lock:
            states = list(self._states.values())
            self._states.clear()
        await asyncio.gather(*(self._stop(state) for state in states))

    async def apply(self, name: str) -> ServerState | None:
        """Bring server `name` in line with its stored config (after any change)."""
        async with self._lock:
            previous = self._states.pop(name, None)
            if previous is not None:
                await self._stop(previous)
            config = self.store.get(name)
            if config is None:
                return None
            state = self._launch(name, config)
            self._states[name] = state
            return state

    async def wait_settled(self, name: str, timeout_s: float) -> ServerState | None:
        """Wait (up to `timeout_s`) for `name`'s connection attempt to finish."""
        state = self._states.get(name)
        if state is not None and state.status == "connecting":
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(state.settled.wait(), timeout_s)
        return self._states.get(name)

    def _launch(self, name: str, config: McpServerConfig) -> ServerState:
        state = ServerState(name=name, config=config)
        if not config.enabled:
            state.settled.set()
            return state
        state.status = "connecting"
        state.task = asyncio.create_task(self._run(state), name=f"mcp:{name}")
        return state

    async def _stop(self, state: ServerState) -> None:
        state.stop.set()
        if state.task is None or state.task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(state.task), _STOP_GRACE_S)
        except TimeoutError:
            state.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await state.task

    async def _run(self, state: ServerState) -> None:
        """Own one connection: open it, publish it, hold it until told to stop."""
        config = state.config
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as errlog:
            try:
                async with connect(
                    config, errlog=cast(TextIO, errlog), allow_stdio=self.allow_stdio
                ) as conn:
                    state.connection = conn
                    state.status = "connected"
                    state.error = None
                    state.connected_at = datetime.now(UTC)
                    state.settled.set()
                    logger.info(
                        "MCP server connected",
                        extra={"server": state.name, "tools": len(conn.tools)},
                    )
                    await state.stop.wait()
            except (Exception, BaseExceptionGroup) as exc:  # noqa: BLE001 - any failure becomes the status
                if not state.stop.is_set():
                    state.status = "error"
                    state.error = describe_failure(exc, config, _tail(errlog))
                    logger.warning(
                        "MCP server failed", extra={"server": state.name, "reason": state.error}
                    )
            finally:
                state.connection = None
                if state.stop.is_set():
                    state.status = "disabled" if not config.enabled else "connecting"
                state.settled.set()

    # --- what the rest of the runtime sees ------------------------------------

    def states(self) -> list[ServerState]:
        """Every configured server, by name, including disabled ones."""
        try:
            configs = self.store.load()
        except McpConfigError:
            configs = {}
        return [
            self._states.get(name) or ServerState(name=name, config=configs[name])
            for name in sorted(configs, key=str.lower)
        ]

    def state(self, name: str) -> ServerState | None:
        """One server's state, if it is configured."""
        return next((s for s in self.states() if s.name == name), None)

    def tools(self) -> list[McpTool]:
        """The tools of every connected server, ready for a `ToolRegistry`."""
        tools: list[McpTool] = []
        seen: set[str] = set()
        for state in self.states():
            for tool in state.tools:
                adapted = McpTool(state.name, tool, self._caller(state), max_chars=self._max_chars)
                if adapted.name not in seen:  # Two tools that differ only in odd characters.
                    seen.add(adapted.name)
                    tools.append(adapted)
        return tools

    def _caller(self, state: ServerState) -> Any:
        async def call(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
            connection = state.connection
            if connection is None or state.status != "connected":
                raise ToolError(f"The {state.name} MCP server is not connected.")
            try:
                return await connection.session.call_tool(
                    name, arguments, read_timeout_seconds=self._tool_timeout
                )
            except (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream) as exc:
                # The server went away (a crashed process, a dropped connection).
                state.status = "error"
                state.error = "The connection was lost. Reconnect to try again."
                raise ToolError(f"The {state.name} MCP server disconnected.") from exc

        return call

    # --- trial connections ----------------------------------------------------

    async def test(self, config: McpServerConfig) -> TestResult:
        """Connect once to `config`, list its tools, and disconnect."""
        started = time.monotonic()
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as errlog:
            try:
                with anyio.fail_after(config.timeout_s + 5):
                    async with connect(
                        config, errlog=cast(TextIO, errlog), allow_stdio=self.allow_stdio
                    ) as conn:
                        return TestResult(
                            ok=True,
                            duration_s=time.monotonic() - started,
                            server_name=conn.server_name,
                            server_version=conn.server_version,
                            tools=conn.tools,
                        )
            except (Exception, BaseExceptionGroup) as exc:  # noqa: BLE001 - any failure becomes the status
                return TestResult(
                    ok=False,
                    duration_s=time.monotonic() - started,
                    error=describe_failure(exc, config, _tail(errlog)),
                )


__all__ = ["McpManager", "ServerState", "Status", "TestResult"]
