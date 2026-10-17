"""Moving files in and out of the agent's workspace over HTTP.

A client uploads the inputs it wants the agent to work on, asks the agent
about them by path, and downloads whatever the agent created. Every path
goes through `Workspace.resolve`, exactly like the agent's own tools, so
the API can't be used to reach outside the workspace either. Every endpoint
takes an optional `?workspace=` naming the directory a chat chose (see
`DirectoryPolicy`); without it, the server's own workspace is used.

These endpoints are plain `def`s on purpose: FastAPI runs them in its
threadpool, so blocking disk I/O never stalls a streaming chat.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from agent_runtime.api.deps import get_request_workspace, get_settings, require_api_key
from agent_runtime.api.schemas import FilesResponse, FileView
from agent_runtime.config import Settings
from agent_runtime.files.workspace import Workspace, WorkspaceError, atomic_target

router = APIRouter(prefix="/v1/files", tags=["files"], dependencies=[Depends(require_api_key)])

_CHUNK_BYTES = 1024 * 1024


def _resolve(workspace: Workspace, path: str) -> Path:
    try:
        return workspace.resolve(path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _existing_file(workspace: Workspace, path: str) -> Path:
    resolved = _resolve(workspace, path)
    if not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No file at {path!r}")
    return resolved


@router.get("", response_model=FilesResponse)
def list_files(
    path: str = ".", workspace: Workspace = Depends(get_request_workspace)
) -> FilesResponse:
    """Every file under `path` (default: the whole workspace), recursively."""
    directory = _resolve(workspace, path)
    if not directory.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No directory at {path!r}"
        )
    return FilesResponse(
        files=[
            FileView.from_path(file, workspace.display(file))
            for file in workspace.iter_files(directory)
        ]
    )


@router.post("", response_model=FileView, status_code=status.HTTP_201_CREATED)
def upload_file(
    file: UploadFile = File(...),
    path: str | None = Form(
        default=None,
        description="Where to store it. A folder (ending in '/') keeps the upload's name; "
        "omit to store it at the workspace root.",
    ),
    overwrite: bool = Form(default=False),
    workspace: Workspace = Depends(get_request_workspace),
    settings: Settings = Depends(get_settings),
) -> FileView:
    """Put a file into the workspace so the agent can work on it."""
    filename = Path(file.filename or "").name
    if path is None or path.endswith(("/", "\\")):
        if not filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The upload has no filename; pass a path.",
            )
        path = f"{path or ''}{filename}"
    target = _resolve(workspace, path)
    if target.is_dir():
        if not filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"{path!r} is a directory."
            )
        target = _resolve(workspace, workspace.display(target / filename))
    if target.exists() and not overwrite:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{workspace.display(target)} already exists; set overwrite=true to replace it.",
        )

    written = 0
    with atomic_target(target) as tmp, tmp.open("wb") as out:
        while chunk := file.file.read(_CHUNK_BYTES):
            written += len(chunk)
            if written > settings.max_file_bytes:
                # Raising inside atomic_target discards the partial upload.
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploads are limited to {settings.max_file_bytes} bytes.",
                )
            out.write(chunk)
    return FileView.from_path(target, workspace.display(target))


@router.get("/{file_path:path}", response_class=FileResponse)
def download_file(
    file_path: str, workspace: Workspace = Depends(get_request_workspace)
) -> FileResponse:
    """Download a file from the workspace, e.g. one the agent created."""
    resolved = _existing_file(workspace, file_path)
    return FileResponse(resolved, filename=resolved.name)


@router.delete("/{file_path:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_path: str, workspace: Workspace = Depends(get_request_workspace)) -> Response:
    """Remove a file from the workspace."""
    _existing_file(workspace, file_path).unlink()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
