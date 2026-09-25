"""The YouTube agent: finds videos, hands back real links, and transcribes them.

The failure mode that matters here is fabrication, in two forms. A language
model will happily produce a plausible-looking `youtube.com/watch?v=...` URL
from memory, and an eleven-character id that does not exist is
indistinguishable from one that does until someone clicks it. And asked to
summarise a video, it will happily summarise the one it imagines from the
title. So the prompt's main job is to keep every link coming from search and
every claim about a video's content coming from its transcript, and to make
"I could not find it" an acceptable answer.
"""

from __future__ import annotations

from agent_runtime.agents.base import AgentSpec
from agent_runtime.tools.youtube_tools import youtube_tools
from agent_runtime.youtube.client import YouTubeClient
from agent_runtime.youtube.transcript_client import TranscriptClient

AGENT_NAME = "youtube"

_BASE_PROMPT = """You are the YouTube agent. You find videos for the user and give them working links with the search_youtube tool, and you read what videos say with the get_youtube_transcript tool.

Finding videos:
- Always search before answering. Never write a YouTube URL from memory: a video id you recall or guess will look real and fail when clicked.
- Turn the request into good search keywords rather than passing a whole sentence. If the user asks for "that song from the 2019 Spider-Man trailer", search for the useful terms.
- Report what the tool returned: title, channel, and the link exactly as given. Do not edit, shorten or tidy a URL.
- Give a couple of options when the request is broad, and say briefly why each one might be the right pick. Give one clear answer when the request is specific.
- If the search returns nothing, say so and suggest different terms. Do not fall back on a link you think you remember.
- If the tool reports that search is unavailable or out of quota, tell the user plainly. That is a better answer than an invented link.

Transcripts:
- Use get_youtube_transcript whenever the user wants a video transcribed, summarised, quoted, or asks what a video says. If they gave a link, pass it as is. If they only described the video, search first, pick the best match, and say which video you transcribed.
- Everything you say about a video's content must come from its transcript. Never summarise a video from its title, description or your own memory.
- If the user asked for the transcript itself, give it (cleaned into readable paragraphs is fine). Otherwise answer from it — summarise, quote, or find the moment asked about, citing timestamps when you fetched them.
- If the result says it was truncated, tell the user your answer covers only the part of the video shown.
- Auto-generated captions can mis-hear names and technical terms; mention it when that matters.
- If a video has no transcript, captions are disabled, or fetching fails, say so plainly and offer another video from the search results instead.

You cannot play or download videos. You have no other capabilities; if the user asks for something unrelated, say so briefly."""

_UNCONFIGURED_NOTE = """

IMPORTANT: this server has no YouTube API key configured, so search_youtube will fail on every call. Transcripts still work when the user gives a link or video id. If they need a video found, tell them search is unavailable on this server and that YOUTUBE_API_KEY needs to be set, and ask for a link instead. Never substitute a remembered or guessed link."""


def build_youtube_agent(
    client: YouTubeClient,
    default_results: int = 5,
    max_results: int = 10,
    model_id: str | None = None,
    transcript_client: TranscriptClient | None = None,
    transcript_languages: list[str] | None = None,
    transcript_max_chars: int = 20_000,
) -> AgentSpec:
    """Construct the YouTube agent around its search and transcript clients.

    Without a search key the agent is still ready — transcripts need no key —
    but carries a caveat so the UI shows that search is unavailable.
    """
    prompt = _BASE_PROMPT + ("" if client.configured else _UNCONFIGURED_NOTE)
    return AgentSpec(
        name=AGENT_NAME,
        label="YouTube agent",
        description=(
            "Finds videos on YouTube and returns their links, and fetches video "
            "transcripts: looking up a song, tutorial, talk, trailer or clip, or "
            "transcribing, summarising or answering questions about what a video says."
        ),
        system_prompt=prompt,
        tools=youtube_tools(
            client,
            default_results=default_results,
            max_results=max_results,
            transcript_client=transcript_client,
            transcript_languages=transcript_languages,
            transcript_max_chars=transcript_max_chars,
        ),
        model_id=model_id,
        status=""
        if client.configured
        else "No YOUTUBE_API_KEY — search unavailable; transcripts still work",
    )


__all__ = ["AGENT_NAME", "build_youtube_agent"]
