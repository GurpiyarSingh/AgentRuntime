"""An in-memory, TTL-bounded store for multi-turn conversation history.

Deliberately simple: a dict behind an asyncio lock, which is right for a
single-process deployment. Running several workers needs a shared store
(Redis, a database) behind the same two methods, `get_history` and
`append`; nothing else in the runtime touches sessions.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from agent_runtime.agent.messages import Message, SystemMessage


@dataclass(slots=True)
class _Session:
    messages: list[Message] = field(default_factory=list)
    last_used: float = field(default_factory=time.monotonic)


def _trim(messages: list[Message], max_messages: int) -> list[Message]:
    """Drop the oldest messages, but keep a leading `SystemMessage` if present.

    Without this, a long conversation would eventually evict the system
    prompt itself, silently changing the agent's instructions.
    """
    overflow = len(messages) - max_messages
    if overflow <= 0:
        return messages
    if isinstance(messages[0], SystemMessage):
        return [messages[0], *messages[1 + overflow :]]
    return messages[overflow:]


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

    async def append(self, session_id: str, new_messages: list[Message]) -> None:
        """Add messages to a session, creating it if needed, and refresh its TTL."""
        async with self._lock:
            self._evict_expired()
            session = self._sessions.setdefault(session_id, _Session())
            session.messages.extend(new_messages)
            session.messages = _trim(session.messages, self._max_messages)
            session.last_used = time.monotonic()

    def _evict_expired(self) -> None:
        """Forget every session idle for longer than the TTL. Caller holds the lock."""
        now = time.monotonic()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_used > self._ttl_s]
        for sid in expired:
            del self._sessions[sid]


__all__ = ["SessionStore"]
