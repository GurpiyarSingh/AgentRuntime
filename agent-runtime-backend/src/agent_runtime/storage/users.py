"""Accounts and sign-in tokens in the database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime.auth import (
    DUMMY_HASH,
    hash_password,
    new_token,
    token_id,
    verify_password,
)
from agent_runtime.storage.tables import AuthTokenRow, UserRow

# A token's last-used time is refreshed at most this often, so ordinary
# requests don't each cost a database write.
_TOUCH_EVERY = timedelta(minutes=5)


class UsernameTaken(ValueError):
    """Another account already has this username."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; they were stored in UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


class UserStore:
    """Creates accounts, checks passwords, and issues and resolves tokens."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], token_ttl: timedelta) -> None:
        """Use `sessions` for database access; tokens last `token_ttl`."""
        self._sessions = sessions
        self._token_ttl = token_ttl

    async def count(self) -> int:
        """How many accounts exist (0 means first-run setup is open)."""
        async with self._sessions() as db:
            return int(await db.scalar(select(func.count()).select_from(UserRow)) or 0)

    async def create(
        self, username: str, password: str, *, display_name: str = "", is_admin: bool = False
    ) -> UserRow:
        """Add an account.

        Raises:
            UsernameTaken: The (case-insensitive) username exists already.
        """
        row = UserRow(
            id=f"usr_{uuid.uuid4().hex[:16]}",
            username=username.strip().lower(),
            display_name=display_name.strip(),
            password_hash=hash_password(password),
            is_admin=is_admin,
            created_at=_now(),
        )
        try:
            async with self._sessions() as db, db.begin():
                db.add(row)
        except IntegrityError as exc:
            raise UsernameTaken(f"The username {row.username!r} is taken.") from exc
        return row

    async def get(self, user_id: str) -> UserRow | None:
        """The account with this id, if it exists."""
        async with self._sessions() as db:
            return await db.get(UserRow, user_id)

    async def list(self) -> list[UserRow]:
        """Every account, oldest first."""
        async with self._sessions() as db:
            return list(await db.scalars(select(UserRow).order_by(UserRow.created_at)))

    async def authenticate(self, username: str, password: str) -> UserRow | None:
        """The account when the password is right, otherwise None."""
        async with self._sessions() as db:
            row = await db.scalar(
                select(UserRow).where(UserRow.username == username.strip().lower())
            )
        # Hash even for an unknown name, so timing doesn't reveal which names exist.
        if not verify_password(password, row.password_hash if row else DUMMY_HASH) or not row:
            return None
        return row

    async def issue_token(
        self, user: UserRow, *, client_host: str | None = None, user_agent: str | None = None
    ) -> str:
        """Sign `user` in: store a new token's hash and return the token itself."""
        token = new_token()
        now = _now()
        async with self._sessions() as db, db.begin():
            db.add(
                AuthTokenRow(
                    id=token_id(token),
                    user_id=user.id,
                    created_at=now,
                    expires_at=now + self._token_ttl,
                    last_used_at=now,
                    client_host=client_host,
                    user_agent=user_agent,
                )
            )
            stored = await db.get(UserRow, user.id)
            if stored is not None:
                stored.last_login_at = now
        return token

    async def user_for_token(self, token: str) -> UserRow | None:
        """The signed-in account for `token`; None if it is unknown or expired."""
        now = _now()
        async with self._sessions() as db, db.begin():
            row = await db.get(AuthTokenRow, token_id(token))
            if row is None or _aware(row.expires_at) <= now:
                return None
            if now - _aware(row.last_used_at) > _TOUCH_EVERY:
                row.last_used_at = now
            return await db.get(UserRow, row.user_id)

    async def revoke_token(self, token: str) -> None:
        """Sign out the browser holding `token`."""
        async with self._sessions() as db, db.begin():
            await db.execute(delete(AuthTokenRow).where(AuthTokenRow.id == token_id(token)))

    async def purge_expired_tokens(self) -> int:
        """Delete tokens past their expiry; returns how many."""
        async with self._sessions() as db, db.begin():
            result = await db.execute(delete(AuthTokenRow).where(AuthTokenRow.expires_at <= _now()))
        return int(getattr(result, "rowcount", 0) or 0)


__all__ = ["UserStore", "UsernameTaken"]
