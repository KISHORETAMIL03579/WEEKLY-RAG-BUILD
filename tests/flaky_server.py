"""A deliberately unreliable MCP server used to prove retry accounting.

``STATE["fail_times"]`` calls fail first. ``STATE["mode"]`` picks the failure shape:
``tool`` -> a retryable tool error; ``rpc`` -> an internal JSON-RPC error (server bug);
``permanent`` -> a non-retryable tool error that must never be retried.
"""

from __future__ import annotations

from backend.mcp.server_base import McpServer, ToolDefinition, ToolFailure

STATE = {"fail_times": 0, "calls": 0, "mode": "tool"}


def reset(fail_times: int = 0, mode: str = "tool") -> None:
    STATE.update(fail_times=fail_times, calls=0, mode=mode)


def _handler(arguments, meta):
    STATE["calls"] += 1
    if STATE["calls"] <= STATE["fail_times"]:
        if STATE["mode"] == "rpc":
            raise RuntimeError("boom")
        if STATE["mode"] == "permanent":
            raise ToolFailure("NOT_ALLOWED", "permanently refused", retryable=False)
        raise ToolFailure("UPSTREAM_DOWN", "upstream is down", retryable=True)
    return {"found": True, "value": 42}


def build_server() -> McpServer:
    server = McpServer("flaky", "0.0.1")
    server.add_tool(
        ToolDefinition(
            name="flaky_lookup",
            title="Flaky lookup",
            description="Returns 42 after zero or more failures (test double).",
            input_schema={
                "type": "object",
                "properties": {"employee_id": {"type": "string"}},
                "additionalProperties": False,
            },
            handler=_handler,
            roles=["employee_lookup", "evidence"],
        )
    )
    return server
