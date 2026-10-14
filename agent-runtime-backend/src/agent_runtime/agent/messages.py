"""The agent's transcript: a plain message history, independent of any provider.

These types are deliberately decoupled from LangChain's message classes.
The OpenAI binding (`agent_runtime.agent.openai`) is the only place that
translates to and from `langchain_core.messages`, so the loop, the API and
the tests depend on a small, stable shape instead of a third-party
library's internals. A message's type is its role; there is no separate
role field to drift out of sync with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from agent_runtime.usage import TokenUsage


@dataclass(slots=True)
class ToolCall:
    """A single function call the model asked for."""

    id: str
    """Provider-assigned id that pairs this call with its `ToolMessage`."""
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ImageAttachment:
    """An image a tool hands back for the model to look at.

    OpenAI tool results can only carry text, so the provider binding
    delivers these as a user turn right after the tool results. `data` is
    base64, never a URL, so the model sees exactly the bytes the tool read.
    """

    media_type: str
    """MIME type of `data`, e.g. ``image/png``."""
    data: str
    """The image bytes, base64-encoded."""
    label: str = ""
    """Shown to the model next to the image, typically the file name."""
    detail: Literal["auto", "low", "high"] = "auto"
    """OpenAI's resolution hint: ``low`` is cheaper, ``high`` reads fine print."""

    @property
    def data_url(self) -> str:
        """The image as a ``data:`` URL, the form OpenAI's API accepts."""
        return f"data:{self.media_type};base64,{self.data}"


@dataclass(slots=True)
class SystemMessage:
    """Instructions that frame the whole conversation; always first."""

    content: str


@dataclass(slots=True)
class UserMessage:
    """What the user said."""

    content: str


@dataclass(slots=True)
class AssistantMessage:
    """A model turn: free text, and/or requests to call tools.

    `usage` is what the provider reported for *this* turn, priced for the
    model that produced it. It is `None` when the provider reported no
    counts, which is deliberately distinct from "zero tokens".
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None

    @property
    def has_tool_calls(self) -> bool:
        """True when the model wants tools run; otherwise this is its answer."""
        return bool(self.tool_calls)


@dataclass(slots=True)
class ToolMessage:
    """The result of executing one tool call, fed back to the model."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
    images: list[ImageAttachment] = field(default_factory=list)


Message = SystemMessage | UserMessage | AssistantMessage | ToolMessage
"""Any entry in a transcript."""


__all__ = [
    "AssistantMessage",
    "ImageAttachment",
    "Message",
    "SystemMessage",
    "ToolCall",
    "ToolMessage",
    "UserMessage",
]
