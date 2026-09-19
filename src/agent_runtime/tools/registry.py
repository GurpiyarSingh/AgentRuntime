"""A simple name -> Tool lookup, with schema export for the model binding."""

from __future__ import annotations

from typing import Any

from agent_runtime.tools.base import Tool


class ToolRegistry:
    """Holds the set of tools available to a given agent run."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return list(self._tools)

    def as_openai_schemas(self) -> list[dict[str, Any]]:
        """Function-calling declarations for every registered tool."""
        return [tool.to_openai_schema() for tool in self._tools.values()]
