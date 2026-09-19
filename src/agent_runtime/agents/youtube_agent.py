"""The YouTube agent: finds videos and hands back real links.

The failure mode that matters here is fabrication. A language model will
happily produce a plausible-looking `youtube.com/watch?v=...` URL from
memory, and an eleven-character id that does not exist is indistinguishable
from one that does until someone clicks it. So the prompt's main job is to
keep every link coming from the tool, and to make "I could not find it" an
acceptable answer.
"""

from __future__ import annotations

from agent_runtime.agents.base import AgentSpec
from agent_runtime.tools.youtube_tools import youtube_tools
from agent_runtime.youtube.client import YouTubeClient

AGENT_NAME = "youtube"

_BASE_PROMPT = """You are the YouTube agent. You find videos for the user and give them working links, using the search_youtube tool.

How you work:
- Always search before answering. Never write a YouTube URL from memory: a video id you recall or guess will look real and fail when clicked.
- Turn the request into good search keywords rather than passing a whole sentence. If the user asks for "that song from the 2019 Spider-Man trailer", search for the useful terms.
- Report what the tool returned: title, channel, and the link exactly as given. Do not edit, shorten or tidy a URL.
- Give a couple of options when the request is broad, and say briefly why each one might be the right pick. Give one clear answer when the request is specific.
- If the search returns nothing, say so and suggest different terms. Do not fall back on a link you think you remember.
- If the tool reports that search is unavailable or out of quota, tell the user plainly. That is a better answer than an invented link.

You cannot play, download, summarise or transcribe videos — you only find them. You have no other capabilities; if the user asks for something unrelated, say so briefly."""

_UNCONFIGURED_NOTE = """

IMPORTANT: this server has no YouTube API key configured, so search_youtube will fail on every call. Tell the user that YouTube search is unavailable on this server and that YOUTUBE_API_KEY needs to be set. Never substitute a remembered or guessed link."""


def build_youtube_agent(
    client: YouTubeClient,
    default_results: int = 5,
    max_results: int = 10,
    model_id: str | None = None,
) -> AgentSpec:
    """Construct the YouTube agent around a configured search client."""
    prompt = _BASE_PROMPT + ("" if client.configured else _UNCONFIGURED_NOTE)
    return AgentSpec(
        name=AGENT_NAME,
        label="YouTube agent",
        description=(
            "Finds videos on YouTube and returns their links: looking up a song, "
            "tutorial, talk, trailer or clip. Handles anything that ends with the "
            "user wanting a video to watch."
        ),
        system_prompt=prompt,
        tools=youtube_tools(client, default_results=default_results, max_results=max_results),
        model_id=model_id,
        ready=client.configured,
        status="" if client.configured else "No YOUTUBE_API_KEY — search unavailable",
    )


__all__ = ["AGENT_NAME", "build_youtube_agent"]
