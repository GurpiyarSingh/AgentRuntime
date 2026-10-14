"""The default tools: list, read, look at, create, edit and search files.

All of them work inside one `Workspace` and never outside it. File I/O and
document parsing block, so each tool runs its work in a worker thread
rather than stalling the event loop (and every other request) on a large
PDF.

A tool's `description` and its `args_schema` field descriptions are what
the model reads to decide how to call it; treat them as prompt text and
keep them accurate when behaviour changes.
"""

from __future__ import annotations

import asyncio
import fnmatch
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent_runtime.files.images import Detail, ImageError, prepare_image
from agent_runtime.files.readers import DocumentError, decode_text, read_document
from agent_runtime.files.workspace import Workspace, WorkspaceError, atomic_target
from agent_runtime.files.writers import Encoding, WriteError, write_file
from agent_runtime.tools.base import Tool, ToolError, ToolOutput
from agent_runtime.tools.registry import ToolRegistry

DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
LIST_LIMIT = 500
"""Most entries `list_files` returns, so one huge folder can't flood the context."""
SEARCH_MATCH_LIMIT = 100
"""Most matching lines `search_files` returns."""


def human_size(size: int) -> str:
    """Format a byte count for people (and models): ``512 B``, ``1.5 MB``."""
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    units = ["KB", "MB", "GB"]
    while value >= 1024 and len(units) > 1:
        value /= 1024
        units.pop(0)
    return f"{value:.1f} {units[0]}"


class _WorkspaceTool(Tool):
    """Shared plumbing: the workspace, a size limit, and error translation.

    Every workspace problem (outside, missing, wrong kind, too big) becomes a
    `ToolError`, which the loop reports to the model as a recoverable error.
    """

    def __init__(self, workspace: Workspace, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
        self._workspace = workspace
        self._max_file_bytes = max_file_bytes

    def _resolve(self, path: str) -> Path:
        try:
            return self._workspace.resolve(path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc

    def _directory(self, path: str) -> Path:
        try:
            return self._workspace.existing_dir(path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc

    def _readable_file(self, path: str) -> Path:
        try:
            resolved = self._workspace.existing_file(path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc
        size = resolved.stat().st_size
        if size > self._max_file_bytes:
            raise ToolError(
                f"{self._workspace.display(resolved)} is {human_size(size)}, over the "
                f"{human_size(self._max_file_bytes)} limit for reading."
            )
        return resolved


# --- list_files ----------------------------------------------------------------------


class ListFilesArgs(BaseModel):
    """Arguments for `list_files`."""

    path: str = Field(default=".", description="Directory to list, relative to the workspace.")
    recursive: bool = Field(default=False, description="Include everything below it, too.")


class ListFilesTool(_WorkspaceTool):
    """List a workspace directory, folders marked with a trailing slash."""

    name = "list_files"
    description = (
        "List the files and folders in a workspace directory, with sizes. Use it to find "
        "out what files exist before reading or creating them."
    )
    args_schema = ListFilesArgs

    async def run(self, path: str = ".", recursive: bool = False) -> str:  # type: ignore[override]
        """List `path`, optionally recursively."""
        return await asyncio.to_thread(self._list, path, recursive)

    def _list(self, path: str, recursive: bool) -> str:
        directory = self._directory(path)
        candidates = directory.rglob("*") if recursive else directory.iterdir()
        # Hide symlinks that lead out of the workspace: tools can't open them.
        entries = sorted(p for p in candidates if p.resolve().is_relative_to(self._workspace.root))

        lines = []
        for entry in entries[:LIST_LIMIT]:
            shown = self._workspace.display(entry)
            if entry.is_dir():
                lines.append(f"{shown}/")
            else:
                lines.append(f"{shown}  ({human_size(entry.stat().st_size)})")
        if len(entries) > LIST_LIMIT:
            lines.append(f"... and {len(entries) - LIST_LIMIT} more entries")

        where = self._workspace.display(directory)
        if not lines:
            return f"{where} is empty."
        return f"Contents of {where}:\n" + "\n".join(lines)


# --- read_file -----------------------------------------------------------------------


class ReadFileArgs(BaseModel):
    """Arguments for `read_file`."""

    path: str = Field(..., description="File to read, relative to the workspace.")
    start_line: int = Field(
        default=1, ge=1, description="First line to return. Use it to continue a long file."
    )
    max_lines: int | None = Field(
        default=None, ge=1, description="Return at most this many lines. Omit for as many as fit."
    )


def paginate(text: str, start_line: int, max_lines: int | None, max_chars: int) -> str:
    """Return a window of `text` under a header saying what is shown.

    The window starts at `start_line` (1-based), holds at most `max_lines`
    lines, and stops before exceeding `max_chars`. The header tells the
    model where to continue, so long files are read page by page instead
    of silently truncated.

    Raises:
        ToolError: `start_line` is past the end of the text.
    """
    lines = text.splitlines()
    total = len(lines)
    if total == 0:
        return "[the file is empty]"
    if start_line > total:
        raise ToolError(f"start_line {start_line} is past the end ({total} lines).")

    last_allowed = total if max_lines is None else min(total, start_line + max_lines - 1)
    shown: list[str] = []
    used = 0
    for line in lines[start_line - 1 : last_allowed]:
        if used + len(line) + 1 > max_chars:
            if not shown:  # A single enormous line (minified JSON, say).
                shown.append(line[:max_chars] + " [line truncated]")
            break
        shown.append(line)
        used += len(line) + 1

    last = start_line + len(shown) - 1
    header = f"Lines {start_line}-{last} of {total}"
    if last < total:
        header += f" (continue with start_line={last + 1})"
    return header + "\n\n" + "\n".join(shown)


class ReadFileTool(_WorkspaceTool):
    """Read any file as text, page by page."""

    name = "read_file"
    description = (
        "Read a file as text. Works for any text or code file in any encoding, PDF, Word "
        "(.docx), Excel (.xlsx, one CSV block per sheet), PowerPoint (.pptx), and zip/tar "
        "archives (lists their contents). Other binary files are described rather than "
        "dumped. Long files come back in pages; the header says how to continue. For "
        "images, use read_image instead."
    )
    args_schema = ReadFileArgs

    def __init__(
        self,
        workspace: Workspace,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_chars: int = 40_000,
    ) -> None:
        """Bind to `workspace`, returning at most `max_chars` per call."""
        super().__init__(workspace, max_file_bytes)
        self._max_chars = max_chars

    async def run(  # type: ignore[override]
        self, path: str, start_line: int = 1, max_lines: int | None = None
    ) -> str:
        """Return a page of `path`'s text, headed by its type and size."""
        return await asyncio.to_thread(self._read, path, start_line, max_lines)

    def _read(self, path: str, start_line: int, max_lines: int | None) -> str:
        resolved = self._readable_file(path)
        try:
            document = read_document(resolved)
        except DocumentError as exc:
            raise ToolError(str(exc)) from exc
        size = human_size(resolved.stat().st_size)
        title = f"File: {self._workspace.display(resolved)} ({document.kind}, {size})"
        return title + "\n" + paginate(document.text, start_line, max_lines, self._max_chars)


# --- read_image ----------------------------------------------------------------------


class ReadImageArgs(BaseModel):
    """Arguments for `read_image`."""

    path: str = Field(..., description="Image file to look at, relative to the workspace.")
    detail: Literal["auto", "low", "high"] = Field(
        default="auto",
        description="'low' is cheaper and enough for a general look; 'high' for small text "
        "or fine detail.",
    )


class ReadImageTool(_WorkspaceTool):
    """Show an image to the model."""

    name = "read_image"
    description = (
        "Look at an image file so you can describe it, read text in it, or answer questions "
        "about it. Supports PNG, JPEG, GIF, WEBP, BMP, TIFF, ICO, PSD, AVIF and other raster "
        "formats; it is converted and scaled automatically."
    )
    args_schema = ReadImageArgs

    def __init__(
        self,
        workspace: Workspace,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_dimension: int = 2048,
    ) -> None:
        """Bind to `workspace`, scaling images to fit `max_dimension` pixels."""
        super().__init__(workspace, max_file_bytes)
        self._max_dimension = max_dimension

    async def run(self, path: str, detail: Detail = "auto") -> ToolOutput:  # type: ignore[override]
        """Return a text summary of the image, with the image itself attached."""
        return await asyncio.to_thread(self._read, path, detail)

    def _read(self, path: str, detail: Detail) -> ToolOutput:
        resolved = self._readable_file(path)
        try:
            image = prepare_image(resolved, self._max_dimension, detail)
        except ImageError as exc:
            raise ToolError(str(exc)) from exc
        return ToolOutput(
            content=image.summary(self._workspace.display(resolved)),
            images=[image.attachment],
        )


# --- write_file ----------------------------------------------------------------------


class WriteFileArgs(BaseModel):
    """Arguments for `write_file`."""

    path: str = Field(
        ...,
        description="File to create, relative to the workspace. The extension picks the "
        "format; missing folders are created.",
    )
    content: str = Field(
        ...,
        description="For .docx/.pdf: Markdown (# headings, - lists, | tables |, **bold**). "
        "For .xlsx: CSV, a JSON list of rows, or a JSON object of {sheet: rows}; cells "
        "starting with = are formulas. For .pptx: slides separated by '---' lines, first "
        "line the title, '- ' bullets, 'Notes:' for speaker notes. Otherwise: the file's "
        "text. With encoding='base64': the file's bytes, base64-encoded.",
    )
    encoding: Literal["text", "base64"] = Field(
        default="text", description="Use 'base64' for binary files such as images or archives."
    )
    overwrite: bool = Field(default=False, description="Replace the file if it already exists.")


class WriteFileTool(_WorkspaceTool):
    """Create a file in any supported format."""

    name = "write_file"
    description = (
        "Create a file of any type: text, code, Markdown, CSV, JSON, HTML, Word (.docx), "
        "PDF, Excel (.xlsx), PowerPoint (.pptx), or any binary format from base64. Refuses "
        "to replace an existing file unless overwrite is true."
    )
    args_schema = WriteFileArgs

    async def run(  # type: ignore[override]
        self, path: str, content: str, encoding: Encoding = "text", overwrite: bool = False
    ) -> str:
        """Write `content` to `path`, reporting the format and size written."""
        return await asyncio.to_thread(self._write, path, content, encoding, overwrite)

    def _write(self, path: str, content: str, encoding: Encoding, overwrite: bool) -> str:
        resolved = self._resolve(path)
        shown = self._workspace.display(resolved)
        if resolved.is_dir():
            raise ToolError(f"{shown} is a directory.")
        existed = resolved.exists()
        if existed and not overwrite:
            raise ToolError(f"{shown} already exists. Pass overwrite=true to replace it.")
        try:
            kind = write_file(resolved, content, encoding)
        except WriteError as exc:
            raise ToolError(str(exc)) from exc
        verb = "Replaced" if existed else "Created"
        return f"{verb} {shown} ({kind}, {human_size(resolved.stat().st_size)})."


# --- edit_file -----------------------------------------------------------------------


class EditFileArgs(BaseModel):
    """Arguments for `edit_file`."""

    path: str = Field(..., description="Text file to edit, relative to the workspace.")
    old_text: str = Field(
        ..., min_length=1, description="Exact text to find, including whitespace."
    )
    new_text: str = Field(..., description="Text to put in its place.")
    replace_all: bool = Field(
        default=False,
        description="Replace every occurrence. Otherwise old_text must occur exactly once.",
    )


class EditFileTool(_WorkspaceTool):
    """Replace exact text in a UTF-8 text file."""

    name = "edit_file"
    description = (
        "Change part of an existing text or code file by replacing exact text. Read the "
        "file first so old_text matches exactly. To change a .docx, .xlsx, .pdf or .pptx, "
        "write the whole file again with write_file."
    )
    args_schema = EditFileArgs

    async def run(  # type: ignore[override]
        self, path: str, old_text: str, new_text: str, replace_all: bool = False
    ) -> str:
        """Replace `old_text` with `new_text` in `path`."""
        return await asyncio.to_thread(self._edit, path, old_text, new_text, replace_all)

    def _edit(self, path: str, old_text: str, new_text: str, replace_all: bool) -> str:
        resolved = self._readable_file(path)
        shown = self._workspace.display(resolved)
        raw = resolved.read_bytes()
        if decode_text(raw) is None:
            raise ToolError(f"{shown} is not a text file, so it can't be edited in place.")
        try:
            # Strict UTF-8 only: re-encoding a lossy legacy-encoding guess would
            # silently corrupt every character the guess got wrong.
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"{shown} is not UTF-8, so it can't be edited safely.") from exc

        count = text.count(old_text)
        if count == 0:
            raise ToolError(f"old_text was not found in {shown}.")
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_text occurs {count} times in {shown}. Add surrounding text to make it "
                "unique, or pass replace_all=true."
            )
        updated = text.replace(old_text, new_text)
        with atomic_target(resolved) as target:
            # Bytes, not write_text: keeps the file's own line endings and BOM.
            target.write_bytes(updated.encode("utf-8"))
        return f"Edited {shown}: replaced {count} occurrence{'s' if count > 1 else ''}."


# --- search_files --------------------------------------------------------------------


class SearchFilesArgs(BaseModel):
    """Arguments for `search_files`."""

    query: str = Field(..., min_length=1, description="Text (or regular expression) to find.")
    path: str = Field(default=".", description="Directory to search, relative to the workspace.")
    file_pattern: str = Field(
        default="*", description="Only search files whose name matches, e.g. '*.py'."
    )
    regex: bool = Field(default=False, description="Treat query as a regular expression.")
    case_sensitive: bool = Field(default=False)


class SearchFilesTool(_WorkspaceTool):
    """Grep the workspace's text files."""

    name = "search_files"
    description = (
        "Search the text and code files in a workspace directory for a word, phrase or "
        "regular expression. Returns matching lines as path:line: text. Does not look "
        "inside PDFs or Office documents; read those with read_file."
    )
    args_schema = SearchFilesArgs

    async def run(  # type: ignore[override]
        self,
        query: str,
        path: str = ".",
        file_pattern: str = "*",
        regex: bool = False,
        case_sensitive: bool = False,
    ) -> str:
        """Return matching lines as ``path:line: text``, capped at the match limit."""
        return await asyncio.to_thread(
            self._search, query, path, file_pattern, regex, case_sensitive
        )

    def _search(
        self, query: str, path: str, file_pattern: str, regex: bool, case_sensitive: bool
    ) -> str:
        directory = self._directory(path)
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query if regex else re.escape(query), flags)
        except re.error as exc:
            raise ToolError(f"Invalid regular expression: {exc}") from exc

        matches: list[str] = []
        for file in self._workspace.iter_files(directory):
            if not fnmatch.fnmatch(file.name, file_pattern):
                continue
            if file.stat().st_size > self._max_file_bytes:
                continue
            text = decode_text(file.read_bytes())
            if text is None:  # Binary: nothing meaningful to match.
                continue
            shown = self._workspace.display(file)
            for number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{shown}:{number}: {line.strip()[:300]}")
                    if len(matches) >= SEARCH_MATCH_LIMIT:
                        return "\n".join(matches) + f"\n[stopped at {SEARCH_MATCH_LIMIT} matches]"
        return "\n".join(matches) if matches else f"No matches for {query!r}."


# --- the default set -----------------------------------------------------------------


def default_tools(
    workspace: Workspace,
    *,
    read_only: bool = False,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    read_max_chars: int = 40_000,
    image_max_dimension: int = 2048,
) -> ToolRegistry:
    """Build the tools every agent gets.

    Args:
        workspace: The only directory the tools may touch.
        read_only: Leave out the tools that create or change files.
        max_file_bytes: Largest file any tool will read.
        read_max_chars: Most characters `read_file` returns per call.
        image_max_dimension: Longest side, in pixels, of images shown to the model.
    """
    tools: list[Tool] = [
        ListFilesTool(workspace, max_file_bytes),
        ReadFileTool(workspace, max_file_bytes, max_chars=read_max_chars),
        ReadImageTool(workspace, max_file_bytes, max_dimension=image_max_dimension),
        SearchFilesTool(workspace, max_file_bytes),
    ]
    if not read_only:
        tools += [WriteFileTool(workspace, max_file_bytes), EditFileTool(workspace, max_file_bytes)]
    return ToolRegistry(tools)


__all__ = [
    "EditFileTool",
    "ListFilesTool",
    "ReadFileTool",
    "ReadImageTool",
    "SearchFilesTool",
    "WriteFileTool",
    "default_tools",
    "human_size",
    "paginate",
]
