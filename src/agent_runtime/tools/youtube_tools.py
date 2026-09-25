"""The tools the YouTube agent can call.

- `search_youtube` normalises the query, clamps the result count to the
  server's ceiling, and hands back a formatted list of titles and canonical
  watch links. Every link is built from the video id by `VideoResult.url`,
  so the agent relays URLs the runtime constructed rather than any it might
  remember.
- `get_youtube_transcript` takes a link or id, fetches the video's
  captions, and hands back the text — cut to the server's size limit, with
  the cut announced — so a summary is grounded in what was actually said.
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
from agent_runtime.youtube.transcript import VideoIdError, extract_video_id, format_transcript
from agent_runtime.youtube.transcript_client import LibraryTranscriptClient, TranscriptClient

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


class GetYouTubeTranscriptArgs(BaseModel):
    """What the model must provide to fetch a transcript."""

    video: str = Field(
        ...,
        description="The video's link exactly as search returned it or the user gave it "
        "(watch, youtu.be or Shorts), or its 11-character id.",
    )
    language: str | None = Field(
        default=None,
        description="Optional caption language code, e.g. 'en' or 'es'. Leave unset "
        "unless the user asked for a specific language.",
    )
    timestamps: bool = Field(
        default=False,
        description="Prefix each line with its time in the video. Use when the user wants "
        "to know when something is said; leave off for summaries.",
    )


class GetYouTubeTranscriptTool(Tool):
    name = "get_youtube_transcript"
    description = (
        "Fetch the transcript (captions) of one YouTube video. Use it to transcribe, "
        "summarise, quote or answer questions about what a video says. Needs a link or "
        "id — if you only have a topic, call search_youtube first. Very long transcripts "
        "are truncated, and the result says how far it got."
    )
    args_schema = GetYouTubeTranscriptArgs

    def __init__(
        self,
        client: TranscriptClient,
        languages: list[str] | None = None,
        max_chars: int = 20_000,
    ) -> None:
        self._client = client
        self._languages = languages or ["en"]
        self._max_chars = max_chars

    async def run(  # type: ignore[override]
        self, video: str, language: str | None = None, timestamps: bool = False
    ) -> str:
        try:
            video_id = extract_video_id(video)
        except VideoIdError as exc:
            raise ToolError(str(exc)) from exc

        # A requested language goes first; the server's defaults remain as fallbacks.
        preferred = [language.strip()] if language and language.strip() else []
        languages = preferred + [code for code in self._languages if code not in preferred]
        try:
            transcript = await self._client.fetch(video_id, languages)
        except YouTubeError as exc:
            raise ToolError(str(exc)) from exc

        logger.info(
            "youtube transcript",
            extra={
                "video_id": video_id,
                "language": transcript.language_code,
                "segments": len(transcript.segments),
            },
        )
        return format_transcript(transcript, timestamps=timestamps, max_chars=self._max_chars)


def youtube_tools(
    client: YouTubeClient,
    default_results: int = 5,
    max_results: int = 10,
    transcript_client: TranscriptClient | None = None,
    transcript_languages: list[str] | None = None,
    transcript_max_chars: int = 20_000,
) -> ToolRegistry:
    """The tool set given to the YouTube agent."""
    return ToolRegistry(
        [
            SearchYouTubeTool(
                client=client, default_results=default_results, max_results=max_results
            ),
            GetYouTubeTranscriptTool(
                client=transcript_client or LibraryTranscriptClient(),
                languages=transcript_languages,
                max_chars=transcript_max_chars,
            ),
        ]
    )


__all__ = [
    "GetYouTubeTranscriptArgs",
    "GetYouTubeTranscriptTool",
    "SearchYouTubeArgs",
    "SearchYouTubeTool",
    "youtube_tools",
]
