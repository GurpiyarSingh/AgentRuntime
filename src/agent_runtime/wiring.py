"""Turning settings into the objects the runtime actually runs on.

One place builds the email policy, picks a transport, and assembles the
agent registry. The API, the CLI and the tests all come through here, so
"what is this runtime capable of right now?" has a single answer rather
than three slightly different ones.
"""

from __future__ import annotations

import logging

from agent_runtime.agents.base import AgentSpec
from agent_runtime.agents.email_agent import build_email_agent
from agent_runtime.agents.registry import AgentRegistry
from agent_runtime.agents.youtube_agent import build_youtube_agent
from agent_runtime.config import Settings
from agent_runtime.mail.message import EmailPolicy
from agent_runtime.mail.transport import (
    DryRunTransport,
    EmailTransport,
    SmtpConfig,
    SmtpTransport,
)
from agent_runtime.youtube.client import (
    ApiYouTubeClient,
    UnconfiguredYouTubeClient,
    YouTubeClient,
)
from agent_runtime.youtube.transcript_client import LibraryTranscriptClient, TranscriptClient

logger = logging.getLogger(__name__)


def build_email_policy(settings: Settings) -> EmailPolicy:
    return EmailPolicy(
        sender=settings.email_from,
        sender_name=settings.email_from_name,
        max_recipients=settings.email_max_recipients,
        allowed_domains=settings.allowed_email_domains,
    )


def build_email_transport(settings: Settings) -> EmailTransport:
    """A real SMTP transport only when fully configured and dry run is off.

    Missing configuration degrades to a dry run rather than failing at
    startup: the runtime stays usable end to end (you can watch the agent
    compose a message) and says clearly that nothing was delivered.
    """
    if settings.email_dry_run:
        return DryRunTransport()
    if not settings.smtp_host or not settings.email_from:
        logger.warning(
            "EMAIL_DRY_RUN is false but SMTP_HOST/EMAIL_FROM are not set; "
            "falling back to dry run so nothing is silently dropped"
        )
        return DryRunTransport()
    return SmtpTransport(
        SmtpConfig(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password.get_secret_value() if settings.smtp_password else "",
            use_starttls=settings.smtp_starttls,
            use_ssl=settings.smtp_ssl,
            timeout_s=settings.smtp_timeout_s,
        )
    )


def build_youtube_client(settings: Settings) -> YouTubeClient:
    """A real search client when a key is set, otherwise one that says why not.

    The agent is registered either way: a visible agent that explains it is
    unconfigured is more useful than one that silently disappears.
    """
    if settings.youtube_api_key is None:
        return UnconfiguredYouTubeClient()
    return ApiYouTubeClient(
        api_key=settings.youtube_api_key.get_secret_value(),
        timeout_s=settings.youtube_timeout_s,
    )


def build_agents(
    settings: Settings,
    transport: EmailTransport | None = None,
    youtube_client: YouTubeClient | None = None,
    transcript_client: TranscriptClient | None = None,
) -> AgentRegistry:
    """Every agent this runtime can route to.

    Register additional specialists here; the router, the `/v1/agents`
    endpoint and the UI picker all read from this registry, so a new agent
    shows up everywhere at once. The first registered is the default the
    router falls back to.
    """
    transport = transport or build_email_transport(settings)
    client = youtube_client or build_youtube_client(settings)
    agents: list[AgentSpec] = [
        build_email_agent(build_email_policy(settings), transport),
        build_youtube_agent(
            client,
            default_results=settings.youtube_max_results,
            max_results=settings.youtube_result_ceiling,
            transcript_client=transcript_client or LibraryTranscriptClient(),
            transcript_languages=settings.transcript_languages,
            transcript_max_chars=settings.youtube_transcript_max_chars,
        ),
    ]
    return AgentRegistry(agents)


__all__ = [
    "build_agents",
    "build_email_policy",
    "build_email_transport",
    "build_youtube_client",
]
