"""YouTube search and transcripts: the result types, the input rules, and the clients.

Nothing here knows about agents or language models, which is what lets the
link-building and error handling be tested on their own.
"""

from agent_runtime.youtube.client import (
    ApiYouTubeClient,
    FakeYouTubeClient,
    UnconfiguredYouTubeClient,
    YouTubeClient,
)
from agent_runtime.youtube.search import (
    SearchQueryError,
    VideoResult,
    YouTubeError,
    format_results,
    normalize_query,
)
from agent_runtime.youtube.transcript import (
    Transcript,
    TranscriptError,
    TranscriptSegment,
    VideoIdError,
    extract_video_id,
    format_transcript,
)
from agent_runtime.youtube.transcript_client import (
    FakeTranscriptClient,
    LibraryTranscriptClient,
    TranscriptClient,
)

__all__ = [
    "ApiYouTubeClient",
    "FakeTranscriptClient",
    "FakeYouTubeClient",
    "LibraryTranscriptClient",
    "SearchQueryError",
    "Transcript",
    "TranscriptClient",
    "TranscriptError",
    "TranscriptSegment",
    "UnconfiguredYouTubeClient",
    "VideoIdError",
    "VideoResult",
    "YouTubeClient",
    "YouTubeError",
    "extract_video_id",
    "format_results",
    "format_transcript",
    "normalize_query",
]
