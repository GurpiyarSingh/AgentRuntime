from __future__ import annotations

import pytest

from agent_runtime.mail.message import (
    EmailPolicy,
    EmailPolicyError,
    normalize_address,
)
from agent_runtime.mail.transport import DryRunTransport, RecordingTransport


def policy(**overrides: object) -> EmailPolicy:
    defaults: dict[str, object] = {"sender": "bot@example.com", "sender_name": "Agent Runtime"}
    defaults.update(overrides)
    return EmailPolicy(**defaults)  # type: ignore[arg-type]


# --- address validation ------------------------------------------------------


@pytest.mark.parametrize(
    "address", ["a@b.com", "first.last@sub.example.co.uk", "  spaced@example.com  "]
)
def test_normalize_accepts_ordinary_addresses(address: str) -> None:
    assert normalize_address(address) == address.strip()


@pytest.mark.parametrize(
    "address",
    ["", "   ", "nope", "no@domain", "two@@example.com", "a b@example.com", "@example.com"],
)
def test_normalize_rejects_malformed_addresses(address: str) -> None:
    with pytest.raises(EmailPolicyError):
        normalize_address(address)


# --- policy ------------------------------------------------------------------


def test_build_produces_a_validated_email() -> None:
    email = policy().build(to=["a@example.com"], subject=" Hello ", body="Hi there")
    assert email.sender == "bot@example.com"
    assert email.to == ("a@example.com",)
    assert email.subject == "Hello"  # trimmed
    assert email.recipients == ("a@example.com",)


def test_build_requires_sender_subject_body_and_recipient() -> None:
    with pytest.raises(EmailPolicyError, match="sender"):
        policy(sender="").build(to=["a@example.com"], subject="s", body="b")
    with pytest.raises(EmailPolicyError, match="subject"):
        policy().build(to=["a@example.com"], subject="   ", body="b")
    with pytest.raises(EmailPolicyError, match="body"):
        policy().build(to=["a@example.com"], subject="s", body="  ")
    with pytest.raises(EmailPolicyError, match="recipient"):
        policy().build(to=[], subject="s", body="b")


def test_duplicate_recipients_are_collapsed() -> None:
    email = policy().build(
        to=["a@example.com", "a@example.com"],
        cc=["a@example.com", "b@example.com"],
        subject="s",
        body="b",
    )
    assert email.to == ("a@example.com",)
    # An address already in To is not also CC'd.
    assert email.cc == ("b@example.com",)


def test_recipient_cap_blocks_accidental_mass_sends() -> None:
    recipients = [f"person{i}@example.com" for i in range(4)]
    with pytest.raises(EmailPolicyError, match="at most 3"):
        policy(max_recipients=3).build(to=recipients, subject="s", body="b")


def test_domain_allowlist_blocks_outside_addresses() -> None:
    restricted = policy(allowed_domains=frozenset({"example.com"}))
    restricted.build(to=["ok@example.com"], subject="s", body="b")  # allowed

    with pytest.raises(EmailPolicyError) as excinfo:
        restricted.build(to=["ok@example.com", "stranger@elsewhere.org"], subject="s", body="b")
    # The error names the blocked address and what is permitted.
    assert "stranger@elsewhere.org" in str(excinfo.value)
    assert "example.com" in str(excinfo.value)


def test_allowlist_is_case_insensitive_on_domain() -> None:
    restricted = policy(allowed_domains=frozenset({"example.com"}))
    email = restricted.build(to=["Person@Example.COM"], subject="s", body="b")
    assert email.to == ("Person@Example.COM",)


# --- MIME rendering ----------------------------------------------------------


def test_mime_carries_headers_and_plain_text_body() -> None:
    email = policy().build(
        to=["a@example.com"], cc=["b@example.com"], subject="Status", body="All good.\n"
    )
    mime = email.to_mime()

    assert mime["Subject"] == "Status"
    assert mime["To"] == "a@example.com"
    assert mime["Cc"] == "b@example.com"
    assert "Agent Runtime" in mime["From"] and "bot@example.com" in mime["From"]
    assert mime["Message-ID"]
    assert mime.get_content_type() == "text/plain"
    assert mime.get_content().strip() == "All good."


def test_preview_shows_what_would_be_sent() -> None:
    email = policy().build(to=["a@example.com"], subject="Status", body="All good.")
    preview = email.preview()
    assert "To: a@example.com" in preview
    assert "Subject: Status" in preview
    assert "All good." in preview


# --- transports --------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_transport_records_but_reports_not_delivered() -> None:
    transport = DryRunTransport()
    email = policy().build(to=["a@example.com"], subject="Status", body="All good.")

    receipt = await transport.send(email)

    assert transport.dry_run is True
    assert transport.sent == [email]
    assert receipt.delivered is False
    assert receipt.dry_run is True
    # The result must make the non-delivery unmissable to the model.
    assert "DRY RUN" in receipt.detail
    assert "All good." in receipt.detail


@pytest.mark.asyncio
async def test_recording_transport_reports_delivery() -> None:
    transport = RecordingTransport()
    email = policy().build(to=["a@example.com"], subject="Status", body="All good.")

    receipt = await transport.send(email)

    assert receipt.delivered is True
    assert receipt.dry_run is False
    assert transport.sent == [email]
