"""Talking to one MCP server: connect over any transport, and expose its tools.

`connect` opens a session (stdio, streamable HTTP or SSE), initializes it and
lists the server's tools. `McpTool` adapts one of those tools to the
runtime's `Tool` contract, so the agent loop calls it like any built-in tool.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TextIO

import anyio
import httpx
import jsonschema
import mcp.types as types
from mcp import ClientSession, McpError
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, ConfigDict

from agent_runtime import __version__
from agent_runtime.agent.messages import ImageAttachment
from agent_runtime.mcp_client.config import McpConfigError, McpServerConfig
from agent_runtime.tools.base import Tool, ToolError, ToolOutput

# OpenAI function names: at most 64 of [A-Za-z0-9_-].
_MAX_NAME = 64
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_STDERR_TAIL = 1500

ToolCaller = Callable[[str, dict[str, Any]], Awaitable[types.CallToolResult]]


@dataclass(slots=True)
class Connection:
    """A live, initialized session and what the server said about itself."""

    session: ClientSession
    server_name: str | None
    server_version: str | None
    instructions: str | None
    tools: list[types.Tool]


@contextlib.asynccontextmanager
async def connect(
    config: McpServerConfig, *, errlog: TextIO, allow_stdio: bool = True
) -> AsyncIterator[Connection]:
    """Open, initialize and list the tools of the server `config` describes.

    Must be entered and exited in the same task (the transports hold anyio
    task groups). The server is shut down on exit.

    Raises:
        McpConfigError: A stdio server while those are not allowed.
        TimeoutError: The server didn't answer within `config.timeout_s`.
        Exception: Whatever the transport raised; see `describe_failure`.
    """
    async with contextlib.AsyncExitStack() as stack:
        if config.type == "stdio":
            if not allow_stdio:
                raise McpConfigError(
                    "Local (stdio) MCP servers are disabled on this server (MCP_ALLOW_STDIO=false)."
                )
            params = StdioServerParameters(
                command=config.command or "",
                args=config.args,
                env=config.env or None,  # The SDK adds a safe default PATH/HOME.
                cwd=config.cwd or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
        elif config.type == "http":
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(
                    config.url or "", headers=config.headers or None, timeout=config.timeout_s
                )
            )
        else:
            read, write = await stack.enter_async_context(
                sse_client(
                    config.url or "", headers=config.headers or None, timeout=config.timeout_s
                )
            )

        session = await stack.enter_async_context(
            ClientSession(
                read,
                write,
                client_info=types.Implementation(name="agent-runtime", version=__version__),
            )
        )
        with anyio.fail_after(config.timeout_s):
            init = await session.initialize()
            tools = await _list_all_tools(session)
        yield Connection(
            session=session,
            server_name=init.serverInfo.name,
            server_version=init.serverInfo.version,
            instructions=init.instructions,
            tools=tools,
        )


async def _list_all_tools(session: ClientSession) -> list[types.Tool]:
    """Every tool, following pagination cursors."""
    tools: list[types.Tool] = []
    cursor: str | None = None
    while True:
        page = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
        tools.extend(page.tools)
        cursor = page.nextCursor
        if not cursor:
            return tools


def _leaf(exc: BaseException) -> BaseException:
    """The first real error inside (possibly nested) exception groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def describe_failure(exc: BaseException, config: McpServerConfig, stderr: str = "") -> str:
    """A one-paragraph explanation of why connecting failed, for people."""
    leaf = _leaf(exc)
    if isinstance(leaf, McpConfigError):
        message = str(leaf)
    elif isinstance(leaf, TimeoutError):
        message = (
            f"The server didn't answer within {config.timeout_s:.0f}s. "
            "A first run may be downloading packages; try a longer timeout."
        )
    elif isinstance(leaf, FileNotFoundError | NotADirectoryError):
        message = (
            f"Couldn't start {config.command!r}: not found. "
            "Is it installed, and on the server's PATH?"
        )
    elif isinstance(leaf, httpx.HTTPStatusError):
        status = leaf.response.status_code
        hint = {
            401: " The server rejected the credentials: check the Authorization header.",
            403: " Access was refused: check the token's permissions.",
            404: " Nothing was found at that URL: check the path (often /mcp or /sse).",
        }.get(status, "")
        message = f"The server answered HTTP {status}.{hint}"
    elif isinstance(leaf, httpx.ConnectError | httpx.ConnectTimeout):
        message = f"Couldn't connect to {config.url}. Is the address right, and the server up?"
    elif isinstance(leaf, McpError):
        message = f"The server refused the session: {leaf.error.message}"
    else:
        detail = str(leaf) or type(leaf).__name__
        message = f"{type(leaf).__name__}: {detail}"
    tail = stderr.strip()[-_STDERR_TAIL:]
    return f"{message}\n\nServer output:\n{tail}" if tail else message


def qualified_name(server: str, tool: str) -> str:
    """`server__tool`, made safe and short enough for a function name."""
    raw = f"{server}__{tool}"
    clean = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    if len(clean) <= _MAX_NAME:
        return clean
    digest = hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:8]
    return f"{clean[: _MAX_NAME - 9]}_{digest}"


def _parameters(schema: dict[str, Any] | None) -> dict[str, Any]:
    """The tool's input schema, as a function-calling `parameters` object."""
    cleaned = {k: v for k, v in (schema or {}).items() if k != "$schema"}
    cleaned["type"] = "object"
    cleaned.setdefault("properties", {})
    return cleaned


class _AnyArguments(BaseModel):
    """Lets every argument through; `McpTool` validates against the server's schema."""

    model_config = ConfigDict(extra="allow")


class McpTool(Tool):
    """One tool of a connected MCP server, callable by the agent."""

    args_schema = _AnyArguments

    def __init__(
        self, server: str, tool: types.Tool, call: ToolCaller, *, max_chars: int = 40_000
    ) -> None:
        """Adapt `tool` from `server`; `call(name, arguments)` runs it remotely."""
        self.server = server
        self.remote_name = tool.name
        self.name = qualified_name(server, tool.name)
        summary = tool.description or tool.title or tool.name
        self.description = f"[{server}] {summary}"[:1024]
        self._parameters = _parameters(tool.inputSchema)
        self._call = call
        self._max_chars = max_chars
        try:
            validator_class = jsonschema.validators.validator_for(self._parameters)
            validator_class.check_schema(self._parameters)
            self._validator: jsonschema.protocols.Validator | None = validator_class(
                self._parameters
            )
        except jsonschema.SchemaError:
            self._validator = None  # A schema we can't check; the server will.

    def to_openai_schema(self) -> dict[str, Any]:
        """The server's own schema, unchanged in substance."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._parameters,
            },
        }

    async def run(self, **kwargs: Any) -> str | ToolOutput:
        """Validate the arguments, call the server, and turn its answer into an observation."""
        if self._validator is not None:
            problems = sorted(self._validator.iter_errors(kwargs), key=lambda e: list(e.path))
            if problems:
                where = "/".join(str(p) for p in problems[0].path) or "arguments"
                raise ToolError(f"Invalid arguments ({where}): {problems[0].message}")
        try:
            result = await self._call(self.remote_name, kwargs)
        except McpError as exc:
            raise ToolError(f"{self.server} error: {exc.error.message}") from exc
        output = result_to_output(result, label=self.server, max_chars=self._max_chars)
        if result.isError:
            raise ToolError(output.content or f"{self.server} reported an error.")
        return output


def result_to_output(
    result: types.CallToolResult, *, label: str, max_chars: int = 40_000
) -> ToolOutput:
    """An MCP tool result as text for the model, plus any images it should see."""
    parts: list[str] = []
    images: list[ImageAttachment] = []
    for item in result.content:
        if isinstance(item, types.TextContent):
            parts.append(item.text)
        elif isinstance(item, types.ImageContent):
            if item.mimeType in _IMAGE_TYPES and _is_base64(item.data):
                images.append(
                    ImageAttachment(
                        media_type=item.mimeType, data=item.data, label=f"{label} image"
                    )
                )
                parts.append(f"[image {len(images)} ({item.mimeType}) attached]")
            else:
                parts.append(f"[an image in {item.mimeType}, which can't be shown to the model]")
        elif isinstance(item, types.AudioContent):
            parts.append(f"[audio ({item.mimeType}) omitted]")
        elif isinstance(item, types.ResourceLink):
            parts.append(f"[resource] {item.name}: {item.uri}")
        elif isinstance(item, types.EmbeddedResource):
            resource = item.resource
            if isinstance(resource, types.TextResourceContents):
                parts.append(resource.text)
            else:
                parts.append(f"[binary resource {resource.uri} ({resource.mimeType or 'unknown'})]")
    if not parts and result.structuredContent is not None:
        parts.append(json.dumps(result.structuredContent, ensure_ascii=False, indent=2))
    text = "\n".join(parts).strip() or "(The tool returned no content.)"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated: {len(text) - max_chars} more characters]"
    return ToolOutput(content=text, images=images)


def _is_base64(data: str) -> bool:
    try:
        base64.b64decode(data, validate=True)
    except ValueError:
        return False
    return True


__all__ = [
    "Connection",
    "McpTool",
    "connect",
    "describe_failure",
    "qualified_name",
    "result_to_output",
]
