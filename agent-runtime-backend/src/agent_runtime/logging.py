"""Structured logging setup.

Two modes:
- human-readable (default): good for a local terminal.
- JSON (``LOG_JSON=true``): one object per line, good for log aggregators.

Both modes carry a ``run_id`` / ``step`` when a log call passes them in
``extra``, which is how the agent loop makes its reasoning traceable.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger, message, extras."""

    def format(self, record: logging.LogRecord) -> str:
        """Render `record`, including anything passed via ``extra``, as JSON."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            (key, value)
            for key, value in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_")
        )
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class HumanFormatter(logging.Formatter):
    """A plain text line, with any ``extra`` fields appended as key=value."""

    def format(self, record: logging.LogRecord) -> str:
        """Render `record` as text followed by its extras."""
        base = super().format(record)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_")
        }
        if extras:
            base += " | " + " ".join(f"{k}={v}" for k, v in extras.items())
        return base


def configure_logging(
    level: str = "INFO", *, json_output: bool = False, stream: TextIO | None = None
) -> None:
    """Install a single handler on the root logger. Idempotent.

    Args:
        level: Minimum level to emit.
        json_output: One JSON object per line instead of human-readable text.
        stream: Where to write; stdout by default. The CLI passes stderr so
            that stdout carries only the agent's answer.
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(stream=stream or sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(HumanFormatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    root.addHandler(handler)

    # Quiet down noisy third-party loggers unless we're debugging.
    if level.upper() != "DEBUG":
        for noisy in ("httpx", "httpcore", "openai"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
