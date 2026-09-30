"""JSON-RPC 2.0 framing and constants for MCP (stdio transport, newline-delimited)."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# JSON-RPC error codes whose retry may succeed (server-side fault, not a bad request).
RETRYABLE_RPC_CODES = frozenset({INTERNAL_ERROR})


class McpError(Exception):
    """The server answered with a JSON-RPC ``error`` object."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_RPC_CODES


class McpTransportError(Exception):
    """The connection failed (timeout, closed pipe, malformed frame)."""

    retryable = True


def request(msg_id: int, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    message: Dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def notification(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    message: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    return message


def result(msg_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": payload}


def error(msg_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": body}


def encode(message: Dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))
