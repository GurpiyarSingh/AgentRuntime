"""Signing in to the web app (needs `DATABASE_URL`; on unless `AUTH_ENABLED=false`).

    GET  /v1/auth/status   is sign-in on, and does the first account still need creating?
    POST /v1/auth/setup    create the first (admin) account; only while there is none
    POST /v1/auth/login    username + password -> token
    POST /v1/auth/logout   forget this browser's token
    GET  /v1/auth/me       who the token belongs to

Clients send the token as `Authorization: Bearer <token>`.
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from agent_runtime.api.deps import bearer_token, get_user_store, require_api_key
from agent_runtime.api.schemas import (
    AuthStatus,
    LoginRequest,
    LoginResponse,
    SetupRequest,
    UserView,
)
from agent_runtime.auth import LoginThrottle, Principal
from agent_runtime.storage.tables import UserRow
from agent_runtime.storage.users import UsernameTaken, UserStore

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _require_users(users: UserStore | None) -> UserStore:
    if users is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sign-in is not enabled on this server.",
        )
    return users


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _signed_in(users: UserStore, user: UserRow, request: Request) -> LoginResponse:
    token = await users.issue_token(
        user, client_host=_client(request), user_agent=request.headers.get("user-agent")
    )
    return LoginResponse(token=token, user=UserView.from_row(user))


@router.get("/status", response_model=AuthStatus)
async def auth_status(users: UserStore | None = Depends(get_user_store)) -> AuthStatus:
    """Whether the web app must show its sign-in page, and in which mode."""
    if users is None:
        return AuthStatus(enabled=False, setup_required=False)
    return AuthStatus(enabled=True, setup_required=await users.count() == 0)


@router.post("/setup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def setup(
    body: SetupRequest, request: Request, users: UserStore | None = Depends(get_user_store)
) -> LoginResponse:
    """Create the first account, as an admin, and sign it in. Refused once one exists."""
    store = _require_users(users)
    if await store.count() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Setup is already complete; sign in."
        )
    try:
        user = await store.create(
            body.username, body.password, display_name=body.display_name, is_admin=True
        )
    except UsernameTaken as exc:  # Two setups racing.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _signed_in(store, user, request)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest, request: Request, users: UserStore | None = Depends(get_user_store)
) -> LoginResponse:
    """Exchange a username and password for a token."""
    store = _require_users(users)
    throttle: LoginThrottle = request.app.state.login_throttle
    client, name = _client(request), body.username.strip().lower()
    wait = throttle.retry_after(client, name)
    if wait > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Try again in {math.ceil(wait / 60)} min.",
            headers={"Retry-After": str(math.ceil(wait))},
        )
    user = await store.authenticate(body.username, body.password)
    if user is None:
        throttle.failed(client, name)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong username or password."
        )
    throttle.succeeded(client, name)
    return await _signed_in(store, user, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token: str | None = Depends(bearer_token), users: UserStore | None = Depends(get_user_store)
) -> Response:
    """Sign this browser out (its token stops working at once)."""
    if users is not None and token is not None:
        await users.revoke_token(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserView)
async def me(
    principal: Principal = Depends(require_api_key),
    users: UserStore | None = Depends(get_user_store),
) -> UserView:
    """The signed-in account. 401 when the token is missing or expired."""
    store = _require_users(users)
    if principal.user_id is None:  # The API key: no account behind it.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No account.")
    user = await store.get(principal.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    return UserView.from_row(user)


__all__ = ["router"]
