"""Deprecated entry name: the stdio MCP server lives in ``mcp_controller``.

``projectwhy-mcp`` is wired to ``projectwhy.mcp_controller:main`` in ``pyproject.toml``.
This module remains so imports like ``projectwhy.mcp_server`` keep working.
"""

from projectwhy.mcp_controller import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
