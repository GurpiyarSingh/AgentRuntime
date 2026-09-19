from __future__ import annotations

import pytest

from agent_runtime.agent.events import (
    FinalAnswer,
    RunFailed,
    ToolCallRequested,
    ToolCallResult,
    UsageUpdated,
)
from agent_runtime.agent.loop import AgentLoop
from agent_runtime.config import Settings

from .fakes import FakeChatModel, echo_registry, final_turn, tool_call_turn, usage


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"stream_tokens": False, "max_steps": 4, "run_timeout_s": 5}
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # type: ignore[arg-type, call-arg]


@pytest.mark.asyncio
async def test_direct_answer_needs_no_tool_call() -> None:
    model = FakeChatModel(turns=[final_turn("2 + 2 is 4.")])
    loop = AgentLoop(settings=make_settings(), tools=echo_registry(), model=model)

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
    loop = AgentLoop(settings=make_settings(), tools=echo_registry(), model=model)

    events = [event async for event in loop.run("what is 6 * 7?")]

    requested = [e for e in events if isinstance(e, ToolCallRequested)]
    results = [e for e in events if isinstance(e, ToolCallResult)]
    assert requested and requested[0].tool_name == "echo"
    assert results and results[0].content == "6 * 7"
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
    loop = AgentLoop(settings=make_settings(), tools=echo_registry(), model=model)

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
    loop = AgentLoop(settings=make_settings(max_steps=2), tools=echo_registry(), model=model)

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
    loop = AgentLoop(settings=make_settings(), tools=echo_registry(), model=model)

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
    loop = AgentLoop(settings=make_settings(), tools=echo_registry(), model=model)

    events = [event async for event in loop.run("hi")]

    # Absent counts stay absent rather than being reported as a free run.
    assert not [e for e in events if isinstance(e, UsageUpdated)]
    assert isinstance(events[-1], FinalAnswer)


@pytest.mark.asyncio
async def test_run_to_completion_returns_full_transcript() -> None:
    model = FakeChatModel(
        turns=[
            tool_call_turn("echo", {"text": "hi"}, token_usage=usage(10, 2, 0.0001)),
            final_turn("It's 2.", token_usage=usage(20, 4, 0.0002)),
        ],
        model_id="gpt-5.2",
    )
    loop = AgentLoop(settings=make_settings(), tools=echo_registry(), model=model)

    result = await loop.run_to_completion("what is 1 + 1?")

    assert result.final_answer == "It's 2."
    assert result.steps_used == 2
    assert result.model == "gpt-5.2"
    assert result.usage.total_tokens == 36
    assert result.usage.cost_usd == 0.0003
    # system + user + assistant(tool call) + tool + assistant(final)
    assert len(result.messages) == 5
