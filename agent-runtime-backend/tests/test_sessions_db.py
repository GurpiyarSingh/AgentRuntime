"""Persistent sessions and the run activity log, on SQLite (same code as PostgreSQL)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_runtime.agent.loop import AgentLoop
from agent_runtime.agent.messages import (
    AssistantMessage,
    ImageAttachment,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from agent_runtime.api.app import create_app
from agent_runtime.api.deps import get_agent_factory
from agent_runtime.config import Settings
from agent_runtime.files.workspace import Workspace
from agent_runtime.runtime import AgentFactory
from agent_runtime.sessions import trim_history
from agent_runtime.storage import async_database_url
from agent_runtime.storage.codec import decode_message, encode_message

from .fakes import FakeChatModel, final_turn, tool_call_turn, usage


class Harness:
    """An app on a SQLite file, with a scripted model shared across requests."""

    def __init__(self, tmp_path: Path, turns: list[AssistantMessage], **overrides: object):
        self.settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            stream_tokens=True,
            workspace_dir=tmp_path / "workspace",
            database_url=f"sqlite:///{(tmp_path / 'agent.db').as_posix()}",
            **({"auth_enabled": False} | overrides),
        )
        self.app = create_app(settings=self.settings)
        self.model = FakeChatModel(turns=turns)
        factory = AgentFactory(settings=self.settings, tools=self.app.state.tools)

        def override() -> object:
            def build(model_id: str | None = None, workspace: Workspace | None = None) -> AgentLoop:
                return factory(model_id, model=self.model, workspace=workspace)

            return build

        self.app.dependency_overrides[get_agent_factory] = override


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[tuple[Harness, TestClient]]:
    h = Harness(
        tmp_path,
        [
            tool_call_turn("list_files", {}, token_usage=usage(50, 5, 0.001)),
            final_turn("Nothing here yet.", token_usage=usage(80, 12, 0.002)),
            final_turn("Second answer."),
        ],
    )
    with TestClient(h.app) as client:  # `with` runs the lifespan, which creates the tables.
        yield h, client


def stream(client: TestClient, body: dict[str, object]) -> str:
    with client.stream("POST", "/v1/chat/stream", json=body) as response:
        assert response.status_code == 200
        return "".join(response.iter_text())


def test_a_streamed_run_is_recorded_with_every_event(harness: tuple[Harness, TestClient]) -> None:
    _, client = harness
    stream(client, {"message": "What files are there?\nPlease list them.", "session_id": "s1"})

    health = client.get("/health").json()
    sessions = client.get("/v1/sessions").json()["sessions"]
    detail = client.get("/v1/sessions/s1").json()

    assert health["history"] is True
    assert [s["id"] for s in sessions] == ["s1"]
    summary = sessions[0]
    assert summary["title"] == "What files are there?"
    assert summary["run_count"] == 1
    assert summary["usage"]["total_tokens"] == 147
    assert summary["usage"]["cost_usd"] == pytest.approx(0.003)  # Both steps.

    (run,) = detail["runs"]
    assert run["status"] == "completed"
    assert run["answer"] == "Nothing here yet."
    assert run["steps_used"] == 2
    assert run["tool_call_count"] == 1
    types = [event["type"] for event in run["events"]]
    assert types[0] == "run_started"
    assert types[-1] == "final_answer"
    assert {"tool_call_requested", "tool_call_result", "usage_updated"} <= set(types)
    # Streamed word by word, stored as one event per step.
    tokens = [e for e in run["events"] if e["type"] == "model_token" and e["data"]["step"] == 2]
    assert len(tokens) == 1
    assert tokens[0]["data"]["text"].strip() == "Nothing here yet."
    assert tokens[0]["data"]["session_id"] == "s1"


def test_tool_calls_are_queryable(harness: tuple[Harness, TestClient]) -> None:
    h, client = harness
    stream(client, {"message": "list", "session_id": "s1"})

    from sqlalchemy import select

    from agent_runtime.storage.tables import ToolCallRow

    async def rows() -> list[ToolCallRow]:
        async with h.app.state.sessions.db() as db:
            return list(await db.scalars(select(ToolCallRow)))

    (call,) = client.portal.call(rows)  # type: ignore[union-attr]
    assert call.tool_name == "list_files"
    assert call.status == "ok"
    assert call.session_id == "s1"
    assert call.duration_s is not None


def test_history_survives_a_restart(tmp_path: Path) -> None:
    first = Harness(tmp_path, [final_turn("One.")])
    with TestClient(first.app) as client:
        stream(client, {"message": "remember 42", "session_id": "s1"})

    second = Harness(tmp_path, [final_turn("It was 42.")])
    with TestClient(second.app) as client:
        stream(client, {"message": "what number?", "session_id": "s1"})
        detail = client.get("/v1/sessions/s1").json()

    seen = second.model.calls[0]
    assert [type(m).__name__ for m in seen] == [
        "SystemMessage",
        "UserMessage",
        "AssistantMessage",
        "UserMessage",
    ]
    assert seen[1].content == "remember 42"  # type: ignore[union-attr]
    assert len(detail["runs"]) == 2
    assert detail["run_count"] == 2


def test_rename_and_delete(harness: tuple[Harness, TestClient]) -> None:
    _, client = harness
    stream(client, {"message": "list", "session_id": "s1"})

    renamed = client.patch("/v1/sessions/s1", json={"title": "My session"})
    assert renamed.json()["title"] == "My session"

    assert client.delete("/v1/sessions/s1").status_code == 204
    assert client.get("/v1/sessions/s1").status_code == 404
    assert client.get("/v1/sessions").json()["sessions"] == []
    assert client.delete("/v1/sessions/s1").status_code == 404


def test_non_streaming_chat_is_recorded_too(harness: tuple[Harness, TestClient]) -> None:
    _, client = harness
    body = client.post("/v1/chat", json={"message": "list", "session_id": "s2"}).json()

    (run,) = client.get("/v1/sessions/s2").json()["runs"]
    assert run["id"] == body["run_id"]
    assert run["status"] == "completed"


def test_sessions_api_needs_a_database(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, workspace_dir=tmp_path / "ws")  # type: ignore[call-arg]
    client = TestClient(create_app(settings=settings))

    assert client.get("/health").json()["history"] is False
    assert client.get("/v1/sessions").status_code == 501


# --- pieces ------------------------------------------------------------------


def test_messages_round_trip_through_the_codec() -> None:
    messages = [
        SystemMessage("rules"),
        UserMessage("hi"),
        AssistantMessage("", [ToolCall("c1", "read_image", {"path": "a.png"})], usage(1, 2)),
        ToolMessage("c1", "read_image", "an image", images=[ImageAttachment("image/png", "AAA=")]),
        AssistantMessage("done"),
    ]
    for message in messages:
        assert decode_message(*encode_message(message)) == message


def test_trimming_never_starts_on_orphaned_tool_results() -> None:
    messages = [
        SystemMessage("rules"),
        UserMessage("1"),
        AssistantMessage("", [ToolCall("c1", "t", {})]),
        ToolMessage("c1", "t", "r1"),
        UserMessage("2"),
    ]
    # Keeping 3 would start right after the assistant turn, on its tool result.
    trimmed = trim_history(messages, 3)
    assert trimmed == [SystemMessage("rules"), UserMessage("2")]


def test_plain_database_urls_get_an_async_driver() -> None:
    assert async_database_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert async_database_url("sqlite:///x.db") == "sqlite+aiosqlite:///x.db"
    assert async_database_url("postgresql+asyncpg://h/db") == "postgresql+asyncpg://h/db"
