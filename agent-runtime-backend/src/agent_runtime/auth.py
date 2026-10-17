"""Passwords, sign-in tokens, and slowing down password guessing.

Standard library only:

- Passwords are hashed with scrypt (memory-hard, so GPU guessing is slow),
  with a random salt per password. The stored string carries its own
  parameters, so they can be raised later without breaking old hashes.
- A sign-in token is 32 random bytes. The database keeps only its SHA-256,
  so a leaked database can't be used to sign in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is making a request, as far as access to stored sessions goes.

    `user_id` None means unrestricted: sign-in is off, or the caller used
    the server's API key (a script or an operator), and sees everything.
    """

    user_id: str | None = None
    username: str | None = None
    is_admin: bool = False

    def can_see(self, owner: str | None) -> bool:
        """Whether this caller may read a session owned by `owner`.

        Sessions without an owner predate sign-in; admins can see them.
        """
        if self.user_id is None or owner == self.user_id:
            return True
        return owner is None and self.is_admin


EVERYONE = Principal()
"""Unrestricted access: sign-in off, or the API key was used."""

# scrypt cost: 2^14 iterations x 8 x 1 uses 16 MB per hash, ~50 ms.
_N, _R, _P = 2**14, 8, 1
_KEY_BYTES = 32
_SALT_BYTES = 16

MIN_PASSWORD_LENGTH = 8


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    """`scrypt$N$r$p$salt$hash`, ready to store."""
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_BYTES)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    """True when `password` matches a hash from `hash_password`."""
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        key = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(expected)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key, base64.b64decode(expected))


# A real hash of nothing in particular: checking a password against it takes
# as long as a real check, so a missing username can't be told apart by timing.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def new_token() -> str:
    """A fresh, unguessable sign-in token for the client."""
    return secrets.token_urlsafe(32)


def token_id(token: str) -> str:
    """What the database stores for `token`: its SHA-256, in hex."""
    return hashlib.sha256(token.encode()).hexdigest()


class LoginThrottle:
    """Refuses sign-in after too many recent failures for one name from one address.

    In memory, per process: enough to make guessing slow on a single server
    without locking the real user out for long.
    """

    def __init__(self, max_failures: int = 5, window_s: float = 300.0) -> None:
        """Allow `max_failures` wrong passwords per `window_s` seconds."""
        self._max = max_failures
        self._window = window_s
        self._failures: defaultdict[tuple[str, str], deque[float]] = defaultdict(deque)

    def retry_after(self, client: str, username: str) -> float:
        """Seconds until another attempt is allowed; 0 when it is allowed now."""
        failures = self._recent(client, username)
        if len(failures) < self._max:
            return 0.0
        return max(0.0, failures[0] + self._window - time.monotonic())

    def failed(self, client: str, username: str) -> None:
        """Record a wrong password."""
        self._recent(client, username).append(time.monotonic())

    def succeeded(self, client: str, username: str) -> None:
        """Forget the failures once the right password is given."""
        self._failures.pop((client, username), None)

    def _recent(self, client: str, username: str) -> deque[float]:
        failures = self._failures[(client, username)]
        cutoff = time.monotonic() - self._window
        while failures and failures[0] < cutoff:
            failures.popleft()
        return failures


__all__ = [
    "DUMMY_HASH",
    "EVERYONE",
    "MIN_PASSWORD_LENGTH",
    "LoginThrottle",
    "Principal",
    "hash_password",
    "new_token",
    "token_id",
    "verify_password",
]
