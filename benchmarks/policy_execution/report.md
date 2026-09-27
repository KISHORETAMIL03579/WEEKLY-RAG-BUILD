# HR Policy Assistant: Policy Agent vs. Policy Workflow Benchmark Report

> **Evidence status:** The historical scorecard below is not valid evidence.
> The workflow originally emitted fixed token estimates, and recorded
> `0.00 ms`/sub-millisecond latencies are incompatible with measured live-model
> execution. The workflow has since been updated to use the selected model and
> actual provider token metadata, but a new live race has not yet been recorded.

## 1. Problem Statement

Organizations frequently deploy LLM-based autonomous agent loops (ReAct) for multi-step tasks without first evaluating whether a deterministic, hard-coded workflow would be faster, cheaper, more predictable, and equally accurate. This benchmark evaluates both architectures over an identical 10-question HR policy entitlement benchmark based on the verified organizational handbook (`HRPolicy.pdf`) and canonical employee records.

## 2. Architecture & Design

### A. Dynamic ReAct Policy Agent (`policy_agent.py`)

- **Loop Structure**: Autonomous Thought -> Action (Tool Call) -> Observation -> Synthesis.
- **Budgets Enforced**:
  - `MAX_ITERATIONS = 5`
  - `MAX_TOKENS = 4000`
  - `MAX_COST = $0.0500`
  - `MAX_WALL_CLOCK = 45.0s` (current code limit)
- **Token Tracking**: Re-sends cumulative conversation context on every iteration, reflecting true production token consumption.

### B. Fixed 3-Step Policy Workflow (`policy_workflow.py`)

- **Pipeline Structure**: (1) Call `get_employee_record` -> (2) Branch on discovered employee attributes (tenure, status, separation reason) -> (3) Call `search_handbook` / `get_jurisdiction_rules` -> (4) Synthesize structured answer.
- **Zero Agent Loops**: Fixed employee lookup and handbook search, optional
  jurisdiction lookup, and one final model call with the selected model and
  temperature used by the agent.

## 3. Jurisdiction Rules Tool: `get_jurisdiction_rules`

- **Single Job**: Returns duty-station statutory guidelines and public holiday frameworks.
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

## 5. Benchmark Results (The 8 Scorecard Metrics)

No valid same-model comparison is currently available. Discard the old
numeric results: the latency and workflow token values are not measured
execution evidence. Run a fresh ten-case comparison and report pass rate,
p50 latency, total tokens, and cost per question from the persisted case-level
results. Cost is a token-cost proxy, not provider billing.

> _Note on Cost: Cost is evaluated using the benchmark token-cost proxy ($0.50 per 1,000,000 tokens) because local inference carries $0.00 monetary provider cost._

## 6. Budget Enforcement Evidence

The agent loop checks iterations, tokens, cost proxy, and elapsed wall-clock
time. The historical budget log is inconsistent with its claimed iteration
limit and should not be treated as execution evidence. Automated budget tests
are the available verification until a captured live-provider termination is
recorded.

## 7. Limitations

- Fixed workflows require explicit engineering of branching paths; if HR introduces a completely novel, unmodeled policy type without prior code updates, the fixed workflow cannot autonomously discover novel tool combinations.
- The ReAct agent consumes significantly higher tokens due to conversational history replay across iterations.

## 8. Verdict on the Decision Rule

**Decision Rule**: _Does the path vary dynamically by unpredictable input, or are the branches deterministic once the employee record is retrieved?_

**Verdict**:
No winner is supported by the historical run. Decide only after both
implementations have executed the same ten questions using the same configured
model with valid latency, token, and answer pass measurements.
