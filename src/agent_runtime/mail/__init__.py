"""The email domain: what a message is, the rules it must pass, and how it ships.

Nothing in here knows about agents, tools or language models — which is
what lets the sending rules be tested (and trusted) on their own.
"""

from agent_runtime.mail.message import (
    EmailPolicy,
    EmailPolicyError,
    OutgoingEmail,
    normalize_address,
)
from agent_runtime.mail.transport import (
    DeliveryReceipt,
    DryRunTransport,
    EmailDeliveryError,
    EmailTransport,
    RecordingTransport,
    SmtpConfig,
    SmtpTransport,
)

__all__ = [
    "DeliveryReceipt",
    "DryRunTransport",
    "EmailDeliveryError",
    "EmailPolicy",
    "EmailPolicyError",
    "EmailTransport",
    "OutgoingEmail",
    "RecordingTransport",
    "SmtpConfig",
    "SmtpTransport",
    "normalize_address",
]
