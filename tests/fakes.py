"""Test doubles for the runtime's dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from agent_runtime.agent.messages import AssistantMessage, Message, ToolCall
from agent_runtime.agents.base import AgentSpec
from agent_runtime.tools.base import Tool, ToolError
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.usage import TokenUsage


@dataclass(slots=True)
class FakeChatModel:
    """Replays a fixed sequence of assistant turns, one per `invoke` call.

    This makes the loop's control flow (tool call -> observation -> next
    turn -> final answer) fully deterministic in tests, with zero network
    access and no LangChain involved. `model_id` stands in for the model a
    real binding would have resolved, so tests can assert on what the API
    reports back.
    """

    turns: list[AssistantMessage]
    model_id: str = "fake-model"
    calls: list[list[Message]] = field(default_factory=list)
    _index: int = 0

    async def invoke(self, messages: list[Message]) -> AssistantMessage:
        self.calls.append(list(messages))
        if self._index >= len(self.turns):
            raise AssertionError("FakeChatModel ran out of scripted turns")
        turn = self.turns[self._index]
        self._index += 1
        return turn

    async def stream(
        self, messages: list[Message]
    ) -> AsyncIterator[Any]:  # pragma: no cover - unused
        raise NotImplementedError("FakeChatModel does not support streaming; disable stream_tokens")

    def accumulate(
        self, chunks: list[Any]
    ) -> AssistantMessage:  # pragma: no cover - streaming is unused
        raise NotImplementedError("FakeChatModel does not support streaming; disable stream_tokens")


# --- a trivial tool, so loop tests don't depend on a real one ----------------


class EchoArgs(BaseModel):
    text: str = Field(..., description="Text to echo back.")


class EchoTool(Tool):
    """Returns its input. Enough to exercise the loop's act/observe stage."""

    name = "echo"
    description = "Echo the given text back."
    args_schema = EchoArgs

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self._fail = fail

    async def run(self, text: str) -> str:  # type: ignore[override]
        self.calls.append(text)
        if self._fail:
            raise ToolError(f"echo refused {text!r}")
        return text


def echo_registry(fail: bool = False) -> ToolRegistry:
    return ToolRegistry([EchoTool(fail=fail)])


def fake_agent(
    name: str = "echo-agent",
    description: str = "Echoes text back.",
    tools: ToolRegistry | None = None,
) -> AgentSpec:
    return AgentSpec(
        name=name,
        label=name.replace("-", " ").title(),
        description=description,
        system_prompt="You echo things.",
        tools=tools if tools is not None else echo_registry(),
    )


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
