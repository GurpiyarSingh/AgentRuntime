"""A universal MCP client that gives any MCP server's tools to the agent.

Connects any Model Context Protocol server, local (stdio) or remote
(streamable HTTP, SSE).

- `config`: server configurations and the JSON file they live in
- `client`: one connection, and the adapter from MCP tools to runtime tools
- `manager`: keeps every enabled server connected
"""

from agent_runtime.mcp_client.client import McpTool, qualified_name
from agent_runtime.mcp_client.config import (
    MASK,
    McpConfigError,
    McpConfigStore,
    McpServerConfig,
    parse_import,
)
from agent_runtime.mcp_client.manager import McpManager, ServerState, TestResult

__all__ = [
    "MASK",
    "McpConfigError",
    "McpConfigStore",
    "McpManager",
    "McpServerConfig",
    "McpTool",
    "ServerState",
    "TestResult",
    "parse_import",
    "qualified_name",
]
