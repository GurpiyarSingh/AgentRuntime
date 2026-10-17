"""The MCP client: configs, the tool bridge, live connections, and the API."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import mcp.types as types
import pytest
from fastapi.testclient import TestClient

from agent_runtime.agent.loop import AgentLoop
from agent_runtime.api.app import create_app
from agent_runtime.api.deps import get_agent_factory
from agent_runtime.config import Settings
from agent_runtime.files.workspace import Workspace
from agent_runtime.mcp_client import (
    MASK,
    McpConfigError,
    McpConfigStore,
    McpManager,
    McpServerConfig,
    McpTool,
    parse_import,
    qualified_name,
)
from agent_runtime.mcp_client.client import result_to_output
from agent_runtime.runtime import AgentFactory
from agent_runtime.tools.base import ToolError

from .fakes import FakeChatModel, final_turn, tool_call_turn

ECHO_SERVER = str(Path(__file__).parent / "mcp_echo_server.py")


def echo_config(**overrides: object) -> McpServerConfig:
    return McpServerConfig.model_validate(
        {"command": sys.executable, "args": [ECHO_SERVER], "timeout_s": 30, **overrides}
    )


# --- configs -----------------------------------------------------------------


def test_import_accepts_claude_vscode_and_bare_formats() -> None:
    claude = parse_import(json.dumps({"mcpServers": {"pw": {"command": "npx", "args": ["x"]}}}))
    vscode = parse_import(
        json.dumps({"servers": {"gh": {"type": "http", "url": "https://example.com/mcp"}}})
    )
    bare = parse_import(json.dumps({"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}}))
    single = parse_import(json.dumps({"name": "solo", "url": "https://example.com/sse"}))

    assert claude["pw"].type == "stdio"
    assert claude["pw"].args == ["x"]
    assert vscode["gh"].type == "http"
    assert bare["fetch"].command == "uvx"
    assert single["solo"].type == "sse"  # Inferred from the /sse URL.


def test_config_understands_other_clients_field_names() -> None:
    config = McpServerConfig.model_validate(
        {"transport": "streamable-http", "serverUrl": "https://example.com/mcp"}
    )
    assert config.type == "http"
    assert config.url == "https://example.com/mcp"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{nope", "Not valid JSON"),
        ('{"mcpServers": {"bad name!": {"command": "x"}}}', "Invalid server name"),
        ('{"mcpServers": {"s": {"type": "stdio"}}}', "needs a command"),
        ('{"mcpServers": {"s": {"type": "http", "url": "ftp://x"}}}', "http:// or https://"),
        (
            '{"mcpServers": {"s": {"type": "carrier-pigeon", "url": "https://x"}}}',
            "Unknown transport",
        ),
        ("[]", "Expected a JSON object"),
    ],
)
def test_import_explains_bad_input(text: str, message: str) -> None:
    with pytest.raises(McpConfigError, match=message):
        parse_import(text)


def test_secrets_are_masked_and_kept_when_left_masked() -> None:
    stored = McpServerConfig(
        type="http", url="https://x/mcp", headers={"Authorization": "Bearer secret"}
    )
    masked = stored.masked()
    assert masked.headers == {"Authorization": MASK}

    edited = masked.model_copy(update={"headers": {**masked.headers, "X-Extra": "new"}})
    merged = edited.merged_secrets(stored)

    assert merged.headers == {"Authorization": "Bearer secret", "X-Extra": "new"}


async def test_store_writes_the_claude_desktop_format(tmp_path: Path) -> None:
    store = McpConfigStore(tmp_path / "mcp.json")
    await store.put("pw", McpServerConfig(command="npx", args=["@playwright/mcp@latest"]))

    on_disk = json.loads((tmp_path / "mcp.json").read_text(encoding="utf-8"))
    assert on_disk == {
        "mcpServers": {
            "pw": {"command": "npx", "args": ["@playwright/mcp@latest"], "type": "stdio"}
        }
    }
    # A fresh store (a restart) reads it back.
    assert McpConfigStore(tmp_path / "mcp.json").get("pw") == store.get("pw")
    assert await store.delete("pw") is True
    assert McpConfigStore(tmp_path / "mcp.json").load() == {}


def test_qualified_names_are_safe_function_names() -> None:
    assert qualified_name("github", "create_issue") == "github__create_issue"
    assert qualified_name("jira", "search.issues v2") == "jira__search_issues_v2"
    long = qualified_name("server", "x" * 100)
    assert len(long) == 64
    assert long != qualified_name("server", "x" * 99)  # Distinct, thanks to the hash.


# --- results -----------------------------------------------------------------


def test_results_become_text_and_images() -> None:
    result = types.CallToolResult(
        content=[
            types.TextContent(type="text", text="Here you go"),
            types.ImageContent(type="image", data="iVBORw0KGgo=", mimeType="image/png"),
            types.EmbeddedResource(
                type="resource",
                resource=types.TextResourceContents(uri="file:///a.txt", text="file body"),
            ),
        ]
    )
    output = result_to_output(result, label="pw")

    assert "Here you go" in output.content
    assert "[image 1 (image/png) attached]" in output.content
    assert "file body" in output.content
    assert len(output.images) == 1
    assert output.images[0].media_type == "image/png"


def test_structured_only_results_and_truncation() -> None:
    structured = types.CallToolResult(content=[], structuredContent={"count": 3})
    assert json.loads(result_to_output(structured, label="s").content) == {"count": 3}

    long = types.CallToolResult(content=[types.TextContent(type="text", text="x" * 50)])
    assert (
        "[truncated: 40 more characters]" in result_to_output(long, label="s", max_chars=10).content
    )


async def test_tool_adapter_validates_and_reports_server_errors() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def call(name: str, arguments: dict[str, object]) -> types.CallToolResult:
        calls.append((name, arguments))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="no such repo")], isError=True
        )

    tool = McpTool(
        "github",
        types.Tool(
            name="get_repo",
            description="Get a repository.",
            inputSchema={
                "type": "object",
                "properties": {"owner": {"type": "string"}},
                "required": ["owner"],
                "$schema": "http://json-schema.org/draft-07/schema#",
            },
        ),
        call,
    )
    schema = tool.to_openai_schema()["function"]

    assert schema["name"] == "github__get_repo"
    assert schema["description"] == "[github] Get a repository."
    assert "$schema" not in schema["parameters"]
    with pytest.raises(ToolError, match="'owner' is a required property"):
        await tool.run()
    assert calls == []  # Never sent to the server.
    with pytest.raises(ToolError, match="no such repo"):
        await tool.run(owner="octocat")
    assert calls == [("get_repo", {"owner": "octocat"})]


# --- live connections ----------------------------------------------------------


async def test_manager_connects_lists_and_calls_over_stdio(tmp_path: Path) -> None:
    store = McpConfigStore(tmp_path / "mcp.json")
    await store.put("echo", echo_config())
    manager = McpManager(store)
    await manager.start()
    try:
        state = await manager.wait_settled("echo", 30)
        assert state is not None
        assert state.status == "connected", state.error
        assert state.connection is not None
        assert state.connection.server_name == "echo-test"

        tools = {tool.name: tool for tool in manager.tools()}
        assert set(tools) == {"echo__echo", "echo__add", "echo__pixel", "echo__fail"}
        assert (await tools["echo__echo"].run(text="hi", times=2)).content == "hi hi"  # type: ignore[union-attr]
        image = await tools["echo__pixel"].run()
        assert isinstance(image, object)
        assert len(image.images) == 1  # type: ignore[union-attr]
        with pytest.raises(ToolError, match="boom"):
            await tools["echo__fail"].run(reason="boom")
    finally:
        await manager.close()
    assert manager.tools() == []


async def test_disabled_servers_are_not_started(tmp_path: Path) -> None:
    store = McpConfigStore(tmp_path / "mcp.json")
    await store.put("echo", echo_config(enabled=False))
    manager = McpManager(store)
    await manager.start()

    state = manager.state("echo")
    assert state is not None
    assert state.status == "disabled"
    assert manager.tools() == []
    await manager.close()


async def test_failures_explain_themselves(tmp_path: Path) -> None:
    manager = McpManager(McpConfigStore(tmp_path / "mcp.json"))

    missing = await manager.test(McpServerConfig(command="no-such-program-xyz", timeout_s=10))
    crashes = await manager.test(
        McpServerConfig(
            command=sys.executable,
            args=["-c", "import sys; sys.stderr.write('token is invalid'); sys.exit(1)"],
            timeout_s=10,
        )
    )
    unreachable = await manager.test(McpServerConfig(url="http://127.0.0.1:9/mcp", timeout_s=5))

    assert not missing.ok
    assert "not found" in (missing.error or "")
    assert not crashes.ok
    assert "token is invalid" in (crashes.error or "")  # What the server printed.
    assert not unreachable.ok
    assert "Couldn't connect" in (unreachable.error or "")


async def test_stdio_can_be_switched_off(tmp_path: Path) -> None:
    manager = McpManager(McpConfigStore(tmp_path / "mcp.json"), allow_stdio=False)
    result = await manager.test(echo_config())
    assert not result.ok
    assert "MCP_ALLOW_STDIO" in (result.error or "")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def http_echo_server() -> Iterator[str]:
    port = _free_port()
    process = subprocess.Popen(  # noqa: S603 - our own test server.
        [sys.executable, ECHO_SERVER, "http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.2)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        process.wait(timeout=10)


async def test_streamable_http_servers_work(http_echo_server: str, tmp_path: Path) -> None:
    manager = McpManager(McpConfigStore(tmp_path / "mcp.json"))
    result = await manager.test(McpServerConfig(type="http", url=http_echo_server, timeout_s=20))
    assert result.ok, result.error
    assert {tool.name for tool in result.tools} == {"echo", "add", "pixel", "fail"}


# --- the API -------------------------------------------------------------------


def make_app(tmp_path: Path, turns: list | None = None, **overrides: object) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        stream_tokens=False,
        workspace_dir=tmp_path / "workspace",
        mcp_config_path=tmp_path / "mcp.json",
        **overrides,
    )
    app = create_app(settings=settings)
    model = FakeChatModel(turns=turns or [final_turn("unused")])

    def override() -> object:
        factory = AgentFactory(settings=settings, tools=app.state.tools, mcp=app.state.mcp)

        def build(model_id: str | None = None, workspace: Workspace | None = None) -> AgentLoop:
            return factory(model_id, model=model, workspace=workspace)

        return build

    app.dependency_overrides[get_agent_factory] = override
    return TestClient(app)


def echo_body(**overrides: object) -> dict[str, object]:
    return {"name": "echo", "config": echo_config(**overrides).model_dump()}


def test_api_add_use_disable_and_delete_a_server(tmp_path: Path) -> None:
    turns = [tool_call_turn("echo__echo", {"text": "ping", "times": 2}), final_turn("Echoed.")]
    with make_app(tmp_path, turns) as client:
        created = client.post("/v1/mcp/servers", json=echo_body())
        assert created.status_code == 201, created.text
        server = created.json()
        assert server["status"] == "connected", server["error"]
        assert server["server_name"] == "echo-test"
        assert {t["qualified_name"] for t in server["tools"]} >= {"echo__echo", "echo__add"}

        # The tools join the agent's list, tagged with their server...
        tools = {t["name"]: t for t in client.get("/v1/tools").json()["tools"]}
        assert tools["echo__echo"]["source"] == "mcp"
        assert tools["echo__echo"]["server"] == "echo"
        assert tools["read_file"]["source"] == "builtin"

        # ...and the agent can call them.
        chat = client.post("/v1/chat", json={"message": "echo ping twice"}).json()
        call = chat["tool_calls"][0]
        assert call["tool_name"] == "echo__echo"
        assert call["is_error"] is False
        assert call["content"] == "ping ping"

        disabled = client.patch("/v1/mcp/servers/echo", json={"enabled": False}).json()
        assert disabled["status"] == "disabled"
        assert "echo__echo" not in {t["name"] for t in client.get("/v1/tools").json()["tools"]}

        assert client.delete("/v1/mcp/servers/echo").status_code == 204
        assert client.get("/v1/mcp/servers").json()["servers"] == []


def test_api_masks_secrets_and_keeps_them_on_edit(tmp_path: Path) -> None:
    with make_app(tmp_path) as client:
        client.post("/v1/mcp/servers", json=echo_body(env={"API_TOKEN": "s3cret"}))
        listed = client.get("/v1/mcp/servers").json()["servers"][0]
        assert listed["config"]["env"] == {"API_TOKEN": MASK}

        edited = listed["config"] | {"args": [*listed["config"]["args"], "--verbose"]}
        assert client.put("/v1/mcp/servers/echo", json=edited).status_code == 200

        stored = McpConfigStore(tmp_path / "mcp.json").get("echo")
        assert stored is not None
        assert stored.env == {"API_TOKEN": "s3cret"}
        assert stored.args[-1] == "--verbose"


def test_api_test_endpoint_and_import(tmp_path: Path) -> None:
    with make_app(tmp_path) as client:
        tried = client.post("/v1/mcp/test", json={"config": echo_config().model_dump()}).json()
        assert tried["ok"] is True, tried["error"]
        assert len(tried["tools"]) == 4
        assert client.get("/v1/mcp/servers").json()["servers"] == []  # Nothing saved.

        pasted = json.dumps(
            {"mcpServers": {"echo": echo_config().model_dump(exclude_defaults=True)}}
        )
        first = client.post("/v1/mcp/import", json={"json": pasted}).json()
        again = client.post("/v1/mcp/import", json={"json": pasted}).json()
        forced = client.post("/v1/mcp/import", json={"json": pasted, "overwrite": True}).json()

        assert first == {"added": ["echo"], "replaced": [], "skipped": []}
        assert again["skipped"] == ["echo"]
        assert forced["replaced"] == ["echo"]
        bad = client.post("/v1/mcp/import", json={"json": "{oops"})
        assert bad.status_code == 400
        assert "Not valid JSON" in bad.json()["detail"]


def test_api_conflicts_and_switches(tmp_path: Path) -> None:
    with make_app(tmp_path, mcp_allow_stdio=False) as client:
        refused = client.post("/v1/mcp/servers", json=echo_body())
        assert refused.status_code == 400
        assert "turned off" in refused.json()["detail"]
        assert client.get("/v1/mcp/servers").json()["allow_stdio"] is False

    with make_app(tmp_path, mcp_enabled=False) as client:
        assert client.get("/v1/mcp/servers").status_code == 404
        assert client.get("/health").json()["mcp"] is False


def test_only_admins_change_servers_when_sign_in_is_on(tmp_path: Path) -> None:
    db = f"sqlite:///{(tmp_path / 'auth.db').as_posix()}"
    with make_app(tmp_path, database_url=db) as client:
        admin_token = client.post(
            "/v1/auth/setup", json={"username": "admin", "password": "a long password"}
        ).json()["token"]
        users = client.app.state.sessions.users  # type: ignore[attr-defined]
        client.portal.call(users.create, "bob", "another long one")  # type: ignore[union-attr]
        bob_token = client.post(
            "/v1/auth/login", json={"username": "bob", "password": "another long one"}
        ).json()["token"]
        admin = {"Authorization": f"Bearer {admin_token}"}
        bob = {"Authorization": f"Bearer {bob_token}"}

        assert client.get("/v1/mcp/servers").status_code == 401
        assert client.get("/v1/mcp/servers", headers=bob).json()["can_manage"] is False
        assert client.post("/v1/mcp/servers", json=echo_body(), headers=bob).status_code == 403
        assert (
            client.post(
                "/v1/mcp/test", json={"config": echo_config().model_dump()}, headers=bob
            ).status_code
            == 403
        )
        assert (
            client.post("/v1/mcp/servers", json=echo_body(enabled=False), headers=admin).status_code
            == 201
        )
        assert len(client.get("/v1/mcp/servers", headers=bob).json()["servers"]) == 1


def test_duplicate_names_are_refused(tmp_path: Path) -> None:
    with make_app(tmp_path) as client:
        assert client.post("/v1/mcp/servers", json=echo_body(enabled=False)).status_code == 201
        assert client.post("/v1/mcp/servers", json=echo_body(enabled=False)).status_code == 409
        assert (
            client.post(
                "/v1/mcp/servers", json={"name": "bad name", "config": echo_config().model_dump()}
            ).status_code
            == 422
        )


def test_reconnect(tmp_path: Path) -> None:
    with make_app(tmp_path) as client:
        client.post("/v1/mcp/servers", json=echo_body())
        again = client.post("/v1/mcp/servers/echo/reconnect")
        assert again.status_code == 200
        assert again.json()["status"] == "connected"
        assert client.post("/v1/mcp/servers/nope/reconnect").status_code == 404


def test_servers_reconnect_after_a_restart(tmp_path: Path) -> None:
    with make_app(tmp_path) as client:
        client.post("/v1/mcp/servers", json=echo_body())

    with make_app(tmp_path) as client:  # A new process, the same config file.
        deadline = time.monotonic() + 30
        status = ""
        while time.monotonic() < deadline:
            status = client.get("/v1/mcp/servers").json()["servers"][0]["status"]
            if status != "connecting":
                break
            asyncio.run(asyncio.sleep(0.2))
        assert status == "connected"
