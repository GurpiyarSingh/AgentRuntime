"""Persistent sessions and run activity in PostgreSQL (or SQLite), via SQLAlchemy.

Enabled by `DATABASE_URL`; without it the runtime keeps sessions in memory
(`agent_runtime.sessions.SessionStore`) and records no activity.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import create_async_engine

from agent_runtime.storage.store import DatabaseRunRecorder, DatabaseStore, SessionDetail


def async_database_url(url: str) -> str:
    """Pick the async driver for a plain URL: asyncpg for PostgreSQL, aiosqlite for SQLite."""
    for plain, driver in (
        ("postgresql://", "postgresql+asyncpg://"),
        ("postgres://", "postgresql+asyncpg://"),
        ("sqlite://", "sqlite+aiosqlite://"),
    ):
        if url.startswith(plain):
            return driver + url[len(plain) :]
    return url


def create_database_store(
    url: str,
    *,
    max_messages: int,
    token_ttl: timedelta = timedelta(days=7),
    echo: bool = False,
) -> DatabaseStore:
    """A `DatabaseStore` on `url`. No connection is made until first use."""
    engine = create_async_engine(async_database_url(url), echo=echo, pool_pre_ping=True)
    return DatabaseStore(engine, max_messages=max_messages, token_ttl=token_ttl)


__all__ = [
    "DatabaseRunRecorder",
    "DatabaseStore",
    "SessionDetail",
    "async_database_url",
    "create_database_store",
]
