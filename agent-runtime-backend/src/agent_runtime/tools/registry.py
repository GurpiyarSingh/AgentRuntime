"""A name -> `Tool` lookup, with schema export for the model binding."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from agent_runtime.tools.base import Tool


class ToolRegistry:
    """The set of tools available to an agent, in registration order.

    The same registry must be given to the model binding (which shows the
    model the schemas) and to the loop (which executes the calls), so the
    model can never call a tool the loop doesn't know.
    """

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        """Register `tools` in order.

        Raises:
            ValueError: Two tools share a name.
        """
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Tool {tool.name!r} is already registered")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Return the tool called `name`, or None if there is none."""
        return self._tools.get(name)

    def names(self) -> list[str]:
        """Return every tool's name, in registration order."""
        return list(self._tools)

    def as_openai_schemas(self) -> list[dict[str, Any]]:
        """Return the function-calling declaration of every registered tool."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __iter__(self) -> Iterator[Tool]:
        """Iterate over the tools in registration order."""
        return iter(self._tools.values())


__all__ = ["ToolRegistry"]
