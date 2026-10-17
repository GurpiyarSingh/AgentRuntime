"""Transcript messages to and from database rows (role, content, JSON data)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agent_runtime.agent.messages import (
    AssistantMessage,
    ImageAttachment,
    Message,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from agent_runtime.usage import TokenUsage


def encode_message(message: Message) -> tuple[str, str, dict[str, Any] | None]:
    """`(role, content, data)` for one transcript entry."""
    match message:
        case SystemMessage(content=content):
            return "system", content, None
        case UserMessage(content=content):
            return "user", content, None
        case AssistantMessage(content=content, tool_calls=calls, usage=usage):
            return (
                "assistant",
                content,
                {
                    "tool_calls": [asdict(call) for call in calls],
                    "usage": asdict(usage) if usage else None,
                },
            )
        case ToolMessage():
            return (
                "tool",
                message.content,
                {
                    "tool_call_id": message.tool_call_id,
                    "name": message.name,
                    "is_error": message.is_error,
                    # Kept so a continued conversation shows the model the
                    # same pictures it saw the first time.
                    "images": [asdict(image) for image in message.images],
                },
            )
    raise TypeError(f"Unknown message type: {type(message).__name__}")


def decode_message(role: str, content: str, data: dict[str, Any] | None) -> Message:
    """Rebuild the transcript entry `encode_message` stored."""
    data = data or {}
    if role == "system":
        return SystemMessage(content=content)
    if role == "user":
        return UserMessage(content=content)
    if role == "assistant":
        usage = data.get("usage")
        return AssistantMessage(
            content=content,
            tool_calls=[ToolCall(**call) for call in data.get("tool_calls", [])],
            usage=TokenUsage(**usage) if usage else None,
        )
    if role == "tool":
        return ToolMessage(
            tool_call_id=data["tool_call_id"],
            name=data["name"],
            content=content,
            is_error=data.get("is_error", False),
            images=[ImageAttachment(**image) for image in data.get("images", [])],
        )
    raise ValueError(f"Unknown message role: {role!r}")


__all__ = ["decode_message", "encode_message"]
