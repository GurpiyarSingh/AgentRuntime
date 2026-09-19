"""The tools the YouTube agent can call.

One tool: `search_youtube`. It normalises the query, clamps the result
count to the server's ceiling, and hands back a formatted list of titles
and canonical watch links. Every link is built from the video id by
`VideoResult.url`, so the agent relays URLs the runtime constructed rather
than any it might remember.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from agent_runtime.tools.base import Tool, ToolError
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.youtube.client import YouTubeClient
from agent_runtime.youtube.search import (
    SearchQueryError,
    YouTubeError,
    clamp_results,
    format_results,
    normalize_query,
)

logger = logging.getLogger(__name__)


class SearchYouTubeArgs(BaseModel):
    """What the model must provide to run a search."""

    query: str = Field(
        ...,
        description="What to search YouTube for. Use keywords, not a full sentence.",
    )
    max_results: int | None = Field(
        default=None,
        description="How many videos to return. Defaults to the server's setting; "
        "larger values are capped rather than rejected.",
    )


class SearchYouTubeTool(Tool):
    name = "search_youtube"
    description = (
        "Search YouTube and return matching videos with their titles, channels and "
        "watch links. Use this for any request to find a video — never recall or "
        "construct a YouTube URL yourself, because a wrong id looks valid but 404s."
    )
    args_schema = SearchYouTubeArgs

    def __init__(self, client: YouTubeClient, default_results: int = 5, max_results: int = 10):
        self._client = client
        self._default_results = default_results
        self._max_results = max_results

    @property
    def configured(self) -> bool:
        return self._client.configured

    async def run(self, query: str, max_results: int | None = None) -> str:  # type: ignore[override]
        try:
            cleaned = normalize_query(query)
        except SearchQueryError as exc:
            # An expected, correctable problem: the model can retry with
            # better terms instead of the run dying.
            raise ToolError(str(exc)) from exc

        count = clamp_results(max_results, self._default_results, self._max_results)
        try:
            results = await self._client.search(cleaned, count)
        except YouTubeError as exc:
            raise ToolError(str(exc)) from exc

        logger.info("youtube search", extra={"query": cleaned, "results": len(results)})
        return format_results(cleaned, results)


def youtube_tools(
    client: YouTubeClient, default_results: int = 5, max_results: int = 10
) -> ToolRegistry:
    """The tool set given to the YouTube agent."""
    return ToolRegistry(
        [
            SearchYouTubeTool(
                client=client, default_results=default_results, max_results=max_results
            )
        ]
    )


__all__ = ["SearchYouTubeArgs", "SearchYouTubeTool", "youtube_tools"]
