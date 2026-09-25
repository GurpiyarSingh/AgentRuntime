from __future__ import annotations

import pytest

from agent_runtime.tools.base import ToolError
from agent_runtime.tools.youtube_tools import GetYouTubeTranscriptTool
from agent_runtime.youtube.transcript import (
    Transcript,
    TranscriptSegment,
    VideoIdError,
    extract_video_id,
    format_timestamp,
    format_transcript,
)
from agent_runtime.youtube.transcript_client import FakeTranscriptClient

VIDEO_ID = "dQw4w9WgXcQ"


def transcript(
    segments: list[TranscriptSegment] | None = None, *, generated: bool = False
) -> Transcript:
    return Transcript(
        video_id=VIDEO_ID,
        language="English",
        language_code="en",
        is_generated=generated,
        segments=segments
        if segments is not None
        else [
            TranscriptSegment("Hello and welcome.", 0.0, 2.0),
            TranscriptSegment("Today: Kalman filters.", 2.0, 3.0),
        ],
    )


# --- finding the video id ----------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        VIDEO_ID,
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&t=42s&list=PL123",
        f"https://m.youtube.com/watch?feature=share&v={VIDEO_ID}",
        f"youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}?si=abc",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}?feature=share",
        f"  {VIDEO_ID}  ",
    ],
)
def test_video_id_is_found_in_every_link_shape(raw: str) -> None:
    assert extract_video_id(raw) == VIDEO_ID


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "kalman filter tutorial",
        "https://www.youtube.com/@somechannel",
        "https://www.youtube.com/playlist?list=PL123",
        f"https://example.com/watch?v={VIDEO_ID}",
        "https://www.youtube.com/watch?v=tooshort",
    ],
)
def test_anything_that_is_not_a_video_is_rejected(raw: str) -> None:
    with pytest.raises(VideoIdError):
        extract_video_id(raw)


# --- formatting --------------------------------------------------------------


def test_timestamps_switch_to_hours_for_long_videos() -> None:
    assert format_timestamp(65) == "1:05"
    assert format_timestamp(3725) == "1:02:05"


def test_plain_transcript_joins_text_under_a_header() -> None:
    text = format_transcript(transcript(), timestamps=False, max_chars=10_000)

    assert f"https://www.youtube.com/watch?v={VIDEO_ID}" in text
    assert "English" in text
    assert "Hello and welcome. Today: Kalman filters." in text
    assert "Truncated" not in text


def test_plain_transcript_breaks_into_paragraphs_by_time() -> None:
    segments = [TranscriptSegment("first", 0.0), TranscriptSegment("second", 90.0)]
    text = format_transcript(transcript(segments), timestamps=False, max_chars=10_000)
    assert "first\n\nsecond" in text


def test_timestamped_transcript_marks_each_line() -> None:
    text = format_transcript(transcript(), timestamps=True, max_chars=10_000)
    assert "[0:00] Hello and welcome." in text
    assert "[0:02] Today: Kalman filters." in text


def test_generated_captions_are_labelled() -> None:
    text = format_transcript(transcript(generated=True), timestamps=False, max_chars=10_000)
    assert "auto-generated" in text


def test_long_transcripts_are_cut_and_the_cut_is_announced() -> None:
    segments = [TranscriptSegment(f"sentence number {i}.", i * 10.0, 10.0) for i in range(600)]
    text = format_transcript(transcript(segments), timestamps=True, max_chars=1_000)

    body = text.split("\n\n", 1)[1]
    assert len(body) < 1_300  # the limit, plus the truncation note
    assert "sentence number 0." in text
    assert "sentence number 599." not in text
    assert "Truncated" in text
    assert "only this part of the video" in text


def test_a_single_oversized_block_is_trimmed_not_dropped() -> None:
    segments = [TranscriptSegment("word " * 2_000, 0.0, 30.0)]
    text = format_transcript(transcript(segments), timestamps=False, max_chars=1_000)
    assert "word word" in text
    assert "Truncated" in text


def test_empty_transcript_does_not_invite_a_made_up_summary() -> None:
    text = format_transcript(transcript([]), timestamps=False, max_chars=10_000)
    assert "empty" in text
    assert "from its title" in text


# --- the tool ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_fetches_by_link_and_returns_the_text() -> None:
    client = FakeTranscriptClient(transcripts={VIDEO_ID: transcript()})
    result = await GetYouTubeTranscriptTool(client).run(video=f"https://youtu.be/{VIDEO_ID}")

    assert "Today: Kalman filters." in result
    assert client.requests == [(VIDEO_ID, ["en"])]


@pytest.mark.asyncio
async def test_requested_language_is_tried_before_the_server_defaults() -> None:
    client = FakeTranscriptClient(transcripts={VIDEO_ID: transcript()})
    tool = GetYouTubeTranscriptTool(client, languages=["en", "de"])

    await tool.run(video=VIDEO_ID, language="de")
    assert client.requests[-1] == (VIDEO_ID, ["de", "en"])


@pytest.mark.asyncio
async def test_tool_applies_the_server_size_limit() -> None:
    segments = [TranscriptSegment(f"line {i}.", float(i), 1.0) for i in range(5_000)]
    client = FakeTranscriptClient(transcripts={VIDEO_ID: transcript(segments)})
    result = await GetYouTubeTranscriptTool(client, max_chars=1_000).run(video=VIDEO_ID)
    assert "Truncated" in result


@pytest.mark.asyncio
async def test_a_topic_instead_of_a_link_is_a_correctable_error() -> None:
    client = FakeTranscriptClient()
    with pytest.raises(ToolError, match="search for the video first"):
        await GetYouTubeTranscriptTool(client).run(video="kalman filter tutorial")
    assert client.requests == []  # never reached the network


@pytest.mark.asyncio
async def test_missing_captions_surface_as_a_tool_error() -> None:
    client = FakeTranscriptClient(fail_with="Captions are turned off for this video.")
    with pytest.raises(ToolError, match="Captions are turned off"):
        await GetYouTubeTranscriptTool(client).run(video=VIDEO_ID)


def test_schema_exposes_video_language_and_timestamps() -> None:
    schema = GetYouTubeTranscriptTool(FakeTranscriptClient()).to_openai_schema()
    assert schema["function"]["name"] == "get_youtube_transcript"
    assert set(schema["function"]["parameters"]["properties"]) == {
        "video",
        "language",
        "timestamps",
    }
    assert schema["function"]["parameters"]["required"] == ["video"]
