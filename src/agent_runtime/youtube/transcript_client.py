"""How a transcript actually reaches us from YouTube.

The Data API's captions endpoint only serves videos the caller owns, so it
cannot transcribe an arbitrary video. Instead this reads the same caption
tracks the YouTube player shows, via `youtube-transcript-api`. That needs no
API key — which is why transcripts keep working when search is unconfigured.

Two clients implement one small protocol:

- `LibraryTranscriptClient` wraps `youtube-transcript-api`.
- `FakeTranscriptClient` is the test double.

The library's many exception types are translated here into
`TranscriptError`s written for the model, so nothing downstream depends on
the library at all.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from youtube_transcript_api import (
    AgeRestricted,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

from agent_runtime.youtube.transcript import Transcript, TranscriptError, TranscriptSegment

logger = logging.getLogger(__name__)


@runtime_checkable
class TranscriptClient(Protocol):
    """Anything that can fetch a video's captions."""

    async def fetch(self, video_id: str, languages: Sequence[str]) -> Transcript: ...


@dataclass(slots=True)
class LibraryTranscriptClient:
    """Fetches caption tracks with `youtube-transcript-api`.

    Language choice: the first of `languages` that has a track, preferring
    human-written captions over auto-generated ones. If none of them exist,
    whatever track the video does have is returned, labelled with its real
    language — a Spanish transcript the model can translate is more useful
    than "no English transcript".
    """

    async def fetch(self, video_id: str, languages: Sequence[str]) -> Transcript:
        # The library is synchronous (requests); keep it off the event loop.
        return await asyncio.to_thread(self._fetch_sync, video_id, list(languages))

    def _fetch_sync(self, video_id: str, languages: list[str]) -> Transcript:
        try:
            available = YouTubeTranscriptApi().list(video_id)
            try:
                track = available.find_transcript(languages)
            except NoTranscriptFound:
                # Iteration yields manual tracks before generated ones.
                fallback = next(iter(available), None)
                if fallback is None:
                    raise
                track = fallback
            fetched = track.fetch()
        except YouTubeTranscriptApiException as exc:
            raise TranscriptError(_explain(exc, video_id)) from exc
        except Exception as exc:  # network errors surface from requests
            logger.warning("transcript fetch failed", extra={"video_id": video_id}, exc_info=True)
            raise TranscriptError(
                f"Could not reach YouTube to fetch the transcript ({type(exc).__name__})."
            ) from exc

        return Transcript(
            video_id=video_id,
            language=fetched.language,
            language_code=fetched.language_code,
            is_generated=fetched.is_generated,
            segments=[
                TranscriptSegment(text=s.text, start=s.start, duration=s.duration)
                for s in fetched.snippets
            ],
        )


def _explain(exc: YouTubeTranscriptApiException, video_id: str) -> str:
    """Turn the library's exception into something the agent can act on or relay."""
    no_content = "Tell the user; do not describe the video's content from its title or memory."
    if isinstance(exc, TranscriptsDisabled):
        return f"Captions are off for video {video_id}, so it has no transcript. {no_content}"
    if isinstance(exc, NoTranscriptFound):
        return f"Video {video_id} has no caption track to transcribe. {no_content}"
    if isinstance(exc, (VideoUnavailable, InvalidVideoId)):
        return (
            f"Video {video_id} does not exist or has been removed. Check the link, "
            "or search for the video again."
        )
    if isinstance(exc, AgeRestricted):
        return f"Video {video_id} is age-restricted, so its transcript cannot be fetched."
    if isinstance(exc, VideoUnplayable):
        return f"Video {video_id} cannot be played (private, region-locked or premium-only)."
    if isinstance(exc, (IpBlocked, RequestBlocked)):
        return (
            "YouTube is blocking transcript requests from this server's network (common on "
            "cloud hosts). Tell the user transcripts are temporarily unavailable here."
        )
    return f"Could not fetch the transcript for video {video_id} ({type(exc).__name__})."


@dataclass(slots=True)
class FakeTranscriptClient:
    """Test double: returns canned transcripts, never touches the network."""

    transcripts: dict[str, Transcript] = field(default_factory=dict)
    requests: list[tuple[str, list[str]]] = field(default_factory=list)
    fail_with: str | None = None

    async def fetch(self, video_id: str, languages: Sequence[str]) -> Transcript:
        self.requests.append((video_id, list(languages)))
        if self.fail_with:
            raise TranscriptError(self.fail_with)
        if video_id not in self.transcripts:
            raise TranscriptError(f"Video {video_id} has no caption track to transcribe.")
        return self.transcripts[video_id]


__all__ = ["FakeTranscriptClient", "LibraryTranscriptClient", "TranscriptClient"]
