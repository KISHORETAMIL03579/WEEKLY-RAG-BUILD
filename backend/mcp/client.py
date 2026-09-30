"""MCP client with a stdio (subprocess) and an in-process transport.

Both transports exchange the same JSON-RPC frames and log every one of them
(``wire_log``), so the raw ``initialize -> tools/list -> tools/call`` exchange
can be captured and inspected regardless of how the server is hosted.
"""

from __future__ import annotations

import itertools
import json
import logging
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from backend.mcp import protocol
from backend.mcp.protocol import McpError, McpTransportError

logger = logging.getLogger("ask_my_docs.mcp.client")

WIRE_LOG_LIMIT = 400
DEFAULT_TIMEOUT = 30.0


class _Transport:
    def send_request(self, message: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        raise NotImplementedError

    def send_notification(self, message: Dict[str, Any]) -> None:
        raise NotImplementedError

    def alive(self) -> bool:
        return True

    def close(self) -> None:
        return None


class InProcessTransport(_Transport):
    """Calls ``server.handle_message`` directly (same frames, no subprocess)."""

    def __init__(self, server: Any):
        self._server = server

    def send_request(self, message: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        # Round-trip through JSON so the server sees exactly what a pipe would carry.
        response = self._server.handle_message(json.loads(protocol.encode(message)))
        if response is None:
            raise McpTransportError("Server returned no response to a request")
        return json.loads(protocol.encode(response))

    def send_notification(self, message: Dict[str, Any]) -> None:
        self._server.handle_message(json.loads(protocol.encode(message)))


class StdioTransport(_Transport):
    """Spawns the server as a subprocess and speaks newline-delimited JSON-RPC."""

    def __init__(self, command: List[str], env: Dict[str, str], cwd: str):
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
            cwd=cwd,
        )
        self._write_lock = threading.Lock()
        self._pending: Dict[Any, Dict[str, Any]] = {}
        self._events: Dict[Any, threading.Event] = {}
        self._state_lock = threading.Lock()
        self._command = command
        threading.Thread(target=self._read_stdout, daemon=True, name="mcp-stdout").start()
        threading.Thread(target=self._drain_stderr, daemon=True, name="mcp-stderr").start()

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("MCP server wrote a non-JSON line to stdout: %.120s", text)
                continue
            msg_id = message.get("id")
            with self._state_lock:
                event = self._events.get(msg_id)
                if event is not None:
                    self._pending[msg_id] = message
            if event is not None:
                event.set()
        # stdout closed: wake every waiter so callers fail fast instead of timing out
        with self._state_lock:
            waiters = list(self._events.values())
        for event in waiters:
            event.set()

    def _drain_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            if line.strip():
                logger.debug("mcp-server stderr: %s", line.rstrip())

    def alive(self) -> bool:
        return self._process.poll() is None

    def _write(self, message: Dict[str, Any]) -> None:
        if not self.alive() or self._process.stdin is None:
            raise McpTransportError("MCP server process is not running")
        with self._write_lock:
            try:
                self._process.stdin.write(protocol.encode(message) + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise McpTransportError(f"Could not write to MCP server: {exc}") from exc

    def send_request(self, message: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        msg_id = message["id"]
        event = threading.Event()
        with self._state_lock:
            self._events[msg_id] = event
        try:
            self._write(message)
            if not event.wait(timeout):
                raise McpTransportError(f"MCP request timed out after {timeout:.1f}s")
            with self._state_lock:
                response = self._pending.pop(msg_id, None)
            if response is None:
                raise McpTransportError("MCP server closed the connection")
            return response
        finally:
            with self._state_lock:
                self._events.pop(msg_id, None)
                self._pending.pop(msg_id, None)

    def send_notification(self, message: Dict[str, Any]) -> None:
        self._write(message)

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
                self._process.wait(timeout=2)
            except Exception:
                self._process.kill()


class McpClient:
    """One connection to one MCP server."""

    def __init__(self, name: str, transport_factory: Any):
        self.name = name
        self._factory = transport_factory
        self._transport: Optional[_Transport] = None
        self._ids = itertools.count(1)
        self._lock = threading.RLock()
        self._wire: Deque[Dict[str, Any]] = deque(maxlen=WIRE_LOG_LIMIT)
        self.server_info: Dict[str, Any] = {}
        self.protocol_version: Optional[str] = None
        self.capabilities: Dict[str, Any] = {}
        self.instructions: Optional[str] = None

    # -- wire log ----------------------------------------------------------

    def _log(self, direction: str, message: Dict[str, Any]) -> None:
        self._wire.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "server": self.name,
                "direction": direction,
                "message": message,
            }
        )

    def wire_log(self) -> List[Dict[str, Any]]:
        return list(self._wire)

    # -- lifecycle ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._transport is not None and self._transport.alive()

    def connect(self) -> None:
        """(Re)open the transport and run the ``initialize`` handshake."""
        with self._lock:
            self.close()
            self._transport = self._factory()
            result = self._request(
                "initialize",
                {
                    "protocolVersion": protocol.PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "ask-my-docs-policy-host", "version": "1.0.0"},
                },
                DEFAULT_TIMEOUT,
            )
            self.protocol_version = result.get("protocolVersion")
            self.capabilities = result.get("capabilities", {})
            self.server_info = result.get("serverInfo", {})
            self.instructions = result.get("instructions")
            self._notify("notifications/initialized")

    def close(self) -> None:
        with self._lock:
            if self._transport is not None:
                self._transport.close()
            self._transport = None

    # -- requests ----------------------------------------------------------

    def _request(self, method: str, params: Optional[Dict[str, Any]], timeout: float) -> Dict[str, Any]:
        if self._transport is None:
            raise McpTransportError("MCP client is not connected")
        message = protocol.request(next(self._ids), method, params)
        self._log("client->server", message)
        response = self._transport.send_request(message, timeout)
        self._log("server->client", response)
        if "error" in response:
            body = response["error"]
            raise McpError(body.get("code", protocol.INTERNAL_ERROR), body.get("message", ""), body.get("data"))
        return response.get("result", {})

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        if self._transport is None:
            raise McpTransportError("MCP client is not connected")
        message = protocol.notification(method, params)
        self._log("client->server", message)
        self._transport.send_notification(message)

    def list_tools(self, timeout: float = DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            params = {"cursor": cursor} if cursor else None
            result = self._request("tools/list", params, timeout)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        meta: Optional[Dict[str, Any]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"name": name, "arguments": arguments}
        if meta:
            params["_meta"] = meta
        started = time.perf_counter()
        result = self._request("tools/call", params, timeout)
        result.setdefault(
            "_client_latency_ms", round((time.perf_counter() - started) * 1000, 3)
        )
        return result
