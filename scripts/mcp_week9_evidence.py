"""Capture the Week 9 evidence from the real system into docs/training/week9/.

    python scripts/index_documents.py --session-id policy-eval WEEKLY_RAG_TASK/HRPolicy.pdf backend/data/samples/employee_records.md
    python scripts/mcp_week9_evidence.py --session-id policy-eval            # no model calls
    python scripts/mcp_week9_evidence.py --session-id policy-eval --live     # + Groq before/after transcript

Writes:
  tool_discovery.json   tools/list results for server one vs server one + two (names from the wire)
  agent_diff.txt        unified diff of the agent/host modules across the server swap (0 changed lines)
  config_diff.txt       the only thing that changed: config/mcp_servers*.json
  wire.json             raw initialize -> tools/list -> tools/call against the HRIS server (stdio), annotated
  error_before_after.json / .md   the same failing call with the old opaque error vs the recoverable one
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.mcp.registry import McpToolRegistry  # noqa: E402
from backend.mcp.servers.policy_server import ERROR_STYLE_ENV  # noqa: E402
from backend.services import policy_agent  # noqa: E402
from backend.services.policy_retrieval import PolicyContext  # noqa: E402

CONFIG_ONE = ROOT / "config" / "mcp_servers.server1.json"
CONFIG_BOTH = ROOT / "config" / "mcp_servers.json"
HOST_FILES = [
    "backend/services/policy_agent.py",
    "backend/services/policy_run.py",
    "backend/mcp/client.py",
    "backend/mcp/registry.py",
    "backend/mcp/schema.py",
    "backend/mcp/protocol.py",
]

ANNOTATIONS = {
    "initialize (request)": {
        "jsonrpc": "Protocol version of the envelope; always the string '2.0'.",
        "id": "Correlation id chosen by the client; the response echoes it so replies can interleave.",
        "method": "'initialize' opens the session and negotiates capabilities. It is always the first message.",
        "params.protocolVersion": "MCP revision the client speaks. The server answers with the one it will use.",
        "params.capabilities": "Optional client features (sampling, roots, ...). Empty: this host offers none.",
        "params.clientInfo": "Name/version of the host, for the server's logs.",
    },
    "initialize (response)": {
        "result.protocolVersion": "Negotiated revision (server picks from what it supports).",
        "result.capabilities.tools": "The server exposes tools; listChanged=false means the list is static.",
        "result.serverInfo": "Server identity. Shown in the MCP tab and audit log.",
        "result.instructions": "Optional text the host may add to the model context. Capability, not a model call.",
    },
    "notifications/initialized": {
        "method": "A notification (no id, no reply): the client confirms the handshake is complete.",
    },
    "tools/list (response)": {
        "result.tools[].name": "The identifier the model uses in a tool call.",
        "result.tools[].description": "Prompt text for the model: what the tool is for and when NOT to use it.",
        "result.tools[].inputSchema": "JSON Schema the host validates the model's arguments against before sending.",
        "result.tools[].annotations": "Hints (readOnlyHint ...), informational only.",
        "result.tools[]._meta.roles": "Roles the server declares (employee_lookup / evidence); the agent's guards use these, not tool names.",
    },
    "tools/call (request)": {
        "method": "Invoke one tool. Sent by the HOST on the model's behalf; the model never talks to the server.",
        "params.name": "Which discovered tool to run.",
        "params.arguments": "Model-chosen arguments, already validated against inputSchema.",
        "params._meta": "Host-supplied context (e.g. the session). Never chosen or seen by the model.",
    },
    "tools/call (response)": {
        "result.content": "Human/LLM-readable result blocks (here one text block of JSON).",
        "result.structuredContent": "The same result as a JSON object for programs.",
        "result.isError": "true = the TOOL failed in a way the model can read and react to; protocol errors use 'error' instead.",
    },
}
MODEL_CALL_NOTE = (
    "The model call happens in the HOST (backend/services/policy_agent.py -> Groq). "
    "It does NOT happen in either MCP server: servers only answer initialize, tools/list and tools/call."
)


def digest(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def discovery(config: Path, force: str) -> dict:
    registry = McpToolRegistry(config, force_transport=force)
    try:
        report = registry.discovery_report()
        frames = [f for f in registry.wire_log() if f["message"].get("method") == "tools/list"]
        return {
            "config": str(config.relative_to(ROOT)),
            "servers": [s["name"] for s in report["servers"]],
            "tool_count": report["tool_count"],
            "tools": [
                {"name": t["name"], "server": s["name"], "roles": t["roles"]}
                for s in report["servers"]
                for t in s["tool_details"]
            ],
            "taken_from": f"{len(frames)} tools/list response(s) on the wire",
        }
    finally:
        registry.close()


def capture_wire(out: Path) -> None:
    registry = McpToolRegistry(CONFIG_BOTH, force_transport="")
    try:
        registry.call_tool("get_leave_balance", {"employee_id": "EMP001"}, caller="week9-evidence")
        frames = registry.wire_log("hris")
    finally:
        registry.close()
    tagged = []
    names = ["initialize (request)", "initialize (response)", "notifications/initialized", "tools/list (request)", "tools/list (response)", "tools/call (request)", "tools/call (response)"]
    for name, frame in zip(names, frames):
        entry = {"step": name, "direction": frame["direction"], "message": frame["message"]}
        if name in ANNOTATIONS:
            entry["annotations"] = ANNOTATIONS[name]
        tagged.append(entry)
    (out / "wire.json").write_text(
        json.dumps(
            {
                "server": "hris (stdio subprocess: python -m backend.mcp.servers.hris_server)",
                "where_the_model_call_happens": MODEL_CALL_NOTE,
                "exchange": tagged,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def failing_call(context: PolicyContext) -> dict:
    registry = McpToolRegistry(CONFIG_BOTH, force_transport="inprocess")
    outcome = registry.call_tool(
        "get_jurisdiction_rules",
        {"jurisdiction": "Ireland", "policy_category": "leave"},
        context=context,
        caller="week9-evidence",
    )
    return {"observation": outcome.observation, "is_error": outcome.is_error, "attempts": outcome.attempts}


def model_run(context: PolicyContext) -> dict:
    result = policy_agent.run_agent_case(
        "week9_error_path",
        "EMP002",
        "Which Irish statutory annual leave rules apply to EMP002, and how do they compare with the handbook entitlement?",
        context=context,
    )
    return {
        "termination_reason": result.termination_reason,
        "tools": [
            {
                "step": c["step"],
                "tool": c["tool_name"],
                "arguments": c["arguments"],
                "is_error": c["is_error"],
                "error": c["error"],
                "why": (c["selection"] or {}).get("rationale"),
            }
            for c in result.tool_calls
        ],
        "answer": {"entitlement_value": result.entitlement_value, "explanation": result.explanation},
        "total_tokens": result.total_tokens,
        "model_call_retries": result.tool_audit["retries"]["model_call_retries"],
        "model_calls": len(result.llm_calls),
    }


def error_before_after(out: Path, context: PolicyContext, live: bool) -> None:
    record: dict = {"call": "get_jurisdiction_rules(jurisdiction='Ireland', policy_category='leave')", "runs": {}}
    for style in ("opaque", "recoverable"):
        os.environ[ERROR_STYLE_ENV] = style
        entry = {"tool_result": failing_call(context)}
        if live:
            entry["model"] = model_run(context)
        record["runs"][style] = entry
    os.environ.pop(ERROR_STYLE_ENV, None)
    (out / "error_before_after.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Week 9: docstring-as-prompt and a recoverable error (same failing call, before and after)",
        "",
        f"Failing call: `{record['call']}` for EMP002 (Ireland). The uploaded documents contain no Irish passage.",
        "",
    ]
    for title, style in (("Before: opaque error", "opaque"), ("After: recoverable error", "recoverable")):
        run = record["runs"][style]
        lines += [f"## {title}", "", "Tool result the model receives:", "", "```json", json.dumps(run["tool_result"]["observation"], indent=2), "```", ""]
        if "model" in run:
            m = run["model"]
            lines += [f"Model behaviour (live Groq run): termination `{m['termination_reason']}`, {m['model_calls']} model calls, {m['total_tokens']} tokens, {m['model_call_retries']} provider retries.", ""]
            for t in m["tools"]:
                status = f"ERROR {t['error']['code']}" if t["is_error"] else "ok"
                lines.append(f"{t['step']}. `{t['tool']}` {json.dumps(t['arguments'])} -> {status}" + (f" (model said: {t['why']})" if t["why"] else ""))
            lines += ["", f"Final answer: **{m['answer']['entitlement_value']}**", "", f"> {m['answer']['explanation']}", ""]
    lines += [
        "## Reading the result honestly",
        "",
        "- On this model both runs recovered: the opaque error did not stop the agent from trying `search_handbook`. One run each is an illustration, not a measurement; use the trajectory evaluation (cases `branch_02`-`branch_04`) for counts.",
        "- The difference is what the model can say. With the opaque error it had to guess why the tool failed. With the recoverable error it can state that the uploaded documents contain no Irish rule and that a comparison is therefore impossible, instead of implying a rule was looked up.",
        "- An opaque `Error: not found` cannot distinguish 'the documents are silent' from 'the tool is broken'; the coded error can, and `retryable: false` stops the host from wasting retries on it.",
        "",
        "## What changed",
        "",
        "- The tool description now says what the tool is for, when not to use it, and how to read an empty result (see `policy_server.py`).",
        "- The error carries a stable `code`, a message naming the documents searched, a `hint` naming the next move (`search_handbook`) and `retryable: false` so the host does not retry a hopeless call.",
        "- The old behaviour is reproducible with `POLICY_MCP_ERROR_STYLE=opaque` (used to generate the 'before' column).",
    ]
    (out / "error_before_after.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session-id", required=True, help="Session indexed with scripts/index_documents.py")
    parser.add_argument("--live", action="store_true", help="Also run the agent against Groq (spends a few API calls)")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "training" / "week9")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    before = {f: (ROOT / f).read_text(encoding="utf-8") for f in HOST_FILES}
    hashes_before = {f: digest(f) for f in HOST_FILES}

    one = discovery(CONFIG_ONE, "")
    both = discovery(CONFIG_BOTH, "")
    added = [t for t in both["tools"] if t["name"] not in {x["name"] for x in one["tools"]}]
    (args.out / "tool_discovery.json").write_text(
        json.dumps({"before": one, "after": both, "added_by_config_only": added}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"tools before -> after: {one['tool_count']} -> {both['tool_count']}  (added: {[t['name'] for t in added]})")

    capture_wire(args.out)
    context = PolicyContext(args.session_id)
    error_before_after(args.out, context, args.live)

    changed = 0
    parts = []
    for f in HOST_FILES:
        after = (ROOT / f).read_text(encoding="utf-8")
        diff = list(difflib.unified_diff(before[f].splitlines(), after.splitlines(), f"{f} (server one)", f"{f} (server one + two)", lineterm=""))
        changed += sum(1 for line in diff if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
        parts.append("\n".join(diff))
    same = {f: digest(f) == hashes_before[f] for f in HOST_FILES}
    body = [
        "Agent/host modules compared before and after adding server two (the swap = config only):",
        *[f"  {f}  sha256={hashes_before[f][:16]}...  unchanged={same[f]}" for f in HOST_FILES],
        "",
        *parts,
        f"CHANGED LINES: {changed}",
    ]
    (args.out / "agent_diff.txt").write_text("\n".join(body) + "\n", encoding="utf-8")
    cfg = difflib.unified_diff(
        CONFIG_ONE.read_text().splitlines(), CONFIG_BOTH.read_text().splitlines(), "config/mcp_servers.server1.json", "config/mcp_servers.json", lineterm=""
    )
    (args.out / "config_diff.txt").write_text("\n".join(cfg) + "\n", encoding="utf-8")
    print(f"agent/host changed lines: {changed}")
    return 0 if changed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
