"""The tool contract: what the agent loop can call, and what it gets back."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from agent_runtime.agent.messages import ImageAttachment


class ToolError(Exception):
    """Raised by a tool for an expected, recoverable failure.

    Caught by the executor and fed back to the model as an observation
    (e.g. "bad input", "not found") rather than crashing the run. Anything
    else raised by a tool is treated as an unexpected failure.
    """


@dataclass(slots=True)
class ToolOutput:
    """A tool result that carries more than text.

    Most tools just return a string. A tool that needs the model to *see*
    something (an image it read) returns one of these instead, and the
    loop attaches the images to the tool's message in the transcript.
    """

    content: str
    images: list[ImageAttachment] = field(default_factory=list)


class Tool(ABC):
    """Base class for a callable the agent can choose to invoke.

    Subclasses declare `name`, `description`, and an `args_schema` (a
    pydantic model) so the schema shown to the model and the validation
    applied to its output are always the same object — the model can't
    drift out of sync with what `run` actually accepts.
    """

    name: str
    description: str
    args_schema: type[BaseModel]

    @abstractmethod
    async def run(self, **kwargs: Any) -> str | ToolOutput:
        """Execute the tool and return an observation for the model.

        Raise `ToolError` for expected failures the model should reason
        about (e.g. invalid input, file not found).

        The executor always calls this with `**validated.model_dump()`
        from `args_schema`, so subclasses intentionally declare specific,
        named parameters instead of `**kwargs` — self-documenting, and
        directly callable by name in tests. That narrows the signature
        from this base method's point of view, so implementations carry
        a `# type: ignore[override]`; the invariant that keeps it safe is
        enforced elsewhere (`args_schema`'s fields must match `run`'s
        parameters), not by the type checker.
        """

    def to_openai_schema(self) -> dict[str, Any]:
        """Render this tool as an OpenAI-style function declaration."""
        schema = self.args_schema.model_json_schema()
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }
