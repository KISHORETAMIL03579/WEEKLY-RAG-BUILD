"""stdio MCP server that reports which environment variables it can see (test double)."""

from __future__ import annotations

import os

from backend.mcp.server_base import McpServer, ToolDefinition


def _env(arguments, meta):
    return {"found": True, "env_names": sorted(os.environ), "pid": os.getpid()}


def build_server() -> McpServer:
    server = McpServer("env-probe", "0.0.1")
    server.add_tool(
        ToolDefinition(
            name="env_names",
            title="Environment names",
            description="Lists environment variable names visible to this process (test double).",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_env,
            roles=["evidence"],
        )
    )
    return server


if __name__ == "__main__":
    build_server().serve_stdio()
