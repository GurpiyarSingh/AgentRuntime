"""What a transcript request asks for, and what it gets back.

The same split as `search.py`: no agents, no language models, no network.
This holds the transcript types, the rules for turning whatever the user
pasted (a watch link, a youtu.be link, a Shorts link, a bare id) into a
video id, and the formatting the model reads — including the cut-off that
keeps a two-hour lecture from swallowing the whole context window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from agent_runtime.youtube.search import WATCH_URL, YouTubeError

# YouTube ids are eleven characters from this alphabet. Checking the shape
# up front turns a typo into a clear error instead of a confusing upstream one.
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

_YOUTUBE_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
)
_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
# Path prefixes where the id is the next path segment.
_ID_PATH_PREFIXES = ("shorts", "embed", "live", "v")

# Group untimestamped text into paragraphs of roughly this many seconds, so
# the model gets readable prose rather than one enormous line.
PARAGRAPH_SECONDS = 60.0


class TranscriptError(YouTubeError):
    """Raised when a transcript cannot be fetched (disabled, missing, blocked)."""


class VideoIdError(ValueError):
    """Raised when the requested video cannot be identified."""


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """One caption line and when it is spoken."""

    text: str
    start: float
    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class Transcript:
    """A video's captions in one language."""

    video_id: str
    language: str
    language_code: str
    is_generated: bool
    segments: list[TranscriptSegment] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"{WATCH_URL}{self.video_id}"

    @property
    def duration(self) -> float:
        """Seconds from the start of the video to the end of the last caption."""
        if not self.segments:
            return 0.0
        last = self.segments[-1]
        return last.start + last.duration


def extract_video_id(raw: str) -> str:
    """Find the video id in a link or accept a bare id.

    Anything else — a channel page, a playlist with no video, a different
    site — is rejected, because transcribing the wrong thing silently is
    worse than asking again.
    """
    value = raw.strip()
    if not value:
        raise VideoIdError("Give a YouTube link or video id to transcribe.")
    if _VIDEO_ID.match(value):
        return value

    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").lower()
    candidate = ""
    if host in _SHORT_HOSTS:
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        segments = [part for part in parsed.path.split("/") if part]
        if segments[:1] == ["watch"]:
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        elif len(segments) >= 2 and segments[0] in _ID_PATH_PREFIXES:
            candidate = segments[1]

    if not _VIDEO_ID.match(candidate):
        raise VideoIdError(
            f"Could not find a YouTube video id in {raw!r}. Pass a watch link "
            "(https://www.youtube.com/watch?v=...), a youtu.be link, or the 11-character id. "
            "If you only know the topic, search for the video first."
        )
    return candidate


def format_timestamp(seconds: float) -> str:
    """`m:ss`, or `h:mm:ss` once a video passes the hour."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _clean(text: str) -> str:
    return " ".join(text.split())


def _body(segments: list[TranscriptSegment], timestamps: bool) -> list[tuple[float, str]]:
    """The transcript as (start time, block of text) pairs, ready to join."""
    if timestamps:
        return [
            (seg.start, f"[{format_timestamp(seg.start)}] {text}")
            for seg in segments
            if (text := _clean(seg.text))
        ]

    blocks: list[tuple[float, str]] = []
    current: list[str] = []
    block_start = 0.0
    for seg in segments:
        text = _clean(seg.text)
        if not text:
            continue
        if current and seg.start - block_start >= PARAGRAPH_SECONDS:
            blocks.append((block_start, " ".join(current)))
            current = []
        if not current:
            block_start = seg.start
        current.append(text)
    if current:
        blocks.append((block_start, " ".join(current)))
    return blocks


def format_transcript(transcript: Transcript, *, timestamps: bool, max_chars: int) -> str:
    """The observation handed back to the model after fetching a transcript.

    Long transcripts are cut at a block boundary and the cut is announced,
    with how far the text gets, so the model can tell the user its summary
    covers only part of the video instead of implying it saw all of it.
    """
    kind = "auto-generated captions" if transcript.is_generated else "captions"
    header = (
        f"Transcript of {transcript.url} "
        f"({transcript.language}, {kind}, about {format_timestamp(transcript.duration)} long):"
    )
    blocks = _body(transcript.segments, timestamps)
    if not blocks:
        return (
            f"{header}\n\nThe transcript is empty. Tell the user no spoken content "
            "was captioned rather than describing the video from its title."
        )

    separator = "\n" if timestamps else "\n\n"
    full_length = sum(len(text) for _, text in blocks) + len(separator) * (len(blocks) - 1)

    kept: list[str] = []
    used = 0
    reached = 0.0
    for start, text in blocks:
        cost = len(text) + (len(separator) if kept else 0)
        if kept and used + cost > max_chars:
            break
        if not kept and cost > max_chars:
            # A single oversized block: keep its head rather than nothing.
            text = text[:max_chars].rsplit(" ", 1)[0] + " …"
            cost = len(text)
        kept.append(text)
        used += cost
        reached = start

    lines = [header, "", separator.join(kept)]
    if len(kept) < len(blocks) or used < full_length:
        lines += [
            "",
            f"[Truncated: showing {used:,} of {full_length:,} characters, up to about "
            f"{format_timestamp(reached)} of {format_timestamp(transcript.duration)}. "
            "Tell the user any summary covers only this part of the video.]",
        ]
    return "\n".join(lines)


__all__ = [
    "PARAGRAPH_SECONDS",
    "Transcript",
    "TranscriptError",
    "TranscriptSegment",
    "VideoIdError",
    "extract_video_id",
    "format_timestamp",
    "format_transcript",
]
