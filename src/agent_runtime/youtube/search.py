"""What a YouTube search asks for, and what it gets back.

Like `agent_runtime.mail`, this layer knows nothing about agents or
language models. It holds the result type, the canonical way to turn a
video id into a link, and the rules a query has to satisfy — so the
"never hand back a broken URL" guarantee is testable on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

WATCH_URL = "https://www.youtube.com/watch?v="

MAX_QUERY_LENGTH = 200


class YouTubeError(RuntimeError):
    """Raised when a search cannot be performed or its answer is unusable.

    The message is written for the model to read and relay: it says what
    went wrong and, where possible, what would fix it.
    """


class SearchQueryError(ValueError):
    """Raised when the requested search is malformed."""


@dataclass(frozen=True, slots=True)
class VideoResult:
    """One video from a search, with the link the user actually wants."""

    video_id: str
    title: str
    channel: str
    published_at: str = ""
    description: str = ""

    @property
    def url(self) -> str:
        """The canonical watch link.

        Built here from the id rather than taken from the API response, so
        the agent can never relay a link the runtime did not construct.
        """
        return f"{WATCH_URL}{self.video_id}"

    def as_line(self, index: int) -> str:
        """One result, formatted for the model to read and cite."""
        parts = [f"{index}. {self.title}", f"   {self.url}", f"   Channel: {self.channel}"]
        if self.published_at:
            parts.append(f"   Published: {self.published_at[:10]}")
        return "\n".join(parts)


def normalize_query(raw: str) -> str:
    """Trim and sanity-check a search query."""
    query = " ".join(raw.split())
    if not query:
        raise SearchQueryError("A search needs a non-empty query.")
    if len(query) > MAX_QUERY_LENGTH:
        raise SearchQueryError(
            f"The search query is {len(query)} characters; keep it under {MAX_QUERY_LENGTH}. "
            "Search for the key terms rather than a whole sentence."
        )
    return query


def clamp_results(requested: int | None, default: int, ceiling: int) -> int:
    """How many results to ask for, kept inside the server's limits.

    A model asking for 50 results gets the ceiling rather than an error —
    the number is incidental to what the user wanted, so silently doing
    the sensible thing beats failing the run over it.
    """
    if requested is None:
        return min(default, ceiling)
    return max(1, min(int(requested), ceiling))


def format_results(query: str, results: list[VideoResult]) -> str:
    """The observation handed back to the model after a search."""
    if not results:
        return (
            f"No videos found for {query!r}. Try different or broader search terms, "
            "and tell the user nothing matched rather than inventing a link."
        )
    lines = [f"Found {len(results)} video(s) for {query!r}:", ""]
    lines.extend(result.as_line(index) for index, result in enumerate(results, start=1))
    return "\n".join(lines)


__all__ = [
    "MAX_QUERY_LENGTH",
    "WATCH_URL",
    "SearchQueryError",
    "VideoResult",
    "YouTubeError",
    "clamp_results",
    "format_results",
    "normalize_query",
]
