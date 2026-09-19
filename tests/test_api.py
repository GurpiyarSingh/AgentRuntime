from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_runtime.agents.registry import AgentRegistry
from agent_runtime.api.app import create_app
from agent_runtime.api.deps import get_orchestrator
from agent_runtime.config import Settings
from agent_runtime.mail.message import EmailPolicy
from agent_runtime.mail.transport import RecordingTransport
from agent_runtime.orchestrator.orchestrator import Orchestrator
from agent_runtime.tools.email_tools import email_tools

from .fakes import FakeChatModel, fake_agent, final_turn, tool_call_turn, usage


def _client_with_scripted_turns(
    turns: list,
    agents: AgentRegistry | None = None,
    routes_to: str = "email",
    **setting_overrides: object,
) -> TestClient:
    settings = Settings(stream_tokens=False, _env_file=None, **setting_overrides)  # type: ignore[arg-type, call-arg]
    app = create_app(settings=settings)
    if agents is not None:
        app.state.agents = agents

    # One model instance across requests, so a multi-turn test keeps working
    # through the same script instead of restarting it each call.
    model = FakeChatModel(turns=turns)
    # Routing gets its own model: with more than one agent registered the
    # router makes a real call, and it must not eat the agent's script.
    router_model = FakeChatModel(turns=[final_turn(routes_to) for _ in range(50)])

    def override() -> object:
        # Mirrors OrchestratorFactory: the route picks the model, we just
        # build an orchestrator around the scripted fake.
        def build(model_id: str | None = None) -> Orchestrator:
            model.model_id = model_id or settings.openai_model
            return Orchestrator(
                settings=settings,
                agents=app.state.agents,
                model_id=model_id,
                model_factory=lambda spec: model,
                routing_model=router_model,
            )

        return build

    app.dependency_overrides[get_orchestrator] = override
    return TestClient(app)


# --- meta endpoints ----------------------------------------------------------


def test_health_reports_agents_and_email_posture() -> None:
    client = _client_with_scripted_turns([final_turn("unused")], email_from="bot@example.com")
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["agents"] == ["email", "youtube"]
    # Nothing is configured to send, so the server must say it is a dry run.
    assert body["email"]["dry_run"] is True
    assert body["email"]["sender"] == "bot@example.com"


def test_health_reports_live_sending_when_fully_configured() -> None:
    client = _client_with_scripted_turns(
        [final_turn("unused")],
        email_from="bot@example.com",
        email_dry_run=False,
        smtp_host="smtp.example.com",
    )
    assert client.get("/health").json()["email"]["dry_run"] is False


def test_agents_endpoint_lists_every_agent_with_its_tools() -> None:
    client = _client_with_scripted_turns([final_turn("unused")])
    body = client.get("/v1/agents").json()

    assert body["default"] == "email"
    agents = {agent["name"]: agent for agent in body["agents"]}
    assert list(agents) == ["email", "youtube"]
    assert agents["email"]["tools"] == ["send_email"]
    assert agents["youtube"]["tools"] == ["search_youtube"]
    assert all(agent["label"] and agent["description"] for agent in agents.values())


def test_agents_endpoint_reports_readiness_honestly() -> None:
    client = _client_with_scripted_turns([final_turn("unused")])
    agents = {a["name"]: a for a in client.get("/v1/agents").json()["agents"]}

    # Email works in dry run, so it is ready but carries a caveat.
    assert agents["email"]["ready"] is True
    assert "Dry run" in agents["email"]["status"]
    # YouTube has no key here, so it says so rather than failing later.
    assert agents["youtube"]["ready"] is False
    assert "YOUTUBE_API_KEY" in agents["youtube"]["status"]


def test_youtube_agent_is_ready_once_a_key_is_configured() -> None:
    client = _client_with_scripted_turns([final_turn("unused")], youtube_api_key="yt-key")
    agents = {a["name"]: a for a in client.get("/v1/agents").json()["agents"]}

    assert agents["youtube"]["ready"] is True
    assert agents["youtube"]["status"] == ""
    assert client.get("/health").json()["youtube"]["configured"] is True


def test_chat_can_be_routed_to_the_youtube_agent() -> None:
    client = _client_with_scripted_turns([final_turn("Here is the link.")], routes_to="youtube")
    body = client.post("/v1/chat", json={"message": "find me a video"}).json()
    assert body["agent"] == "youtube"


def test_models_endpoint_lists_selectable_models_with_prices() -> None:
    client = _client_with_scripted_turns([final_turn("unused")])
    body = client.get("/v1/models").json()

    assert body["default"] == "gpt-4o"
    ids = [model["id"] for model in body["models"]]
    assert ids == ["gpt-4o", "gpt-5.2"]
    assert all(model["input_usd_per_1m"] > 0 for model in body["models"])


def test_models_endpoint_reflects_price_overrides() -> None:
    client = _client_with_scripted_turns(
        [final_turn("unused")],
        model_pricing_json='{"gpt-4o": {"input_usd_per_1m": 9.0, "output_usd_per_1m": 9.5}}',
    )
    models = {model["id"]: model for model in client.get("/v1/models").json()["models"]}
    assert models["gpt-4o"]["input_usd_per_1m"] == 9.0


# --- chat --------------------------------------------------------------------


def test_chat_returns_final_answer_and_the_agent_that_produced_it() -> None:
    client = _client_with_scripted_turns([final_turn("I sent it.")])
    response = client.post("/v1/chat", json={"message": "email alex@example.com hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "I sent it."
    assert body["agent"] == "email"
    assert body["model"] == "gpt-4o"
    assert body["steps_used"] == 1
    assert body["session_id"]


def test_chat_reports_the_send_email_tool_call() -> None:
    transport = RecordingTransport()
    agents = AgentRegistry(
        [
            fake_agent(
                "email",
                tools=email_tools(EmailPolicy(sender="bot@example.com"), transport),
            )
        ]
    )
    client = _client_with_scripted_turns(
        [
            tool_call_turn(
                "send_email",
                {"to": ["alex@example.com"], "subject": "Hi", "body": "Hello there."},
            ),
            final_turn("Sent it to alex@example.com."),
        ],
        agents=agents,
    )

    body = client.post("/v1/chat", json={"message": "email alex"}).json()

    assert len(body["tool_calls"]) == 1
    call = body["tool_calls"][0]
    assert call["tool_name"] == "send_email"
    assert call["is_error"] is False
    assert call["arguments"]["to"] == ["alex@example.com"]
    # The email really went through the transport the agent was built with.
    assert len(transport.sent) == 1
    assert transport.sent[0].subject == "Hi"


def test_chat_honours_requested_agent() -> None:
    agents = AgentRegistry([fake_agent("first"), fake_agent("second")])
    client = _client_with_scripted_turns([final_turn("done")], agents=agents)

    body = client.post("/v1/chat", json={"message": "hi", "agent": "second"}).json()
    assert body["agent"] == "second"


def test_chat_rejects_unknown_agent() -> None:
    client = _client_with_scripted_turns([final_turn("unused")])
    response = client.post("/v1/chat", json={"message": "hi", "agent": "accounting"})

    assert response.status_code == 400
    assert "accounting" in response.json()["detail"]


def test_chat_honours_requested_model() -> None:
    client = _client_with_scripted_turns([final_turn("done")])
    body = client.post("/v1/chat", json={"message": "hi", "model": "gpt-5.2"}).json()
    assert body["model"] == "gpt-5.2"


def test_chat_rejects_unknown_model() -> None:
    client = _client_with_scripted_turns([final_turn("unused")])
    response = client.post("/v1/chat", json={"message": "hi", "model": "gpt-9000"})
    assert response.status_code == 400


def test_chat_reports_token_usage_and_cost() -> None:
    client = _client_with_scripted_turns(
        [
            tool_call_turn("send_email", {}, token_usage=usage(100, 20, 0.001)),
            final_turn("Sent.", token_usage=usage(140, 30, 0.002)),
        ]
    )
    body = client.post("/v1/chat", json={"message": "email someone"}).json()

    assert body["usage"]["total_tokens"] == 290
    assert body["usage"]["cost_usd"] == 0.003


def test_chat_persists_session_history() -> None:
    client = _client_with_scripted_turns([final_turn("first"), final_turn("second")])
    first = client.post("/v1/chat", json={"message": "hello"})
    session_id = first.json()["session_id"]
    second = client.post("/v1/chat", json={"message": "again", "session_id": session_id})
    assert second.json()["answer"] == "second"


def test_chat_reports_failure_as_status_not_answer() -> None:
    client = _client_with_scripted_turns(
        [tool_call_turn("send_email", {}, call_id=f"c{i}") for i in range(5)], max_steps=2
    )
    body = client.post("/v1/chat", json={"message": "never finish"}).json()

    assert body["status"] == "failed"
    assert body["answer"] == ""
    assert "did not finish" in body["error"]


# --- streaming ---------------------------------------------------------------


def test_chat_stream_emits_routing_and_loop_events() -> None:
    client = _client_with_scripted_turns([final_turn("Sent it.")])
    with client.stream("POST", "/v1/chat/stream", json={"message": "email alex"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    # Routing brackets the agent's own events.
    assert "event: agent_selected" in body
    assert "event: run_started" in body
    assert "event: final_answer" in body
    assert "event: agent_completed" in body
    # Two agents are registered, so the router actually made a choice.
    assert '"routed_by": "model"' in body
    assert "Sent it." in body


def test_chat_stream_emits_usage_events() -> None:
    client = _client_with_scripted_turns(
        [final_turn("Sent.", token_usage=usage(80, 12, 0.0004))]
    )
    with client.stream(
        "POST", "/v1/chat/stream", json={"message": "email alex", "model": "gpt-5.2"}
    ) as response:
        body = "".join(response.iter_text())

    assert "event: usage_updated" in body
    assert '"total_tokens": 92' in body
    assert "gpt-5.2" in body


def test_chat_stream_rejects_unknown_agent() -> None:
    client = _client_with_scripted_turns([final_turn("unused")])
    response = client.post("/v1/chat/stream", json={"message": "hi", "agent": "nope"})
    assert response.status_code == 400


# --- app plumbing ------------------------------------------------------------


def test_root_redirects_to_ui() -> None:
    client = _client_with_scripted_turns([final_turn("unused")])
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/ui/"


def test_ui_is_served() -> None:
    client = _client_with_scripted_turns([final_turn("unused")])
    page = client.get("/ui/")
    assert page.status_code == 200
    assert "Agent Runtime" in page.text

    for asset in ("/ui/app.js", "/ui/styles.css"):
        assert client.get(asset).status_code == 200


def test_chat_rejects_empty_message() -> None:
    client = _client_with_scripted_turns([final_turn("unused")])
    assert client.post("/v1/chat", json={"message": ""}).status_code == 422


@pytest.mark.parametrize("path", ["/v1/chat"])
def test_requires_api_key_when_configured(path: str) -> None:
    client = _client_with_scripted_turns([final_turn("hi")], api_key="secret-key")

    assert client.post(path, json={"message": "hi"}).status_code == 401
    authorized = client.post(path, json={"message": "hi"}, headers={"X-API-Key": "secret-key"})
    assert authorized.status_code == 200
