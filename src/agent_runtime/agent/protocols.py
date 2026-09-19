"""The structural interface `AgentLoop` needs from a chat model.

`OpenAIModel` satisfies this implicitly. Tests substitute a fake that
implements just these members, without touching LangChain or network
calls at all.

`accumulate` lives here rather than in the loop because merging streamed
chunks — and knowing what those tokens cost — is provider knowledge; the
loop only needs a finished `AssistantMessage`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from agent_runtime.agent.messages import AssistantMessage, Message


class ChatModel(Protocol):
    model_id: str

    async def invoke(self, messages: list[Message]) -> AssistantMessage: ...

    def stream(self, messages: list[Message]) -> AsyncIterator[Any]: ...

    def accumulate(self, chunks: list[Any]) -> AssistantMessage: ...
