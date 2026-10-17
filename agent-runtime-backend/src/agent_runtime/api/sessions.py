"""Browsing, renaming and deleting stored sessions (needs `DATABASE_URL`).

A session's detail carries every run with its recorded events in the same
shape the SSE stream sent them, so a client replays a past conversation
with exactly the code that rendered it live.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from agent_runtime.api.deps import get_history_store, require_api_key
from agent_runtime.api.schemas import (
    SessionDetailView,
    SessionsResponse,
    SessionSummary,
    SessionUpdate,
)
from agent_runtime.auth import Principal
from agent_runtime.storage import DatabaseStore

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No session {session_id!r}")


@router.get("", response_model=SessionsResponse)
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200, description="Filter by title."),
    store: DatabaseStore = Depends(get_history_store),
    viewer: Principal = Depends(require_api_key),
) -> SessionsResponse:
    """The caller's stored sessions, most recently active first."""
    rows = await store.list_sessions(viewer=viewer, limit=limit, offset=offset, query=q)
    return SessionsResponse(sessions=[SessionSummary.from_row(row) for row in rows])


@router.get("/{session_id}", response_model=SessionDetailView)
async def get_session(
    session_id: str,
    store: DatabaseStore = Depends(get_history_store),
    viewer: Principal = Depends(require_api_key),
) -> SessionDetailView:
    """A session with every run and every recorded event."""
    detail = await store.get_session(session_id, viewer)
    if detail is None:
        raise _not_found(session_id)
    return SessionDetailView.from_detail(detail)


@router.patch("/{session_id}", response_model=SessionSummary)
async def rename_session(
    session_id: str,
    body: SessionUpdate,
    store: DatabaseStore = Depends(get_history_store),
    viewer: Principal = Depends(require_api_key),
) -> SessionSummary:
    """Rename a session."""
    row = await store.rename_session(session_id, body.title.strip(), viewer)
    if row is None:
        raise _not_found(session_id)
    return SessionSummary.from_row(row)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    store: DatabaseStore = Depends(get_history_store),
    viewer: Principal = Depends(require_api_key),
) -> Response:
    """Delete a session, its transcript and its whole activity log."""
    if not await store.delete_session(session_id, viewer):
        raise _not_found(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
