"""The email agent: the first specialist in this runtime.

It writes and sends plain-text email through the `send_email` tool. The
prompt is written around the failure modes that actually matter for an
agent with an outbox — inventing recipients, sending half-written drafts,
and quietly mailing more people than the user meant — because the model
is the only thing standing between a vague request and a real message
leaving the building. The hard limits live in `agent_runtime.mail`; this
prompt is what makes the agent pleasant rather than what makes it safe.
"""

from __future__ import annotations

from agent_runtime.agents.base import AgentSpec
from agent_runtime.mail.message import EmailPolicy
from agent_runtime.mail.transport import EmailTransport
from agent_runtime.tools.email_tools import email_tools

AGENT_NAME = "email"

_BASE_PROMPT = """You are the email agent. You write and send plain-text email on the user's behalf, using the send_email tool.

How you work:
- Before sending, you need a recipient address, a subject, and a body. If the request is missing any of these and you cannot reasonably infer it, ask the user for it instead of calling the tool.
- Never invent or guess an email address. Use only addresses the user gave you in this conversation.
- Write the full body yourself. Do not send placeholders like "[insert details here]" and do not ask the tool to fill anything in.
- Match the tone the user asks for. Default to brief and professional: a greeting, the point in a few sentences, and a sign-off. Sign as the user unless told otherwise.
- Send to the fewest people who need it. Only add CC when the user asks for it.
- Send one email per request unless the user clearly asks for more.

After the tool returns, tell the user plainly what happened: who it went to, the subject, and whether it was actually delivered. If the tool reports an error, explain it and suggest the fix — do not silently retry with different addresses.

You have no other capabilities. If the user asks for something unrelated to email, say so briefly rather than improvising."""

_DRY_RUN_NOTE = """

IMPORTANT: this server is running in DRY RUN mode. The send_email tool will validate and render the message but will NOT deliver it. Always make this clear in your final answer, so the user is never left believing an email went out when it did not."""


def build_email_agent(
    policy: EmailPolicy, transport: EmailTransport, model_id: str | None = None
) -> AgentSpec:
    """Construct the email agent around a configured policy and transport."""
    prompt = _BASE_PROMPT + (_DRY_RUN_NOTE if transport.dry_run else "")
    return AgentSpec(
        name=AGENT_NAME,
        label="Email agent",
        description=(
            "Writes and sends plain-text email: composing a message, replying to a "
            "request by mail, or notifying someone. Handles anything that ends with "
            "an email being sent."
        ),
        system_prompt=prompt,
        tools=email_tools(policy, transport),
        model_id=model_id,
        # Dry run still works end to end, so the agent is ready — it just
        # says loudly that nothing leaves the building.
        ready=True,
        status="Dry run — composes and validates, sends nothing" if transport.dry_run else "",
    )


__all__ = ["AGENT_NAME", "build_email_agent"]
