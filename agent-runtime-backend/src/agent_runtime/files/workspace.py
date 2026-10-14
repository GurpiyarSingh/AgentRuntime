"""The directory the agent is allowed to touch, and nothing outside it.

Every path a tool or the files API receives comes from a model or a
client, so every one is treated as hostile: it is resolved (following
symlinks and `..`) and rejected unless the result still lies inside the
workspace root. Tools never open a path that did not come through
`Workspace.resolve`.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class WorkspaceError(ValueError):
    """A path is outside the workspace, missing, or the wrong kind of thing."""


class Workspace:
    """A root directory plus safe path resolution beneath it."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str | Path = ".") -> Path:
        """An absolute path inside the workspace, or `WorkspaceError`.

        Absolute paths are accepted only when they already point inside
        the root, so a model that echoes back a path it was shown still
        works, but `/etc/passwd` or `../../secrets` never do.
        """
        raw = str(path).strip() or "."
        if "\x00" in raw:
            raise WorkspaceError("Path contains a NUL byte.")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise WorkspaceError(f"Path {raw!r} is outside the workspace.")
        return resolved

    def existing_file(self, path: str | Path) -> Path:
        """Resolve `path` and require it to be an existing regular file."""
        resolved = self.resolve(path)
        if not resolved.exists():
            raise WorkspaceError(f"File not found: {self.display(resolved)}")
        if not resolved.is_file():
            raise WorkspaceError(f"Not a file: {self.display(resolved)}")
        return resolved

    def existing_dir(self, path: str | Path = ".") -> Path:
        """Resolve `path` and require it to be an existing directory."""
        resolved = self.resolve(path)
        if not resolved.exists():
            raise WorkspaceError(f"Directory not found: {self.display(resolved)}")
        if not resolved.is_dir():
            raise WorkspaceError(f"Not a directory: {self.display(resolved)}")
        return resolved

    def display(self, path: Path) -> str:
        """A workspace-relative, forward-slash path for messages to the model."""
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return path.name
        text = relative.as_posix()
        return text if text != "." else "."

    def iter_files(self, start: Path, recursive: bool = True) -> Iterator[Path]:
        """Files under `start`, sorted, skipping anything that escapes via a symlink."""
        pattern = "**/*" if recursive else "*"
        for path in sorted(start.glob(pattern)):
            if path.is_file() and path.resolve().is_relative_to(self.root):
                yield path


@contextmanager
def atomic_target(destination: Path) -> Iterator[Path]:
    """A temp path beside `destination` that replaces it only on success.

    A writer that fails half way (a bad spreadsheet cell, a full disk)
    leaves the previous file intact instead of a truncated one.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.stem}-", suffix=destination.suffix, dir=destination.parent
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        yield tmp
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)


__all__ = ["Workspace", "WorkspaceError", "atomic_target"]
