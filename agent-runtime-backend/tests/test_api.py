from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_runtime.agent.loop import AgentLoop
from agent_runtime.api.app import create_app
from agent_runtime.api.deps import get_agent_factory
from agent_runtime.config import Settings
from agent_runtime.files.workspace import Workspace
from agent_runtime.runtime import AgentFactory

from .fakes import FakeChatModel, final_turn, tool_call_turn, usage


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


def make_client(
    workspace_dir: Path, turns: list | None = None, **setting_overrides: object
) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, stream_tokens=False, workspace_dir=workspace_dir, **setting_overrides
    )
    app = create_app(settings=settings)

    # One model instance across requests, so a multi-turn test keeps working
    # through the same script instead of restarting it each call.
    model = FakeChatModel(turns=turns or [final_turn("unused")])
    factory = AgentFactory(settings=settings, tools=app.state.tools)

    def override() -> object:
        def build(model_id: str | None = None, workspace: Workspace | None = None) -> AgentLoop:
            model.model_id = model_id or settings.openai_model
            return factory(model_id, model=model, workspace=workspace)

        return build

    app.dependency_overrides[get_agent_factory] = override
    return TestClient(app)


# --- meta endpoints ----------------------------------------------------------


def test_health_reports_tools_and_workspace(workspace_dir: Path) -> None:
    body = make_client(workspace_dir).get("/health").json()

    assert body["status"] == "ok"
    assert body["tools"] == [
        "list_files",
        "read_file",
        "read_image",
        "search_files",
        "write_file",
        "edit_file",
    ]
    assert body["workspace"]["read_only"] is False
    assert Path(body["workspace"]["path"]) == workspace_dir.resolve()
    # The workspace is created on startup.
    assert workspace_dir.is_dir()


def test_read_only_workspace_has_no_writing_tools(workspace_dir: Path) -> None:
    body = make_client(workspace_dir, workspace_read_only=True).get("/health").json()

    assert body["workspace"]["read_only"] is True
    assert "write_file" not in body["tools"]
    assert "edit_file" not in body["tools"]
    assert "read_file" in body["tools"]


def test_health_hides_workspace_path_in_prod(workspace_dir: Path) -> None:
    body = make_client(workspace_dir, environment="prod").get("/health").json()
    assert body["workspace"]["path"] is None


def test_tools_endpoint_returns_model_facing_schemas(workspace_dir: Path) -> None:
    tools = {t["name"]: t for t in make_client(workspace_dir).get("/v1/tools").json()["tools"]}

    assert tools["read_file"]["description"]
    assert tools["read_file"]["parameters"]["required"] == ["path"]
    assert "encoding" in tools["write_file"]["parameters"]["properties"]


def test_models_endpoint_lists_selectable_models_with_prices(workspace_dir: Path) -> None:
    body = make_client(workspace_dir).get("/v1/models").json()

    assert body["default"] == "gpt-4o"
    assert [model["id"] for model in body["models"]] == ["gpt-4o", "gpt-5.2"]
    assert all(model["input_usd_per_1m"] > 0 for model in body["models"])


def test_models_endpoint_reflects_price_overrides(workspace_dir: Path) -> None:
    client = make_client(
        workspace_dir,
        model_pricing_json='{"gpt-4o": {"input_usd_per_1m": 9.0, "output_usd_per_1m": 9.5}}',
    )
    models = {model["id"]: model for model in client.get("/v1/models").json()["models"]}
    assert models["gpt-4o"]["input_usd_per_1m"] == 9.0


# --- chat --------------------------------------------------------------------


def test_chat_returns_final_answer(workspace_dir: Path) -> None:
    client = make_client(workspace_dir, [final_turn("Hello!")])
    response = client.post("/v1/chat", json={"message": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Hello!"
    assert body["status"] == "completed"
    assert body["model"] == "gpt-4o"
    assert body["steps_used"] == 1
    assert body["session_id"]


def test_chat_runs_real_file_tools_in_the_workspace(workspace_dir: Path) -> None:
    client = make_client(
        workspace_dir,
        [
            tool_call_turn("write_file", {"path": "notes/todo.md", "content": "# Todo\n- ship"}),
            final_turn("Created notes/todo.md."),
        ],
    )

    body = client.post("/v1/chat", json={"message": "make a todo list"}).json()

    assert body["answer"] == "Created notes/todo.md."
    call = body["tool_calls"][0]
    assert call["tool_name"] == "write_file"
    assert call["is_error"] is False
    assert call["arguments"]["path"] == "notes/todo.md"
    assert (workspace_dir / "notes" / "todo.md").read_text(encoding="utf-8") == "# Todo\n- ship"


def test_chat_reports_tool_errors_without_failing_the_run(workspace_dir: Path) -> None:
    client = make_client(
        workspace_dir,
        [
            tool_call_turn("read_file", {"path": "../outside.txt"}),
            final_turn("I can't read outside the workspace."),
        ],
    )

    body = client.post("/v1/chat", json={"message": "read it"}).json()

    assert body["status"] == "completed"
    assert body["tool_calls"][0]["is_error"] is True
    assert "outside the workspace" in body["tool_calls"][0]["content"]


def test_chat_honours_requested_model(workspace_dir: Path) -> None:
    client = make_client(workspace_dir, [final_turn("done")])
    body = client.post("/v1/chat", json={"message": "hi", "model": "gpt-5.2"}).json()
    assert body["model"] == "gpt-5.2"


def test_chat_rejects_unknown_model(workspace_dir: Path) -> None:
    response = make_client(workspace_dir).post(
        "/v1/chat", json={"message": "hi", "model": "gpt-9000"}
    )
    assert response.status_code == 400


def test_chat_reports_token_usage_and_cost(workspace_dir: Path) -> None:
    client = make_client(
        workspace_dir,
        [
            tool_call_turn("list_files", {}, token_usage=usage(100, 20, 0.001)),
            final_turn("Empty.", token_usage=usage(140, 30, 0.002)),
        ],
    )
    body = client.post("/v1/chat", json={"message": "what's here?"}).json()

    assert body["usage"]["total_tokens"] == 290
    assert body["usage"]["cost_usd"] == 0.003


def test_chat_persists_session_history(workspace_dir: Path) -> None:
    client = make_client(workspace_dir, [final_turn("first"), final_turn("second")])
    session_id = client.post("/v1/chat", json={"message": "hello"}).json()["session_id"]
    second = client.post("/v1/chat", json={"message": "again", "session_id": session_id})
    assert second.json()["answer"] == "second"


def test_chat_reports_failure_as_status_not_answer(workspace_dir: Path) -> None:
    client = make_client(
        workspace_dir,
        [tool_call_turn("list_files", {}, call_id=f"c{i}") for i in range(5)],
        max_steps=2,
    )
    body = client.post("/v1/chat", json={"message": "never finish"}).json()

    assert body["status"] == "failed"
    assert body["answer"] == ""
    assert "did not finish" in body["error"]


def test_chat_rejects_empty_message(workspace_dir: Path) -> None:
    assert make_client(workspace_dir).post("/v1/chat", json={"message": ""}).status_code == 422


# --- streaming ---------------------------------------------------------------


def test_chat_stream_emits_loop_events(workspace_dir: Path) -> None:
    client = make_client(
        workspace_dir,
        [
            tool_call_turn("list_files", {}),
            final_turn("Nothing here yet.", token_usage=usage(80, 12, 0.0004)),
        ],
    )
    with client.stream(
        "POST", "/v1/chat/stream", json={"message": "list", "model": "gpt-5.2"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    for name in ("run_started", "tool_call_requested", "tool_call_result", "usage_updated"):
        assert f"event: {name}" in body
    assert "event: final_answer" in body
    assert '"total_tokens": 92' in body
    assert "gpt-5.2" in body
    assert "Nothing here yet." in body


def test_chat_stream_rejects_unknown_model(workspace_dir: Path) -> None:
    response = make_client(workspace_dir).post(
        "/v1/chat/stream", json={"message": "hi", "model": "nope"}
    )
    assert response.status_code == 400


# --- auth --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/v1/chat"), ("get", "/v1/files"), ("get", "/v1/files/a.txt")],
)
def test_requires_api_key_when_configured(workspace_dir: Path, method: str, path: str) -> None:
    client = make_client(workspace_dir, [final_turn("hi")], api_key="secret-key")
    (workspace_dir / "a.txt").write_text("a")
    kwargs: dict[str, object] = {"json": {"message": "hi"}} if method == "post" else {}

    assert getattr(client, method)(path, **kwargs).status_code == 401
    authorized = getattr(client, method)(path, headers={"X-API-Key": "secret-key"}, **kwargs)
    assert authorized.status_code == 200


def test_no_ui_is_served(workspace_dir: Path) -> None:
    client = make_client(workspace_dir)
    assert client.get("/").status_code == 404
    assert client.get("/ui/").status_code == 404


# --- configuration failures --------------------------------------------------


def test_chat_without_openai_key_is_503_not_500(workspace_dir: Path) -> None:
    settings = Settings(_env_file=None, workspace_dir=workspace_dir)  # type: ignore[call-arg]
    client = TestClient(create_app(settings=settings))  # Real factory, no key.

    response = client.post("/v1/chat", json={"message": "hi"})

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_chat_without_openai_key_hides_detail_in_prod(workspace_dir: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, workspace_dir=workspace_dir, environment="prod"
    )
    response = TestClient(create_app(settings=settings)).post("/v1/chat", json={"message": "hi"})

    assert response.status_code == 503
    assert "OPENAI_API_KEY" not in response.json()["detail"]


@pytest.mark.parametrize("session_id", ["has space", "x" * 129, "../etc"])
def test_chat_rejects_malformed_session_ids(workspace_dir: Path, session_id: str) -> None:
    response = make_client(workspace_dir).post(
        "/v1/chat", json={"message": "hi", "session_id": session_id}
    )
    assert response.status_code == 422


# --- choosing the workspace directory --------------------------------------


def test_chat_works_in_the_directory_the_request_chose(workspace_dir: Path, tmp_path: Path) -> None:
    chosen = tmp_path / "project"
    chosen.mkdir()
    client = make_client(
        workspace_dir,
        [tool_call_turn("write_file", {"path": "a.txt", "content": "hi"}), final_turn("done")],
    )

    body = client.post("/v1/chat", json={"message": "write", "workspace": str(chosen)}).json()

    assert body["tool_calls"][0]["is_error"] is False
    assert (chosen / "a.txt").read_text(encoding="utf-8") == "hi"
    assert not (workspace_dir / "a.txt").exists()


def test_chat_refuses_a_missing_or_relative_directory(workspace_dir: Path, tmp_path: Path) -> None:
    client = make_client(workspace_dir)

    missing = client.post("/v1/chat", json={"message": "hi", "workspace": str(tmp_path / "nope")})
    relative = client.post("/v1/chat", json={"message": "hi", "workspace": "some/dir"})

    assert missing.status_code == 400
    assert "not found" in missing.json()["detail"]
    assert relative.status_code == 400


def test_chat_refuses_another_directory_when_selection_is_off(
    workspace_dir: Path, tmp_path: Path
) -> None:
    client = make_client(workspace_dir, workspace_selectable=False)

    response = client.post("/v1/chat", json={"message": "hi", "workspace": str(tmp_path)})

    assert response.status_code == 403
    assert client.get("/health").json()["workspace"]["selectable"] is False


def test_chosen_directory_must_be_under_a_browse_root(workspace_dir: Path, tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    (allowed / "inner").mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    client = make_client(workspace_dir, [final_turn("ok")], workspace_browse_roots=str(allowed))

    inside = client.post("/v1/chat", json={"message": "hi", "workspace": str(allowed / "inner")})
    outside = client.post("/v1/chat", json={"message": "hi", "workspace": str(other)})

    assert inside.status_code == 200
    assert outside.status_code == 400
    assert "outside" in outside.json()["detail"]


def test_directories_lists_subfolders_only(workspace_dir: Path, tmp_path: Path) -> None:
    (tmp_path / "b").mkdir()
    (tmp_path / "A").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    client = make_client(workspace_dir)

    body = client.get("/v1/directories", params={"path": str(tmp_path)}).json()

    names = [entry["name"] for entry in body["directories"]]
    assert names == ["A", "b", "workspace"]
    assert Path(body["path"]) == tmp_path.resolve()
    assert Path(body["parent"]) == tmp_path.resolve().parent


def test_directories_top_level_is_the_browse_roots(workspace_dir: Path, tmp_path: Path) -> None:
    client = make_client(workspace_dir, workspace_browse_roots=str(tmp_path))

    top = client.get("/v1/directories").json()
    at_root = client.get("/v1/directories", params={"path": str(tmp_path)}).json()
    escape = client.get("/v1/directories", params={"path": str(tmp_path.parent)})

    assert top["path"] is None
    assert [Path(entry["path"]) for entry in top["directories"]] == [tmp_path.resolve()]
    assert at_root["parent"] is None
    assert escape.status_code == 400


def test_directories_forbidden_when_selection_is_off(workspace_dir: Path) -> None:
    client = make_client(workspace_dir, workspace_selectable=False)
    assert client.get("/v1/directories").status_code == 403
