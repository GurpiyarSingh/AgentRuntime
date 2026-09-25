from __future__ import annotations

import pytest

from agent_runtime.agents.youtube_agent import build_youtube_agent
from agent_runtime.tools.base import ToolError
from agent_runtime.tools.youtube_tools import SearchYouTubeTool, youtube_tools
from agent_runtime.youtube.client import FakeYouTubeClient, UnconfiguredYouTubeClient
from agent_runtime.youtube.search import VideoResult


def video(video_id: str, title: str = "A video") -> VideoResult:
    return VideoResult(video_id=video_id, title=title, channel="Channel")


@pytest.mark.asyncio
async def test_search_returns_titles_and_links() -> None:
    client = FakeYouTubeClient(results=[video("a1", "Kalman filters"), video("b2", "More")])
    result = await SearchYouTubeTool(client).run(query="kalman filters")

    assert "Kalman filters" in result
    assert "https://www.youtube.com/watch?v=a1" in result
    assert "https://www.youtube.com/watch?v=b2" in result


@pytest.mark.asyncio
async def test_query_is_normalized_before_searching() -> None:
    client = FakeYouTubeClient(results=[video("a1")])
    await SearchYouTubeTool(client).run(query="  kalman   filter  ")
    assert client.queries[0][0] == "kalman filter"


@pytest.mark.asyncio
async def test_result_count_is_clamped_to_the_server_ceiling() -> None:
    client = FakeYouTubeClient(results=[video(str(i)) for i in range(20)])
    tool = SearchYouTubeTool(client, default_results=5, max_results=8)

    await tool.run(query="anything", max_results=50)
    assert client.queries[-1][1] == 8  # capped, not rejected

    await tool.run(query="anything")
    assert client.queries[-1][1] == 5  # server default


@pytest.mark.asyncio
async def test_empty_search_does_not_invite_a_made_up_link() -> None:
    result = await SearchYouTubeTool(FakeYouTubeClient(results=[])).run(query="nothing")
    assert "No videos found" in result
    assert "inventing" in result


@pytest.mark.asyncio
async def test_bad_query_surfaces_as_a_correctable_tool_error() -> None:
    with pytest.raises(ToolError):
        await SearchYouTubeTool(FakeYouTubeClient()).run(query="   ")


@pytest.mark.asyncio
async def test_missing_api_key_surfaces_as_a_tool_error() -> None:
    tool = SearchYouTubeTool(UnconfiguredYouTubeClient())
    assert tool.configured is False
    with pytest.raises(ToolError, match="YOUTUBE_API_KEY"):
        await tool.run(query="anything")


@pytest.mark.asyncio
async def test_upstream_failure_surfaces_as_a_tool_error() -> None:
    client = FakeYouTubeClient(fail_with="The YouTube API quota has been exhausted.")
    with pytest.raises(ToolError, match="quota"):
        await SearchYouTubeTool(client).run(query="anything")


def test_schema_exposes_only_query_and_count() -> None:
    schema = SearchYouTubeTool(FakeYouTubeClient()).to_openai_schema()
    properties = schema["function"]["parameters"]["properties"]

    assert set(properties) == {"query", "max_results"}
    assert schema["function"]["name"] == "search_youtube"


def test_registry_exposes_search_and_transcript_tools() -> None:
    assert youtube_tools(FakeYouTubeClient()).names() == [
        "search_youtube",
        "get_youtube_transcript",
    ]


# --- the agent spec ----------------------------------------------------------


def test_agent_is_ready_when_configured() -> None:
    spec = build_youtube_agent(FakeYouTubeClient())
    assert spec.name == "youtube"
    assert spec.ready is True
    assert spec.status == ""
    assert spec.tool_names == ["search_youtube", "get_youtube_transcript"]


def test_agent_stays_ready_without_a_key_but_says_search_is_down() -> None:
    spec = build_youtube_agent(UnconfiguredYouTubeClient())
    # Transcripts need no key, so the agent is still useful given a link.
    assert spec.ready is True
    assert "YOUTUBE_API_KEY" in spec.status
    assert "transcripts still work" in spec.status
    # The prompt itself warns the model, not just the UI.
    assert "no YouTube API key" in spec.system_prompt


def test_agent_prompt_forbids_recalled_links() -> None:
    prompt = build_youtube_agent(FakeYouTubeClient()).system_prompt
    assert "Never write a YouTube URL from memory" in prompt


def test_agent_prompt_grounds_content_in_the_transcript() -> None:
    prompt = build_youtube_agent(FakeYouTubeClient()).system_prompt
    assert "get_youtube_transcript" in prompt
    assert "Never summarise a video from its title" in prompt
