"""The agent loop: think -> act -> observe, until a final answer or a limit.

This is deliberately not hidden behind a LangChain `AgentExecutor`. The
loop below is the whole control flow in one readable place:

    1. Ask the model for the next step, given the transcript so far.
    2. If it answered with tool calls, run them (in parallel, bounded by
       `max_parallel_tool_calls`) and append the results as ToolMessages.
    3. If it answered with plain content and no tool calls, that's the
       final answer — stop.
    4. Repeat until `max_steps` or `run_timeout_s` is hit.

Each stage yields an `AgentEvent`, so a caller can observe every decision
the loop makes (and the API layer streams these straight to the client).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from agent_runtime.agent.events import (
    AgentEvent,
    FinalAnswer,
    ModelToken,
    RunFailed,
    RunStarted,
    StepStarted,
    ToolCallRequested,
    ToolCallResult,
    UsageUpdated,
)
from agent_runtime.agent.messages import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from agent_runtime.agent.openai import OpenAIModel, text_of
from agent_runtime.agent.protocols import ChatModel
from agent_runtime.config import Settings
from agent_runtime.tools.base import ToolError
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.usage import TokenUsage

logger = logging.getLogger(__name__)

# A neutral fallback. In practice every run gets its prompt from the
# `AgentSpec` the orchestrator selected, so this is only used when the loop
# is driven directly (tests, or a one-off script).
DEFAULT_SYSTEM_PROMPT = (
    "You are a careful, concise assistant with access to tools. "
    "Call a tool when it is the only way to complete the request accurately, "
    "and answer directly when it is not. "
    "Keep the final answer focused and avoid unnecessary repetition."
)


class MaxStepsExceeded(RuntimeError):
    """Raised when the loop hits its step budget without a final answer."""


class RunTimeoutExceeded(RuntimeError):
    """Raised when the loop hits its wall-clock budget without a final answer."""


@dataclass(slots=True)
class RunResult:
    """The outcome of a completed run, plus the full transcript for inspection."""

    run_id: str
    final_answer: str
    steps_used: int
    model: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    messages: list[Message] = field(default_factory=list)


class AgentLoop:
    """Runs the think/act/observe cycle for a single conversation turn."""

    def __init__(
        self,
        settings: Settings,
        tools: ToolRegistry,
        model: ChatModel | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        model_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._tools = tools
        self._model = model or OpenAIModel(settings, tools, model_id=model_id)
        self._system_prompt = system_prompt

    @property
    def model_id(self) -> str:
        """The model this loop will actually call."""
        return self._model.model_id

    async def run(
        self,
        user_input: str,
        history: list[Message] | None = None,
        run_id: str | None = None,
        transcript: list[Message] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the loop, yielding events as it goes.

        The final event is either `FinalAnswer` or `RunFailed`. Callers that
        just want the end result can use `AgentLoop.run_to_completion`
        instead of consuming this generator themselves.

        If `transcript` is given, it is used (and mutated in place) as the
        working message list, so the caller can inspect the full transcript
        — including assistant and tool messages added during the run —
        after the generator is exhausted.
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        deadline = time.monotonic() + self._settings.run_timeout_s

        messages: list[Message] = transcript if transcript is not None else list(history or [])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages.insert(0, SystemMessage(content=self._system_prompt))
        messages.append(UserMessage(content=user_input))

        run_usage = TokenUsage()

        yield RunStarted(run_id=run_id, max_steps=self._settings.max_steps)

        try:
            for step in range(1, self._settings.max_steps + 1):
                yield StepStarted(run_id=run_id, step=step)

                if time.monotonic() > deadline:
                    raise RunTimeoutExceeded(
                        f"Run {run_id} exceeded {self._settings.run_timeout_s}s"
                    )

                assistant_message = None
                async for think_event in self._think(run_id, step, messages):
                    if isinstance(think_event, AssistantMessage):
                        assistant_message = think_event
                    else:
                        yield think_event
                assert assistant_message is not None
                messages.append(assistant_message)

                if assistant_message.usage is not None:
                    run_usage = run_usage + assistant_message.usage
                    yield UsageUpdated(
                        run_id=run_id,
                        step=step,
                        model=self.model_id,
                        step_usage=assistant_message.usage,
                        run_usage=run_usage,
                    )

                if not assistant_message.has_tool_calls:
                    yield FinalAnswer(run_id=run_id, step=step, content=assistant_message.content)
                    return

                async for act_event in self._act(
                    run_id, step, assistant_message.tool_calls, deadline
                ):
                    if isinstance(act_event, ToolMessage):
                        messages.append(act_event)
                    else:
                        yield act_event

            raise MaxStepsExceeded(
                f"Run {run_id} did not finish within {self._settings.max_steps} steps"
            )

        except (MaxStepsExceeded, RunTimeoutExceeded) as exc:
            logger.warning("agent run stopped early", extra={"run_id": run_id, "reason": str(exc)})
            yield RunFailed(run_id=run_id, step=self._settings.max_steps, reason=str(exc))
        except Exception as exc:
            logger.exception("agent run failed", extra={"run_id": run_id})
            yield RunFailed(run_id=run_id, step=0, reason=f"{type(exc).__name__}: {exc}")

    async def _think(
        self, run_id: str, step: int, messages: list[Message]
    ) -> AsyncIterator[AgentEvent | AssistantMessage]:
        """The 'think' stage: one model call, optionally streamed token-by-token."""
        if not self._settings.stream_tokens:
            yield await self._model.invoke(messages)
            return

        chunks = []
        async for chunk in self._model.stream(messages):
            chunks.append(chunk)
            text = text_of(chunk)
            if text:
                yield ModelToken(run_id=run_id, step=step, text=text)
        yield self._model.accumulate(chunks)

    async def _act(
        self, run_id: str, step: int, tool_calls: list[ToolCall], deadline: float
    ) -> AsyncIterator[AgentEvent | ToolMessage]:
        """The 'act' stage: execute all requested tool calls, bounded by concurrency."""
        semaphore = asyncio.Semaphore(self._settings.max_parallel_tool_calls)
        remaining = max(0.0, deadline - time.monotonic())
        per_call_timeout = min(self._settings.tool_timeout_s, remaining) if remaining else 0.0

        for call in tool_calls:
            yield ToolCallRequested(
                run_id=run_id,
                step=step,
                call_id=call.id,
                tool_name=call.name,
                arguments=call.arguments,
            )

        results = await asyncio.gather(
            *(self._call_one(call, semaphore, per_call_timeout) for call in tool_calls)
        )
        for call, (content, is_error, duration_s) in zip(tool_calls, results, strict=True):
            yield ToolCallResult(
                run_id=run_id,
                step=step,
                call_id=call.id,
                tool_name=call.name,
                content=content,
                is_error=is_error,
                duration_s=duration_s,
            )
            yield ToolMessage(
                tool_call_id=call.id, name=call.name, content=content, is_error=is_error
            )

    async def _call_one(
        self, call: ToolCall, semaphore: asyncio.Semaphore, timeout_s: float
    ) -> tuple[str, bool, float]:
        tool = self._tools.get(call.name)
        started = time.monotonic()
        async with semaphore:
            if tool is None:
                return f"Unknown tool: {call.name!r}", True, time.monotonic() - started
            try:
                validated = tool.args_schema(**call.arguments)
                content = await asyncio.wait_for(
                    tool.run(**validated.model_dump()),
                    timeout=timeout_s or self._settings.tool_timeout_s,
                )
                return content, False, time.monotonic() - started
            except ToolError as exc:
                return str(exc), True, time.monotonic() - started
            except TimeoutError:
                return (
                    f"Tool {call.name!r} timed out after {timeout_s:.0f}s",
                    True,
                    time.monotonic() - started,
                )
            except Exception as exc:
                logger.exception("tool call failed", extra={"tool": call.name, "call_id": call.id})
                return (
                    f"Tool {call.name!r} raised {type(exc).__name__}: {exc}",
                    True,
                    time.monotonic() - started,
                )

    async def run_to_completion(
        self, user_input: str, history: list[Message] | None = None, run_id: str | None = None
    ) -> RunResult:
        """Convenience wrapper: drain the event stream, return the final result."""
        final_content: str | None = None
        failure: str | None = None
        steps_used = 0
        usage = TokenUsage()
        transcript: list[Message] = list(history or [])

        async for event in self.run(user_input, run_id=run_id, transcript=transcript):
            if isinstance(event, StepStarted):
                steps_used = event.step
            elif isinstance(event, UsageUpdated):
                usage = event.run_usage
            elif isinstance(event, FinalAnswer):
                final_content = event.content
            elif isinstance(event, RunFailed):
                failure = event.reason

        if final_content is None:
            raise RuntimeError(failure or "Agent run ended without a final answer")

        return RunResult(
            run_id=run_id or "unknown",
            final_answer=final_content,
            steps_used=steps_used,
            model=self.model_id,
            usage=usage,
            messages=transcript,
        )
