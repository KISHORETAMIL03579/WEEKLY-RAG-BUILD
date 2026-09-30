"""Minimal MCP server: initialize, ping, tools/list, tools/call over JSON-RPC.

A server exposes *capabilities* (tools); it never calls a model. The host runs
the model and decides which tool to invoke (see docs/training/week9).
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from backend.mcp import protocol
from backend.mcp.schema import validate_arguments

logger = logging.getLogger("ask_my_docs.mcp.server")

ToolHandler = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


class ToolFailure(Exception):
    """A tool-execution error the *model* should see (returned with isError=true)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        hint: Optional[str] = None,
    ):
        super().__init__(message)
        self.payload: Dict[str, Any] = {
            "code": code,
            "message": message,
            "retryable": retryable,
        }
        if hint:
            self.payload["hint"] = hint


@dataclass
class ToolDefinition:
    name: str
    title: str
    description: str
    input_schema: Dict[str, Any]
    handler: ToolHandler
    roles: List[str] = field(default_factory=list)

    def listing(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
            "_meta": {"roles": self.roles},
        }


class McpServer:
    def __init__(self, name: str, version: str, instructions: str = ""):
        self.name = name
        self.version = version
        self.instructions = instructions
        self._tools: Dict[str, ToolDefinition] = {}
        self._initialized = False

    def add_tool(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    # -- JSON-RPC dispatch -------------------------------------------------

    def handle_message(self, message: Any) -> Optional[Dict[str, Any]]:
        """Return the response for a request, or ``None`` for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return protocol.error(None, protocol.INVALID_REQUEST, "Not a JSON-RPC 2.0 message")
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}
        if method is None:
            return None  # a response addressed to us; these servers never send requests
        if msg_id is None:
            if method == "notifications/initialized":
                self._initialized = True
            return None
        try:
            if method == "initialize":
                return protocol.result(msg_id, self._initialize(params))
            if method == "ping":
                return protocol.result(msg_id, {})
            if method == "tools/list":
                listing = [tool.listing() for tool in self._tools.values()]
                return protocol.result(msg_id, {"tools": listing})
            if method == "tools/call":
                return self._call_tool(msg_id, params)
            return protocol.error(
                msg_id, protocol.METHOD_NOT_FOUND, f"Method not found: {method}"
            )
        except Exception as exc:  # a bug must not kill the connection
            logger.exception("Unhandled error in %s", method)
            return protocol.error(
                msg_id, protocol.INTERNAL_ERROR, f"Internal error: {type(exc).__name__}"
            )

    def _initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        requested = params.get("protocolVersion")
        version = (
            requested
            if requested in protocol.SUPPORTED_PROTOCOL_VERSIONS
            else protocol.PROTOCOL_VERSION
        )
        payload: Dict[str, Any] = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
        }
        if self.instructions:
            payload["instructions"] = self.instructions
        return payload

    def _call_tool(self, msg_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return protocol.error(msg_id, protocol.INVALID_PARAMS, f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        meta = params.get("_meta") or {}
        try:
            validate_arguments(tool.input_schema, arguments)
            payload = tool.handler(arguments, meta)
            return protocol.result(msg_id, _tool_result(payload, is_error=False))
        except ToolFailure as failure:
            body = {"error": failure.payload}
            return protocol.result(msg_id, _tool_result(body, is_error=True))
        except (TypeError, ValueError) as exc:
            failure_payload = {
                "code": "INVALID_ARGUMENTS",
                "message": str(exc),
                "retryable": False,
            }
            body = {"error": failure_payload}
            return protocol.result(msg_id, _tool_result(body, is_error=True))

    # -- stdio loop --------------------------------------------------------

    def serve_stdio(self) -> None:
        """Read newline-delimited JSON-RPC from stdin, write responses to stdout.

        stdout carries protocol frames only; all logging goes to stderr.
        """
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                response: Optional[Dict[str, Any]] = protocol.error(
                    None, protocol.PARSE_ERROR, "Invalid JSON"
                )
            else:
                response = self.handle_message(message)
            if response is not None:
                sys.stdout.write(protocol.encode(response) + "\n")
                sys.stdout.flush()


def _tool_result(payload: Dict[str, Any], *, is_error: bool) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "structuredContent": payload,
        "isError": is_error,
    }
