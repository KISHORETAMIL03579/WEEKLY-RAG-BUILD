"""MCP tool registry: config-driven discovery, validated routing, retries, audit.

The agent talks only to this class. Which servers exist comes from
``config/mcp_servers.json``; which tools exist comes from each server's
``tools/list``. Adding a server is therefore a config change and no agent code
changes (see scripts/mcp_prove_config_only_swap.py).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import (
    BASE_DIR,
    MCP_AUDIT_LOG_PATH,
    MCP_CONFIG_PATH,
    MCP_FORCE_TRANSPORT,
    MCP_TOOL_MAX_RETRIES,
    MCP_TOOL_RETRY_BACKOFF_SECONDS,
    MCP_TOOL_TIMEOUT_SECONDS,
)
from backend.mcp.client import InProcessTransport, McpClient, StdioTransport
from backend.mcp.protocol import McpError, McpTransportError
from backend.mcp.schema import normalize_arguments, validate_arguments

logger = logging.getLogger("ask_my_docs.mcp.registry")

# A third-party server gets no secrets: only what a Python process needs to start.
_CHILD_ENV_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "LANG",
    "PYTHONIOENCODING",
)


class UnknownToolError(KeyError):
    """The requested tool was not discovered on any connected server."""


@dataclass
class ToolSpec:
    name: str
    title: str
    description: str
    input_schema: Dict[str, Any]
    server: str
    roles: List[str] = field(default_factory=list)

    def as_function_definition(self) -> Dict[str, Any]:
        """OpenAI/Groq function-calling shape built from the discovered schema."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        }


@dataclass
class ToolOutcome:
    """Everything observed about one tool call, including every attempt."""

    name: str
    server: str
    arguments: Dict[str, Any]
    observation: Dict[str, Any]
    is_error: bool
    error: Optional[Dict[str, Any]]
    attempts: int
    attempt_log: List[Dict[str, Any]]
    latency_ms: float

    @property
    def retries(self) -> int:
        return max(0, self.attempts - 1)


class McpToolRegistry:
    def __init__(self, config_path: Path = MCP_CONFIG_PATH, force_transport: str = MCP_FORCE_TRANSPORT):
        self.config_path = Path(config_path)
        self.force_transport = force_transport
        self._clients: Dict[str, McpClient] = {}
        self._status: Dict[str, Dict[str, Any]] = {}
        self._tools: Dict[str, ToolSpec] = {}
        self._lock = threading.RLock()
        self._connected = False
        self._audit_lock = threading.Lock()

    # -- configuration -----------------------------------------------------

    def _load_config(self) -> List[Dict[str, Any]]:
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        servers = payload.get("servers")
        if not isinstance(servers, list) or not servers:
            raise ValueError(f"{self.config_path} must define a non-empty 'servers' list")
        names = [entry.get("name") for entry in servers]
        if len(set(names)) != len(names) or not all(names):
            raise ValueError("MCP server names must be unique and non-empty")
        return servers

    def _transport_factory(self, entry: Dict[str, Any]):
        module = entry["module"]
        transport = self.force_transport or entry.get("transport", "stdio")
        if transport == "inprocess":

            def build_inprocess() -> InProcessTransport:
                return InProcessTransport(importlib.import_module(module).build_server())

            return build_inprocess

        def build_stdio() -> StdioTransport:
            env = {key: os.environ[key] for key in _CHILD_ENV_ALLOWLIST if key in os.environ}
            for key, value in entry.get("env", {}).items():
                candidate = Path(value)
                env[key] = str(BASE_DIR / candidate) if not candidate.is_absolute() and "/" in value else value
            command = [sys.executable, "-m", module]
            return StdioTransport(command, env, str(BASE_DIR))

        return build_stdio

    # -- discovery ---------------------------------------------------------

    def connect(self) -> None:
        """Connect to every configured server and run ``tools/list`` on each."""
        with self._lock:
            for client in self._clients.values():
                client.close()
            self._clients.clear()
            self._status.clear()
            self._tools.clear()
            for entry in self._load_config():
                name = entry["name"]
                client = McpClient(name, self._transport_factory(entry))
                self._clients[name] = client
                status: Dict[str, Any] = {
                    "name": name,
                    "transport": self.force_transport or entry.get("transport", "stdio"),
                    "module": entry["module"],
                    "status": "error",
                    "tools": [],
                }
                try:
                    client.connect()
                    listed = client.list_tools()
                    status.update(
                        status="connected",
                        protocol_version=client.protocol_version,
                        server_info=client.server_info,
                        capabilities=client.capabilities,
                    )
                    for raw in listed:
                        spec = ToolSpec(
                            name=raw["name"],
                            title=raw.get("title", raw["name"]),
                            description=raw.get("description", ""),
                            input_schema=raw.get("inputSchema", {"type": "object"}),
                            server=name,
                            roles=list(raw.get("_meta", {}).get("roles", [])),
                        )
                        if spec.name in self._tools:
                            logger.error(
                                "Tool %r from server %r duplicates one from %r; ignoring it",
                                spec.name,
                                name,
                                self._tools[spec.name].server,
                            )
                            continue
                        self._tools[spec.name] = spec
                        status["tools"].append(spec.name)
                except Exception as exc:
                    status["error"] = f"{type(exc).__name__}: {exc}"
                    logger.error("MCP server %r failed discovery: %s", name, exc)
                self._status[name] = status
            self._connected = True

    def ensure_connected(self) -> None:
        with self._lock:
            if not self._connected:
                self.connect()

    def close(self) -> None:
        with self._lock:
            for client in self._clients.values():
                client.close()
            self._connected = False

    def discovery_report(self) -> Dict[str, Any]:
        self.ensure_connected()
        servers = []
        for name, status in self._status.items():
            listing = [
                {
                    "name": spec.name,
                    "title": spec.title,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                    "roles": spec.roles,
                }
                for spec in self._tools.values()
                if spec.server == name
            ]
            servers.append({**status, "tool_count": len(listing), "tool_details": listing})
        return {
            "config_path": str(self.config_path),
            "server_count": len(servers),
            "tool_count": len(self._tools),
            "tool_names": list(self._tools),
            "servers": servers,
        }

    def wire_log(self, server: Optional[str] = None) -> List[Dict[str, Any]]:
        frames: List[Dict[str, Any]] = []
        for name, client in self._clients.items():
            if server in (None, name):
                frames.extend(client.wire_log())
        return sorted(frames, key=lambda frame: frame["ts"])

    # -- tool access -------------------------------------------------------

    def list_tools(self) -> List[ToolSpec]:
        self.ensure_connected()
        return list(self._tools.values())

    def tool_definitions(self) -> List[Dict[str, Any]]:
        return [spec.as_function_definition() for spec in self.list_tools()]

    def get_tool(self, name: str) -> ToolSpec:
        self.ensure_connected()
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(name) from None

    def roles_for(self, name: str) -> List[str]:
        spec = self._tools.get(name)
        return list(spec.roles) if spec else []

    def normalize_arguments(self, name: str, arguments: Any) -> Any:
        return normalize_arguments(self.get_tool(name).input_schema, arguments)

    def validate_call(self, name: str, arguments: Any) -> None:
        """Raise ``UnknownToolError``/``TypeError``/``ValueError`` before anything is sent."""
        validate_arguments(self.get_tool(name).input_schema, arguments)

    # -- execution ---------------------------------------------------------

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        context: Optional[Any] = None,
        caller: str = "policy_agent",
        timeout: float = MCP_TOOL_TIMEOUT_SECONDS,
        max_retries: int = MCP_TOOL_MAX_RETRIES,
        backoff: float = MCP_TOOL_RETRY_BACKOFF_SECONDS,
    ) -> ToolOutcome:
        """Call ``name`` with bounded retries; every attempt is recorded.

        Retried: transport failures (timeout, dead process; the connection is
        re-established), JSON-RPC internal errors, and tool results whose error
        payload says ``retryable``. Not retried: unknown tools, invalid
        arguments, "not found" style answers the model must act on itself.
        """
        spec = self.get_tool(name)
        client = self._clients[spec.server]
        meta = context.to_meta() if hasattr(context, "to_meta") else (context or None)
        attempt_log: List[Dict[str, Any]] = []
        started = time.perf_counter()
        observation: Dict[str, Any] = {}
        error: Optional[Dict[str, Any]] = None
        is_error = True
        for attempt in range(1, max(0, max_retries) + 2):
            attempt_started = time.perf_counter()
            retryable = False
            try:
                if not client.connected:
                    client.connect()
                result = client.call_tool(name, arguments, meta=meta, timeout=timeout)
                observation = _observation(result)
                is_error = bool(result.get("isError"))
                error = observation.get("error") if is_error and isinstance(observation, dict) else None
                retryable = bool(is_error and isinstance(error, dict) and error.get("retryable"))
                status = "error" if is_error else "ok"
                detail = error.get("code") if isinstance(error, dict) else None
            except McpError as exc:
                observation = {"error": {"code": f"RPC_{exc.code}", "message": str(exc), "retryable": exc.retryable}}
                is_error, error, retryable = True, observation["error"], exc.retryable
                status, detail = "rpc_error", str(exc)
            except McpTransportError as exc:
                observation = {"error": {"code": "TRANSPORT_ERROR", "message": str(exc), "retryable": True}}
                is_error, error, retryable = True, observation["error"], True
                status, detail = "transport_error", str(exc)
            except Exception as exc:  # a client bug must surface as a tool error, not a crash
                logger.exception("Unexpected MCP client error calling %s", name)
                observation = {"error": {"code": "CLIENT_ERROR", "message": type(exc).__name__, "retryable": False}}
                is_error, error, retryable = True, observation["error"], False
                status, detail = "client_error", type(exc).__name__
            attempt_log.append(
                {
                    "attempt": attempt,
                    "status": status,
                    "detail": detail,
                    "retryable": retryable,
                    "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 3),
                }
            )
            if not retryable or attempt > max_retries:
                break
            delay = backoff * (2 ** (attempt - 1))
            logger.warning(
                "MCP tool %s attempt %d failed (%s); retrying in %.2fs", name, attempt, detail, delay
            )
            time.sleep(delay)
        outcome = ToolOutcome(
            name=name,
            server=spec.server,
            arguments=arguments,
            observation=observation,
            is_error=is_error,
            error=error,
            attempts=len(attempt_log),
            attempt_log=attempt_log,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        self._audit(outcome, caller, meta)
        return outcome

    # -- audit -------------------------------------------------------------

    def _audit(self, outcome: ToolOutcome, caller: str, meta: Optional[Dict[str, Any]]) -> None:
        session_id = (meta or {}).get("session_id")
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "caller": caller,
            "server": outcome.server,
            "tool": outcome.name,
            "employee_id": outcome.arguments.get("employee_id"),
            "session_hash": hashlib.sha256(session_id.encode()).hexdigest()[:16] if session_id else None,
            "attempts": outcome.attempts,
            "is_error": outcome.is_error,
            "error_code": (outcome.error or {}).get("code"),
            "latency_ms": outcome.latency_ms,
        }
        logger.info(
            "mcp tools/call tool=%s server=%s attempts=%d error=%s latency_ms=%.1f",
            outcome.name,
            outcome.server,
            outcome.attempts,
            line["error_code"],
            outcome.latency_ms,
        )
        try:
            with self._audit_lock:
                MCP_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(MCP_AUDIT_LOG_PATH, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Could not write MCP audit line: %s", exc)


def _observation(result: Dict[str, Any]) -> Dict[str, Any]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in result.get("content", []):
        if block.get("type") == "text":
            try:
                parsed = json.loads(block.get("text", ""))
            except json.JSONDecodeError:
                return {"text": block.get("text", "")}
            return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


_registry: Optional[McpToolRegistry] = None
_registry_lock = threading.Lock()


def get_tool_registry() -> McpToolRegistry:
    """Process-wide registry (created lazily; servers connect on first use)."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = McpToolRegistry()
        return _registry


def reset_tool_registry() -> None:
    """Drop the singleton (tests and config reloads)."""
    global _registry
    with _registry_lock:
        if _registry is not None:
            _registry.close()
        _registry = None
