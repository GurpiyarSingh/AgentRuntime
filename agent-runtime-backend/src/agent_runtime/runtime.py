"""Composition root: turns settings into the objects the runtime runs on.

One place builds the workspace, the tool set, the agent's instructions,
and the per-request `AgentLoop`. The API and the tests both come through
here, so "what can this runtime do right now?" has a single answer.
"""

from __future__ import annotations

from agent_runtime.agent.loop import AgentLoop
from agent_runtime.agent.openai import OpenAIModel
from agent_runtime.agent.protocols import ChatModel
from agent_runtime.config import Settings
from agent_runtime.files.directories import DirectoryPolicy
from agent_runtime.files.workspace import Workspace
from agent_runtime.tools.file_tools import default_tools
from agent_runtime.tools.registry import ToolRegistry

SYSTEM_PROMPT = """You are a capable, careful assistant with access to a file workspace through tools.

Working with files:
- All paths are relative to the workspace root. You cannot reach anything outside it.
- If you are unsure what files exist, call list_files before guessing a name.
- Use read_file for documents, data and code (text in any encoding, PDF, Word, Excel, PowerPoint, archives). Use read_image to look at pictures, screenshots and scans.
- Base every statement about a file's content on what the tools returned, never on its name alone. If a read was paged or truncated, say what part you covered, or keep reading.
- Use write_file to create files; the extension decides the format (.docx, .pdf, .xlsx, .pptx, .md, .csv, .json, code, ...). Write complete content, never placeholders.
- Do not overwrite an existing file unless the user asked for it to be replaced or changed.
- Use edit_file for targeted changes to text and code files, and read the file first so old_text matches exactly.

When you finish, tell the user plainly what you did, including the path of every file you created or changed. If a tool reports an error, explain it and what would fix it rather than pretending it worked. Answer directly, without tools, when the request does not involve files."""

READ_ONLY_NOTE = """

This workspace is READ-ONLY: you can list, read, search and look at files, but you cannot create or change them. If asked to, say so and give the content in your answer instead."""


def build_workspace(settings: Settings) -> Workspace:
    """Open (creating if needed) the workspace directory from settings."""
    return Workspace(settings.workspace_dir)


def build_directory_policy(settings: Settings, workspace: Workspace) -> DirectoryPolicy:
    """Decide which other directories clients may point the agent at."""
    return DirectoryPolicy(
        workspace, selectable=settings.workspace_selectable, roots=settings.browse_roots
    )


def build_tools(settings: Settings, workspace: Workspace) -> ToolRegistry:
    """Build every tool the agent may call, honouring the workspace's limits."""
    return default_tools(
        workspace,
        read_only=settings.workspace_read_only,
        max_file_bytes=settings.max_file_bytes,
        read_max_chars=settings.read_max_chars,
        image_max_dimension=settings.image_max_dimension,
    )


def system_prompt(settings: Settings) -> str:
    """Return the agent's instructions, noting a read-only workspace if configured."""
    return SYSTEM_PROMPT + (READ_ONLY_NOTE if settings.workspace_read_only else "")


class AgentFactory:
    """Builds the `AgentLoop` for one request, honouring its model choice.

    The model can only be chosen once the request body has been parsed,
    which is after FastAPI dependencies resolve, so the API holds a factory
    rather than a finished loop.
    """

    def __init__(self, settings: Settings, tools: ToolRegistry) -> None:
        """Capture what every loop shares: settings and the tool registry."""
        self._settings = settings
        self._tools = tools

    def __call__(
        self,
        model_id: str | None = None,
        model: ChatModel | None = None,
        workspace: Workspace | None = None,
    ) -> AgentLoop:
        """Build a loop on `model`, or on an OpenAI model for `model_id`.

        Args:
            model_id: Catalog id for the OpenAI model; the default if omitted.
            model: A ready `ChatModel` to use instead (tests pass a fake).
            workspace: A directory the request chose; the shared tools (bound
                to the configured workspace) are used if omitted.

        Raises:
            ModelConfigurationError: No OpenAI API key is configured.
        """
        tools = self._tools if workspace is None else build_tools(self._settings, workspace)
        return AgentLoop(
            settings=self._settings,
            tools=tools,
            model=model or OpenAIModel(self._settings, tools, model_id=model_id),
            system_prompt=system_prompt(self._settings),
        )


__all__ = [
    "SYSTEM_PROMPT",
    "AgentFactory",
    "build_directory_policy",
    "build_tools",
    "build_workspace",
    "system_prompt",
]
