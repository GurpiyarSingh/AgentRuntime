from __future__ import annotations

import pytest

from agent_runtime.mail.message import EmailPolicy
from agent_runtime.mail.transport import DryRunTransport, RecordingTransport
from agent_runtime.tools.base import ToolError
from agent_runtime.tools.email_tools import SendEmailTool, email_tools

POLICY = EmailPolicy(sender="bot@example.com", sender_name="Agent Runtime")


def tool(transport: RecordingTransport | DryRunTransport | None = None) -> SendEmailTool:
    return SendEmailTool(policy=POLICY, transport=transport or RecordingTransport())


@pytest.mark.asyncio
async def test_send_email_delivers_and_reports_back() -> None:
    transport = RecordingTransport()
    result = await tool(transport).run(
        to=["alex@example.com"], subject="Release slipped", body="Hi Alex, it moved to Tuesday."
    )

    assert len(transport.sent) == 1
    sent = transport.sent[0]
    assert sent.to == ("alex@example.com",)
    assert sent.subject == "Release slipped"
    assert sent.sender == "bot@example.com"  # never chosen by the model
    assert "alex@example.com" in result


@pytest.mark.asyncio
async def test_dry_run_sends_nothing_and_says_so() -> None:
    transport = DryRunTransport()
    result = await tool(transport).run(
        to=["alex@example.com"], subject="Hello", body="Body text."
    )
    assert "DRY RUN" in result
    assert transport.sent  # recorded, but the receipt says not delivered


@pytest.mark.asyncio
async def test_policy_failures_surface_as_tool_errors_the_model_can_fix() -> None:
    # A ToolError is fed back as an observation, so the agent can correct
    # itself instead of the whole run crashing.
    with pytest.raises(ToolError, match="@"):
        await tool().run(to=["not-an-address"], subject="s", body="b")

    with pytest.raises(ToolError, match="subject"):
        await tool().run(to=["a@example.com"], subject="", body="b")


@pytest.mark.asyncio
async def test_recipient_cap_is_enforced_through_the_tool() -> None:
    capped = SendEmailTool(
        policy=EmailPolicy(sender="bot@example.com", max_recipients=2),
        transport=RecordingTransport(),
    )
    with pytest.raises(ToolError, match="at most 2"):
        await capped.run(
            to=["a@example.com", "b@example.com", "c@example.com"], subject="s", body="b"
        )


@pytest.mark.asyncio
async def test_delivery_failure_becomes_a_tool_error() -> None:
    transport = RecordingTransport(fail_with="The SMTP server refused the connection.")
    with pytest.raises(ToolError, match="refused"):
        await tool(transport).run(to=["a@example.com"], subject="s", body="b")


def test_schema_exposes_no_sender_or_bcc_field() -> None:
    schema = tool().to_openai_schema()
    properties = schema["function"]["parameters"]["properties"]

    assert set(properties) == {"to", "subject", "body", "cc"}
    # The model cannot choose who the mail is from, nor hide recipients.
    assert "from" not in properties
    assert "bcc" not in properties
    assert schema["function"]["name"] == "send_email"


def test_email_tools_registry_exposes_only_send_email() -> None:
    registry = email_tools(POLICY, RecordingTransport())
    assert registry.names() == ["send_email"]
