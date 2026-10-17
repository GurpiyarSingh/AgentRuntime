"""Request and response models for the public API.

These are the HTTP contract. Internal types (`TokenUsage`, `Tool`,
`ModelInfo`) are converted at the edge through the `from_*` constructors,
so internal refactors never change what clients receive by accident.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import mcp.types as mcp_types
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.agent.outcome import RunOutcome, ToolCallRecord
from agent_runtime.auth import MIN_PASSWORD_LENGTH
from agent_runtime.files.directories import DirectoryListing
from agent_runtime.mcp_client import (
    McpServerConfig,
    McpTool,
    ServerState,
    TestResult,
    qualified_name,
)
from agent_runtime.mcp_client.config import NAME_PATTERN
from agent_runtime.models import ModelInfo
from agent_runtime.storage.store import SessionDetail
from agent_runtime.storage.tables import RunEventRow, RunRow, SessionRow, UserRow
from agent_runtime.tools.base import Tool
from agent_runtime.usage import TokenUsage

# --- chat ------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """One user message for the agent."""

    message: str = Field(..., min_length=1, max_length=32_000)
    session_id: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
        description="Reuse to continue a conversation; omit to start fresh.",
    )
    model: str | None = Field(
        default=None,
        description="Model id from /v1/models; omit to use the server default.",
    )
    workspace: str | None = Field(
        default=None,
        max_length=4096,
        description="Absolute path of an existing directory for the agent's tools to work "
        "in (see /v1/directories); omit to use the server's workspace.",
    )


class UsageView(BaseModel):
    """Token spend for one run, priced for the model that produced it."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = Field(
        default=None, description="Null when the model has no known price — not the same as 0."
    )

    @classmethod
    def from_usage(cls, usage: TokenUsage) -> UsageView:
        """Convert internal usage accounting to its API form."""
        return cls(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
        )


class ToolCallView(BaseModel):
    """One tool call the agent made during the run, and what it returned."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    content: str = Field(description="The observation the model received.")
    is_error: bool
    duration_s: float
    image_count: int = Field(default=0, description="Images shown to the model; not included.")

    @classmethod
    def from_record(cls, record: ToolCallRecord) -> ToolCallView:
        """Convert a recorded tool call to its API form."""
        return cls(
            call_id=record.call_id,
            tool_name=record.tool_name,
            arguments=record.arguments,
            content=record.content,
            is_error=record.is_error,
            duration_s=record.duration_s,
            image_count=record.image_count,
        )


class ChatResponse(BaseModel):
    """The outcome of a run. A failure is a `status`, never a fake answer."""

    run_id: str
    session_id: str
    status: Literal["completed", "failed"] = "completed"
    answer: str
    model: str
    steps_used: int
    usage: UsageView = Field(default_factory=UsageView)
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    error: str | None = Field(default=None, description="Populated only when status is 'failed'.")

    @classmethod
    def from_outcome(
        cls,
        outcome: RunOutcome,
        *,
        run_id: str,
        session_id: str,
        model: str,
        hide_error_detail: bool = False,
    ) -> ChatResponse:
        """Describe a finished run.

        Args:
            outcome: The run's summary.
            run_id: The run's correlation id.
            session_id: The conversation it belongs to.
            model: The model that ran it.
            hide_error_detail: Replace a failure's reason with a generic
                message, so provider internals (quota details, model names)
                never reach clients in production.
        """
        error = outcome.error
        if error is not None and hide_error_detail:
            error = "The agent run did not complete."
        return cls(
            run_id=run_id,
            session_id=session_id,
            status="completed" if outcome.succeeded else "failed",
            answer=outcome.answer if outcome.succeeded else "",
            model=model,
            steps_used=outcome.steps_used,
            # A failed run still burned tokens; report them rather than
            # letting the caller think it was free.
            usage=UsageView.from_usage(outcome.usage),
            tool_calls=[ToolCallView.from_record(record) for record in outcome.tool_calls],
            error=error,
        )


# --- catalog ---------------------------------------------------------------------


class ModelView(BaseModel):
    """One selectable model, with the prices used to cost its runs."""

    id: str
    label: str
    description: str
    input_usd_per_1m: float
    output_usd_per_1m: float

    @classmethod
    def from_info(cls, info: ModelInfo, input_usd: float, output_usd: float) -> ModelView:
        """Describe `info` at the effective prices (catalog or override)."""
        return cls(
            id=info.id,
            label=info.label,
            description=info.description,
            input_usd_per_1m=input_usd,
            output_usd_per_1m=output_usd,
        )


class ModelsResponse(BaseModel):
    """Every model a caller may select, and which one is used by default."""

    default: str
    models: list[ModelView]


class ToolView(BaseModel):
    """One tool the agent can call, exactly as the model sees it."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(description="JSON Schema of the tool's arguments.")
    source: Literal["builtin", "mcp"] = "builtin"
    server: str | None = Field(default=None, description="The MCP server it comes from.")

    @classmethod
    def from_tool(cls, tool: Tool) -> ToolView:
        """Describe `tool` from the same schema the model is given."""
        function = tool.to_openai_schema()["function"]
        server = tool.server if isinstance(tool, McpTool) else None
        return cls(
            name=function["name"],
            description=function["description"],
            parameters=function["parameters"],
            source="mcp" if server else "builtin",
            server=server,
        )


class ToolsResponse(BaseModel):
    """Every tool the agent can call."""

    tools: list[ToolView]


# --- files -----------------------------------------------------------------------


class FileView(BaseModel):
    """One file in the workspace."""

    path: str = Field(description="Workspace-relative, with forward slashes.")
    size: int
    modified: datetime

    @classmethod
    def from_path(cls, path: Path, display: str) -> FileView:
        """Describe the file at `path`, shown to clients as `display`."""
        stat = path.stat()
        return cls(
            path=display,
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )


class FilesResponse(BaseModel):
    """A listing of workspace files."""

    files: list[FileView]


class DirectoryEntry(BaseModel):
    """One folder a client may open or choose as the workspace."""

    name: str
    path: str = Field(description="Absolute path on the server.")

    @classmethod
    def from_path(cls, path: Path) -> DirectoryEntry:
        """Describe `path`; a drive or filesystem root is named by its full path."""
        return cls(name=path.name or str(path), path=str(path))


class DirectoryListingView(BaseModel):
    """The subfolders of one folder on the server."""

    path: str | None = Field(description="The folder listed; null for the top-level locations.")
    parent: str | None = Field(
        description="The folder above; null when `path` is a top-level location (or is null)."
    )
    directories: list[DirectoryEntry]
    truncated: bool = Field(default=False, description="True when not every folder is listed.")

    @classmethod
    def from_listing(cls, listing: DirectoryListing) -> DirectoryListingView:
        """Convert a policy listing to its API form."""
        return cls(
            path=None if listing.path is None else str(listing.path),
            parent=None if listing.parent is None else str(listing.parent),
            directories=[DirectoryEntry.from_path(path) for path in listing.directories],
            truncated=listing.truncated,
        )


# --- MCP servers -----------------------------------------------------------------


class McpToolView(BaseModel):
    """One tool an MCP server offers."""

    name: str = Field(description="The tool's own name on the server.")
    qualified_name: str = Field(description="The name the agent calls it by: server__tool.")
    description: str
    parameters: dict[str, Any]

    @classmethod
    def from_tool(cls, server: str, tool: mcp_types.Tool) -> McpToolView:
        """Describe `tool` from `server`."""
        return cls(
            name=tool.name,
            qualified_name=qualified_name(server, tool.name),
            description=tool.description or tool.title or "",
            parameters=tool.inputSchema or {},
        )


class McpServerView(BaseModel):
    """A configured MCP server, its connection, and its tools. Secrets are masked."""

    name: str
    config: McpServerConfig
    status: Literal["disabled", "connecting", "connected", "error"]
    error: str | None = None
    server_name: str | None = Field(default=None, description="What the server calls itself.")
    server_version: str | None = None
    connected_at: datetime | None = None
    tools: list[McpToolView] = Field(default_factory=list)

    @classmethod
    def from_state(cls, state: ServerState) -> McpServerView:
        """Describe a server as the manager sees it now."""
        connection = state.connection
        return cls(
            name=state.name,
            config=state.config.masked(),
            status=state.status,
            error=state.error,
            server_name=connection.server_name if connection else None,
            server_version=connection.server_version if connection else None,
            connected_at=state.connected_at if connection else None,
            tools=[McpToolView.from_tool(state.name, tool) for tool in state.tools],
        )


class McpServersResponse(BaseModel):
    """Every configured MCP server, and what this caller may do with them."""

    servers: list[McpServerView]
    can_manage: bool = Field(description="False for signed-in non-admins: they can only look.")
    allow_stdio: bool = Field(description="False when local (stdio) servers are turned off.")


class McpServerCreate(BaseModel):
    """A new server: its name (which prefixes its tools) and how to reach it."""

    name: str = Field(..., pattern=NAME_PATTERN, description="1-32 letters, digits, _ or -.")
    config: McpServerConfig


class McpServerPatch(BaseModel):
    """Turn a server on or off without touching the rest of its config."""

    enabled: bool


class McpTestRequest(BaseModel):
    """A configuration to try, before or without saving it."""

    config: McpServerConfig
    name: str | None = Field(
        default=None,
        description="An existing server whose stored secrets fill in masked values.",
    )


class McpTestView(BaseModel):
    """What a trial connection found."""

    ok: bool
    duration_s: float
    error: str | None = None
    server_name: str | None = None
    server_version: str | None = None
    tools: list[McpToolView] = Field(default_factory=list)

    @classmethod
    def from_result(cls, result: TestResult, name: str) -> McpTestView:
        """Describe a trial connection, naming tools as server `name` would."""
        return cls(
            ok=result.ok,
            duration_s=round(result.duration_s, 3),
            error=result.error,
            server_name=result.server_name,
            server_version=result.server_version,
            tools=[McpToolView.from_tool(name, tool) for tool in result.tools],
        )


class McpImportRequest(BaseModel):
    """Pasted JSON, as Claude Desktop, Cursor or VS Code write it."""

    json_text: str = Field(..., min_length=2, max_length=200_000, alias="json")
    overwrite: bool = Field(default=False, description="Replace servers that already exist.")

    model_config = ConfigDict(populate_by_name=True)


class McpImportResponse(BaseModel):
    """What an import did, by server name."""

    added: list[str]
    replaced: list[str]
    skipped: list[str] = Field(description="Already existed, and overwrite was false.")


# --- sign-in ---------------------------------------------------------------------

_USERNAME = Field(
    ...,
    min_length=3,
    max_length=64,
    pattern=r"^[A-Za-z0-9_.@-]+$",
    description="Letters, digits and _ . @ - (not case-sensitive).",
)


class AuthStatus(BaseModel):
    """What the web app should show before anything else."""

    enabled: bool = Field(description="True when people must sign in.")
    setup_required: bool = Field(description="True until the first (admin) account exists.")


class LoginRequest(BaseModel):
    """A username and password."""

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class SetupRequest(BaseModel):
    """The first account, which becomes the admin."""

    username: str = _USERNAME
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=256)
    display_name: str = Field(default="", max_length=100)


class UserView(BaseModel):
    """A signed-in account (never its password hash)."""

    id: str
    username: str
    display_name: str
    is_admin: bool
    created_at: datetime
    last_login_at: datetime | None

    @classmethod
    def from_row(cls, row: UserRow) -> UserView:
        """Describe a stored account."""
        return cls(
            id=row.id,
            username=row.username,
            display_name=row.display_name,
            is_admin=row.is_admin,
            created_at=row.created_at,
            last_login_at=row.last_login_at,
        )


class LoginResponse(BaseModel):
    """A new sign-in: send `token` as `Authorization: Bearer <token>`."""

    token: str
    user: UserView


# --- sessions --------------------------------------------------------------------


class SessionSummary(BaseModel):
    """One stored conversation, with totals over all its runs."""

    id: str
    title: str
    model: str | None
    workspace: str | None
    created_at: datetime
    updated_at: datetime
    run_count: int
    usage: UsageView

    @classmethod
    def from_row(cls, row: SessionRow) -> SessionSummary:
        """Describe a stored session."""
        return cls(
            id=row.id,
            title=row.title,
            model=row.model,
            workspace=row.workspace,
            created_at=row.created_at,
            updated_at=row.updated_at,
            run_count=row.run_count,
            usage=UsageView(
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                total_tokens=row.total_tokens,
                cost_usd=row.cost_usd,
            ),
        )


class SessionsResponse(BaseModel):
    """Stored sessions, most recently active first."""

    sessions: list[SessionSummary]


class RecordedEvent(BaseModel):
    """One stored event, in the same shape as the SSE stream sent it."""

    type: str = Field(description="The SSE event name, e.g. `tool_call_result`.")
    data: dict[str, Any]
    created_at: datetime


class RunView(BaseModel):
    """One run of a session: the user's message and everything the agent did."""

    id: str
    status: Literal["running", "completed", "failed", "cancelled"]
    user_message: str
    model: str
    workspace: str | None
    answer: str | None
    error: str | None
    steps_used: int
    tool_call_count: int
    usage: UsageView
    started_at: datetime
    finished_at: datetime | None
    duration_s: float | None
    events: list[RecordedEvent] = Field(
        description="Every event, in order; model tokens are merged into one event per step."
    )

    @classmethod
    def from_row(cls, row: RunRow, events: list[RunEventRow]) -> RunView:
        """Describe a stored run and its events."""
        return cls(
            id=row.id,
            status=row.status,  # type: ignore[arg-type]
            user_message=row.user_message,
            model=row.model,
            workspace=row.workspace,
            answer=row.answer,
            error=row.error,
            steps_used=row.steps_used,
            tool_call_count=row.tool_call_count,
            usage=UsageView(
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                total_tokens=row.total_tokens,
                cost_usd=row.cost_usd,
            ),
            started_at=row.started_at,
            finished_at=row.finished_at,
            duration_s=row.duration_s,
            events=[
                RecordedEvent(type=event.type, data=event.payload, created_at=event.created_at)
                for event in events
            ],
        )


class SessionDetailView(SessionSummary):
    """A session with every run, enough to replay the whole conversation."""

    runs: list[RunView]

    @classmethod
    def from_detail(cls, detail: SessionDetail) -> SessionDetailView:
        """Describe a stored session and all its runs."""
        summary = SessionSummary.from_row(detail.session)
        return cls(
            **summary.model_dump(),
            runs=[RunView.from_row(run, detail.events.get(run.id, [])) for run in detail.runs],
        )


class SessionUpdate(BaseModel):
    """Changes to a session."""

    title: str = Field(..., min_length=1, max_length=200)


# --- meta ------------------------------------------------------------------------


class WorkspaceStatus(BaseModel):
    """How the agent's workspace is configured."""

    read_only: bool = Field(description="True when the agent cannot create or change files.")
    path: str | None = Field(default=None, description="Hidden in production.")
    selectable: bool = Field(
        default=False, description="True when a request may choose another directory to work in."
    )


class HealthResponse(BaseModel):
    """Liveness plus a summary of the server's configuration."""

    status: str
    app_name: str
    environment: str
    model: str
    tools: list[str]
    workspace: WorkspaceStatus
    mcp: bool = Field(default=False, description="True when MCP servers can be managed.")
    history: bool = Field(
        default=False,
        description="True when sessions are stored in a database (listed at /v1/sessions).",
    )


class ErrorResponse(BaseModel):
    """Body of an unhandled-error (500) response."""

    error: str
    detail: str | None = None
