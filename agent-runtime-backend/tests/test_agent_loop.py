from __future__ import annotations

import pytest

from agent_runtime.agent.events import (
    FinalAnswer,
    ModelToken,
    RunFailed,
    ToolCallRequested,
    ToolCallResult,
    UsageUpdated,
)
from agent_runtime.agent.loop import AgentLoop
from agent_runtime.agent.messages import (
    AssistantMessage,
    ImageAttachment,
    Message,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from agent_runtime.config import Settings
from agent_runtime.tools.base import ToolOutput
from agent_runtime.tools.registry import ToolRegistry

from .fakes import (
    SYSTEM_PROMPT,
    EchoTool,
    FakeChatModel,
    echo_registry,
    final_turn,
    tool_call_turn,
    usage,
)


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"stream_tokens": False, "max_steps": 4, "run_timeout_s": 5}
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # type: ignore[arg-type, call-arg]


def make_loop(
    tools: ToolRegistry, model: FakeChatModel, settings: Settings | None = None
) -> AgentLoop:
    return AgentLoop(
        settings=settings or make_settings(),
        tools=tools,
        model=model,
        system_prompt=SYSTEM_PROMPT,
    )


@pytest.mark.asyncio
async def test_direct_answer_needs_no_tool_call() -> None:
    model = FakeChatModel(turns=[final_turn("2 + 2 is 4.")])
    loop = make_loop(echo_registry(), model)

    events = [event async for event in loop.run("what is 2 + 2?")]

    assert isinstance(events[-1], FinalAnswer)
    assert events[-1].content == "2 + 2 is 4."
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_tool_call_then_final_answer() -> None:
    model = FakeChatModel(
        turns=[
            tool_call_turn("echo", {"text": "6 * 7"}),
            final_turn("6 * 7 is 42."),
        ]
    )
    loop = make_loop(echo_registry(), model)

    events = [event async for event in loop.run("what is 6 * 7?")]

    requested = [e for e in events if isinstance(e, ToolCallRequested)]
    results = [e for e in events if isinstance(e, ToolCallResult)]
    assert [e.tool_name for e in requested] == ["echo"]
    assert [e.content for e in results] == ["6 * 7"]
    assert not results[0].is_error
    assert isinstance(events[-1], FinalAnswer)
    assert events[-1].content == "6 * 7 is 42."
    # Second model call must have seen the tool's observation in its transcript.
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_unknown_tool_reports_error_but_keeps_running() -> None:
    model = FakeChatModel(
        turns=[
            tool_call_turn("does_not_exist", {}),
            final_turn("I could not find that tool."),
        ]
    )
    loop = make_loop(echo_registry(), model)

    events = [event async for event in loop.run("try a missing tool")]

    results = [e for e in events if isinstance(e, ToolCallResult)]
    assert results[0].is_error
    assert "Unknown tool" in results[0].content
    assert isinstance(events[-1], FinalAnswer)


@pytest.mark.asyncio
async def test_max_steps_exceeded_yields_run_failed() -> None:
    # Model always asks for another tool call and never finalizes.
    turns = [tool_call_turn("echo", {"text": "again"}, call_id=f"call_{i}") for i in range(10)]
    model = FakeChatModel(turns=turns)
    loop = make_loop(echo_registry(), model, make_settings(max_steps=2))

    events = [event async for event in loop.run("loop forever")]

    assert isinstance(events[-1], RunFailed)
    assert "did not finish" in events[-1].reason


@pytest.mark.asyncio
async def test_usage_accumulates_across_steps() -> None:
    model = FakeChatModel(
        turns=[
            tool_call_turn("echo", {"text": "hi"}, token_usage=usage(100, 20, 0.001)),
            final_turn("It is 4.", token_usage=usage(150, 30, 0.002)),
        ],
        model_id="gpt-4o",
    )
    loop = make_loop(echo_registry(), model)

    events = [event async for event in loop.run("2 + 2?")]
    usage_events = [e for e in events if isinstance(e, UsageUpdated)]

    assert len(usage_events) == 2
    assert usage_events[0].step_usage.total_tokens == 120
    assert usage_events[0].model == "gpt-4o"
    # The second event carries the running total for the whole run, not just its step.
    assert usage_events[1].step_usage.total_tokens == 180
    assert usage_events[1].run_usage.input_tokens == 250
    assert usage_events[1].run_usage.output_tokens == 50
    assert usage_events[1].run_usage.total_tokens == 300
    assert usage_events[1].run_usage.cost_usd == 0.003


@pytest.mark.asyncio
async def test_no_usage_event_when_provider_reports_none() -> None:
    model = FakeChatModel(turns=[final_turn("hello")])
    loop = make_loop(echo_registry(), model)

    events = [event async for event in loop.run("hi")]

    # Absent counts stay absent rather than being reported as a free run.
    assert not [e for e in events if isinstance(e, UsageUpdated)]
    assert isinstance(events[-1], FinalAnswer)


@pytest.mark.asyncio
async def test_transcript_is_extended_in_place() -> None:
    model = FakeChatModel(turns=[tool_call_turn("echo", {"text": "hi"}), final_turn("It's 2.")])
    loop = make_loop(echo_registry(), model)
    transcript: list[Message] = [UserMessage(content="earlier"), AssistantMessage(content="ok")]

    events = [event async for event in loop.run("what is 1 + 1?", transcript)]

    assert isinstance(events[-1], FinalAnswer)
    # The system prompt is put first, and the turn's messages are appended.
    assert isinstance(transcript[0], SystemMessage)
    assert transcript[0].content == SYSTEM_PROMPT
    kinds = [type(m) for m in transcript[1:]]
    assert kinds == [
        UserMessage, AssistantMessage, UserMessage, AssistantMessage, ToolMessage, AssistantMessage,
    ]  # fmt: skip


@pytest.mark.asyncio
async def test_streaming_emits_tokens_then_the_answer() -> None:
    model = FakeChatModel(turns=[final_turn("Hello there friend")])
    loop = make_loop(echo_registry(), model, make_settings(stream_tokens=True))

    events = [event async for event in loop.run("hi")]

    tokens = "".join(e.text for e in events if isinstance(e, ModelToken))
    assert tokens.strip() == "Hello there friend"
    assert isinstance(events[-1], FinalAnswer)
    assert events[-1].content == "Hello there friend"


@pytest.mark.asyncio
async def test_run_failed_reports_the_step_it_failed_on() -> None:
    class ExplodingModel(FakeChatModel):
        async def invoke(self, messages: list[Message]) -> AssistantMessage:
            if self._index == 1:
                raise ConnectionError("provider down")
            return await super().invoke(messages)

    model = ExplodingModel(turns=[tool_call_turn("echo", {"text": "x"}), final_turn("never")])
    events = [event async for event in make_loop(echo_registry(), model).run("go")]

    assert isinstance(events[-1], RunFailed)
    assert events[-1].step == 2
    assert events[-1].reason == "ConnectionError: provider down"


@pytest.mark.asyncio
async def test_invalid_arguments_are_reported_to_the_model() -> None:
    model = FakeChatModel(
        turns=[tool_call_turn("echo", {"wrong": "field"}), final_turn("Retrying failed.")]
    )
    loop = make_loop(echo_registry(), model)

    events = [event async for event in loop.run("echo")]

    result = next(e for e in events if isinstance(e, ToolCallResult))
    assert result.is_error
    assert "Invalid arguments for 'echo'" in result.content
    assert isinstance(events[-1], FinalAnswer)


@pytest.mark.asyncio
async def test_tool_images_reach_the_transcript_but_not_the_event() -> None:
    image = ImageAttachment(media_type="image/png", data="AAAA", label="x.png")

    class PictureTool(EchoTool):
        name = "picture"

        async def run(self, text: str) -> ToolOutput:  # type: ignore[override]
            return ToolOutput(content=f"showing {text}", images=[image])

    model = FakeChatModel(
        turns=[tool_call_turn("picture", {"text": "x.png"}), final_turn("A red square.")]
    )
    loop = make_loop(ToolRegistry([PictureTool()]), model)

    events = [event async for event in loop.run("what is in x.png?")]

    result = next(e for e in events if isinstance(e, ToolCallResult))
    assert result.content == "showing x.png"
    assert result.image_count == 1
    # The second model call sees the image attached to the tool's message.
    tool_messages = [m for m in model.calls[1] if isinstance(m, ToolMessage)]
    assert tool_messages[0].images == [image]
