"""The agent's transcript: a plain, serializable message history.

These are intentionally decoupled from LangChain's message classes. The
OpenAI binding (`agent_runtime.agent.openai`) is the only place that
translates to and from `langchain_core.messages`, so the rest of the
codebase — the loop, the API, tests — depends on a small, stable shape
instead of a third-party library's internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from agent_runtime.usage import TokenUsage

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class ToolCall:
    """A single function call the model asked for."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class SystemMessage:
    content: str
    role: Literal["system"] = "system"


@dataclass(slots=True)
class UserMessage:
    content: str
    role: Literal["user"] = "user"


@dataclass(slots=True)
class AssistantMessage:
    """A model turn: free text, and/or requests to call tools.

    `usage` is what the provider reported for *this* turn, priced for the
    model that produced it. It is `None` when the provider didn't report
    counts, which is deliberately distinct from "zero tokens".
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    role: Literal["assistant"] = "assistant"

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass(slots=True)
class ToolMessage:
    """The result of executing one tool call, fed back to the model."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
    role: Literal["tool"] = "tool"


Message = SystemMessage | UserMessage | AssistantMessage | ToolMessage
