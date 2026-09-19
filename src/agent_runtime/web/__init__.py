"""Static web UI served alongside the API.

The chat client is plain HTML/CSS/JS with no build step and no external
CDN dependencies, so it works offline and is served same-origin — which
is what lets it call `/v1/chat/stream` directly.
"""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"

__all__ = ["STATIC_DIR"]
