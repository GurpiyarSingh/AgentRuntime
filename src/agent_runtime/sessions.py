"""An in-memory, TTL-bounded store for multi-turn conversation history.

This is intentionally simple: a dict behind a lock. It's enough for a
single-process dev/demo deployment. For multi-process or persistent
deployments, swap this for a Redis- or DB-backed implementation behind the
same interface (`get`, `append`, `touch`).
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
    """Drop the oldest messages, but keep a leading SystemMessage if present.

    Without this, a long conversation would eventually evict the system
    prompt itself, silently changing the agent's instructions.
    """
    overflow = len(messages) - max_messages
    if overflow <= 0:
        return messages
    has_leading_system = bool(messages) and isinstance(messages[0], SystemMessage)
    if has_leading_system:
        return [messages[0], *messages[1 + overflow :]]
    return messages[overflow:]


class SessionStore:
    def __init__(self, ttl_s: float, max_messages: int) -> None:
        self._ttl_s = ttl_s
        self._max_messages = max_messages
        self._sessions: dict[str, _Session] = {}
        self._lock = asyncio.Lock()

    async def get_history(self, session_id: str) -> list[Message]:
        async with self._lock:
            self._evict_expired()
            session = self._sessions.get(session_id)
            return list(session.messages) if session else []

    async def append(self, session_id: str, new_messages: list[Message]) -> None:
        async with self._lock:
            self._evict_expired()
            session = self._sessions.setdefault(session_id, _Session())
            session.messages.extend(new_messages)
            session.messages = _trim(session.messages, self._max_messages)
            session.last_used = time.monotonic()

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_used > self._ttl_s]
        for sid in expired:
            del self._sessions[sid]

    def __len__(self) -> int:
        return len(self._sessions)
