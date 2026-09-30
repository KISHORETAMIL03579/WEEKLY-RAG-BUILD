"""Server one: policy search over the user's uploaded documents.

Tools read only the session's Qdrant chunks (see backend/services/policy_retrieval.py).
The host supplies the session through the request ``_meta`` (``session_id``); the
model never chooses or sees it. Tool descriptions are written as prompts: what the
tool does, when to call it, when *not* to, and how to read an empty or failed result.

Run standalone over stdio with ``python -m backend.mcp.servers.policy_server``.
Standalone mode needs the same ``.env``/Qdrant access as the app.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from backend.mcp.server_base import McpServer, ToolDefinition, ToolFailure
from backend.services import policy_retrieval as retrieval

# "opaque" reproduces the pre-Week-9 behaviour (one unexplained error string) so the
# before/after transcript in docs/training/week9 can be regenerated. Default: recoverable.
ERROR_STYLE_ENV = "POLICY_MCP_ERROR_STYLE"


def _fail(error: retrieval.PolicyToolError) -> ToolFailure:
    if os.environ.get(ERROR_STYLE_ENV, "recoverable") == "opaque":
        return ToolFailure("ERROR", "Error: not found")
    payload = error.to_error()
    return ToolFailure(
        payload["code"],
        payload["message"],
        retryable=payload["retryable"],
        hint=payload.get("hint"),
    )


def _context(meta: Dict[str, Any]) -> retrieval.PolicyContext | None:
    return retrieval.PolicyContext.from_meta(meta)


def _get_employee_record(arguments: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return retrieval.find_employee_record(_context(meta), arguments["employee_id"])
    except retrieval.PolicyToolError as error:
        raise _fail(error) from error


def _search_handbook(arguments: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return retrieval.search_policy(
            _context(meta), arguments["query"], arguments.get("top_k", 5)
        )
    except retrieval.PolicyToolError as error:
        raise _fail(error) from error


def _get_jurisdiction_rules(arguments: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return retrieval.find_jurisdiction_rules(
            _context(meta), arguments["jurisdiction"], arguments["policy_category"]
        )
    except retrieval.PolicyToolError as error:
        raise _fail(error) from error


def build_server() -> McpServer:
    server = McpServer(
        "policy-search",
        "1.0.0",
        instructions=(
            "Read-only tools over the user's uploaded HR documents. Results are quotations "
            "from those documents; an empty or error result means the documents do not say."
        ),
    )
    server.add_tool(
        ToolDefinition(
            name="get_employee_record",
            title="Get employee record",
            description=(
                "Look up ONE employee's HR record (employment status, tenure in months, "
                "jurisdiction, duty station, separation reason, leave balance) exactly as "
                "stored in the uploaded employee-records document. Call this FIRST for any "
                "question about a specific employee: probation versus confirmed status, "
                "tenure and jurisdiction decide which rule applies and which jurisdiction to "
                "pass to other tools. Do NOT use it to find policy wording (use "
                "search_handbook). If the id is unknown it returns an error saying so; never "
                "guess an employee's details."
            ),
            input_schema={
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
            },
            handler=_get_employee_record,
            roles=["employee_lookup"],
        )
    )
    server.add_tool(
        ToolDefinition(
            name="search_handbook",
            title="Search policy documents",
            description=(
                "Search the uploaded policy document(s) for passages that state a rule, "
                "entitlement, notice period, eligibility condition or severance formula. "
                "Pass a short topic query (for example 'resignation notice probation'), not "
                "an employee id. Returns ranked passages with filename, page, section label "
                "and score; cite the section label in your answer. Do NOT use it for "
                "employee facts (use get_employee_record) or for rules specific to one "
                "country (use get_jurisdiction_rules). An empty result means the documents "
                "do not cover the topic: say so instead of inventing a rule."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Topic to look up, e.g. 'annual leave carry forward'.",
                        "minLength": 2,
                        "maxLength": 300,
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "How many passages to return.",
                        "minimum": 1,
                        "maximum": retrieval.MAX_TOP_K,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=_search_handbook,
            roles=["evidence"],
        )
    )
    server.add_tool(
        ToolDefinition(
            name="get_jurisdiction_rules",
            title="Get jurisdiction-specific rules",
            description=(
                "Retrieve passages from the uploaded documents that state rules specific to "
                "ONE jurisdiction for ONE policy category (local law, statutory minimums, "
                "public holidays, duty-station rules). Use it only when the question is about "
                "such local rules, and take `jurisdiction` from the employee's record "
                "(field 'jurisdiction'), never from a name or a guess. Do NOT use it for "
                "general handbook rules (use search_handbook) or employee facts (use "
                "get_employee_record). If no passage mentions the jurisdiction the error says "
                "so; then rely on search_handbook or state the gap."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "jurisdiction": {
                        "type": "string",
                        "description": "The jurisdiction from the employee record.",
                        "enum": retrieval.jurisdictions(),
                    },
                    "policy_category": {
                        "type": "string",
                        "description": "The one policy area to retrieve.",
                        "enum": retrieval.policy_categories(),
                    },
                },
                "required": ["jurisdiction", "policy_category"],
                "additionalProperties": False,
            },
            handler=_get_jurisdiction_rules,
            roles=["evidence"],
        )
    )
    return server


if __name__ == "__main__":
    build_server().serve_stdio()
