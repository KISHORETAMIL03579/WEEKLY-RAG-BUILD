# Week 8: Policy Agent Trajectory Evaluation

Week 8 evaluates the Week 7 Agent's live tool trajectories on the existing
10-case policy benchmark. It records the answer score, required tool ordering,
extra and duplicate calls, termination reason, measured latency, actual token
usage, and the existing token-cost proxy. It reads the canonical `cases.json`
without changing its questions, expected values, or pass criteria.

The reference trajectory requires `get_employee_record` before
`search_handbook`. The evaluator also records, but does not hide, extra tool
calls. A baseline must be completed before selecting a mitigation; implement
only one mitigation for the highest-frequency observed failure mode, then run
the same cases again and compare the two evidence files.

Set `CHAT_BACKEND=groq`, a rotated `GROQ_API_KEY`, `GROQ_MODEL`, and the same
model in `GROQ_AGENT_MODELS` in the ignored local `.env`. The key pasted in chat
must not be reused. Configure one live run at a time:

```powershell
python -m benchmarks.policy_execution.trajectory_eval run baseline
# After reviewing baseline evidence and implementing one measured mitigation:
python -m benchmarks.policy_execution.trajectory_eval run mitigation
python -m benchmarks.policy_execution.trajectory_eval compare `
  benchmarks/policy_execution/trajectory_baseline.json `
  benchmarks/policy_execution/trajectory_mitigation.json
```

## Live baseline and one-mitigation result

The measured baseline had 7/10 runs terminate with Groq HTTP 429 and 3/10
complete. Its required tool sequence was valid in 3/10 cases; none passed the
existing deterministic answer criteria. The observed top failure mode was
provider rate limiting.

Exactly one mitigation was applied: bounded Groq retries now honor
`Retry-After` and the existing request wall-clock budget. The rerun completed
all 10 executions, with the required tool sequence valid in 10/10 cases and
2/10 passing the unchanged answer criteria.

| Measure | Baseline | After mitigation |
| --- | ---: | ---: |
| Provider executions completed | 3/10 | 10/10 |
| Required tool sequence valid | 3/10 (30%) | 10/10 (100%) |
| Existing answer criteria passed | 0/10 (0%) | 2/10 (20%) |
| p50 end-to-end latency | 1,099.421 ms | 17,157.343 ms |
| Actual provider-reported tokens | 9,555 | 26,035 |
| Token-cost proxy (not provider billing) | $0.0047775 | $0.0130175 |

The mitigation removed terminal 429 failures in this run but increased p50
latency because requests waited and retried. Eight answers still failed the
unchanged deterministic criteria; benchmark data and criteria were not edited.
This is not a claim of 100% answer correctness.

Evidence JSON files are ignored by Git because they are generated runtime
artifacts. The report distinguishes actual Groq token usage from the existing
estimated token-cost proxy; it does not claim provider billing amounts.

The runner refuses to overwrite evidence. For subsequent runs, use a new
`--output` path and pass that path to `compare`.
