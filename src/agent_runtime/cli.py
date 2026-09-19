"""A terminal REPL that drives the orchestrator directly, no HTTP involved.

Useful for watching routing and the agent loop live while developing an
agent or tuning its prompt:

    python -m agent_runtime.cli
"""

from __future__ import annotations

import asyncio

from agent_runtime.agent.events import (
    FinalAnswer,
    ModelToken,
    RunFailed,
    ToolCallRequested,
    ToolCallResult,
    UsageUpdated,
)
from agent_runtime.agent.messages import Message
from agent_runtime.config import get_settings
from agent_runtime.logging import configure_logging
from agent_runtime.orchestrator.events import AgentSelected
from agent_runtime.orchestrator.orchestrator import Orchestrator
from agent_runtime.usage import TokenUsage
from agent_runtime.wiring import build_agents


async def _run_repl() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=False)
    agents = build_agents(settings)
    orchestrator = Orchestrator(settings=settings, agents=agents)

    print(
        f"agent-runtime REPL — model={settings.openai_model}, "
        f"agents={', '.join(agents.names())}, max_steps={settings.max_steps}"
    )
    if not settings.can_send_email:
        print("email: DRY RUN — messages are composed and validated, but never sent.")
    else:
        print(f"email: LIVE — sending as {settings.email_from}.")
    print("Type a message and press enter. Ctrl+C to quit.\n")

    transcript: list[Message] = []
    while True:
        try:
            user_input = (await asyncio.to_thread(input, "you> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue

        printed_answer_prefix = False
        run_usage: TokenUsage | None = None
        async for event in orchestrator.run(user_input, transcript=transcript):
            if isinstance(event, AgentSelected):
                print(f"  [routed to] {event.agent} ({event.routed_by})")
            elif isinstance(event, ToolCallRequested):
                print(f"  [tool call] {event.tool_name}({event.arguments})")
            elif isinstance(event, ToolCallResult):
                status = "error" if event.is_error else "ok"
                print(f"  [tool result:{status}] {event.content!r} ({event.duration_s:.2f}s)")
            elif isinstance(event, ModelToken):
                if not printed_answer_prefix:
                    print("agent> ", end="", flush=True)
                    printed_answer_prefix = True
                print(event.text, end="", flush=True)
            elif isinstance(event, FinalAnswer):
                if not printed_answer_prefix:
                    print(f"agent> {event.content}")
                else:
                    print()
            elif isinstance(event, UsageUpdated):
                run_usage = event.run_usage
            elif isinstance(event, RunFailed):
                print(f"\n[run failed] {event.reason}")

        if run_usage is not None:
            cost = "n/a" if run_usage.cost_usd is None else f"${run_usage.cost_usd:.6f}"
            print(
                f"  [usage] {run_usage.input_tokens} in + {run_usage.output_tokens} out "
                f"= {run_usage.total_tokens} tokens · {cost}"
            )
        print()


def main() -> None:
    asyncio.run(_run_repl())


if __name__ == "__main__":
    main()
