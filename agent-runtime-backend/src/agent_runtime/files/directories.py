"""Which directories a client may point the agent at, and browsing them.

The server starts with one workspace (`WORKSPACE_DIR`). A client may ask for
a different one per request — the web app's "Browse…" button — when
`WORKSPACE_SELECTABLE` is on. A requested directory must already exist, be
absolute, and (when `WORKSPACE_BROWSE_ROOTS` is set) lie beneath one of the
allowed roots. Browsing follows the same rules, so a client can only ever
see the folders it could also choose.
"""

from __future__ import annotations

import os
import string
from dataclasses import dataclass
from pathlib import Path

from agent_runtime.files.workspace import Workspace, WorkspaceError

# A folder with more subfolders than this is listed in part, not at all.
MAX_LISTED_DIRECTORIES = 2000


class DirectorySelectionDisabled(WorkspaceError):
    """The server only works in its configured workspace."""


@dataclass(frozen=True, slots=True)
class DirectoryListing:
    """The subfolders of one folder, or the top-level locations when `path` is None."""

    path: Path | None
    parent: Path | None
    directories: list[Path]
    truncated: bool = False


def _top_level() -> list[Path]:
    """Every filesystem root: drive letters on Windows, `/` elsewhere."""
    if os.name == "nt":
        return [
            Path(f"{letter}:\\")
            for letter in string.ascii_uppercase
            if Path(f"{letter}:\\").exists()
        ]
    return [Path("/")]


class DirectoryPolicy:
    """Turns a client's requested directory into a `Workspace`, safely."""

    def __init__(self, default: Workspace, *, selectable: bool, roots: list[Path]) -> None:
        """Create the policy.

        Args:
            default: The workspace used when a request names none.
            selectable: Whether a request may name another directory at all.
            roots: Directories a request may choose beneath; empty = anywhere.
        """
        self.default = default
        self.selectable = selectable
        self.roots = [root.expanduser().resolve() for root in roots]

    def workspace_for(self, requested: str | None) -> Workspace:
        """The workspace for a request: the default, or the directory it names.

        Raises:
            DirectorySelectionDisabled: A directory was named, but choosing is off.
            WorkspaceError: The directory is relative, missing, or not allowed.
        """
        if requested is None or not requested.strip():
            return self.default
        resolved = self._allowed_dir(requested)
        if resolved == self.default.root:
            return self.default
        return Workspace(resolved)

    def browse(self, path: str | None) -> DirectoryListing:
        """List the subfolders of `path`, or the top-level locations if it is empty.

        Raises:
            DirectorySelectionDisabled: Choosing a directory is off.
            WorkspaceError: `path` is relative, missing, or not allowed.
        """
        self._require_selectable()
        if path is None or not path.strip():
            tops = self.roots or _top_level()
            return DirectoryListing(path=None, parent=None, directories=tops)

        directory = self._allowed_dir(path)
        children: list[Path] = []
        truncated = False
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            raise WorkspaceError(f"Cannot open {directory}: {exc.strerror or exc}") from exc
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue  # Unreadable entry (permissions, broken link): not offered.
            if self.roots and not self._within_roots(entry.resolve()):
                continue  # A symlink leading out of the allowed roots.
            if len(children) >= MAX_LISTED_DIRECTORIES:
                truncated = True
                break
            children.append(entry)
        return DirectoryListing(
            path=directory,
            parent=self._parent(directory),
            directories=children,
            truncated=truncated,
        )

    def _require_selectable(self) -> None:
        if not self.selectable:
            raise DirectorySelectionDisabled(
                "This server does not allow choosing the workspace directory."
            )

    def _allowed_dir(self, raw: str) -> Path:
        """Resolve `raw` and require an existing, allowed directory."""
        text = raw.strip()
        if "\x00" in text:
            raise WorkspaceError("Path contains a NUL byte.")
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            raise WorkspaceError(f"Choose an absolute directory path, not {text!r}.")
        resolved = candidate.resolve()
        if resolved == self.default.root:
            return resolved
        self._require_selectable()
        if not self._within_roots(resolved):
            raise WorkspaceError(f"{resolved} is outside the directories this server allows.")
        if not resolved.is_dir():
            raise WorkspaceError(f"Directory not found: {resolved}")
        return resolved

    def _within_roots(self, path: Path) -> bool:
        if not self.roots:
            return True
        return any(path == root or path.is_relative_to(root) for root in self.roots)

    def _parent(self, directory: Path) -> Path | None:
        """The folder above `directory`, or None when it is a top-level location."""
        if directory in self.roots or directory.parent == directory:
            return None
        parent = directory.parent
        return parent if self._within_roots(parent) else None


__all__ = [
    "MAX_LISTED_DIRECTORIES",
    "DirectoryListing",
    "DirectoryPolicy",
    "DirectorySelectionDisabled",
]
