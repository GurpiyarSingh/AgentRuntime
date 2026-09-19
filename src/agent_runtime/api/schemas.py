"""Request/response models for the public API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_runtime.agents.base import AgentSpec
from agent_runtime.models import ModelInfo
from agent_runtime.usage import TokenUsage


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = Field(
        default=None, description="Reuse to continue a conversation; omit to start fresh."
    )
    model: str | None = Field(
        default=None,
        description="Model id from /v1/models; omit to use the server default.",
    )
    agent: str | None = Field(
        default=None,
        description="Agent name from /v1/agents; omit to let the orchestrator route.",
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
        return cls(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=usage.cost_usd,
        )


class ToolCallView(BaseModel):
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    content: str | None = None
    is_error: bool | None = None
    duration_s: float | None = None


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    status: Literal["completed", "failed"] = "completed"
    answer: str
    agent: str
    model: str
    steps_used: int
    usage: UsageView = Field(default_factory=UsageView)
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    error: str | None = Field(default=None, description="Populated only when status is 'failed'.")


class ModelView(BaseModel):
    """One selectable model, with the prices used to cost its runs."""

    id: str
    label: str
    description: str
    input_usd_per_1m: float
    output_usd_per_1m: float

    @classmethod
    def from_info(cls, info: ModelInfo, input_usd: float, output_usd: float) -> ModelView:
        return cls(
            id=info.id,
            label=info.label,
            description=info.description,
            input_usd_per_1m=input_usd,
            output_usd_per_1m=output_usd,
        )


class ModelsResponse(BaseModel):
    default: str
    models: list[ModelView]


class AgentView(BaseModel):
    """One specialist agent the orchestrator can route to."""

    name: str
    label: str
    description: str
    tools: list[str]
    ready: bool = True
    status: str = Field(
        default="", description="Short caveat, e.g. a dry run or missing credentials."
    )

    @classmethod
    def from_spec(cls, spec: AgentSpec) -> AgentView:
        return cls(
            name=spec.name,
            label=spec.label,
            description=spec.description,
            tools=spec.tool_names,
            ready=spec.ready,
            status=spec.status,
        )


class AgentsResponse(BaseModel):
    default: str
    agents: list[AgentView]


class EmailStatus(BaseModel):
    """Whether this server would actually deliver mail, and from where."""

    dry_run: bool = Field(description="True when nothing is really sent.")
    sender: str | None = None
    max_recipients: int = 5
    allowed_domains: list[str] = Field(default_factory=list)


class YouTubeStatus(BaseModel):
    """Whether this server can search YouTube at all."""

    configured: bool = Field(description="False when no API key is set.")
    max_results: int = 5


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    model: str
    agents: list[str]
    email: EmailStatus
    youtube: YouTubeStatus
