"""Where conversations live between requests, and who records what runs did.

`ConversationStore` is the seam: the API only calls `get_history`,
`append` and `start_run`. Two implementations exist:

- `SessionStore` (here): an in-memory, TTL-bounded dict behind an asyncio
  lock. Right for a single process and for tests; it forgets everything on
  restart and records no activity.
- `agent_runtime.storage.DatabaseStore`: PostgreSQL (or SQLite), used when
  `DATABASE_URL` is set. Keeps every session, run, event and tool call.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_runtime.agent.events import AgentEvent
from agent_runtime.agent.messages import Message, SystemMessage, ToolMessage
from agent_runtime.auth import Principal


@dataclass(frozen=True, slots=True)
class RunContext:
    """Who started a run, and with what, as known before it begins."""

    session_id: str
    run_id: str
    user_message: str
    model: str
    workspace: str | None = None
    client_host: str | None = None
    user_agent: str | None = None
    user_id: str | None = None
    """The signed-in owner; a new session is created as theirs."""


class RunRecorder(Protocol):
    """Receives every event of one run, as it happens."""

    async def observe(self, event: AgentEvent, payload: dict[str, Any]) -> None:
        """Record `event`; `payload` is exactly what clients were sent for it."""

    async def finish(self) -> None:
        """The run is over (answered, failed, or abandoned by the client)."""


class ConversationStore(Protocol):
    """Conversation history plus, optionally, an activity log of every run."""

    @property
    def keeps_history(self) -> bool:
        """True when sessions outlive the process and can be listed later."""

    async def get_history(self, session_id: str) -> list[Message]:
        """The transcript to continue `session_id` with; empty if unknown."""

    async def append(
        self, session_id: str, new_messages: list[Message], run_id: str | None = None
    ) -> None:
        """Add one whole turn's messages to the session."""

    async def start_run(self, context: RunContext) -> RunRecorder:
        """Begin recording a run; the recorder is told every event."""

    async def can_continue(self, session_id: str, viewer: Principal) -> bool:
        """False when the session exists but belongs to someone else."""


class NullRunRecorder:
    """Records nothing: activity logging is off without a database."""

    async def observe(self, event: AgentEvent, payload: dict[str, Any]) -> None:
        """Ignore `event`."""

    async def finish(self) -> None:
        """Nothing to close."""


@dataclass(slots=True)
class _Session:
    messages: list[Message] = field(default_factory=list)
    last_used: float = field(default_factory=time.monotonic)


def trim_history(messages: list[Message], max_messages: int) -> list[Message]:
    """Drop the oldest messages, but keep a leading `SystemMessage` if present.

    Without this, a long conversation would eventually evict the system
    prompt itself, silently changing the agent's instructions.
    """
    overflow = len(messages) - max_messages
    if overflow <= 0:
        return messages
    head = [messages[0]] if isinstance(messages[0], SystemMessage) else []
    tail = messages[len(head) + overflow :]
    # A cut can land between an assistant turn and its tool results; the
    # model rejects tool results whose request is gone, so drop them too.
    while tail and isinstance(tail[0], ToolMessage):
        tail = tail[1:]
    return [*head, *tail]


class SessionStore:
    """Conversation transcripts keyed by session id.

    A session expires `ttl_s` seconds after it was last written. Expired
    sessions are evicted lazily, on the next access to the store.
    """

    def __init__(self, ttl_s: float, max_messages: int) -> None:
        """Create an empty store.

        Args:
            ttl_s: Idle time after which a session is forgotten.
            max_messages: Most messages kept per session; older ones are
                dropped first, except a leading system prompt.
        """
        self._ttl_s = ttl_s
        self._max_messages = max_messages
        self._sessions: dict[str, _Session] = {}
        self._lock = asyncio.Lock()

    async def get_history(self, session_id: str) -> list[Message]:
        """Return a copy of a session's transcript; empty for an unknown id."""
        async with self._lock:
            self._evict_expired()
            session = self._sessions.get(session_id)
            return list(session.messages) if session else []

    @property
    def keeps_history(self) -> bool:
        """In-memory sessions vanish on restart, so there is no history to browse."""
        return False

    async def start_run(self, context: RunContext) -> RunRecorder:
        """No activity log in memory."""
        return NullRunRecorder()

    async def can_continue(self, session_id: str, viewer: Principal) -> bool:
        """In-memory sessions have no owners (sign-in needs a database)."""
        return True

    async def append(
        self, session_id: str, new_messages: list[Message], run_id: str | None = None
    ) -> None:
        """Add messages to a session, creating it if needed, and refresh its TTL."""
        async with self._lock:
            self._evict_expired()
            session = self._sessions.setdefault(session_id, _Session())
            session.messages.extend(new_messages)
            session.messages = trim_history(session.messages, self._max_messages)
            session.last_used = time.monotonic()

    def _evict_expired(self) -> None:
        """Forget every session idle for longer than the TTL. Caller holds the lock."""
        now = time.monotonic()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_used > self._ttl_s]
        for sid in expired:
            del self._sessions[sid]


__all__ = [
    "ConversationStore",
    "NullRunRecorder",
    "RunContext",
    "RunRecorder",
    "SessionStore",
    "trim_history",
]
