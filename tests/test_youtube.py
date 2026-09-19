from __future__ import annotations

import httpx
import pytest

from agent_runtime.youtube.client import (
    ApiYouTubeClient,
    FakeYouTubeClient,
    UnconfiguredYouTubeClient,
    parse_results,
)
from agent_runtime.youtube.search import (
    SearchQueryError,
    VideoResult,
    YouTubeError,
    clamp_results,
    format_results,
    normalize_query,
)


def video(video_id: str = "dQw4w9WgXcQ", title: str = "A video") -> VideoResult:
    return VideoResult(
        video_id=video_id, title=title, channel="Some Channel", published_at="2024-05-01T10:00:00Z"
    )


# --- links -------------------------------------------------------------------


def test_url_is_built_from_the_id_not_taken_from_the_provider() -> None:
    assert video("abc123").url == "https://www.youtube.com/watch?v=abc123"


def test_result_line_carries_title_link_and_channel() -> None:
    line = video(title="Kalman filters explained").as_line(1)
    assert "1. Kalman filters explained" in line
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in line
    assert "Some Channel" in line
    assert "2024-05-01" in line


# --- query handling ----------------------------------------------------------


def test_normalize_query_collapses_whitespace() -> None:
    assert normalize_query("  kalman   filter  tutorial ") == "kalman filter tutorial"


def test_normalize_query_rejects_empty_and_overlong() -> None:
    with pytest.raises(SearchQueryError):
        normalize_query("   ")
    with pytest.raises(SearchQueryError, match="under 200"):
        normalize_query("x" * 201)


def test_clamp_results_caps_rather_than_failing() -> None:
    # An over-eager model gets the ceiling, not an error.
    assert clamp_results(50, default=5, ceiling=10) == 10
    assert clamp_results(None, default=5, ceiling=10) == 5
    assert clamp_results(0, default=5, ceiling=10) == 1
    assert clamp_results(3, default=5, ceiling=10) == 3


# --- formatting --------------------------------------------------------------


def test_format_results_lists_every_video() -> None:
    text = format_results("kalman", [video("a1"), video("b2")])
    assert "Found 2 video(s)" in text
    assert "watch?v=a1" in text and "watch?v=b2" in text


def test_empty_results_tell_the_model_not_to_invent_a_link() -> None:
    text = format_results("nothing at all", [])
    assert "No videos found" in text
    assert "inventing" in text


# --- parsing -----------------------------------------------------------------


def test_parse_results_reads_the_api_shape() -> None:
    payload = {
        "items": [
            {
                "id": {"videoId": "abc"},
                "snippet": {
                    "title": "Title",
                    "channelTitle": "Channel",
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "description": "Desc",
                },
            }
        ]
    }
    [result] = parse_results(payload)
    assert result.video_id == "abc"
    assert result.title == "Title"
    assert result.channel == "Channel"


def test_parse_results_drops_entries_without_a_usable_link() -> None:
    payload = {
        "items": [
            {"id": {"kind": "youtube#channel"}, "snippet": {"title": "A channel"}},  # no videoId
            {"id": {"videoId": "ok"}, "snippet": {}},  # no title
            {"id": {"videoId": "good"}, "snippet": {"title": "Real"}},
        ]
    }
    results = parse_results(payload)
    assert [r.video_id for r in results] == ["good"]


# --- clients -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfigured_client_explains_itself() -> None:
    with pytest.raises(YouTubeError) as excinfo:
        await UnconfiguredYouTubeClient().search("anything", 5)

    message = str(excinfo.value)
    assert "YOUTUBE_API_KEY" in message
    # It must actively steer the model away from fabricating a link.
    assert "do not guess" in message.lower()
    assert UnconfiguredYouTubeClient().configured is False


@pytest.mark.asyncio
async def test_fake_client_records_queries() -> None:
    client = FakeYouTubeClient(results=[video("a"), video("b"), video("c")])
    results = await client.search("kalman", 2)

    assert client.queries == [("kalman", 2)]
    assert [r.video_id for r in results] == ["a", "b"]


@pytest.mark.asyncio
async def test_api_client_sends_the_expected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"items": [{"id": {"videoId": "xyz"}, "snippet": {"title": "Found"}}]},
        )

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport  # type: ignore[index]
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    results = await ApiYouTubeClient(api_key="key-123").search("kalman filter", 3)

    url = str(seen["url"])
    assert "youtube/v3/search" in url
    assert "q=kalman+filter" in url or "q=kalman%20filter" in url
    assert "maxResults=3" in url
    assert "type=video" in url  # never channels or playlists
    assert "key=key-123" in url
    assert [r.video_id for r in results] == ["xyz"]


@pytest.mark.asyncio
async def test_api_client_turns_quota_errors_into_readable_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"error": {"errors": [{"reason": "quotaExceeded"}], "message": "over quota"}}
        )

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: original(*a, **{**kw, "transport": transport}),  # type: ignore[arg-type]
    )

    with pytest.raises(YouTubeError, match="quota"):
        await ApiYouTubeClient(api_key="key").search("anything", 5)


@pytest.mark.asyncio
async def test_api_client_explains_a_bad_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"errors": [{"reason": "badRequest"}]}})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: original(*a, **{**kw, "transport": transport}),  # type: ignore[arg-type]
    )

    with pytest.raises(YouTubeError, match="YOUTUBE_API_KEY"):
        await ApiYouTubeClient(api_key="bad").search("anything", 5)
