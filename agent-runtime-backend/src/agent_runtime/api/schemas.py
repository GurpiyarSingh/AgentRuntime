"""Request and response models for the public API.

These are the HTTP contract. Internal types (`TokenUsage`, `Tool`,
`ModelInfo`) are converted at the edge through the `from_*` constructors,
so internal refactors never change what clients receive by accident.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_runtime.agent.outcome import RunOutcome, ToolCallRecord
from agent_runtime.models import ModelInfo
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

    @classmethod
    def from_tool(cls, tool: Tool) -> ToolView:
        """Describe `tool` from the same schema the model is given."""
        function = tool.to_openai_schema()["function"]
        return cls(
            name=function["name"],
            description=function["description"],
            parameters=function["parameters"],
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


# --- meta ------------------------------------------------------------------------


class WorkspaceStatus(BaseModel):
    """How the agent's workspace is configured."""

    read_only: bool = Field(description="True when the agent cannot create or change files.")
    path: str | None = Field(default=None, description="Hidden in production.")


class HealthResponse(BaseModel):
    """Liveness plus a summary of the server's configuration."""

    status: str
    app_name: str
    environment: str
    model: str
    tools: list[str]
    workspace: WorkspaceStatus


class ErrorResponse(BaseModel):
    """Body of an unhandled-error (500) response."""

    error: str
    detail: str | None = None
