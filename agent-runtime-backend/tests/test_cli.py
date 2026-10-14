"""The CLI, driven end to end through `main()` with a scripted model.

The real factory is swapped for one that builds the loop around a
`FakeChatModel`, so every test runs the actual tools in a temp workspace
without touching the network.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

import pytest

from agent_runtime import cli
from agent_runtime.agent.loop import AgentLoop
from agent_runtime.agent.messages import AssistantMessage, Message
from agent_runtime.config import Settings
from agent_runtime.runtime import AgentFactory
from agent_runtime.tools.base import Tool
from agent_runtime.tools.registry import ToolRegistry

from .fakes import EchoArgs, FakeChatModel, final_turn, tool_call_turn, usage


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run each test from an empty folder, so no real `.env` (or key) is ever read."""
    monkeypatch.chdir(tmp_path)
    for name in ("OPENAI_API_KEY", "WORKSPACE_DIR", "WORKSPACE_READ_ONLY", "STREAM_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "ws"))
    return tmp_path / "ws"


def script(monkeypatch: pytest.MonkeyPatch, *turns: AssistantMessage) -> FakeChatModel:
    """Make the CLI's agents run on a fake model replaying `turns`."""
    model = FakeChatModel(turns=list(turns))

    class ScriptedFactory(AgentFactory):
        def __call__(self, model_id: str | None = None, model_: Any = None) -> AgentLoop:
            return super().__call__(model_id, model=model)

    monkeypatch.setattr(cli, "AgentFactory", ScriptedFactory)
    return model


# --- ask -------------------------------------------------------------------------


def test_ask_prints_answer_on_stdout_and_activity_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], isolated_env: Path
) -> None:
    script(
        monkeypatch,
        tool_call_turn("write_file", {"path": "hi.txt", "content": "hello"}),
        final_turn("Created hi.txt.", token_usage=usage(100, 20, 0.0012)),
    )

    exit_code = cli.main(["ask", "--no-stream", "make", "a", "file"])

    out, err = capsys.readouterr()
    assert exit_code == cli.EXIT_OK
    assert out == "Created hi.txt.\n"
    assert "[tool] write_file(path='hi.txt', content='hello')" in err
    assert "[ok " in err
    assert "120 tokens, $0.0012" in err
    assert (isolated_env / "hi.txt").read_text() == "hello"


def test_ask_streams_tokens(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script(monkeypatch, final_turn("streamed answer here"))

    assert cli.main(["ask", "hi"]) == cli.EXIT_OK
    out, _ = capsys.readouterr()
    assert out.strip() == "streamed answer here"
    assert out.count("streamed answer here") == 1  # Not printed again at the end.


def test_ask_quiet_hides_activity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script(monkeypatch, tool_call_turn("list_files", {}), final_turn("Empty."))

    cli.main(["ask", "-q", "--no-stream", "what is here?"])

    out, err = capsys.readouterr()
    assert out == "Empty.\n"
    assert err == ""


def test_ask_json_matches_the_api_response_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script(monkeypatch, tool_call_turn("list_files", {}), final_turn("Nothing yet."))

    assert cli.main(["ask", "--json", "list"]) == cli.EXIT_OK

    out, _ = capsys.readouterr()
    body = json.loads(out)
    assert body["status"] == "completed"
    assert body["answer"] == "Nothing yet."
    assert body["tool_calls"][0]["tool_name"] == "list_files"
    assert body["steps_used"] == 2


def test_ask_reads_the_message_from_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    model = script(monkeypatch, final_turn("ok"))
    monkeypatch.setattr("sys.stdin", io.StringIO("summarise this\nplease"))

    cli.main(["ask", "-q", "-"])

    user_message = model.calls[0][-1]
    assert getattr(user_message, "content", None) == "summarise this\nplease"


def test_failed_run_exits_1_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script(monkeypatch, *[tool_call_turn("list_files", {}, call_id=f"c{i}") for i in range(5)])

    exit_code = cli.main(["ask", "--max-steps", "2", "loop"])

    _, err = capsys.readouterr()
    assert exit_code == cli.EXIT_RUN_FAILED
    assert "error: " in err
    assert "did not finish within 2 steps" in err


# --- usage and configuration errors -----------------------------------------------


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["ask", "hi"], "OPENAI_API_KEY is not set"),
        (["ask", "hi", "--model", "gpt-9"], "Unknown model 'gpt-9'"),
        (["ask", "--max-steps", "0", "hi"], "invalid configuration"),
    ],
)
def test_setup_problems_exit_2_without_a_traceback(
    capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    assert cli.main(argv) == cli.EXIT_USAGE
    _, err = capsys.readouterr()
    assert message in err
    assert "Traceback" not in err


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == cli.EXIT_USAGE
    assert "COMMAND" in capsys.readouterr().err


# --- tools and models ---------------------------------------------------------------


def test_tools_lists_every_tool(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["tools"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    for name in ("list_files", "read_file", "read_image", "write_file", "edit_file"):
        assert name in out


def test_tools_read_only_hides_writers(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["tools", "--read-only"])
    out = capsys.readouterr().out
    assert "write_file" not in out
    assert "read-only" in out


def test_models_marks_the_default(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["models"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "gpt-4o  (default)" in out
    assert "gpt-5.2" in out


# --- chat -----------------------------------------------------------------------------


def feed_input(monkeypatch: pytest.MonkeyPatch, *lines: str) -> None:
    """Answer successive `input()` prompts with `lines`, then signal end of input."""
    remaining = list(lines)

    def fake_input(prompt: str = "") -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)


def test_chat_remembers_the_conversation_and_handles_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    model = script(monkeypatch, final_turn("Hi Ada."), final_turn("Ada."), final_turn("Fresh."))
    feed_input(monkeypatch, "I am Ada", "who am I?", "/help", "/bogus", "/new", "hello", "/exit")

    assert cli.main(["chat", "--no-stream"]) == cli.EXIT_OK

    out, err = capsys.readouterr()
    assert "Hi Ada." in out
    assert "Ada." in out
    assert "/new" in err  # From /help.
    assert "Unknown command /bogus" in err
    # The second turn saw the first; after /new the third saw neither.
    assert any(getattr(m, "content", "") == "I am Ada" for m in model.calls[1])
    assert not any(getattr(m, "content", "") == "I am Ada" for m in model.calls[2])


def test_chat_ends_cleanly_on_end_of_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script(monkeypatch)
    feed_input(monkeypatch)
    assert cli.main(["chat"]) == cli.EXIT_OK


async def test_interrupted_chat_turn_leaves_no_half_finished_turn() -> None:
    class HangingTool(Tool):
        name = "echo"
        description = "Never finishes."
        args_schema = EchoArgs

        async def run(self, text: str) -> str:  # type: ignore[override]
            raise asyncio.CancelledError  # As if Ctrl+C landed mid-tool.

    settings = Settings(_env_file=None, stream_tokens=False)  # type: ignore[call-arg]
    agent = AgentLoop(
        settings=settings,
        tools=ToolRegistry([HangingTool()]),
        model=FakeChatModel(turns=[tool_call_turn("echo", {"text": "x"})]),
        system_prompt="sys",
    )
    transcript: list[Message] = [AssistantMessage(content="earlier turn")]

    with pytest.raises(asyncio.CancelledError):
        await cli._chat_turn(agent, "go", transcript, quiet=True)

    # Back to exactly what it was: no user message, no unanswered tool call.
    assert transcript == [AssistantMessage(content="earlier turn")]
