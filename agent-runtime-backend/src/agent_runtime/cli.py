"""Command-line interface: the same agent as the HTTP API, from a terminal.

    agent-runtime chat                      interactive conversation
    agent-runtime ask "summarise a.pdf"     one question, answer on stdout
    agent-runtime serve                     run the HTTP API
    agent-runtime tools | models            show what is available

Both front ends share everything below them: settings, the workspace, the
tools, the loop and the run summary. The CLI only renders events. The
agent's answer goes to stdout, and everything else (tool activity, usage,
errors, logs) goes to stderr, so `ask` output can be piped or redirected
cleanly.

Exit codes: 0 success, 1 the agent run failed, 2 bad usage or
configuration, 130 interrupted.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import os
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn, TextIO

import uvicorn
from pydantic import ValidationError

from agent_runtime import __version__
from agent_runtime.agent.events import (
    AgentEvent,
    FinalAnswer,
    ModelToken,
    RunFailed,
    ToolCallRequested,
    ToolCallResult,
)
from agent_runtime.agent.loop import AgentLoop
from agent_runtime.agent.messages import Message
from agent_runtime.agent.openai import ModelConfigurationError
from agent_runtime.agent.outcome import RunOutcome
from agent_runtime.api.schemas import ChatResponse
from agent_runtime.config import Settings
from agent_runtime.logging import configure_logging
from agent_runtime.models import UnknownModelError, available_models, pricing_for
from agent_runtime.runtime import AgentFactory, build_tools, build_workspace

EXIT_OK = 0
EXIT_RUN_FAILED = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

_CHAT_HELP = """Commands:
  /new    start a fresh conversation
  /help   show this help
  /exit   quit (Ctrl+D or Ctrl+C also work)"""


class CliError(Exception):
    """A problem the user can fix (bad option, missing key); printed without a traceback."""

    def __init__(self, message: str, exit_code: int = EXIT_USAGE) -> None:
        """Carry the message to print and the process exit code to use."""
        super().__init__(message)
        self.exit_code = exit_code


# --- settings and wiring ---------------------------------------------------------


def _load_settings(args: argparse.Namespace) -> Settings:
    """Read settings from the environment and `.env`, then apply command-line overrides."""
    overrides: dict[str, Any] = {}
    if getattr(args, "workspace", None):
        overrides["workspace_dir"] = args.workspace
    if getattr(args, "read_only", False):
        overrides["workspace_read_only"] = True
    if getattr(args, "max_steps", None) is not None:
        overrides["max_steps"] = args.max_steps
    if getattr(args, "no_stream", False) or getattr(args, "json", False):
        overrides["stream_tokens"] = False
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        raise CliError(f"invalid configuration:\n{exc}") from exc


def _build_agent(settings: Settings, model: str | None) -> AgentLoop:
    """Build the agent exactly as the API does, turning setup problems into `CliError`."""
    tools = build_tools(settings, build_workspace(settings))
    try:
        return AgentFactory(settings, tools)(model)
    except (UnknownModelError, ModelConfigurationError) as exc:
        raise CliError(str(exc)) from exc


def _configure_cli_logging(verbosity: int) -> None:
    """Send logs to stderr: silent by default, INFO with -v, DEBUG with -vv.

    Silent is right for a terminal: the renderer already reports every tool
    failure and run failure in plain words, so log lines would only repeat
    them with a traceback attached.
    """
    level = {0: "CRITICAL", 1: "INFO"}.get(verbosity, "DEBUG")
    configure_logging(level, stream=sys.stderr)


# --- rendering -------------------------------------------------------------------


def _short(value: Any, limit: int = 60) -> str:
    """Render a tool argument compactly; `write_file` content can be pages long."""
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


class EventRenderer:
    """Prints a run's events for a person at a terminal."""

    def __init__(self, out: TextIO, err: TextIO, *, quiet: bool, streaming: bool) -> None:
        """Write the answer to `out` and activity to `err`.

        Args:
            out: Receives the agent's answer.
            err: Receives tool activity, usage and errors.
            quiet: Suppress tool activity and the usage line.
            streaming: Tokens arrive as `ModelToken` events and are already
                printed, so the final answer must not be printed again.
        """
        self._out = out
        self._err = err
        self._quiet = quiet
        self._streaming = streaming
        self._mid_line = False

    def _end_answer_line(self) -> None:
        """Finish a partly streamed line before writing anything else."""
        if self._mid_line:
            self._out.write("\n")
            self._out.flush()
            self._mid_line = False

    def _activity(self, text: str) -> None:
        if self._quiet:
            return
        self._end_answer_line()
        self._err.write(text + "\n")
        self._err.flush()

    def handle(self, event: AgentEvent) -> None:
        """Print one event, if it is one a person needs to see."""
        if isinstance(event, ModelToken):
            self._out.write(event.text)
            self._out.flush()
            self._mid_line = not event.text.endswith("\n")
        elif isinstance(event, ToolCallRequested):
            arguments = ", ".join(f"{k}={_short(v)}" for k, v in event.arguments.items())
            self._activity(f"  [tool] {event.tool_name}({arguments})")
        elif isinstance(event, ToolCallResult):
            first_line = event.content.strip().splitlines()[0] if event.content.strip() else ""
            status = "failed" if event.is_error else f"ok {event.duration_s:.1f}s"
            self._activity(f"  [{status}] {first_line[:100]}")
        elif isinstance(event, FinalAnswer):
            if not self._streaming:
                self._out.write(event.content)
                self._mid_line = not event.content.endswith("\n")
            self._end_answer_line()
        elif isinstance(event, RunFailed):
            self._end_answer_line()
            self._err.write(f"error: {event.reason}\n")
            self._err.flush()

    def summary(self, outcome: RunOutcome) -> None:
        """Print the steps and tokens a run used, and its cost when known."""
        usage = outcome.usage
        if not usage.total_tokens:
            return
        cost = "" if usage.cost_usd is None else f", ${usage.cost_usd:.4f}"
        steps = f"{outcome.steps_used} step{'s' if outcome.steps_used != 1 else ''}"
        self._activity(f"  [{steps}, {usage.total_tokens} tokens{cost}]")


# --- commands --------------------------------------------------------------------


def _read_message(words: list[str]) -> str:
    """Join the message words, or read stdin when the message is `-`."""
    message = sys.stdin.read() if words == ["-"] else " ".join(words)
    if not message.strip():
        raise CliError("the message is empty")
    return message


async def _ask(args: argparse.Namespace) -> int:
    message = _read_message(args.message)
    settings = _load_settings(args)
    agent = _build_agent(settings, args.model)
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    outcome = RunOutcome()
    renderer = EventRenderer(
        sys.stdout, sys.stderr, quiet=args.quiet, streaming=agent.streams_tokens
    )
    async for event in agent.run(message, run_id=run_id):
        outcome.observe(event)
        if not args.json:
            renderer.handle(event)

    if args.json:
        response = ChatResponse.from_outcome(
            outcome, run_id=run_id, session_id=f"cli_{uuid.uuid4().hex[:12]}", model=agent.model_id
        )
        sys.stdout.write(response.model_dump_json(indent=2) + "\n")
    else:
        renderer.summary(outcome)
    return EXIT_OK if outcome.succeeded else EXIT_RUN_FAILED


async def _chat_turn(
    agent: AgentLoop, message: str, transcript: list[Message], quiet: bool
) -> None:
    """Run one conversational turn, keeping the transcript consistent if interrupted."""
    snapshot = list(transcript)
    outcome = RunOutcome()
    renderer = EventRenderer(sys.stdout, sys.stderr, quiet=quiet, streaming=agent.streams_tokens)
    try:
        async for event in agent.run(message, transcript):
            outcome.observe(event)
            renderer.handle(event)
    except asyncio.CancelledError:
        # An interrupted turn can stop between a tool request and its result,
        # and the model rejects such a transcript; forget the partial turn.
        # Restore a copy rather than truncating by length: the loop may also
        # have inserted the system prompt at the front.
        transcript[:] = snapshot
        raise
    renderer.summary(outcome)


def _chat(args: argparse.Namespace) -> int:
    settings = _load_settings(args)
    agent = _build_agent(settings, args.model)
    with contextlib.suppress(ImportError):  # Line editing and history, where available.
        import readline  # noqa: F401

    workspace = Path(settings.workspace_dir).resolve()
    mode = " (read-only)" if settings.workspace_read_only else ""
    sys.stderr.write(
        f"agent-runtime {__version__} | model {agent.model_id} | workspace {workspace}{mode}\n"
        "Type a message and press Enter. /help for commands.\n\n"
    )

    transcript: list[Message] = []
    # One event loop for the whole session: the model's HTTP client is bound to it.
    with asyncio.Runner() as runner:
        while True:
            try:
                line = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                sys.stderr.write("\n")
                return EXIT_OK
            if not line:
                continue
            if line in ("/exit", "/quit"):
                return EXIT_OK
            if line == "/help":
                sys.stderr.write(_CHAT_HELP + "\n\n")
                continue
            if line == "/new":
                transcript.clear()
                sys.stderr.write("Started a new conversation.\n\n")
                continue
            if line.startswith("/"):
                sys.stderr.write(f"Unknown command {line.split()[0]}. /help lists commands.\n\n")
                continue
            try:
                runner.run(_chat_turn(agent, line, transcript, args.quiet))
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                sys.stderr.write("[interrupted]\n")
            sys.stdout.write("\n")


def _serve(args: argparse.Namespace) -> int:
    # The app is built inside uvicorn (and, with --reload, in a child
    # process), so overrides travel as environment variables.
    if args.workspace:
        os.environ["WORKSPACE_DIR"] = str(args.workspace)
    if args.read_only:
        os.environ["WORKSPACE_READ_ONLY"] = "true"
    settings = _load_settings(args)
    uvicorn.run(
        "agent_runtime.api.app:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload or settings.reload,
        log_level=settings.log_level.lower(),
    )
    return EXIT_OK


def _tools(args: argparse.Namespace) -> int:
    settings = _load_settings(args)
    tools = build_tools(settings, build_workspace(settings))
    width = max(len(name) for name in tools.names())
    for tool in tools:
        first_sentence = tool.description.split(". ")[0].rstrip(".") + "."
        sys.stdout.write(f"{tool.name:<{width}}  {first_sentence}\n")
    if settings.workspace_read_only:
        sys.stdout.write("\n(read-only workspace: tools that change files are disabled)\n")
    return EXIT_OK


def _models(args: argparse.Namespace) -> int:
    settings = _load_settings(args)
    for info in available_models():
        pricing = pricing_for(info.id, settings.pricing_overrides) or info.pricing
        default = "  (default)" if info.id == settings.openai_model else ""
        sys.stdout.write(
            f"{info.id}{default}\n  {info.description}\n"
            f"  ${pricing.input_usd_per_1m:.2f} input / ${pricing.output_usd_per_1m:.2f} "
            "output per 1M tokens\n"
        )
    return EXIT_OK


# --- argument parsing ------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    """An `ArgumentParser` that exits with `EXIT_USAGE` and our message format."""

    def error(self, message: str) -> NoReturn:
        """Print usage and the error, then exit with the usage exit code."""
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the parser for every subcommand."""
    workspace_options = _Parser(add_help=False)
    workspace_options.add_argument(
        "--workspace", type=Path, metavar="DIR", help="folder the agent works in (WORKSPACE_DIR)"
    )
    workspace_options.add_argument(
        "--read-only", action="store_true", help="let the agent read files but never change them"
    )

    agent_options = _Parser(add_help=False)
    agent_options.add_argument("--model", help="model id from 'agent-runtime models'")
    agent_options.add_argument("--max-steps", type=int, metavar="N", help="step budget per run")
    agent_options.add_argument(
        "--no-stream", action="store_true", help="print the answer at the end, not as it is typed"
    )
    agent_options.add_argument(
        "-q", "--quiet", action="store_true", help="hide tool activity and token usage"
    )
    agent_options.add_argument(
        "-v", "--verbose", action="count", default=0, help="show logs on stderr (-vv for debug)"
    )

    parser = _Parser(
        prog="agent-runtime",
        description="An AI agent that reads, views and creates files in a workspace folder.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)

    chat = commands.add_parser(
        "chat",
        parents=[workspace_options, agent_options],
        help="have a conversation in the terminal",
        description="Interactive conversation. The agent remembers earlier messages.",
    )
    chat.set_defaults(handler=_chat)

    ask = commands.add_parser(
        "ask",
        parents=[workspace_options, agent_options],
        help="ask one question and print the answer",
        description="Ask one question; the answer goes to stdout, activity to stderr.",
    )
    ask.add_argument("message", nargs="+", help="the request; use - to read it from stdin")
    ask.add_argument(
        "--json", action="store_true", help="print the full result as JSON (same as /v1/chat)"
    )
    ask.set_defaults(handler=lambda args: asyncio.run(_ask(args)))

    serve = commands.add_parser(
        "serve",
        parents=[workspace_options],
        help="run the HTTP API server",
        description="Run the HTTP API. Interactive docs are served at /docs.",
    )
    serve.add_argument("--host", help="interface to bind (HOST, default 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port to listen on (PORT, default 8000)")
    serve.add_argument("--reload", action="store_true", help="restart on code changes (dev only)")
    serve.set_defaults(handler=_serve)

    tools = commands.add_parser(
        "tools", parents=[workspace_options], help="list the tools the agent can use"
    )
    tools.set_defaults(handler=_tools)

    models = commands.add_parser("models", help="list the models you can choose")
    models.set_defaults(handler=_models)
    return parser


def _make_console_safe() -> None:
    """Never crash on a character the terminal's encoding can't show (old Windows consoles)."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    _make_console_safe()
    _configure_cli_logging(getattr(args, "verbose", 0))
    try:
        exit_code: int = args.handler(args)
    except CliError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return exc.exit_code
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        return EXIT_INTERRUPTED
    return exit_code


__all__ = ["CliError", "EventRenderer", "build_parser", "main"]
