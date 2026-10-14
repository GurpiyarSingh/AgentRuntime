from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from agent_runtime.files.workspace import Workspace
from agent_runtime.tools.base import ToolError, ToolOutput
from agent_runtime.tools.file_tools import (
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    ReadImageTool,
    SearchFilesTool,
    WriteFileTool,
    default_tools,
    paginate,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "ws")


def _put(workspace: Workspace, path: str, content: str | bytes) -> Path:
    target = workspace.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target


# --- registry ----------------------------------------------------------------------


def test_default_tools_and_read_only_mode(workspace: Workspace) -> None:
    assert default_tools(workspace).names() == [
        "list_files", "read_file", "read_image", "search_files", "write_file", "edit_file",
    ]  # fmt: skip
    assert default_tools(workspace, read_only=True).names() == [
        "list_files", "read_file", "read_image", "search_files",
    ]  # fmt: skip


# --- list_files --------------------------------------------------------------------


async def test_list_files(workspace: Workspace) -> None:
    _put(workspace, "a.txt", "hello")
    _put(workspace, "docs/b.md", "x")
    tool = ListFilesTool(workspace)

    top = await tool.run()
    assert "a.txt  (5 B)" in top
    assert "docs/" in top
    assert "docs/b.md" not in top
    assert "docs/b.md" in await tool.run(recursive=True)


async def test_list_files_empty_and_missing(workspace: Workspace) -> None:
    tool = ListFilesTool(workspace)
    assert "empty" in await tool.run()
    with pytest.raises(ToolError, match="not found"):
        await tool.run(path="nope")


# --- read_file ---------------------------------------------------------------------


async def test_read_file_returns_text_with_header(workspace: Workspace) -> None:
    _put(workspace, "notes.txt", "line one\nline two")
    result = await ReadFileTool(workspace).run(path="notes.txt")

    assert result.startswith("File: notes.txt (text, ")
    assert "Lines 1-2 of 2" in result
    assert result.endswith("line one\nline two")


async def test_read_file_refuses_paths_outside_workspace(workspace: Workspace) -> None:
    with pytest.raises(ToolError, match="outside the workspace"):
        await ReadFileTool(workspace).run(path="../../etc/passwd")


async def test_read_file_enforces_size_limit(workspace: Workspace) -> None:
    _put(workspace, "big.txt", "x" * 5000)
    with pytest.raises(ToolError, match="limit"):
        await ReadFileTool(workspace, max_file_bytes=1024).run(path="big.txt")


async def test_read_file_pages_long_files(workspace: Workspace) -> None:
    _put(workspace, "long.txt", "\n".join(f"line {i}" for i in range(1, 501)))
    tool = ReadFileTool(workspace, max_chars=1000)

    first = await tool.run(path="long.txt")
    assert "of 500 (continue with start_line=" in first

    tail = await tool.run(path="long.txt", start_line=499)
    assert "Lines 499-500 of 500" in tail
    assert "continue" not in tail


async def test_read_file_reads_documents(workspace: Workspace) -> None:
    await WriteFileTool(workspace).run(path="report.docx", content="# Hello\n\nWorld")
    result = await ReadFileTool(workspace).run(path="report.docx")
    assert "(docx, " in result
    assert "# Hello" in result


def test_paginate_window_and_long_lines() -> None:
    text = "\n".join(str(i) for i in range(1, 11))
    assert paginate(text, 3, 2, 1000).endswith("3\n4")
    assert "[line truncated]" in paginate("y" * 100, 1, None, 10)
    assert paginate("", 1, None, 100) == "[the file is empty]"
    with pytest.raises(ToolError, match="past the end"):
        paginate("a\nb", 5, None, 100)


# --- read_image --------------------------------------------------------------------


async def test_read_image_attaches_the_image(workspace: Workspace) -> None:
    Image.new("RGB", (30, 20), "green").save(workspace.root / "chart.bmp")

    result = await ReadImageTool(workspace).run(path="chart.bmp", detail="low")

    assert isinstance(result, ToolOutput)
    assert "chart.bmp: BMP, 30x20" in result.content
    assert len(result.images) == 1
    assert result.images[0].detail == "low"


async def test_read_image_on_non_image_is_a_tool_error(workspace: Workspace) -> None:
    _put(workspace, "notes.txt", "hi")
    with pytest.raises(ToolError):
        await ReadImageTool(workspace).run(path="notes.txt")


# --- write_file --------------------------------------------------------------------


async def test_write_file_creates_folders_and_refuses_to_clobber(workspace: Workspace) -> None:
    tool = WriteFileTool(workspace)

    created = await tool.run(path="out/data.csv", content="a,b\n1,2\n")
    assert created.startswith("Created out/data.csv (text, ")
    assert (workspace.root / "out" / "data.csv").read_text() == "a,b\n1,2\n"

    with pytest.raises(ToolError, match="already exists"):
        await tool.run(path="out/data.csv", content="new")

    replaced = await tool.run(path="out/data.csv", content="new", overwrite=True)
    assert replaced.startswith("Replaced")
    assert (workspace.root / "out" / "data.csv").read_text() == "new"


async def test_write_file_refuses_outside_and_directories(workspace: Workspace) -> None:
    (workspace.root / "folder").mkdir()
    tool = WriteFileTool(workspace)
    with pytest.raises(ToolError, match="outside"):
        await tool.run(path="../escape.txt", content="x")
    with pytest.raises(ToolError, match="directory"):
        await tool.run(path="folder", content="x")


@pytest.mark.parametrize("name", ["r.docx", "r.pdf", "r.xlsx", "r.pptx", "r.md", "r.html"])
async def test_write_file_supports_every_format(workspace: Workspace, name: str) -> None:
    await WriteFileTool(workspace).run(path=name, content="# Title\n\n- point one\n- point two")
    assert (workspace.root / name).stat().st_size > 0


# --- edit_file ---------------------------------------------------------------------


async def test_edit_file_replaces_unique_text(workspace: Workspace) -> None:
    path = _put(workspace, "app.py", "x = 1\ny = 2\n")
    result = await EditFileTool(workspace).run(path="app.py", old_text="y = 2", new_text="y = 3")
    assert "replaced 1 occurrence" in result
    assert path.read_text() == "x = 1\ny = 3\n"


async def test_edit_file_needs_unique_match_unless_replace_all(workspace: Workspace) -> None:
    path = _put(workspace, "a.txt", "foo foo")
    tool = EditFileTool(workspace)
    with pytest.raises(ToolError, match="occurs 2 times"):
        await tool.run(path="a.txt", old_text="foo", new_text="bar")
    with pytest.raises(ToolError, match="not found"):
        await tool.run(path="a.txt", old_text="baz", new_text="bar")
    await tool.run(path="a.txt", old_text="foo", new_text="bar", replace_all=True)
    assert path.read_text() == "bar bar"


async def test_edit_file_refuses_binary_and_non_utf8(workspace: Workspace) -> None:
    _put(workspace, "blob.bin", b"\x00\x01\x02")
    _put(workspace, "legacy.txt", "café".encode("cp1252"))
    tool = EditFileTool(workspace)
    with pytest.raises(ToolError, match="not a text file"):
        await tool.run(path="blob.bin", old_text="a", new_text="b")
    with pytest.raises(ToolError, match="not UTF-8"):
        await tool.run(path="legacy.txt", old_text="caf", new_text="x")


async def test_edit_file_preserves_crlf(workspace: Workspace) -> None:
    path = _put(workspace, "win.txt", b"one\r\ntwo\r\n")
    await EditFileTool(workspace).run(path="win.txt", old_text="two", new_text="2")
    assert path.read_bytes() == b"one\r\n2\r\n"


# --- search_files ------------------------------------------------------------------


async def test_search_files(workspace: Workspace) -> None:
    _put(workspace, "src/main.py", "import os\nprint('Hello')\n")
    _put(workspace, "README.md", "hello world\n")
    _put(workspace, "blob.bin", b"\x00hello")
    tool = SearchFilesTool(workspace)

    found = await tool.run(query="hello")
    assert "src/main.py:2: print('Hello')" in found
    assert "README.md:1: hello world" in found
    assert "blob.bin" not in found

    assert "README.md" not in await tool.run(query="Hello", case_sensitive=True)
    assert "README.md" not in await tool.run(query="hello", file_pattern="*.py")
    assert "src/main.py:1" in await tool.run(query=r"^import\s+\w+", regex=True)
    assert "No matches" in await tool.run(query="absent")


async def test_search_files_rejects_bad_regex(workspace: Workspace) -> None:
    with pytest.raises(ToolError, match="regular expression"):
        await SearchFilesTool(workspace).run(query="(", regex=True)
