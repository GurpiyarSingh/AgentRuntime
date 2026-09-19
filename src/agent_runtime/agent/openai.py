"""The only module that talks to LangChain / OpenAI directly.

Everything else in `agent_runtime` works with the plain message types in
`agent_runtime.agent.messages`. This module is the translation boundary:
it builds a `ChatOpenAI` for the selected model, binds tool schemas to it,
converts between our messages and `langchain_core.messages`, and attaches
the token usage the provider reports to each assistant turn. Swapping
providers later means editing this file, not the loop.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
)
from langchain_core.messages import (
    SystemMessage as LCSystemMessage,
)
from langchain_core.messages import (
    ToolMessage as LCToolMessage,
)
from langchain_openai import ChatOpenAI

from agent_runtime.agent.messages import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from agent_runtime.config import Settings
from agent_runtime.models import ModelPricing, pricing_for, resolve_model_id
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.usage import TokenUsage


def build_chat_model(settings: Settings, model_id: str) -> ChatOpenAI:
    """Construct the OpenAI chat model for `model_id` from settings."""
    if settings.openai_api_key is None:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your OpenAI API key "
            "(https://platform.openai.com/api-keys)."
        )
    return ChatOpenAI(
        model=model_id,
        api_key=settings.openai_api_key,
        temperature=settings.model_temperature,
        # The `max_completion_tokens` spelling is what newer OpenAI models
        # require; LangChain maps it to the legacy field where needed.
        max_completion_tokens=settings.model_max_output_tokens,
        timeout=settings.model_timeout_s,
        max_retries=settings.model_max_retries,
        # Without this, a streamed call reports no token counts at all and
        # the per-message cost on the UI would silently read zero.
        stream_usage=True,
    )


def _to_langchain(messages: list[Message]) -> list[BaseMessage]:
    lc_messages: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            lc_messages.append(LCSystemMessage(content=message.content))
        elif isinstance(message, UserMessage):
            lc_messages.append(HumanMessage(content=message.content))
        elif isinstance(message, AssistantMessage):
            lc_messages.append(
                AIMessage(
                    content=message.content,
                    tool_calls=[
                        {"name": tc.name, "args": tc.arguments, "id": tc.id, "type": "tool_call"}
                        for tc in message.tool_calls
                    ],
                )
            )
        elif isinstance(message, ToolMessage):
            lc_messages.append(
                LCToolMessage(
                    content=message.content, tool_call_id=message.tool_call_id, name=message.name
                )
            )
        else:  # pragma: no cover - exhaustiveness guard
            raise TypeError(f"Unknown message type: {type(message)!r}")
    return lc_messages


def text_of(message: AIMessage | AIMessageChunk) -> str:
    """Plain text of a model turn, whether its content is a string or blocks."""
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    content = message.content
    return content if isinstance(content, str) else str(content)


def _from_ai_message(
    ai_message: AIMessage | AIMessageChunk, pricing: ModelPricing | None = None
) -> AssistantMessage:
    tool_calls = [
        ToolCall(
            id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}", name=tc["name"], arguments=tc["args"]
        )
        for tc in (ai_message.tool_calls or [])
    ]
    return AssistantMessage(
        content=text_of(ai_message),
        tool_calls=tool_calls,
        usage=TokenUsage.from_metadata(ai_message.usage_metadata, pricing),
    )


class OpenAIModel:
    """A thin, typed wrapper: our messages in, our `AssistantMessage` out."""

    def __init__(
        self, settings: Settings, tools: ToolRegistry | None = None, model_id: str | None = None
    ) -> None:
        self._settings = settings
        self.model_id = resolve_model_id(model_id, settings.openai_model)
        self._pricing = pricing_for(self.model_id, settings.pricing_overrides)
        model = build_chat_model(settings, self.model_id)
        self._model = model.bind_tools(tools.as_openai_schemas()) if tools and len(tools) else model

    async def invoke(self, messages: list[Message]) -> AssistantMessage:
        """Non-streaming call: one model turn in, one assistant turn out."""
        response = await self._model.ainvoke(_to_langchain(messages))
        assert isinstance(response, AIMessage)
        return _from_ai_message(response, self._pricing)

    async def stream(self, messages: list[Message]) -> AsyncIterator[Any]:
        """Streaming call: yields raw `AIMessageChunk`s as they arrive.

        The caller is responsible for accumulating chunks into a final
        `AssistantMessage` (see `agent_runtime.agent.loop`), since tool-call
        arguments only become valid JSON once all chunks are merged — and
        the token usage only arrives on the very last chunk.
        """
        async for chunk in self._model.astream(_to_langchain(messages)):
            yield chunk

    def accumulate(self, chunks: list[AIMessageChunk]) -> AssistantMessage:
        """Merge streamed chunks into one `AssistantMessage`, priced for this model."""
        return accumulate_chunks(chunks, self._pricing)


def accumulate_chunks(
    chunks: list[AIMessageChunk], pricing: ModelPricing | None = None
) -> AssistantMessage:
    """Merge streamed chunks into one `AssistantMessage`."""
    if not chunks:
        return AssistantMessage()
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk  # AIMessageChunk supports `+` to merge deltas
    return _from_ai_message(merged, pricing)
