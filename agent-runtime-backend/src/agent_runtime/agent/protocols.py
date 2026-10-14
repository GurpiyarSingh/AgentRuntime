"""The structural interface `AgentLoop` needs from a chat model.

`OpenAIModel` satisfies it implicitly; tests substitute a scripted fake
that implements just these members, with no LangChain or network at all.

Chunk handling (`chunk_text`, `accumulate`) lives here rather than in the
loop because the shape of a streamed chunk, how chunks merge, and what
their tokens cost are all provider knowledge. The loop only ever sees
text fragments and a finished `AssistantMessage`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from agent_runtime.agent.messages import AssistantMessage, Message


class ChatModel(Protocol):
    """A tool-calling chat model, as the agent loop uses it."""

    model_id: str
    """The catalog id of the model actually called, for usage reporting."""

    async def invoke(self, messages: list[Message]) -> AssistantMessage:
        """Return the model's next turn for `messages`, in one call."""
        ...

    def stream(self, messages: list[Message]) -> AsyncIterator[Any]:
        """Yield provider-specific chunks of the model's next turn."""
        ...

    def chunk_text(self, chunk: Any) -> str:
        """Return the answer text carried by one streamed chunk."""
        ...

    def accumulate(self, chunks: list[Any]) -> AssistantMessage:
        """Merge every chunk of a finished stream into the complete turn."""
        ...


__all__ = ["ChatModel"]
