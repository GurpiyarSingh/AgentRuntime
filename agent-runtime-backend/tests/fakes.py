"""Test doubles for the runtime's dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from agent_runtime.agent.messages import AssistantMessage, Message, ToolCall
from agent_runtime.tools.base import Tool
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.usage import TokenUsage

SYSTEM_PROMPT = "You are a test agent."


@dataclass(slots=True)
class FakeChatModel:
    """Replays a fixed sequence of assistant turns, one per model call.

    Makes the loop's control flow (tool call -> observation -> next turn ->
    final answer) fully deterministic, with no network and no LangChain.
    Streaming is supported too: a turn's content is streamed word by word,
    and `accumulate` hands back the scripted turn. `model_id` stands in for
    the model a real binding would have resolved.
    """

    turns: list[AssistantMessage]
    model_id: str = "fake-model"
    calls: list[list[Message]] = field(default_factory=list)
    _index: int = 0

    def _next_turn(self, messages: list[Message]) -> AssistantMessage:
        self.calls.append(list(messages))
        if self._index >= len(self.turns):
            raise AssertionError("FakeChatModel ran out of scripted turns")
        turn = self.turns[self._index]
        self._index += 1
        return turn

    async def invoke(self, messages: list[Message]) -> AssistantMessage:
        return self._next_turn(messages)

    async def stream(self, messages: list[Message]) -> AsyncIterator[Any]:
        turn = self._next_turn(messages)
        for word in turn.content.split(" "):
            yield (turn, word + " ")
        if not turn.content:
            yield (turn, "")

    def chunk_text(self, chunk: tuple[AssistantMessage, str]) -> str:
        return chunk[1]

    def accumulate(self, chunks: list[tuple[AssistantMessage, str]]) -> AssistantMessage:
        return chunks[0][0]


# --- a trivial tool, so loop tests don't depend on a real one ----------------


class EchoArgs(BaseModel):
    text: str = Field(..., description="Text to echo back.")


class EchoTool(Tool):
    """Returns its input. Enough to exercise the loop's act/observe stage."""

    name = "echo"
    description = "Echo the given text back."
    args_schema = EchoArgs

    async def run(self, text: str) -> str:  # type: ignore[override]
        return text


def echo_registry() -> ToolRegistry:
    return ToolRegistry([EchoTool()])


# --- scripted model turns ----------------------------------------------------


def usage(
    input_tokens: int = 100, output_tokens: int = 20, cost_usd: float | None = 0.0005
) -> TokenUsage:
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_usd=cost_usd,
    )


def tool_call_turn(
    name: str,
    arguments: dict[str, Any],
    call_id: str = "call_1",
    token_usage: TokenUsage | None = None,
) -> AssistantMessage:
    return AssistantMessage(
        content="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        usage=token_usage,
    )


def final_turn(content: str, token_usage: TokenUsage | None = None) -> AssistantMessage:
    return AssistantMessage(content=content, tool_calls=[], usage=token_usage)
