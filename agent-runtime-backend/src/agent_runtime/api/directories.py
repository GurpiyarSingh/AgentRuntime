"""Browsing server folders, so a client can choose where the agent works.

A browser cannot reveal real filesystem paths, and the agent's tools run on
the server anyway, so the folder picker browses the server's disk through
this endpoint. It obeys the same `DirectoryPolicy` as choosing a workspace:
only folders a client could choose are ever listed.

A plain `def` on purpose, like the files API: listing a large folder is
blocking disk I/O, which FastAPI runs in its threadpool.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agent_runtime.api.deps import get_directory_policy, require_api_key
from agent_runtime.api.schemas import DirectoryListingView
from agent_runtime.files.directories import DirectoryPolicy, DirectorySelectionDisabled
from agent_runtime.files.workspace import WorkspaceError

router = APIRouter(
    prefix="/v1/directories", tags=["files"], dependencies=[Depends(require_api_key)]
)


@router.get("", response_model=DirectoryListingView)
def list_directories(
    path: str | None = None, policy: DirectoryPolicy = Depends(get_directory_policy)
) -> DirectoryListingView:
    """The subfolders of `path` (absolute), or the top-level locations if omitted."""
    try:
        return DirectoryListingView.from_listing(policy.browse(path))
    except DirectorySelectionDisabled as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except WorkspaceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


__all__ = ["router"]
