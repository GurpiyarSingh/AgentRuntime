"""The tools the email agent can call.

Only one for now — `send_email` — and it is deliberately thin: it parses
what the model asked for, hands it to `EmailPolicy` for validation, and
gives the result to a transport. All the judgement about what may be sent
lives in `agent_runtime.mail`, not here, so the rules hold no matter what
the model is persuaded to ask for.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from agent_runtime.mail.message import EmailPolicy, EmailPolicyError
from agent_runtime.mail.transport import EmailDeliveryError, EmailTransport
from agent_runtime.tools.base import Tool, ToolError
from agent_runtime.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SendEmailArgs(BaseModel):
    """What the model must provide to send an email.

    Note what is absent: the sender. That comes from server config, so the
    agent cannot send as somebody else. There is no BCC either — hidden
    recipients are the one thing a reviewer of a run's trace could not see.
    """

    to: list[str] = Field(
        ...,
        min_length=1,
        description="Recipient email addresses. Use the fewest that answer the request.",
    )
    subject: str = Field(..., description="A specific, informative subject line.")
    body: str = Field(
        ...,
        description="The plain-text body of the email, already written out in full. "
        "Include a greeting and sign-off. Do not use HTML or markdown.",
    )
    cc: list[str] = Field(
        default_factory=list, description="Optional addresses to copy. Usually empty."
    )


class SendEmailTool(Tool):
    name = "send_email"
    description = (
        "Send a plain-text email from the account this server is configured with. "
        "Use it once the recipient, subject and full body are known. "
        "The sender address is fixed by the server and cannot be chosen."
    )
    args_schema = SendEmailArgs

    def __init__(self, policy: EmailPolicy, transport: EmailTransport) -> None:
        self._policy = policy
        self._transport = transport

    @property
    def dry_run(self) -> bool:
        return self._transport.dry_run

    async def run(  # type: ignore[override]
        self, to: list[str], subject: str, body: str, cc: list[str] | None = None
    ) -> str:
        try:
            email = self._policy.build(to=to, subject=subject, body=body, cc=cc)
        except EmailPolicyError as exc:
            # A rejected send is an expected outcome the model should react
            # to (fix the address, drop a recipient), not a crashed run.
            raise ToolError(str(exc)) from exc

        try:
            receipt = await self._transport.send(email)
        except EmailDeliveryError as exc:
            raise ToolError(str(exc)) from exc

        return receipt.detail


def email_tools(policy: EmailPolicy, transport: EmailTransport) -> ToolRegistry:
    """The tool set given to the email agent."""
    return ToolRegistry([SendEmailTool(policy=policy, transport=transport)])


__all__ = ["SendEmailArgs", "SendEmailTool", "email_tools"]
