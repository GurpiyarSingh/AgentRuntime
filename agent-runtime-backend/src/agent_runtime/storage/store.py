"""A `ConversationStore` on a SQL database, with a full activity log.

Conversation history survives restarts, and every run is recorded.

What gets written, and when:

- `start_run`: the session row (created on its first run) and a `runs` row
  with status `running`, before the model is called.
- `observe`: each event as it streams, into `run_events`; tool calls also
  into `tool_calls`. Model tokens are merged into one `model_token` event
  per step: thousands of rows per answer would add nothing a replay needs.
- `finish`: the run's outcome, usage and cost, and the session's totals.
- `append`: the turn's transcript messages, which `get_history` replays to
  the model on the next message.

Activity logging is best effort: a failed write is logged and the run
carries on, because losing a log row must never cost the user their answer.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, func, inspect, or_, select, text, true, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agent_runtime.agent.events import (
    AgentEvent,
    FinalAnswer,
    ModelToken,
    RunFailed,
    RunStarted,
    ToolCallRequested,
    ToolCallResult,
    UsageUpdated,
    event_name,
)
from agent_runtime.agent.messages import Message
from agent_runtime.auth import EVERYONE, Principal
from agent_runtime.sessions import RunContext, RunRecorder, trim_history
from agent_runtime.storage.codec import decode_message, encode_message
from agent_runtime.storage.tables import (
    Base,
    MessageRow,
    RunEventRow,
    RunRow,
    SessionRow,
    ToolCallRow,
)
from agent_runtime.storage.users import UserStore
from agent_runtime.usage import TokenUsage

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 80


def _now() -> datetime:
    return datetime.now(UTC)


def session_title(message: str) -> str:
    """A session's default title: the first line of its first message."""
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    if len(first_line) <= TITLE_MAX_CHARS:
        return first_line
    return first_line[: TITLE_MAX_CHARS - 1].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class SessionDetail:
    """A session with every run it holds and every event of each run, in order."""

    session: SessionRow
    runs: list[RunRow]
    events: dict[str, list[RunEventRow]]


class DatabaseStore:
    """Sessions, transcripts and run activity in a SQL database."""

    def __init__(
        self,
        engine: AsyncEngine,
        max_messages: int,
        token_ttl: timedelta = timedelta(days=7),
    ) -> None:
        """Create a store on `engine`.

        Args:
            engine: An async SQLAlchemy engine (asyncpg, or aiosqlite in tests).
            max_messages: Most transcript messages replayed to the model per
                turn. Every message is kept; only the model's view is trimmed.
            token_ttl: How long a sign-in lasts.
        """
        self._engine = engine
        self._max_messages = max_messages
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self.users = UserStore(self._sessions, token_ttl)

    @property
    def keeps_history(self) -> bool:
        """Sessions persist and can be listed."""
        return True

    async def create_schema(self) -> None:
        """Create any missing tables (existing ones are left as they are)."""
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(_add_missing_columns)

    async def close(self) -> None:
        """Close every pooled connection."""
        await self._engine.dispose()

    def db(self) -> AsyncSession:
        """A new ORM session (use as `async with store.db() as db:`)."""
        return self._sessions()

    # --- transcript ---------------------------------------------------------

    async def get_history(self, session_id: str) -> list[Message]:
        """The newest `max_messages` messages (plus the system prompt) of a session."""
        async with self.db() as db:
            last = await db.scalar(
                select(func.max(MessageRow.position)).where(MessageRow.session_id == session_id)
            )
            if last is None:
                return []
            first_kept = last + 1 - self._max_messages
            rows = await db.scalars(
                select(MessageRow)
                .where(
                    MessageRow.session_id == session_id,
                    or_(MessageRow.position == 0, MessageRow.position >= first_kept),
                )
                .order_by(MessageRow.position)
            )
            messages = [decode_message(row.role, row.content, row.data) for row in rows]
        return trim_history(messages, self._max_messages)

    async def append(
        self, session_id: str, new_messages: list[Message], run_id: str | None = None
    ) -> None:
        """Add one turn's messages after the session's existing ones."""
        if not new_messages:
            return
        async with self.db() as db, db.begin():
            await self._ensure_session(db, session_id)
            last = await db.scalar(
                select(func.max(MessageRow.position)).where(MessageRow.session_id == session_id)
            )
            start = 0 if last is None else last + 1
            now = _now()
            for offset, message in enumerate(new_messages):
                role, content, data = encode_message(message)
                db.add(
                    MessageRow(
                        session_id=session_id,
                        run_id=run_id,
                        position=start + offset,
                        role=role,
                        content=content,
                        data=data,
                        created_at=now,
                    )
                )

    async def _ensure_session(self, db: AsyncSession, session_id: str) -> SessionRow:
        row = await db.get(SessionRow, session_id)
        if row is None:
            now = _now()
            row = SessionRow(id=session_id, title="", created_at=now, updated_at=now)
            db.add(row)
            await db.flush()
        return row

    # --- activity -----------------------------------------------------------

    async def start_run(self, context: RunContext) -> RunRecorder:
        """Write the session and a `running` run row, and return its recorder."""
        now = _now()
        try:
            async with self.db() as db, db.begin():
                session = await self._ensure_session(db, context.session_id)
                if session.user_id is None and session.run_count == 0:
                    session.user_id = context.user_id
                if not session.title:
                    session.title = session_title(context.user_message)
                session.model = context.model
                session.workspace = context.workspace
                session.updated_at = now
                if context.client_host:
                    session.client_host = context.client_host
                if context.user_agent:
                    session.user_agent = context.user_agent
                db.add(
                    RunRow(
                        id=context.run_id,
                        session_id=context.session_id,
                        user_message=context.user_message,
                        model=context.model,
                        workspace=context.workspace,
                        status="running",
                        client_host=context.client_host,
                        started_at=now,
                    )
                )
        except Exception:
            logger.exception("could not record run start", extra={"run_id": context.run_id})
        return DatabaseRunRecorder(self, context, started_at=now)

    # --- browsing -----------------------------------------------------------

    async def can_continue(self, session_id: str, viewer: Principal) -> bool:
        """False when the session exists but `viewer` may not see it."""
        async with self.db() as db:
            session = await db.get(SessionRow, session_id)
        return session is None or viewer.can_see(session.user_id)

    async def list_sessions(
        self,
        *,
        viewer: Principal = EVERYONE,
        limit: int = 50,
        offset: int = 0,
        query: str | None = None,
    ) -> list[SessionRow]:
        """`viewer`'s sessions, most recently active first, optionally filtered by title."""
        statement = select(SessionRow).where(SessionRow.run_count > 0, _visible_to(viewer))
        if query:
            statement = statement.where(SessionRow.title.ilike(f"%{query}%"))
        statement = statement.order_by(SessionRow.updated_at.desc()).limit(limit).offset(offset)
        async with self.db() as db:
            return list(await db.scalars(statement))

    async def get_session(
        self, session_id: str, viewer: Principal = EVERYONE
    ) -> SessionDetail | None:
        """A session with its runs and events; None if missing or not `viewer`'s."""
        async with self.db() as db:
            session = await db.get(SessionRow, session_id)
            if session is None or not viewer.can_see(session.user_id):
                return None
            runs = list(
                await db.scalars(
                    select(RunRow)
                    .where(RunRow.session_id == session_id)
                    .order_by(RunRow.started_at, RunRow.id)
                )
            )
            events: dict[str, list[RunEventRow]] = defaultdict(list)
            for event in await db.scalars(
                select(RunEventRow)
                .where(RunEventRow.session_id == session_id)
                .order_by(RunEventRow.run_id, RunEventRow.seq)
            ):
                events[event.run_id].append(event)
        return SessionDetail(session=session, runs=runs, events=dict(events))

    async def rename_session(
        self, session_id: str, title: str, viewer: Principal = EVERYONE
    ) -> SessionRow | None:
        """Set a session's title; None if missing or not `viewer`'s."""
        async with self.db() as db, db.begin():
            session = await db.get(SessionRow, session_id)
            if session is None or not viewer.can_see(session.user_id):
                return None
            session.title = title
        return session

    async def delete_session(self, session_id: str, viewer: Principal = EVERYONE) -> bool:
        """Delete a session and all its records; False if missing or not `viewer`'s."""
        if not await self.can_continue(session_id, viewer):
            return False
        async with self.db() as db, db.begin():
            # Children first, explicitly: SQLite ignores ON DELETE CASCADE
            # unless foreign keys are switched on per connection.
            for table in (RunEventRow, ToolCallRow, MessageRow, RunRow):
                await db.execute(delete(table).where(table.session_id == session_id))
            result = await db.execute(delete(SessionRow).where(SessionRow.id == session_id))
        return bool(getattr(result, "rowcount", 0))


def _visible_to(viewer: Principal) -> ColumnElement[bool]:
    """SQL form of `Principal.can_see`."""
    if viewer.user_id is None:
        return true()
    if viewer.is_admin:
        return or_(SessionRow.user_id == viewer.user_id, SessionRow.user_id.is_(None))
    return SessionRow.user_id == viewer.user_id


def _add_missing_columns(connection: Connection) -> None:
    """Bring tables created by an older version up to date.

    `create_all` creates missing tables but never changes existing ones, so
    columns added since are added here. (A migration tool such as Alembic is
    the next step once changes stop being purely additive.)
    """
    columns = {column["name"] for column in inspect(connection).get_columns("sessions")}
    if "user_id" not in columns:
        connection.execute(text("ALTER TABLE sessions ADD COLUMN user_id VARCHAR(64)"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id)")
        )


class DatabaseRunRecorder:
    """Writes one run's events as they stream, then its outcome."""

    def __init__(self, store: DatabaseStore, context: RunContext, started_at: datetime) -> None:
        """Record the run described by `context`, which began at `started_at`."""
        self._store = store
        self._context = context
        self._started_at = started_at
        self._seq = 0
        self._token_step = 0
        self._token_text: list[str] = []
        self._token_payload: dict[str, Any] | None = None
        self._steps = 0
        self._tool_calls = 0
        self._usage = TokenUsage()
        self._answer: str | None = None
        self._error: str | None = None
        self._finished = False

    async def observe(self, event: AgentEvent, payload: dict[str, Any]) -> None:
        """Record `event` (tokens are buffered until their step's text is complete)."""
        step = getattr(event, "step", 0)
        self._steps = max(self._steps, step)
        if isinstance(event, ModelToken):
            if self._token_text and step != self._token_step:
                await self._flush_tokens()
            self._token_step = step
            self._token_text.append(event.text)
            self._token_payload = payload
            return
        await self._flush_tokens()

        if isinstance(event, UsageUpdated):
            self._usage = event.run_usage
        elif isinstance(event, FinalAnswer):
            self._answer = event.content
        elif isinstance(event, RunFailed):
            self._error = event.reason
        elif isinstance(event, ToolCallRequested):
            self._tool_calls += 1
        await self._write(event, payload)

    async def finish(self) -> None:
        """Close the run: its status, answer or error, usage, and the session totals."""
        if self._finished:
            return
        self._finished = True
        await self._flush_tokens()
        now = _now()
        if self._answer is not None:
            status = "completed"
        elif self._error is not None:
            status = "failed"
        else:
            status = "cancelled"  # The client went away before the run ended.
        usage = self._usage
        run_id = self._context.run_id
        try:
            async with self._store.db() as db, db.begin():
                await db.execute(
                    update(RunRow)
                    .where(RunRow.id == run_id)
                    .values(
                        status=status,
                        answer=self._answer,
                        error=self._error,
                        steps_used=self._steps,
                        tool_call_count=self._tool_calls,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        total_tokens=usage.total_tokens,
                        cost_usd=usage.cost_usd,
                        finished_at=now,
                        duration_s=(now - self._started_at).total_seconds(),
                    )
                )
                await db.execute(
                    update(ToolCallRow)
                    .where(ToolCallRow.run_id == run_id, ToolCallRow.status == "running")
                    .values(status="cancelled", finished_at=now)
                )
                await db.execute(
                    update(SessionRow)
                    .where(SessionRow.id == self._context.session_id)
                    .values(
                        run_count=SessionRow.run_count + 1,
                        input_tokens=SessionRow.input_tokens + usage.input_tokens,
                        output_tokens=SessionRow.output_tokens + usage.output_tokens,
                        total_tokens=SessionRow.total_tokens + usage.total_tokens,
                        cost_usd=SessionRow.cost_usd + (usage.cost_usd or 0.0),
                        updated_at=now,
                    )
                )
        except Exception:
            logger.exception("could not record run outcome", extra={"run_id": run_id})

    async def _flush_tokens(self) -> None:
        """Write the buffered tokens of one step as a single `model_token` event."""
        if not self._token_text or self._token_payload is None:
            return
        payload = {**self._token_payload, "text": "".join(self._token_text)}
        self._token_text = []
        self._token_payload = None
        await self._write_row("model_token", self._token_step, payload)

    async def _write(self, event: AgentEvent, payload: dict[str, Any]) -> None:
        name = event_name(event)
        step = getattr(event, "step", 0)
        await self._write_row(name, step, payload, event)

    async def _write_row(
        self, name: str, step: int, payload: dict[str, Any], event: AgentEvent | None = None
    ) -> None:
        self._seq += 1
        now = _now()
        context = self._context
        try:
            async with self._store.db() as db, db.begin():
                db.add(
                    RunEventRow(
                        run_id=context.run_id,
                        session_id=context.session_id,
                        seq=self._seq,
                        type=name,
                        step=step,
                        payload=payload,
                        created_at=now,
                    )
                )
                if isinstance(event, RunStarted):
                    await db.execute(
                        update(RunRow)
                        .where(RunRow.id == context.run_id)
                        .values(max_steps=event.max_steps)
                    )
                elif isinstance(event, ToolCallRequested):
                    db.add(
                        ToolCallRow(
                            run_id=context.run_id,
                            session_id=context.session_id,
                            call_id=event.call_id,
                            step=event.step,
                            tool_name=event.tool_name,
                            arguments=event.arguments,
                            status="running",
                            requested_at=now,
                        )
                    )
                elif isinstance(event, ToolCallResult):
                    await db.execute(
                        update(ToolCallRow)
                        .where(
                            ToolCallRow.run_id == context.run_id,
                            ToolCallRow.call_id == event.call_id,
                        )
                        .values(
                            status="error" if event.is_error else "ok",
                            content=event.content,
                            is_error=event.is_error,
                            duration_s=event.duration_s,
                            image_count=event.image_count,
                            finished_at=now,
                        )
                    )
        except Exception:
            logger.exception(
                "could not record run event", extra={"run_id": context.run_id, "event": name}
            )


__all__ = ["DatabaseRunRecorder", "DatabaseStore", "SessionDetail", "session_title"]
