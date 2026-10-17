"""MCP server configurations: the model, JSON import, and the file they live in.

The file uses the format Claude Desktop, Cursor and VS Code use, so configs
can be pasted between them:

    {
      "mcpServers": {
        "playwright": {"command": "npx", "args": ["@playwright/mcp@latest"]},
        "github": {
          "type": "http",
          "url": "https://api.githubcopilot.com/mcp/",
          "headers": {"Authorization": "Bearer ghp_..."}
        }
      }
    }

plus two optional fields of ours per server: `enabled` and `timeout_s`.
Secret values (env vars, headers) are masked whenever a config leaves the
server; see `masked` and `McpServerConfig.merged_secrets`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Transport = Literal["stdio", "http", "sse"]

# Server names prefix their tools (`github__create_issue`), and OpenAI
# function names allow only [A-Za-z0-9_-], so names are held to that.
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$"
_NAME_RE = re.compile(NAME_PATTERN)

MASK = "••••••••"
"""Stands in for a secret value in API responses; sent back, it means "unchanged"."""

# Aliases other clients use for the same transport.
_TRANSPORT_ALIASES: dict[str, Transport] = {
    "stdio": "stdio",
    "local": "stdio",
    "http": "http",
    "streamable-http": "http",
    "streamable_http": "http",
    "streamablehttp": "http",
    "sse": "sse",
}


class McpConfigError(ValueError):
    """A configuration that can't be used, with a message fit for the user."""


class McpServerConfig(BaseModel):
    """How to reach one MCP server."""

    model_config = ConfigDict(extra="ignore")

    type: Transport = Field(
        default="stdio",
        description="stdio: run a local program. http: streamable HTTP. sse: the older HTTP+SSE.",
    )
    # --- stdio ---
    command: str | None = Field(default=None, description="Program to run, e.g. npx, uvx, python.")
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict, description="Extra environment variables.")
    cwd: str | None = None
    # --- http / sse ---
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict, description="e.g. Authorization.")
    # --- ours ---
    enabled: bool = True
    timeout_s: float = Field(
        default=60.0, gt=0, le=600, description="Seconds to wait for the server to start."
    )
    description: str = Field(default="", max_length=500)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        """Accept the field names other clients use (`transport`, `serverUrl`, ...)."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        url = data.get("url") or data.get("serverUrl")
        if url:
            data["url"] = url
        kind = str(data.get("type") or data.get("transport") or "").strip().lower()
        if kind:
            if kind not in _TRANSPORT_ALIASES:
                raise ValueError(f"Unknown transport {kind!r}; use stdio, http or sse.")
            data["type"] = _TRANSPORT_ALIASES[kind]
        elif url and not data.get("command"):
            # A remote server without a stated transport: SSE if the URL says
            # so (a common convention), streamable HTTP otherwise.
            data["type"] = "sse" if str(url).rstrip("/").endswith("/sse") else "http"
        return data

    @model_validator(mode="after")
    def _complete(self) -> McpServerConfig:
        if self.type == "stdio":
            if not (self.command or "").strip():
                raise ValueError("A local (stdio) server needs a command, e.g. npx or uvx.")
        else:
            if not self.url or not re.match(r"^https?://", self.url, re.IGNORECASE):
                raise ValueError("A remote server needs an http:// or https:// URL.")
        return self

    def merged_secrets(self, previous: McpServerConfig | None) -> McpServerConfig:
        """This config, with any `MASK` value replaced by the previous secret.

        A client edits the masked view it was given; values it left masked
        mean "keep what was there".
        """
        if previous is None:
            return self
        return self.model_copy(
            update={
                "env": _unmask(self.env, previous.env),
                "headers": _unmask(self.headers, previous.headers),
            }
        )

    def masked(self) -> McpServerConfig:
        """A copy safe to send to clients: env and header values hidden."""
        return self.model_copy(
            update={
                "env": dict.fromkeys(self.env, MASK),
                "headers": dict.fromkeys(self.headers, MASK),
            }
        )

    def to_file(self) -> dict[str, Any]:
        """The compact form written to the config file (defaults left out)."""
        return self.model_dump(exclude_defaults=True) | {"type": self.type}


def _unmask(current: dict[str, str], previous: dict[str, str]) -> dict[str, str]:
    return {
        key: previous.get(key, "") if value == MASK else value for key, value in current.items()
    }


def validate_name(name: str) -> str:
    """`name`, or `McpConfigError` when it can't prefix tool names."""
    if not _NAME_RE.match(name):
        raise McpConfigError(
            f"Invalid server name {name!r}: use 1-32 letters, digits, _ or -, "
            "starting with a letter or digit."
        )
    return name


def parse_import(text: str) -> dict[str, McpServerConfig]:
    """Server configs from pasted JSON.

    Accepts `{"mcpServers": {...}}` (Claude Desktop, Cursor), `{"servers":
    {...}}` (VS Code), a bare `{"name": {...}}` map, or one server with a
    `"name"` field.

    Raises:
        McpConfigError: The JSON is malformed, or a server in it is invalid.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpConfigError(f"Not valid JSON: {exc.msg} (line {exc.lineno})") from exc
    if not isinstance(data, dict):
        raise McpConfigError("Expected a JSON object.")

    servers: Any
    if isinstance(data.get("mcpServers"), dict):
        servers = data["mcpServers"]
    elif isinstance(data.get("servers"), dict):
        servers = data["servers"]
    elif isinstance(data.get("name"), str):
        servers = {data["name"]: {k: v for k, v in data.items() if k != "name"}}
    else:
        servers = data
    if not servers or not all(isinstance(v, dict) for v in servers.values()):
        raise McpConfigError(
            'Expected {"mcpServers": {"name": {...}}}, as in Claude Desktop or VS Code.'
        )

    parsed: dict[str, McpServerConfig] = {}
    for name, raw in servers.items():
        validate_name(name)
        try:
            parsed[name] = McpServerConfig.model_validate(raw)
        except ValidationError as exc:
            raise McpConfigError(f"Server {name!r}: {first_error(exc)}") from exc
    return parsed


def first_error(exc: ValidationError) -> str:
    """The first validation message, without pydantic's boilerplate."""
    error = exc.errors()[0]
    message = str(error.get("msg", exc))
    return message.removeprefix("Value error, ")


def _parse_file(text: str) -> dict[str, McpServerConfig]:
    """The servers in the config file; an empty file or empty list means none."""
    try:
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as exc:
        raise McpConfigError(f"The MCP config file is not valid JSON: {exc.msg}") from exc
    if not data or data == {"mcpServers": {}}:
        return {}
    return parse_import(text)


class McpConfigStore:
    """The servers file: read once, rewritten atomically on every change."""

    def __init__(self, path: Path) -> None:
        """Keep configs in `path` (created on first save)."""
        self.path = path.expanduser()
        self._lock = asyncio.Lock()
        self._servers: dict[str, McpServerConfig] | None = None

    def load(self) -> dict[str, McpServerConfig]:
        """Every config, by name. A missing file means none.

        Raises:
            McpConfigError: The file exists but can't be read.
        """
        if self._servers is None:
            text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
            self._servers = _parse_file(text)
        return dict(self._servers)

    def get(self, name: str) -> McpServerConfig | None:
        """One config, or None."""
        return self.load().get(name)

    async def put(self, name: str, config: McpServerConfig) -> None:
        """Add or replace a config."""
        async with self._lock:
            servers = self.load()
            servers[validate_name(name)] = config
            self._write(servers)

    async def delete(self, name: str) -> bool:
        """Remove a config; False if there was none."""
        async with self._lock:
            servers = self.load()
            if servers.pop(name, None) is None:
                return False
            self._write(servers)
            return True

    def _write(self, servers: dict[str, McpServerConfig]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"mcpServers": {name: cfg.to_file() for name, cfg in servers.items()}}
        fd, tmp = tempfile.mkstemp(prefix=".mcp-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(payload, out, indent=2, ensure_ascii=False)
                out.write("\n")
            os.replace(tmp, self.path)
        finally:
            Path(tmp).unlink(missing_ok=True)
        self._servers = servers


__all__ = [
    "MASK",
    "NAME_PATTERN",
    "McpConfigError",
    "McpConfigStore",
    "McpServerConfig",
    "Transport",
    "first_error",
    "parse_import",
    "validate_name",
]
