"""How a search actually reaches YouTube — or explains why it can't.

Three clients implement one small protocol, mirroring the mail transports:

- `ApiYouTubeClient` calls the YouTube Data API v3 over httpx.
- `UnconfiguredYouTubeClient` is what you get with no API key: it fails
  with an actionable message instead of the agent quietly making links up.
- `FakeYouTubeClient` is the test double.

Results are parsed into `VideoResult` here, so nothing downstream ever
touches the provider's JSON shape.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

from agent_runtime.youtube.search import VideoResult, YouTubeError

logger = logging.getLogger(__name__)

SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"


@runtime_checkable
class YouTubeClient(Protocol):
    """Anything that can turn a query into a list of videos."""

    configured: bool

    async def search(self, query: str, max_results: int) -> list[VideoResult]: ...


@dataclass(slots=True)
class UnconfiguredYouTubeClient:
    """Stands in when no API key is set, and says so plainly."""

    configured: bool = False

    async def search(self, query: str, max_results: int) -> list[VideoResult]:
        raise YouTubeError(
            "YouTube search is not configured on this server: YOUTUBE_API_KEY is not set. "
            "Tell the user that search is unavailable — do not guess or recall video links, "
            "because a made-up YouTube URL looks real and will not work."
        )


@dataclass(slots=True)
class ApiYouTubeClient:
    """Searches with the YouTube Data API v3."""

    api_key: str
    timeout_s: float = 15.0
    configured: bool = True

    async def search(self, query: str, max_results: int) -> list[VideoResult]:
        params = {
            "part": "snippet",
            "type": "video",  # never return channels or playlists
            "q": query,
            "maxResults": str(max_results),
            "key": self.api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.get(SEARCH_ENDPOINT, params=params)
        except httpx.TimeoutException as exc:
            raise YouTubeError(
                f"The YouTube search timed out after {self.timeout_s:.0f}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise YouTubeError(f"Could not reach YouTube: {type(exc).__name__}.") from exc

        if response.status_code != 200:
            raise YouTubeError(_explain_error(response))

        try:
            payload = response.json()
        except ValueError as exc:
            raise YouTubeError("YouTube returned a response that could not be parsed.") from exc

        return parse_results(payload)


def _explain_error(response: httpx.Response) -> str:
    """Turn an API error into something the agent can act on or relay."""
    reason = ""
    try:
        body = response.json()
        errors = body.get("error", {}).get("errors") or []
        reason = errors[0].get("reason", "") if errors else body.get("error", {}).get("message", "")
    except ValueError:
        reason = ""

    if response.status_code == 403 and "quota" in reason.lower():
        return (
            "The YouTube API quota for this server has been exhausted for the day. "
            "Tell the user search is temporarily unavailable."
        )
    if response.status_code in (400, 403):
        return (
            "YouTube rejected the request, which usually means YOUTUBE_API_KEY is invalid "
            f"or the YouTube Data API is not enabled for it. ({reason or response.status_code})"
        )
    return f"YouTube search failed with HTTP {response.status_code}. ({reason})"


def parse_results(payload: dict[str, Any]) -> list[VideoResult]:
    """Pull the fields we need out of an API response, skipping junk entries."""
    results: list[VideoResult] = []
    for item in payload.get("items", []):
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        if not video_id or not snippet.get("title"):
            # Missing an id means we cannot build a working link, so the
            # entry is dropped rather than surfaced as a dead result.
            continue
        results.append(
            VideoResult(
                video_id=video_id,
                title=snippet.get("title", ""),
                channel=snippet.get("channelTitle", ""),
                published_at=snippet.get("publishedAt", "") or "",
                description=snippet.get("description", "") or "",
            )
        )
    return results


@dataclass(slots=True)
class FakeYouTubeClient:
    """Test double: returns canned results, never touches the network."""

    results: list[VideoResult] = field(default_factory=list)
    configured: bool = True
    queries: list[tuple[str, int]] = field(default_factory=list)
    fail_with: str | None = None

    async def search(self, query: str, max_results: int) -> list[VideoResult]:
        self.queries.append((query, max_results))
        if self.fail_with:
            raise YouTubeError(self.fail_with)
        return self.results[:max_results]


__all__ = [
    "SEARCH_ENDPOINT",
    "ApiYouTubeClient",
    "FakeYouTubeClient",
    "UnconfiguredYouTubeClient",
    "YouTubeClient",
    "parse_results",
]
