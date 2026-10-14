"""The only module that talks to LangChain / OpenAI directly.

Everything else in `agent_runtime` works with the plain message types in
`agent_runtime.agent.messages`. This module is the translation boundary:
it builds a `ChatOpenAI` for the selected model, binds tool schemas to it,
converts between our messages and `langchain_core.messages`, and attaches
the token usage the provider reports to each assistant turn. Swapping
providers means writing another `ChatModel` like `OpenAIModel`, not
editing the loop.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.messages import SystemMessage as LCSystemMessage
from langchain_core.messages import ToolMessage as LCToolMessage
from langchain_openai import ChatOpenAI

from agent_runtime.agent.messages import (
    AssistantMessage,
    ImageAttachment,
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


class ModelConfigurationError(RuntimeError):
    """The model can't be called because the server is not configured for it."""


def _images_message(images: list[ImageAttachment]) -> HumanMessage:
    """Build one user turn carrying every image the preceding tool calls returned."""
    content: list[str | dict[str, Any]] = [
        {"type": "text", "text": "Images returned by the tool calls above:"}
    ]
    for image in images:
        if image.label:
            content.append({"type": "text", "text": image.label})
        content.append(
            {"type": "image_url", "image_url": {"url": image.data_url, "detail": image.detail}}
        )
    return HumanMessage(content=content)


def _to_langchain(messages: list[Message]) -> list[BaseMessage]:
    """Translate our transcript into LangChain messages for one model call."""
    lc_messages: list[BaseMessage] = []
    # OpenAI requires an assistant's tool calls to be answered by an unbroken
    # run of tool messages, and those can only carry text. Images are held
    # back until that run ends, then sent together as one user turn.
    pending_images: list[ImageAttachment] = []
    for message in messages:
        if pending_images and not isinstance(message, ToolMessage):
            lc_messages.append(_images_message(pending_images))
            pending_images = []
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
            pending_images.extend(message.images)
        else:  # pragma: no cover - exhaustiveness guard
            raise TypeError(f"Unknown message type: {type(message)!r}")
    if pending_images:
        lc_messages.append(_images_message(pending_images))
    return lc_messages


def _text_of(message: AIMessage | AIMessageChunk) -> str:
    """Return the plain text of a model turn, whether its content is a string or blocks."""
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    content = message.content
    return content if isinstance(content, str) else str(content)


def _from_ai_message(
    ai_message: AIMessage | AIMessageChunk, pricing: ModelPricing | None
) -> AssistantMessage:
    """Translate a LangChain model turn back into our `AssistantMessage`."""
    tool_calls = [
        ToolCall(
            # Some providers omit ids on streamed calls; the transcript needs
            # one to pair each call with its result.
            id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
            name=tc["name"],
            arguments=tc["args"],
        )
        for tc in (ai_message.tool_calls or [])
    ]
    return AssistantMessage(
        content=_text_of(ai_message),
        tool_calls=tool_calls,
        usage=TokenUsage.from_metadata(ai_message.usage_metadata, pricing),
    )


class OpenAIModel:
    """A `ChatModel` backed by OpenAI: our messages in, our `AssistantMessage` out."""

    def __init__(
        self, settings: Settings, tools: ToolRegistry | None = None, model_id: str | None = None
    ) -> None:
        """Build the client for one model, with the tool schemas bound to it.

        Args:
            settings: API key, sampling, timeout, retry and pricing settings.
            tools: Tools whose schemas the model is offered; none if omitted.
            model_id: A catalog model id; defaults to `settings.openai_model`.

        Raises:
            ModelConfigurationError: `OPENAI_API_KEY` is not set.
            UnknownModelError: `model_id` is not in the model catalog.
        """
        # The caller's mistake is reported before the operator's: a bad model
        # id should never be masked by a missing key.
        self.model_id = resolve_model_id(model_id, settings.openai_model)
        if settings.openai_api_key is None:
            raise ModelConfigurationError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add your OpenAI "
                "API key (https://platform.openai.com/api-keys)."
            )
        self._pricing = pricing_for(self.model_id, settings.pricing_overrides)
        client = ChatOpenAI(
            model=self.model_id,
            api_key=settings.openai_api_key,
            temperature=settings.model_temperature,
            # The `max_completion_tokens` spelling is what newer OpenAI models
            # require; LangChain maps it to the legacy field where needed.
            max_completion_tokens=settings.model_max_output_tokens,
            timeout=settings.model_timeout_s,
            max_retries=settings.model_max_retries,
            # Without this a streamed call reports no token counts at all, and
            # the run's cost would silently read zero.
            stream_usage=True,
        )
        self._client = client.bind_tools(tools.as_openai_schemas()) if tools else client

    async def invoke(self, messages: list[Message]) -> AssistantMessage:
        """Make a non-streaming call: one model turn in, one assistant turn out."""
        response = await self._client.ainvoke(_to_langchain(messages))
        if not isinstance(response, AIMessage):
            raise TypeError(f"Expected an AIMessage from the model, got {type(response)!r}")
        return _from_ai_message(response, self._pricing)

    async def stream(self, messages: list[Message]) -> AsyncIterator[AIMessageChunk]:
        """Make a streaming call, yielding raw chunks as they arrive.

        Pass the chunks to `accumulate` once the stream ends: tool-call
        arguments only become valid JSON once every chunk is merged, and
        the token usage arrives on the very last chunk.
        """
        async for chunk in self._client.astream(_to_langchain(messages)):
            if isinstance(chunk, AIMessageChunk):
                yield chunk

    def chunk_text(self, chunk: AIMessageChunk) -> str:
        """Return the text a streamed chunk adds to the answer (often empty)."""
        return _text_of(chunk)

    def accumulate(self, chunks: list[AIMessageChunk]) -> AssistantMessage:
        """Merge streamed chunks into one `AssistantMessage`, priced for this model."""
        if not chunks:
            return AssistantMessage()
        merged = chunks[0]
        for chunk in chunks[1:]:
            merged = merged + chunk  # AIMessageChunk merges deltas with `+`.
        return _from_ai_message(merged, self._pricing)


__all__ = ["ModelConfigurationError", "OpenAIModel"]
