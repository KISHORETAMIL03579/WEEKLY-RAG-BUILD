# Week 8: find the outcome-vs-trajectory gap, then close one mode

Brief: [`WEEKLY_RAG_TASK/W8-Task-Set-C.md`](../../../WEEKLY_RAG_TASK/W8-Task-Set-C.md).
How it fits the system: [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md#5-week-8-scoring-the-path-not-just-the-answer).

## The problem in one sentence

An agent can give the right notice period **without ever reading the employee's tenure** (it guessed the common
case and got lucky). That passes the outcome eval. The trajectory eval scores the *path* and exposes the gap as a number.

## Requirement -> where it lives

| # | Requirement | Implementation |
| --- | --- | --- |
| 1 | Expected tool sequences for the cases; alternate valid paths asserted as a set | `benchmarks/policy_execution/expected_trajectories.json`: per case a list of allowed paths (`case_03` lists both orders; `branch_01` lists three). A run passes if it matches **any one exactly** |
| 2 | Four numbers: tool-choice accuracy, argument validity, step efficiency, cost **p50 and max** | `backend/services/policy_trajectory.py::summarize` (also latency and tokens p50/max) |
| 3 | Outcome-vs-trajectory gap as a number, plus one named right-answer-wrong-path case | `summary.outcome_vs_trajectory_gap_pct` and `summary.right_answer_wrong_path[]` (observed sequence, allowed paths, why) |
| 4 | Exactly ONE mitigation, top mode before -> after, price paid as a number | `trajectory_eval run baseline` -> one change -> `run mitigation` -> `compare` (`policy_trajectory.compare`: per-mode counts, latency/token/cost deltas) |
| 5 | Regression check over every mode | `compare` always lists all nine modes and names any that increased (`regressions[]`) |

Cases: 10 canonical (all follow `employee record + policy search`, either order) and 6 branching (`branch_01..06`:
the jurisdiction argument must come from the record; two need the HRIS tools and are **skipped, not failed**, if that
server is not connected). Without the branching cases the workflow wins by construction, because nothing varies.

## The four numbers, exactly

| Metric | Definition |
| --- | --- |
| Tool-choice accuracy | Jaccard overlap between the tools the agent used and the closest allowed path (1.0 = same tool set); also the exact-set rate |
| Argument validity | Share of argument checks that passed. Checks: `employee_id_real` (the record was found and the id equals the request), `jurisdiction_matches_record` (argument equals the record's jurisdiction), `schema_valid` (every **rejected** model call counts as a failure), `citation_resolves` (cited section numbers exist in the uploaded document) |
| Step efficiency | `(executed + rejected tool calls) / steps needed` (shortest allowed path); 1.0 is ideal, reported as mean and worst |
| Cost | Token-proxy cost per question at **p50 and max** (plus latency and tokens). The mean hides the run that looped |
| Gap | `outcome pass rate - trajectory pass rate` |

**Failure-mode zoo** (one *primary* mode per case, all modes kept): `provider_error`, `budget_exhausted`, `tool_error`,
`invalid_tool_call`, `skipped_required_tool`, `wrong_tool_selection`, `bad_arguments`, `redundant_calls`, `answer_wrong`.

## What the recorded evidence actually says (re-scored offline, no model calls)

`benchmarks/policy_execution/trajectory_baseline.json` and `trajectory_mitigation.json` are from a live Groq run
(the old code path, hard-coded knowledge base). Re-grading the **recorded answers** with the fixed scorer:

```text
python -m benchmarks.policy_execution.trajectory_eval rescore benchmarks/policy_execution/trajectory_mitigation.json
strict (old literal match):  20.0 %   <- what the old report quoted
normalised (fixed scorer):   90.0 %
```

- 7 of the 8 "answer_quality failures" were **correct answers the literal matcher rejected**: "One (1) week (7 calendar
  days)" vs `1 week`, "not eligible" vs `ineligible`, "two (2) working days" vs `2 working days`.
- The one genuine failure is `case_02`: it answered **"0"** days of carry-forward (the rule allows 5 with no CEO consent)
  while its explanation quoted "five (5) days". A criterion matched anywhere in the answer would have hidden it, so the
  scorer now has **headline criteria** that must be in `entitlement_value` itself. `case_02` fails, correctly.
- So the old "outcome pass rate 20%" and the old gap were artifacts of the scorer, not the agent. The old recorded
  mitigation (Groq retry honouring `Retry-After`) did what it claimed: 7/10 provider failures -> 0, at the price of
  +16 s p50 latency and +16 480 tokens (because 7 more cases now ran to completion).
- Argument validity and step efficiency **cannot** be computed from that old evidence (it stored tool names only, not
  arguments). New runs store everything.

## Run it

```powershell
# live, in the UI
#   Policy Assistant -> suite "all" -> Start benchmark -> Trajectory panel

# from the command line
python scripts/index_documents.py --session-id policy-eval WEEKLY_RAG_TASK/HRPolicy.pdf backend/data/samples/employee_records.md
python -m benchmarks.policy_execution.trajectory_eval run baseline --session-id policy-eval --suite all
# ... apply exactly ONE mitigation ...
python -m benchmarks.policy_execution.trajectory_eval run mitigation --session-id policy-eval --suite all --note "what changed"
python -m benchmarks.policy_execution.trajectory_eval compare benchmarks/policy_execution/trajectory_baseline.json benchmarks/policy_execution/trajectory_mitigation.json
```

`run` calls Groq once per case (agent loop), so it spends API quota; it refuses to overwrite evidence. Generated
`trajectory_*.json` and `runs/*.csv` are git-ignored.

## Choosing the mitigation (do this from data, not from a guess)

The candidates from the brief: a sharper tool description, argument validation, a hard step limit, re-planning, or
replacing the agent with the workflow. Several already exist **by design** (schema validation of every argument,
recoverable rejection with a bound, four budgets, retry with back-off) so they are part of the baseline, not the
mitigation. Run the baseline on `all`, take the most frequent primary mode, change **one** thing aimed at it, re-run,
and read `compare`: the mode count before -> after, the price (latency, tokens, cost p50 and max), and any mode that rose.
A mitigation with no measured price, or two changes at once, does not count.

## Not implemented

The bonus (indirect prompt injection through a record comment, read-only scoping, output guardrail) is not built. What exists
toward it: tool results are labelled as data in both system prompts, tools are read-only, and arguments are schema-validated.
