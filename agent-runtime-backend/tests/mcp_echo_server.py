"""A tiny MCP server for tests, built with the SDK's FastMCP.

python tests/mcp_echo_server.py            serve over stdio
python tests/mcp_echo_server.py http PORT  serve streamable HTTP on 127.0.0.1:PORT/mcp
"""

from __future__ import annotations

import base64
import sys

from mcp.server.fastmcp import FastMCP, Image

# A 1x1 transparent PNG.
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

server = FastMCP("echo-test", port=int(sys.argv[2]) if len(sys.argv) > 2 else 8000)


@server.tool()
def echo(text: str, times: int = 1) -> str:
    """Repeat the text."""
    return " ".join([text] * times)


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@server.tool()
def pixel() -> Image:
    """Return a tiny PNG image."""
    return Image(data=PIXEL, format="png")


@server.tool()
def fail(reason: str) -> str:
    """Always fails, with the given reason."""
    raise ValueError(reason)


if __name__ == "__main__":
    print("echo-test starting", file=sys.stderr)  # noqa: T201 - checked by the stderr test
    if len(sys.argv) > 1 and sys.argv[1] == "http":
        server.run(transport="streamable-http")
    else:
        server.run()
