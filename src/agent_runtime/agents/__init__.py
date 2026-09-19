"""The specialist agents this runtime can route work to."""

from agent_runtime.agents.base import AgentSpec
from agent_runtime.agents.email_agent import build_email_agent
from agent_runtime.agents.registry import AgentRegistry, UnknownAgentError
from agent_runtime.agents.youtube_agent import build_youtube_agent

__all__ = [
    "AgentRegistry",
    "AgentSpec",
    "UnknownAgentError",
    "build_email_agent",
    "build_youtube_agent",
]
