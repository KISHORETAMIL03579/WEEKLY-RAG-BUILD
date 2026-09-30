# Week 9: bolt on the HRIS server without touching the agent

Brief: [`WEEKLY_RAG_TASK/W9-Task-Set-C.md`](../../../WEEKLY_RAG_TASK/W9-Task-Set-C.md).
How it fits the system: [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md#6-week-9-mcp-adding-a-tool-server-with-config-only).

## Requirement -> evidence

| # | Requirement | Evidence (all generated from the running system) |
| --- | --- | --- |
| 1 | Add the HRIS server via config and run a query that calls one of its tools, tool name visible in the trace | `config/mcp_servers.json`; ask *"What is EMP001's grade band and accrued leave balance?"* in Policy Search: trace shows `get_grade_band@hris`. Unit test: `test_policy_agent.py::test_hris_tools_are_used_when_the_model_picks_them_with_no_code_change` |
| 2 | Zero changed lines in the agent module across the swap | [`agent_diff.txt`](agent_diff.txt): **CHANGED LINES: 0** (six host files hashed and diffed before/after). Enforced per test run by `test_mcp.py::test_adding_the_second_server_needs_no_code_change`. The swap is exactly [`config_diff.txt`](config_diff.txt) |
| 3 | Tool count before -> after, with names, from `tools/list` | [`tool_discovery.json`](tool_discovery.json): **3 -> 5**. Before: `get_employee_record`, `search_handbook`, `get_jurisdiction_rules`. Added by config only: `get_grade_band`, `get_leave_balance` (both from server `hris`) |
| 4 | Raw `initialize -> tools/list -> tools/call`, every top-level field annotated, where the model call does and does not happen | [`wire.json`](wire.json): real frames from the stdio subprocess with per-field annotations. **The model call happens in the host (`policy_agent.py` -> Groq); it does not happen in either MCP server.** |
| 5 | Rewrite one tool docstring as a prompt, make one error path recoverable, before/after transcript of the same failing call | [`error_before_after.md`](error_before_after.md) (real Groq runs; `.json` has the raw results). Summary below |
| 6 | 5-line supply-chain note | [`risk_note.md`](risk_note.md) (exactly five lines) |

Regenerate everything: `python scripts/mcp_week9_evidence.py --session-id <indexed session> [--live]`
(index a session first with `scripts/index_documents.py`). The script exits non-zero if any host line changed.

## The docstring-as-prompt rewrite (`get_jurisdiction_rules`, server one)

Before (description and error):

> "Retrieve the policy rule for one specified jurisdiction and policy category."  ->  `Error: not found`

After:

> "Retrieve passages from the uploaded documents that state rules specific to ONE jurisdiction for ONE policy category (local law, statutory minimums, public holidays, duty-station rules). Use it only when the question is about such local rules, and take `jurisdiction` from the employee's record (field 'jurisdiction'), never from a name or a guess. Do NOT use it for general handbook rules (use search_handbook) or employee facts (use get_employee_record). If no passage mentions the jurisdiction the error says so; then rely on search_handbook or state the gap."
>
> error: `{"code":"NO_EVIDENCE","message":"No passage in the uploaded documents mentions Ireland.","retryable":false,"hint":"Documents searched: HRPolicy.pdf, employee_records.md. Answer from search_handbook results instead, or state that no Ireland-specific rule was provided."}`

Result on this model (one live run each, see the report for the full transcript): both runs recovered via
`search_handbook`; the recoverable error lets the model state that the documents contain no Irish rule and that a
comparison is impossible, where the opaque error made it guess why the tool failed. One run each is an illustration;
`retryable:false` also stops the host from retrying a hopeless call. The old behaviour stays reproducible with
`POLICY_MCP_ERROR_STYLE=opaque`.

The HRIS server draws the same distinction the brief asks for: unknown employee (`EMPLOYEE_NOT_FOUND`, not retried)
versus HRIS down (`HRIS_UNAVAILABLE`, `retryable:true`), tested in `test_mcp.py`.

## Common mistakes the design avoids

- **Hard-coding the tool list.** The agent asks `tools/list`; the diff shows it unchanged.
- **A model call inside a server.** Servers answer three methods; the host runs Groq.
- **The handbook as a model-fetched "tool" for context it should be handed.** Retrieval is per question; the roster is data behind a tool.
- **Collapsing "not found" and "down".** Distinct codes, distinct retry behaviour.
- **Trusting the connector.** Minimal launch environment, audit line per call, see `risk_note.md`.

## Not done (bonus)

The single-gateway process and per-token tool scoping (bonus) are not implemented; the audit line and minimal
environment cover the logging and isolation parts only.
