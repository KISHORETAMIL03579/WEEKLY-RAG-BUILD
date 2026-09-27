# Week 7 Practical Report: Racing the HR Agent Against a Fixed Workflow

> **Evidence status:** The previously reported race is invalid and must not be
> used as a performance result. Its `race.csv` records `0.0 ms` latencies,
> although runtime latency is clamped to at least `0.01 ms`; workflow token
> counts in the original implementation were fixed estimates, not provider
> usage. The workflow now uses the selected model and reports provider token
> metadata, but a fresh live race has not yet been recorded.

## 1. Problem Statement

Organizations frequently deploy LLM-based autonomous agent loops (ReAct) for multi-step tasks without first asking whether a deterministic, hard-coded workflow would be faster, cheaper, more predictable, and equally accurate. This experiment evaluates both architectures over an identical 10-question HR policy entitlement benchmark based on the verified organizational handbook (`HRPolicy.pdf`) and canonical employee records.

## 2. Architecture & Design

### A. Dynamic ReAct HR Policy Agent

- **Loop Structure**: Autonomous Thought -> Action (Tool Call) -> Observation -> Synthesis.
- **Budgets Enforced**:
  - `MAX_ITERATIONS = 5`
  - `MAX_TOKENS = 4000`
  - `MAX_COST = $0.0500`
  - `MAX_WALL_CLOCK = 45.0s` (current code limit)
- **Token Tracking**: Re-sends cumulative conversation context on every iteration, reflecting true production token consumption.

### B. Fixed 3-Step Deterministic Workflow

- **Pipeline Structure**: (1) Call `get_employee_record` -> (2) Branch on discovered employee attributes (tenure, status, separation reason) -> (3) Call `search_handbook` / `get_jurisdiction_rules` -> (4) Synthesize structured answer.
- **Zero Agent Loops**: Fixed employee lookup, handbook search, optional
  jurisdiction-rule lookup, and exactly one structured-answer model call. The
  workflow uses the same selected provider/model, temperature, benchmark
  inputs, tool implementations, output contract, and token-cost proxy as the
  agent.

## 3. The Third Tool: `get_jurisdiction_rules`

- **Single Job**: Retrieves one policy rule for a specified jurisdiction and
  policy category.
- **Typed Enums**: Strict `JurisdictionEnum` and `PolicyCategoryEnum` parameters.
- **Zero Description Overlap**: Dedicated schema distinct from employee profile retrieval (`get_employee_record`) and global handbook search (`search_handbook`).

## 4. Benchmark Cases & Dependency Branching

All 10 benchmark cases are verified against verbatim clauses from `HRPolicy.pdf`. At least 6 cases contain genuine data-dependent branching where downstream reasoning depends on upstream discoveries:

| Case ID   | Employee | Intent / Section                           | Branching Dependency                    | Deterministic Pass Criteria                      |
| :-------- | :------- | :----------------------------------------- | :-------------------------------------- | :----------------------------------------------- |
| `case_01` | EMP001   | Annual leave entitlement (Sec 5.2.1)       | Standard confirmed staff                | 24 working days/year, 2 days/month               |
| `case_02` | EMP002   | Annual leave carryover cap (Sec 5.2.7)     | Global year-end cap                     | 5 days max carry forward                         |
| `case_03` | EMP003   | Resignation notice (Sec 10.1 / 3.6.4)      | **Probation status (tenure 4m < 6m)**   | 1 week (7 days) written notice                   |
| `case_04` | EMP004   | Resignation notice (Sec 10.1)              | **Confirmed status (tenure 36m >= 6m)** | 4 weeks written notice                           |
| `case_05` | EMP005   | Paid sick leave eligibility (Sec 5.3.2)    | **Tenure < 2 consecutive months**       | Ineligible (< 2 months threshold)                |
| `case_06` | EMP006   | Paid sick leave accrual & min (Sec 5.3.2)  | Confirmed tenure >= 2 months            | 2 days/month (1 full/1 half), min 7+7 days       |
| `case_07` | EMP007   | Redundancy notice & severance (Sec 10.5.1) | **Redundancy + 4 completed years**      | 1 month notice + 60 days severance (15d * 4y)    |
| `case_08` | EMP008   | Unsatisfactory performance (Sec 10.5.2)    | **Performance termination**             | 0 severance pay                                  |
| `case_09` | EMP009   | Pension allowance (Sec 4.4.1)              | **Probation status (tenure 4m < 6m)**   | Ineligible during probation (10% post-probation) |
| `case_10` | EMP010   | Separation leave commutation (Sec 10.7)    | Separation from service                 | Maximum 10 working days commutation              |

## 5. Race Results (The 8 Benchmark Numbers)

No valid same-model comparison is currently available. Discard the old
numeric results: latency is invalid, and workflow tokens were fixed estimates.
After this implementation change, record a fresh live run with provider, model,
settings, and per-case outputs before calculating the four metrics for each
system. Do not infer a winner from the old `race.csv`.

Cost remains an explicitly estimated token-cost proxy ($0.50 per 1,000,000
tokens), not provider billing.

## 6. Budget Enforcement Evidence

The agent loop checks iterations, tokens, cost proxy, and elapsed wall-clock
time. The historical `budget_termination.log` is invalid: it reports two
iterations despite a one-iteration limit and a `0.00 ms` duration. Do not treat
it as execution evidence. A corrected automated test now exercises clean
iteration-budget termination after one model step; the test result is the
available verification until a captured live-provider budget run is recorded.

## 7. Limitations

- Fixed workflows require explicit engineering of branching paths; if HR introduces a completely novel, unmodeled policy type without prior code updates, the fixed workflow cannot autonomously discover novel tool combinations.
- The ReAct agent consumes significantly higher tokens due to conversational history replay across iterations.

## 8. Verdict on the Decision Rule

**Decision Rule**: _Does the path vary dynamically by unpredictable input, or are the branches deterministic once the employee record is retrieved?_

**Verdict**:
No architecture winner can yet be declared: the previous measurements are
invalid and a fresh live comparison has not been run. Employee status, tenure,
separation reason, and jurisdiction affect the answer or selected evidence.
Apply the decision rule only after both implementations have run the same ten
cases with the same configured provider/model and valid latency/token
measurements.
