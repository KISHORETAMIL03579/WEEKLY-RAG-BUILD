"""Model Context Protocol (MCP) host and reference servers.

The policy agent never imports a tool implementation. It asks the
:mod:`backend.mcp.registry` which tools exist (``tools/list``) and calls them by
name (``tools/call``); servers are added or removed in ``config/mcp_servers.json``.
"""
