# backend/routes/mcp.py — MCP visibility API (Week 9)
#
# Read-only view of what the host discovered (servers, tools, protocol versions) and
# of the raw JSON-RPC frames exchanged, plus a config reload. There is no endpoint to
# call a tool directly: tools are invoked only by the agent and the workflow.
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.errors import DependencyError
from backend.mcp.registry import get_tool_registry, reset_tool_registry

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/status")
def mcp_status():
    """Servers, their ``initialize`` results and every tool from ``tools/list``."""
    try:
        return JSONResponse(content=get_tool_registry().discovery_report())
    except Exception as exc:
        raise DependencyError(f"MCP discovery failed: {type(exc).__name__}") from exc


@router.get("/wire")
def mcp_wire(server: Optional[str] = Query(None), limit: int = Query(60, ge=1, le=400)):
    """Most recent raw JSON-RPC frames (initialize, tools/list, tools/call, ...)."""
    registry = get_tool_registry()
    registry.ensure_connected()
    return JSONResponse(content={"frames": registry.wire_log(server)[-limit:]})


@router.post("/reload")
def mcp_reload():
    """Re-read config/mcp_servers.json and rediscover tools (no restart, no code change)."""
    reset_tool_registry()
    return mcp_status()
