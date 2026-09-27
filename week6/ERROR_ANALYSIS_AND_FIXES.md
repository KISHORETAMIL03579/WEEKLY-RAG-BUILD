# Week 6 Evaluation Implementation Audit

This audit compares the Week 6 Task Set C requirements with the current code
and available run artifacts. Historical measurements below are identified by
their source; they are not presented as one reproducible before/after result.

## Current implementation

- `eval_cases_25.json` contains 25 cases across the five Week 5 taxonomy modes.
  Three cases are marked as regressions. The one-command evaluator now checks
  that each marked case's question, answer, and retrieved chunk text match its
  referenced record in `traces/traces.jsonl`.
- The labels file contains one binary label per case. Git history places the
  label-and-case commit before the evaluator/prompt commit, which supports the
  original blind-label-before-judge ordering. It does not prove a new blind
  labeling protocol for later runs.
- The evaluator reports five deterministic checks and one semantic judge
  criterion. The handbook-version check now requires the expected `2018`
  version instead of accepting generic mentions such as “handbook”; an empty
  response no longer satisfies an out-of-jurisdiction refusal check.
- Judge V2 now contains two examples based on the selected V1 disagreements:
  the incomplete salary-advance condition list (case 03) and the valid refusal
  for an unstated overtime rule (case 18).
- Live evaluations now stop on judge transport/provider errors instead of
  turning an error into a binary verdict. Live mode is the default; set
  `WEEK6_LIVE_LLM=0` explicitly to run the deterministic offline diagnostic,
  which is not a live judge-agreement measurement.

## Historical evidence and limitations

| Artifact | Recorded result | Qualification |
| --- | --- | --- |
| `evidence/eval_v1_output.txt` | 17/25 agreement (68%) | Contains timed-out cases that the prior code treated as binary fallback results; do not treat as clean live agreement. |
| `evidence/eval_v2_output.txt` | 7/25 agreement (28%) | Same historical error-handling problem; this run falsified the prediction but is not a clean provider-complete comparison. |
| `live_llm_audit_results.json` | 76% / 52% | A separate run with its own errors and configuration; not comparable as a replacement for the first pair. |
| `certified_final_eval_results.json` | Contains duplicate JSON keys and conflicting agreement values | Invalid as a canonical result; JSON duplicate keys cannot represent both values reliably. |

The prediction in `prediction.txt` expected agreement to rise from 68% to above
88%. The saved first run instead recorded 68% to 28%, so the prediction was
wrong for that run. No current agreement-before/after result is claimed: after
the fail-closed runner and V2 few-shot changes, a new live run must complete
all 25 calls for each prompt before agreement is reported.

## Scope not established by this Week 6 evaluator

The archived RAG findings document contains claims about retrieval depth,
temperature, embeddings, and large score improvements. Those claims are not
validated by the judge benchmark alone. The current Week 6 evaluator validates
the saved answer/context pairs and judge behavior; it does not rerun document
retrieval or prove that a production RAG change improved live answers.

The optional RAGAS faithfulness/context-precision bonus is not implemented or
evidenced here.

## Verification

The targeted regression command used for the current Week 6/7 implementation
was:

```powershell
python -m pytest tests\test_week6.py tests\test_policy_workflow.py tests\test_policy_agent_react.py tests\test_policy_execution.py tests\test_policy_router.py -q
```

Its latest recorded result was **90 passed**. This is automated test
verification, not a live Week 6 judge run.
