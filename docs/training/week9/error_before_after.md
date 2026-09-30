# Week 9: docstring-as-prompt and a recoverable error (same failing call, before and after)

Failing call: `get_jurisdiction_rules(jurisdiction='Ireland', policy_category='leave')` for EMP002 (Ireland). The uploaded documents contain no Irish passage.

## Before: opaque error

Tool result the model receives:

```json
{
  "error": {
    "code": "ERROR",
    "message": "Error: not found",
    "retryable": false
  }
}
```

Model behaviour (live Groq run): termination `SUCCESS`, 4 model calls, 6301 tokens, 0 provider retries.

1. `get_employee_record` {"employee_id": "EMP002"} -> ok (model said: Need employee record to get jurisdiction.)
2. `get_jurisdiction_rules` {"jurisdiction": "Ireland", "policy_category": "leave"} -> ERROR ERROR (model said: Now need jurisdiction rules for Ireland, policy_category leave.)
3. `search_handbook` {"query": "Irish statutory annual leave", "top_k": 5} -> ok (model said: No jurisdiction specific. Use search_handbook for Irish statutory annual leave.)

Final answer: **The handbook specifies a standard entitlement of 24 days per annum for full‑time staff (section 5.2.1 Annual leave entitlement). No statutory Irish annual leave rule is cited in the uploaded documents. Therefore, the employee’s entitlement is governed solely by the handbook provision above.**

> The search for Irish statutory annual leave returned only the handbook passage stating the 24‑day entitlement. No jurisdiction‑specific statutory rule was found in the provided documents, so the handbook rule applies.

## After: recoverable error

Tool result the model receives:

```json
{
  "error": {
    "code": "NO_EVIDENCE",
    "message": "No passage in the uploaded documents mentions Ireland.",
    "retryable": false,
    "hint": "Documents searched: HRPolicy.pdf, employee_records.md. Answer from search_handbook results instead, or state that no Ireland-specific rule was provided."
  }
}
```

Model behaviour (live Groq run): termination `SUCCESS`, 4 model calls, 6563 tokens, 3 provider retries.

1. `get_employee_record` {"employee_id": "EMP002"} -> ok (model said: Need get_employee_record for EMP002. Then get_jurisdiction_rules for Ireland, policy_category leave. Then search_handbook for 'statutory annual leave Ireland'.)
2. `get_jurisdiction_rules` {"jurisdiction": "Ireland", "policy_category": "leave"} -> ERROR NO_EVIDENCE (model said: Now get_jurisdiction_rules.)
3. `search_handbook` {"query": "statutory annual leave Ireland", "top_k": 5} -> ok (model said: So no jurisdiction rules. Use search_handbook for statutory annual leave Ireland.)

Final answer: **The uploaded documents do not contain any statutory annual leave rules for Ireland. The handbook only specifies the company’s own entitlement (24 days per annum for full‑time staff, accruing at 2 days per month for less than a year – see section 5.2.1 of HRPolicy.pdf). Since no Ireland‑specific statutory rule is present in the documents, we cannot compare it to the handbook entitlement.**

> The employee’s jurisdiction is Ireland (from the employee record), but the get_jurisdiction_rules tool returned NO_EVIDENCE, indicating no jurisdiction‑specific rules were found. The search_handbook results show only the company’s entitlement, not statutory provisions. Therefore the documents do not cover Irish statutory annual leave rules, and the handbook entitlement remains the only applicable rule.

## Reading the result honestly

- On this model both runs recovered: the opaque error did not stop the agent from trying `search_handbook`. One run each is an illustration, not a measurement; use the trajectory evaluation (cases `branch_02`-`branch_04`) for counts.
- The difference is what the model can say. With the opaque error it had to guess why the tool failed. With the recoverable error it can state that the uploaded documents contain no Irish rule and that a comparison is therefore impossible, instead of implying a rule was looked up.
- An opaque `Error: not found` cannot distinguish 'the documents are silent' from 'the tool is broken'; the coded error can, and `retryable: false` stops the host from wasting retries on it.

## What changed

- The tool description now says what the tool is for, when not to use it, and how to read an empty result (see `policy_server.py`).
- The error carries a stable `code`, a message naming the documents searched, a `hint` naming the next move (`search_handbook`) and `retryable: false` so the host does not retry a hopeless call.
- The old behaviour is reproducible with `POLICY_MCP_ERROR_STYLE=opaque` (used to generate the 'before' column).
