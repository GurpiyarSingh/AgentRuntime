from __future__ import annotations

import pytest

from agent_runtime.agent.events import FinalAnswer, ToolCallResult
from agent_runtime.agents.registry import AgentRegistry, UnknownAgentError
from agent_runtime.config import Settings
from agent_runtime.orchestrator.events import AgentCompleted, AgentSelected
from agent_runtime.orchestrator.orchestrator import Orchestrator
from agent_runtime.orchestrator.router import AgentRouter

from .fakes import FakeChatModel, fake_agent, final_turn, tool_call_turn, usage


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"stream_tokens": False, "max_steps": 4, "run_timeout_s": 5}
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # type: ignore[arg-type, call-arg]


def orchestrator_with(
    model: FakeChatModel, agents: AgentRegistry, **kwargs: object
) -> Orchestrator:
    return Orchestrator(
        settings=make_settings(),
        agents=agents,
        model_factory=lambda spec: model,
        **kwargs,  # type: ignore[arg-type]
    )


# --- routing -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_agent_is_chosen_without_a_model_call() -> None:
    agents = AgentRegistry([fake_agent()])
    router = AgentRouter(agents, model=None)

    decision = await router.route("anything at all")

    assert decision.agent.name == "echo-agent"
    assert decision.routed_by == "only-agent"


@pytest.mark.asyncio
async def test_explicit_request_wins_over_routing() -> None:
    agents = AgentRegistry([fake_agent("first"), fake_agent("second")])
    # A model that would pick 'first' if it were ever consulted.
    router = AgentRouter(agents, model=FakeChatModel(turns=[final_turn("first")]))

    decision = await router.route("anything", requested="second")

    assert decision.agent.name == "second"
    assert decision.routed_by == "explicit"


@pytest.mark.asyncio
async def test_unknown_explicit_agent_is_rejected() -> None:
    router = AgentRouter(AgentRegistry([fake_agent()]), model=None)
    with pytest.raises(UnknownAgentError, match="nope"):
        await router.route("anything", requested="nope")


@pytest.mark.asyncio
async def test_model_routes_between_several_agents() -> None:
    agents = AgentRegistry([fake_agent("first"), fake_agent("second")])
    model = FakeChatModel(turns=[final_turn("second")])
    router = AgentRouter(agents, model=model)

    decision = await router.route("something only the second agent handles")

    assert decision.agent.name == "second"
    assert decision.routed_by == "model"
    # The router prompt lists every agent so the model can actually choose.
    routing_prompt = model.calls[0][0].content
    assert "first" in routing_prompt and "second" in routing_prompt


@pytest.mark.asyncio
async def test_unusable_routing_answer_falls_back_to_the_default_agent() -> None:
    agents = AgentRegistry([fake_agent("first"), fake_agent("second")])
    router = AgentRouter(agents, model=FakeChatModel(turns=[final_turn("a third thing")]))

    decision = await router.route("anything")

    assert decision.agent.name == "first"  # the default is the first registered
    assert decision.routed_by == "fallback"


@pytest.mark.asyncio
async def test_router_failure_never_fails_the_run() -> None:
    agents = AgentRegistry([fake_agent("first"), fake_agent("second")])
    # An exhausted script raises inside the router.
    router = AgentRouter(agents, model=FakeChatModel(turns=[]))

    decision = await router.route("anything")

    assert decision.agent.name == "first"
    assert decision.routed_by == "fallback"


# --- orchestration -----------------------------------------------------------


@pytest.mark.asyncio
async def test_run_brackets_the_agent_loop_with_routing_events() -> None:
    agents = AgentRegistry([fake_agent()])
    model = FakeChatModel(turns=[final_turn("done")])

    events = [event async for event in orchestrator_with(model, agents).run("hello")]

    assert isinstance(events[0], AgentSelected)
    assert events[0].agent == "echo-agent"
    assert events[0].available == ["echo-agent"]
    assert isinstance(events[-1], AgentCompleted)
    assert events[-1].status == "completed"
    # The agent's own events are in between, unchanged.
    assert any(isinstance(event, FinalAnswer) for event in events)


@pytest.mark.asyncio
async def test_agent_completed_carries_steps_and_usage() -> None:
    agents = AgentRegistry([fake_agent()])
    model = FakeChatModel(
        turns=[
            tool_call_turn("echo", {"text": "hi"}, token_usage=usage(100, 20, 0.001)),
            final_turn("said hi", token_usage=usage(150, 30, 0.002)),
        ]
    )

    events = [event async for event in orchestrator_with(model, agents).run("say hi")]
    completed = events[-1]

    assert isinstance(completed, AgentCompleted)
    assert completed.steps_used == 2
    assert completed.usage.total_tokens == 300
    assert completed.usage.cost_usd == 0.003
    # The selected agent's tools really were the ones called.
    results = [e for e in events if isinstance(e, ToolCallResult)]
    assert results and results[0].content == "hi"


@pytest.mark.asyncio
async def test_failed_run_is_reported_as_failed_not_completed() -> None:
    agents = AgentRegistry([fake_agent()])
    # Never finalizes, so the loop exhausts its step budget.
    model = FakeChatModel(
        turns=[tool_call_turn("echo", {"text": "x"}, call_id=f"c{i}") for i in range(10)]
    )
    orchestrator = Orchestrator(
        settings=make_settings(max_steps=2), agents=agents, model_factory=lambda spec: model
    )

    events = [event async for event in orchestrator.run("loop forever")]

    assert isinstance(events[-1], AgentCompleted)
    assert events[-1].status == "failed"


@pytest.mark.asyncio
async def test_run_to_completion_summarises_the_turn() -> None:
    agents = AgentRegistry([fake_agent()])
    model = FakeChatModel(turns=[final_turn("all done", token_usage=usage(40, 10, 0.0007))])

    result = await orchestrator_with(model, agents).run_to_completion("hello")

    assert result.status == "completed"
    assert result.answer == "all done"
    assert result.agent == "echo-agent"
    assert result.usage.total_tokens == 50
    assert result.error is None
    # system + user + assistant
    assert len(result.messages) == 3


@pytest.mark.asyncio
async def test_each_agent_runs_under_its_own_prompt_and_tools() -> None:
    agents = AgentRegistry([fake_agent("first"), fake_agent("second")])
    model = FakeChatModel(turns=[final_turn("ok")])
    orchestrator = orchestrator_with(model, agents)

    [event async for event in orchestrator.run("hello", agent="second")]

    system_prompt = model.calls[0][0].content
    assert system_prompt == agents.get("second").system_prompt
