from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_runtime.files.workspace import Workspace, WorkspaceError, atomic_target


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "ws")


def test_creates_root(tmp_path: Path) -> None:
    Workspace(tmp_path / "new" / "root")
    assert (tmp_path / "new" / "root").is_dir()


@pytest.mark.parametrize("path", ["a.txt", "./a.txt", "sub/../a.txt", "sub/deeper/b.md", "."])
def test_resolves_paths_inside(workspace: Workspace, path: str) -> None:
    resolved = workspace.resolve(path)
    assert resolved == workspace.root or resolved.is_relative_to(workspace.root)


@pytest.mark.parametrize("path", ["..", "../x.txt", "sub/../../x.txt", "a\x00b"])
def test_rejects_paths_that_escape(workspace: Workspace, path: str) -> None:
    with pytest.raises(WorkspaceError):
        workspace.resolve(path)


def test_rejects_absolute_paths_outside(workspace: Workspace, tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        workspace.resolve(str(tmp_path / "elsewhere.txt"))


def test_accepts_absolute_paths_inside(workspace: Workspace) -> None:
    inside = workspace.root / "file.txt"
    assert workspace.resolve(str(inside)) == inside


def test_rejects_symlink_escape(workspace: Workspace, tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    link = workspace.root / "link.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    with pytest.raises(WorkspaceError):
        workspace.resolve("link.txt")


def test_display_is_relative_with_forward_slashes(workspace: Workspace) -> None:
    assert workspace.display(workspace.root / "a" / "b.txt") == "a/b.txt"
    assert workspace.display(workspace.root) == "."


def test_existing_file_reports_missing_and_directories(workspace: Workspace) -> None:
    (workspace.root / "dir").mkdir()
    with pytest.raises(WorkspaceError, match="not found"):
        workspace.existing_file("missing.txt")
    with pytest.raises(WorkspaceError, match="Not a file"):
        workspace.existing_file("dir")


def test_atomic_target_keeps_the_old_file_when_writing_fails(workspace: Workspace) -> None:
    target = workspace.root / "keep.txt"
    target.write_text("original")

    def write_then_fail() -> None:
        with atomic_target(target) as tmp:
            tmp.write_text("half written")
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        write_then_fail()

    assert target.read_text() == "original"
    assert list(workspace.root.iterdir()) == [target]


def test_atomic_target_replaces_on_success(workspace: Workspace) -> None:
    target = workspace.root / "nested" / "new.txt"
    with atomic_target(target) as tmp:
        tmp.write_text("done")
    assert target.read_text() == "done"
