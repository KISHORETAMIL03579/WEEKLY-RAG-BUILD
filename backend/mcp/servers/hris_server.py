"""Server two: HRIS stand-in exposing an employee's grade band and leave balance.

This process is the People Ops system of record as seen from the app. It is
launched as a subprocess with a minimal environment (no API keys) and reads its
records from ``HRIS_DATA_PATH`` (default: the sample extract next to this repo's
data). It calls no model: it exposes capabilities; the host runs the model.

Run standalone over stdio with ``python -m backend.mcp.servers.hris_server``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

from backend.mcp.server_base import McpServer, ToolDefinition, ToolFailure

DEFAULT_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "samples" / "hris_records.json"

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("ask_my_docs.mcp.hris")


def _load_records() -> Dict[str, Dict[str, Any]]:
    path = Path(os.environ.get("HRIS_DATA_PATH", str(DEFAULT_DATA_PATH)))
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {key.upper(): value for key, value in payload["employees"].items()}


def _record(arguments: Dict[str, Any]) -> Dict[str, Any]:
    employee_id = arguments["employee_id"].strip().upper()
    try:
        records = _load_records()
    except (OSError, ValueError, KeyError) as exc:
        logger.error("HRIS data unavailable: %s", exc)
        raise ToolFailure(
            "HRIS_UNAVAILABLE",
            "The HRIS is unavailable right now.",
            retryable=True,
            hint="Retry shortly. Do not estimate a grade band or balance.",
        ) from exc
    record = records.get(employee_id)
    if record is None:
        raise ToolFailure(
            "EMPLOYEE_NOT_FOUND",
            f"The HRIS has no employee {employee_id}.",
            hint="Check the id spelling. This is different from the HRIS being down; do not guess.",
        )
    return record


def _get_grade_band(arguments: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    record = _record(arguments)
    return {
        "found": True,
        "employee_id": arguments["employee_id"].strip().upper(),
        "grade_band": record["grade_band"],
        "source": "hris",
    }


def _get_leave_balance(arguments: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    record = _record(arguments)
    return {
        "found": True,
        "employee_id": arguments["employee_id"].strip().upper(),
        "accrued_leave_days": record["accrued_leave_days"],
        "source": "hris",
    }


_EMPLOYEE_ID_SCHEMA = {
    "type": "object",
    "properties": {
        "employee_id": {
            "type": "string",
            "description": "The employee id exactly as given in the question, e.g. EMP001.",
            "minLength": 2,
            "maxLength": 32,
            "pattern": "^[A-Za-z0-9_-]+$",
        }
    },
    "required": ["employee_id"],
    "additionalProperties": False,
}


def build_server() -> McpServer:
    server = McpServer(
        "hris",
        "1.0.0",
        instructions="Read-only HRIS lookups by employee id: grade band and accrued leave balance.",
    )
    server.add_tool(
        ToolDefinition(
            name="get_grade_band",
            title="Get HRIS grade band",
            description=(
                "Return ONE employee's salary grade band (for example G7) from the HRIS "
                "system of record. Use it when the question asks about grade, band or "
                "seniority level. Do NOT use it for leave or policy wording. If the employee "
                "does not exist the error says so, which is different from the HRIS being "
                "down (retryable): never guess a band."
            ),
            input_schema=_EMPLOYEE_ID_SCHEMA,
            handler=_get_grade_band,
            roles=["employee_lookup", "evidence"],
        )
    )
    server.add_tool(
        ToolDefinition(
            name="get_leave_balance",
            title="Get HRIS leave balance",
            description=(
                "Return ONE employee's accrued, unused annual leave in days from the HRIS "
                "system of record. Use it for 'how many days does this person have left'. "
                "It is a balance, not the entitlement rule: use search_handbook for what the "
                "policy grants. If the employee does not exist the error says so; never "
                "estimate a balance."
            ),
            input_schema=_EMPLOYEE_ID_SCHEMA,
            handler=_get_leave_balance,
            roles=["employee_lookup", "evidence"],
        )
    )
    return server


if __name__ == "__main__":
    build_server().serve_stdio()
