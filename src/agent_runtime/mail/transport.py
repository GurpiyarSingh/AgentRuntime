"""How a validated email actually leaves the process — or doesn't.

Three transports implement one small protocol:

- `DryRunTransport` renders the message and records it, sending nothing.
  This is the default, so a misconfigured or over-eager agent cannot mail
  real people by accident on someone's first run.
- `SmtpTransport` talks to a real SMTP server (stdlib `smtplib`, run off
  the event loop) — no extra dependency for one blocking call.
- `RecordingTransport` is the test double.

Swapping transports is the only difference between "show me what you
would send" and "send it", which keeps that decision in configuration
rather than scattered through the agent's logic.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from agent_runtime.mail.message import OutgoingEmail

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when a transport accepted the email but could not deliver it."""


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """What happened to one email, as reported back to the agent."""

    delivered: bool
    detail: str
    recipients: tuple[str, ...]
    dry_run: bool = False


@runtime_checkable
class EmailTransport(Protocol):
    """Anything that can take a validated email and try to deliver it."""

    dry_run: bool

    async def send(self, email: OutgoingEmail) -> DeliveryReceipt: ...


@dataclass(slots=True)
class DryRunTransport:
    """Records emails instead of sending them. The safe default."""

    dry_run: bool = True
    sent: list[OutgoingEmail] = field(default_factory=list)

    async def send(self, email: OutgoingEmail) -> DeliveryReceipt:
        self.sent.append(email)
        logger.info(
            "dry-run email not sent",
            extra={"to": list(email.to), "subject": email.subject},
        )
        return DeliveryReceipt(
            delivered=False,
            dry_run=True,
            recipients=email.recipients,
            detail=(
                "DRY RUN - nothing was sent. The server is running with EMAIL_DRY_RUN=true. "
                "This is exactly what would have been delivered:\n\n" + email.preview()
            ),
        )


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    use_starttls: bool = True
    use_ssl: bool = False
    timeout_s: float = 30.0


@dataclass(slots=True)
class SmtpTransport:
    """Delivers over SMTP, with the blocking work pushed to a worker thread."""

    config: SmtpConfig
    dry_run: bool = False

    async def send(self, email: OutgoingEmail) -> DeliveryReceipt:
        try:
            await asyncio.to_thread(self._send_blocking, email)
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailDeliveryError(
                "The SMTP server rejected the configured credentials. Check SMTP_USERNAME "
                f"and SMTP_PASSWORD. ({exc.smtp_code})"
            ) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            refused = ", ".join(sorted(exc.recipients))
            raise EmailDeliveryError(f"The server refused these recipients: {refused}.") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError(
                f"Could not deliver the email: {type(exc).__name__}: {exc}"
            ) from exc

        logger.info(
            "email sent", extra={"to": list(email.to), "subject": email.subject}
        )
        return DeliveryReceipt(
            delivered=True,
            dry_run=False,
            recipients=email.recipients,
            detail=f"Sent to {', '.join(email.recipients)} with subject {email.subject!r}.",
        )

    def _send_blocking(self, email: OutgoingEmail) -> None:
        config = self.config
        context = ssl.create_default_context()
        if config.use_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                config.host, config.port, timeout=config.timeout_s, context=context
            )
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=config.timeout_s)
        with server:
            server.ehlo()
            if config.use_starttls and not config.use_ssl:
                server.starttls(context=context)
                server.ehlo()
            if config.username:
                server.login(config.username, config.password)
            server.send_message(email.to_mime())


@dataclass(slots=True)
class RecordingTransport:
    """Test double: remembers every email and never touches the network."""

    dry_run: bool = False
    sent: list[OutgoingEmail] = field(default_factory=list)
    fail_with: str | None = None

    async def send(self, email: OutgoingEmail) -> DeliveryReceipt:
        if self.fail_with:
            raise EmailDeliveryError(self.fail_with)
        self.sent.append(email)
        return DeliveryReceipt(
            delivered=True,
            dry_run=False,
            recipients=email.recipients,
            detail=f"Sent to {', '.join(email.recipients)}.",
        )


__all__ = [
    "DeliveryReceipt",
    "DryRunTransport",
    "EmailDeliveryError",
    "EmailTransport",
    "RecordingTransport",
    "SmtpConfig",
    "SmtpTransport",
]
