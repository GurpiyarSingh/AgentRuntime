"""Shared test setup."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_mcp_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point MCP_CONFIG_PATH at a fresh file for every test.

    Its default (`data/mcp.json`) is relative to the working directory, so
    without this a test run would read, and could rewrite, the developer's
    real MCP servers.
    """
    path: Path = tmp_path_factory.mktemp("mcp") / "mcp.json"
    monkeypatch.setenv("MCP_CONFIG_PATH", str(path))
