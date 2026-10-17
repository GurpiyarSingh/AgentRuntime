"""Sign-in: first-run setup, tokens, per-user sessions, and the API key alongside."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_runtime.auth import LoginThrottle, Principal, hash_password, verify_password

from .fakes import final_turn
from .test_sessions_db import Harness

PASSWORD = "correct horse battery"  # noqa: S105 - a test fixture.


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    harness = Harness(tmp_path, [final_turn(f"answer {n}") for n in range(10)], auth_enabled=True)
    with TestClient(harness.app) as test_client:
        yield test_client


def setup_admin(client: TestClient, username: str = "Admin") -> dict[str, str]:
    response = client.post(
        "/v1/auth/setup",
        json={"username": username, "password": PASSWORD, "display_name": "The Admin"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def chat(client: TestClient, headers: dict[str, str], session_id: str) -> int:
    return client.post(
        "/v1/chat", json={"message": "hi", "session_id": session_id}, headers=headers
    ).status_code


def test_first_visit_creates_the_admin(client: TestClient) -> None:
    assert client.get("/v1/auth/status").json() == {"enabled": True, "setup_required": True}

    headers = setup_admin(client)

    assert client.get("/v1/auth/status").json()["setup_required"] is False
    me = client.get("/v1/auth/me", headers=headers).json()
    assert me["username"] == "admin"  # Stored lower-case.
    assert me["display_name"] == "The Admin"
    assert me["is_admin"] is True
    # Setup is a one-time door.
    again = client.post("/v1/auth/setup", json={"username": "eve", "password": PASSWORD})
    assert again.status_code == 409


def test_everything_needs_sign_in(client: TestClient) -> None:
    setup_admin(client)

    assert client.post("/v1/chat", json={"message": "hi"}).status_code == 401
    assert client.get("/v1/sessions").status_code == 401
    assert client.get("/v1/files").status_code == 401
    assert client.get("/v1/sessions", headers={"Authorization": "Bearer nope"}).status_code == 401
    # Still public: what the sign-in page itself needs.
    assert client.get("/health").status_code == 200
    assert client.get("/v1/auth/status").status_code == 200


def test_login_is_case_insensitive_and_logout_revokes(client: TestClient) -> None:
    setup_admin(client)

    wrong = client.post("/v1/auth/login", json={"username": "admin", "password": "nope"})
    response = client.post("/v1/auth/login", json={"username": "ADMIN", "password": PASSWORD})

    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "Wrong username or password."
    headers = {"Authorization": f"Bearer {response.json()['token']}"}
    assert client.get("/v1/auth/me", headers=headers).status_code == 200
    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/auth/me", headers=headers).status_code == 401


def test_users_only_see_their_own_sessions(client: TestClient) -> None:
    admin = setup_admin(client)
    users = client.app.state.sessions.users  # type: ignore[attr-defined]
    client.portal.call(users.create, "bob", PASSWORD)  # type: ignore[union-attr]
    bob_token = client.post("/v1/auth/login", json={"username": "bob", "password": PASSWORD})
    bob = {"Authorization": f"Bearer {bob_token.json()['token']}"}

    assert chat(client, admin, "admin_s") == 200
    assert chat(client, bob, "bob_s") == 200

    def ids(headers: dict[str, str]) -> list[str]:
        return [s["id"] for s in client.get("/v1/sessions", headers=headers).json()["sessions"]]

    assert ids(admin) == ["admin_s"]
    assert ids(bob) == ["bob_s"]
    # Bob can't read, rename, delete, or continue the admin's session.
    assert client.get("/v1/sessions/admin_s", headers=bob).status_code == 404
    assert client.patch("/v1/sessions/admin_s", json={"title": "x"}, headers=bob).status_code == 404
    assert client.delete("/v1/sessions/admin_s", headers=bob).status_code == 404
    assert chat(client, bob, "admin_s") == 404


def test_the_api_key_still_works_and_sees_everything(tmp_path: Path) -> None:
    harness = Harness(tmp_path, [final_turn("ok")], auth_enabled=True, api_key="script-key")
    with TestClient(harness.app) as client:
        admin = setup_admin(client)
        assert chat(client, admin, "admin_s") == 200

        listing = client.get("/v1/sessions", headers={"X-API-Key": "script-key"})

        assert [s["id"] for s in listing.json()["sessions"]] == ["admin_s"]
        assert client.get("/v1/sessions", headers={"X-API-Key": "wrong"}).status_code == 401


def test_sign_in_can_be_switched_off(tmp_path: Path) -> None:
    harness = Harness(tmp_path, [final_turn("ok")], auth_enabled=False)
    with TestClient(harness.app) as client:
        assert client.get("/v1/auth/status").json()["enabled"] is False
        assert client.get("/v1/sessions").status_code == 200


def test_repeated_wrong_passwords_are_throttled(client: TestClient) -> None:
    setup_admin(client)
    for _ in range(5):
        client.post("/v1/auth/login", json={"username": "admin", "password": "nope"})

    blocked = client.post("/v1/auth/login", json={"username": "admin", "password": PASSWORD})

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_setup_rejects_a_short_password(client: TestClient) -> None:
    response = client.post("/v1/auth/setup", json={"username": "admin", "password": "short"})
    assert response.status_code == 422


# --- pieces ------------------------------------------------------------------


def test_password_hashes_verify_and_are_salted() -> None:
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)

    assert first != second
    assert verify_password(PASSWORD, first)
    assert not verify_password("wrong", first)
    assert not verify_password(PASSWORD, "garbage")


def test_principal_visibility() -> None:
    admin = Principal(user_id="a", is_admin=True)
    user = Principal(user_id="u")

    assert admin.can_see("a")
    assert admin.can_see(None)  # Sessions from before sign-in.
    assert not admin.can_see("u")
    assert user.can_see("u")
    assert not user.can_see(None)
    assert not user.can_see("a")
    assert Principal().can_see("anyone")


def test_throttle_forgets_after_success() -> None:
    throttle = LoginThrottle(max_failures=2, window_s=60)
    throttle.failed("ip", "bob")
    throttle.failed("ip", "bob")
    assert throttle.retry_after("ip", "bob") > 0
    assert throttle.retry_after("other-ip", "bob") == 0

    throttle.succeeded("ip", "bob")
    assert throttle.retry_after("ip", "bob") == 0
