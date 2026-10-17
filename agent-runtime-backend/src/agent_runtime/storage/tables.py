"""The database schema: sessions, their transcripts, and everything each run did.

    users ─┬─ auth_tokens  sign-ins (only a hash of each token is stored)
           └─ sessions ─┬─ messages     the transcript replayed to the model
                        └─ runs ─┬─ run_events   every streamed event, in order
                                 └─ tool_calls   one row per tool call, for querying

Event payloads and tool arguments vary by type, so they are JSON (`JSONB`
on PostgreSQL, where they stay queryable and indexable). Everything else is
a plain column, so questions like "cost per day" or "which tool fails most"
are ordinary SQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")
# SQLite only auto-increments an INTEGER primary key.
IdType = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    """Declarative base for every table."""


class UserRow(Base):
    """Someone who can sign in to the web app."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Stored lower-case, so sign-in is case-insensitive.
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    # scrypt, with its parameters and salt: see `agent_runtime.auth`.
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthTokenRow(Base):
    """One signed-in browser. The id is the SHA-256 of the token, never the token."""

    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    client_host: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)


class SessionRow(Base):
    """One conversation, with running totals over all its runs."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # Who owns it; null for sessions made before sign-in was turned on
    # (visible to admins) or without it.
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    model: Mapped[str | None] = mapped_column(String(64))
    workspace: Mapped[str | None] = mapped_column(Text)
    client_host: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class MessageRow(Base):
    """One transcript entry, in order; `data` holds tool calls, usage and images."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_session_position", "session_id", "position"),)

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    run_id: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunRow(Base):
    """One user message and everything the agent did to answer it."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    user_message: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    workspace: Mapped[str | None] = mapped_column(Text)
    # running -> completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), index=True)
    answer: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    max_steps: Mapped[int | None] = mapped_column(Integer)
    steps_used: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    client_host: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float | None] = mapped_column(Float)


class RunEventRow(Base):
    """One event of a run, exactly as streamed (tokens merged per step)."""

    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_run_seq", "run_id", "seq"),)

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32), index=True)
    step: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ToolCallRow(Base):
    """One tool call: what was asked, what came back, and how long it took."""

    __tablename__ = "tool_calls"
    __table_args__ = (UniqueConstraint("run_id", "call_id", name="uq_tool_calls_run_call"),)

    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    call_id: Mapped[str] = mapped_column(String(128))
    step: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JsonType)
    # running -> ok | error | cancelled
    status: Mapped[str] = mapped_column(String(16))
    content: Mapped[str | None] = mapped_column(Text)
    is_error: Mapped[bool | None] = mapped_column(Boolean)
    duration_s: Mapped[float | None] = mapped_column(Float)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "AuthTokenRow",
    "Base",
    "MessageRow",
    "RunEventRow",
    "RunRow",
    "SessionRow",
    "ToolCallRow",
    "UserRow",
]
