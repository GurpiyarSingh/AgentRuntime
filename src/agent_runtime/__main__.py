"""Entry point: `python -m agent_runtime` or the `agent-runtime` console script.

Runs the uvicorn server. For an interactive terminal REPL instead, use
`agent_runtime.cli`.
"""

from __future__ import annotations

import uvicorn

from agent_runtime.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "agent_runtime.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
