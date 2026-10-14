"""The agent loop: think -> act -> observe, until a final answer or a limit.

This is deliberately not hidden behind a LangChain `AgentExecutor`. The
loop below is the whole control flow in one readable place:

    1. Ask the model for the next step, given the transcript so far.
    2. If it answered with tool calls, run them (in parallel, bounded by
       `max_parallel_tool_calls`) and append the results as ToolMessages.
    3. If it answered with plain content and no tool calls, that is the
       final answer: stop.
    4. Repeat until `max_steps` or `run_timeout_s` is hit.

Each stage yields an `AgentEvent`, so a caller can observe every decision
the loop makes; the API layer streams these straight to the client.

The loop knows nothing about any model provider. It talks to the
`ChatModel` protocol only, which is what lets tests drive it with a
scripted fake and lets a different provider slot in without touching it.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator

from pydantic import ValidationError

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
from agent_runtime.agent.protocols import ChatModel
from agent_runtime.config import Settings
from agent_runtime.tools.base import ToolError, ToolOutput
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.usage import TokenUsage

logger = logging.getLogger(__name__)

# (output, is_error, duration_s) for one executed tool call.
_CallOutcome = tuple[ToolOutput, bool, float]


class BudgetExceededError(RuntimeError):
    """The run hit its step or wall-clock budget without a final answer.

    Expected and recoverable from the caller's point of view, so it is
    reported as a `RunFailed` event with its message rather than logged as
    a crash.
    """


class AgentLoop:
    """Runs the think/act/observe cycle for a single conversation turn.

    A loop is cheap and holds no per-run state, so callers build one per
    request (see `agent_runtime.runtime.AgentFactory`).
    """

    def __init__(
        self,
        settings: Settings,
        tools: ToolRegistry,
        model: ChatModel,
        system_prompt: str,
    ) -> None:
        """Bind a model, its tools and instructions under the given budgets.

        Args:
            settings: Supplies the step, time and concurrency budgets.
            tools: The tools the model may call. Must be the same registry
                the model was given the schemas of.
            model: The chat model to drive.
            system_prompt: Instructions placed at the head of a transcript
                that does not already start with a system message.
        """
        self._settings = settings
        self._tools = tools
        self._model = model
        self._system_prompt = system_prompt

    @property
    def model_id(self) -> str:
        """The id of the model this loop calls, as reported in usage events."""
        return self._model.model_id

    @property
    def streams_tokens(self) -> bool:
        """True when runs emit `ModelToken` events as the answer is generated."""
        return self._settings.stream_tokens

    async def run(
        self,
        user_input: str,
        transcript: list[Message] | None = None,
        run_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one turn, yielding an event for every step of the loop.

        The final event is always either `FinalAnswer` or `RunFailed`: this
        generator never raises for a model, tool or budget failure.

        Args:
            user_input: The user's message for this turn.
            transcript: Prior conversation. It is used as the working
                message list and mutated in place, so after the generator is
                exhausted it holds everything this turn added (the user
                message, assistant turns, tool results). Pass a copy if the
                original must stay untouched.
            run_id: Correlation id for events and logs; generated if omitted.

        Yields:
            The events of the run, in order.
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        deadline = time.monotonic() + self._settings.run_timeout_s

        messages: list[Message] = transcript if transcript is not None else []
        if not messages or not isinstance(messages[0], SystemMessage):
            messages.insert(0, SystemMessage(content=self._system_prompt))
        messages.append(UserMessage(content=user_input))

        run_usage = TokenUsage()
        step = 0
        yield RunStarted(run_id=run_id, max_steps=self._settings.max_steps)

        try:
            for step in range(1, self._settings.max_steps + 1):
                yield StepStarted(run_id=run_id, step=step)

                if time.monotonic() > deadline:
                    raise BudgetExceededError(
                        f"Run {run_id} exceeded {self._settings.run_timeout_s}s"
                    )

                assistant_message: AssistantMessage | None = None
                async for think_event in self._think(run_id, step, messages):
                    if isinstance(think_event, AssistantMessage):
                        assistant_message = think_event
                    else:
                        yield think_event
                if assistant_message is None:  # A ChatModel contract violation.
                    raise RuntimeError("The model returned no assistant message")
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

            raise BudgetExceededError(
                f"Run {run_id} did not finish within {self._settings.max_steps} steps"
            )

        except BudgetExceededError as exc:
            logger.warning("agent run stopped early", extra={"run_id": run_id, "reason": str(exc)})
            yield RunFailed(run_id=run_id, step=step, reason=str(exc))
        except Exception as exc:
            # The boundary of the run: anything a provider or tool binding
            # raises becomes a reported failure instead of a broken stream.
            logger.exception("agent run failed", extra={"run_id": run_id})
            yield RunFailed(run_id=run_id, step=step, reason=f"{type(exc).__name__}: {exc}")

    async def _think(
        self, run_id: str, step: int, messages: list[Message]
    ) -> AsyncIterator[AgentEvent | AssistantMessage]:
        """Make one model call, streaming tokens as events when enabled.

        Yields `ModelToken` events, then exactly one `AssistantMessage`.
        """
        if not self._settings.stream_tokens:
            yield await self._model.invoke(messages)
            return

        chunks = []
        async for chunk in self._model.stream(messages):
            chunks.append(chunk)
            text = self._model.chunk_text(chunk)
            if text:
                yield ModelToken(run_id=run_id, step=step, text=text)
        yield self._model.accumulate(chunks)

    async def _act(
        self, run_id: str, step: int, tool_calls: list[ToolCall], deadline: float
    ) -> AsyncIterator[AgentEvent | ToolMessage]:
        """Execute every requested tool call concurrently, within the budgets.

        Yields all `ToolCallRequested` events first, then a `ToolCallResult`
        event and a `ToolMessage` per call, in the order the model asked.
        """
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
        for call, (output, is_error, duration_s) in zip(tool_calls, results, strict=True):
            yield ToolCallResult(
                run_id=run_id,
                step=step,
                call_id=call.id,
                tool_name=call.name,
                content=output.content,
                is_error=is_error,
                duration_s=duration_s,
                image_count=len(output.images),
            )
            yield ToolMessage(
                tool_call_id=call.id,
                name=call.name,
                content=output.content,
                is_error=is_error,
                images=output.images,
            )

    async def _call_one(
        self, call: ToolCall, semaphore: asyncio.Semaphore, timeout_s: float
    ) -> _CallOutcome:
        """Validate and run a single tool call. Never raises.

        Every failure (unknown tool, bad arguments, `ToolError`, timeout, an
        unexpected exception) becomes an error observation for the model, so
        it can correct itself instead of the whole run dying.
        """
        tool = self._tools.get(call.name)
        started = time.monotonic()

        def failed(message: str) -> _CallOutcome:
            return ToolOutput(content=message), True, time.monotonic() - started

        async with semaphore:
            if tool is None:
                return failed(f"Unknown tool: {call.name!r}")
            try:
                validated = tool.args_schema(**call.arguments)
            except ValidationError as exc:
                return failed(f"Invalid arguments for {call.name!r}: {exc}")
            try:
                result = await asyncio.wait_for(
                    tool.run(**validated.model_dump()),
                    timeout=timeout_s or self._settings.tool_timeout_s,
                )
            except ToolError as exc:
                return failed(str(exc))
            except TimeoutError:
                return failed(f"Tool {call.name!r} timed out after {timeout_s:.0f}s")
            except Exception as exc:
                logger.exception("tool call failed", extra={"tool": call.name, "call_id": call.id})
                return failed(f"Tool {call.name!r} raised {type(exc).__name__}: {exc}")
            output = result if isinstance(result, ToolOutput) else ToolOutput(content=result)
            return output, False, time.monotonic() - started


__all__ = ["AgentLoop", "BudgetExceededError"]
