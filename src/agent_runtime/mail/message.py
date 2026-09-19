"""What an outgoing email is, and the rules it has to satisfy before it goes.

This module knows nothing about agents or language models. It is the
domain layer: an `OutgoingEmail` value, and an `EmailPolicy` that decides
whether the runtime is willing to send it. Keeping the rules here — rather
than inside the tool the model calls — means the guardrails are unit
testable on their own and cannot be talked around by a clever prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


class EmailPolicyError(ValueError):
    """Raised when a requested email breaks a configured rule.

    The message is written to be read by the model: it says what was
    rejected and why, so the agent can correct itself and try again
    instead of simply failing the run.
    """


def normalize_address(raw: str) -> str:
    """Trim and validate a single address, or raise `EmailPolicyError`.

    Deliberately strict and boring: exactly one '@', no whitespace, a dot
    in the domain. Anything exotic is rejected rather than guessed at, so
    a malformed address fails here instead of at the SMTP server.
    """
    address = raw.strip()
    if not address:
        raise EmailPolicyError("An email address cannot be empty.")
    if any(char.isspace() for char in address):
        raise EmailPolicyError(f"Address {raw!r} contains whitespace.")
    if address.count("@") != 1:
        raise EmailPolicyError(f"Address {raw!r} must contain exactly one '@'.")
    local, _, domain = address.partition("@")
    if not local:
        raise EmailPolicyError(f"Address {raw!r} is missing the part before '@'.")
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise EmailPolicyError(f"Address {raw!r} does not have a valid domain.")
    return address


def domain_of(address: str) -> str:
    return address.rpartition("@")[2].lower()


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """One email, already validated, ready to hand to a transport."""

    sender: str
    to: tuple[str, ...]
    subject: str
    body: str
    cc: tuple[str, ...] = ()
    sender_name: str = ""

    @property
    def recipients(self) -> tuple[str, ...]:
        """Everyone who will actually receive this message."""
        return self.to + self.cc

    def to_mime(self) -> EmailMessage:
        """Render as a plain-text MIME message.

        Plain text only, on purpose: an agent composing arbitrary HTML is
        a far larger surface (tracking pixels, spoofed links) for no gain
        on the kind of mail this runtime is meant to send.
        """
        message = EmailMessage()
        message["From"] = (
            formataddr((self.sender_name, self.sender)) if self.sender_name else self.sender
        )
        message["To"] = ", ".join(self.to)
        if self.cc:
            message["Cc"] = ", ".join(self.cc)
        message["Subject"] = self.subject
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid()
        message.set_content(self.body)
        return message

    def preview(self) -> str:
        """A short, human-readable summary used in tool results and logs."""
        lines = [f"From: {self.sender}", f"To: {', '.join(self.to)}"]
        if self.cc:
            lines.append(f"Cc: {', '.join(self.cc)}")
        lines.append(f"Subject: {self.subject}")
        lines.append("")
        lines.append(self.body)
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class EmailPolicy:
    """The rules every outgoing email must pass.

    `sender` comes from server configuration and is never taken from the
    model — an agent that could choose its own From address could
    impersonate anyone the SMTP server is willing to relay for.
    """

    sender: str
    sender_name: str = ""
    max_recipients: int = 5
    allowed_domains: frozenset[str] = field(default_factory=frozenset)

    def build(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
    ) -> OutgoingEmail:
        """Validate a requested send and return the email to be sent."""
        if not self.sender:
            raise EmailPolicyError(
                "No sender address is configured. Set EMAIL_FROM before sending mail."
            )
        if not subject.strip():
            raise EmailPolicyError("An email needs a non-empty subject.")
        if not body.strip():
            raise EmailPolicyError("An email needs a non-empty body.")

        to_addresses = tuple(dict.fromkeys(normalize_address(item) for item in to))
        cc_addresses = tuple(
            address
            for address in dict.fromkeys(normalize_address(item) for item in (cc or []))
            if address not in to_addresses
        )
        if not to_addresses:
            raise EmailPolicyError("An email needs at least one recipient in 'to'.")

        total = len(to_addresses) + len(cc_addresses)
        if total > self.max_recipients:
            raise EmailPolicyError(
                f"This email has {total} recipients, but at most {self.max_recipients} "
                "are allowed per send. Send to fewer people, or raise EMAIL_MAX_RECIPIENTS."
            )

        if self.allowed_domains:
            blocked = sorted(
                {
                    address
                    for address in to_addresses + cc_addresses
                    if domain_of(address) not in self.allowed_domains
                }
            )
            if blocked:
                allowed = ", ".join(sorted(self.allowed_domains))
                raise EmailPolicyError(
                    f"Cannot send to {', '.join(blocked)}: only these domains are "
                    f"allowed by this server: {allowed}."
                )

        return OutgoingEmail(
            sender=self.sender,
            sender_name=self.sender_name,
            to=to_addresses,
            cc=cc_addresses,
            subject=subject.strip(),
            body=body,
        )


__all__ = [
    "EmailPolicy",
    "EmailPolicyError",
    "OutgoingEmail",
    "domain_of",
    "normalize_address",
]
