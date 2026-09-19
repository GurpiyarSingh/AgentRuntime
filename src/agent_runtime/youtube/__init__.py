"""YouTube search: the result type, the query rules, and the API client.

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

__all__ = [
    "ApiYouTubeClient",
    "FakeYouTubeClient",
    "SearchQueryError",
    "UnconfiguredYouTubeClient",
    "VideoResult",
    "YouTubeClient",
    "YouTubeError",
    "format_results",
    "normalize_query",
]
