# HR Policy Assistant & Evaluation — End-to-End Workflow Architecture

This document provides a comprehensive technical reference for the **Week 6 (RAG & Judge Evaluation)** and **Week 7 (HR Policy Search, Routing & ReAct Agent Loops)** subsystems.

---

## 1. High-Level System Architecture

The application has two distinct and isolated operational modes:
1. **Week 6: Evaluation & Judge Benchmark Suite**: Evaluates document retrieval quality and generation accuracy using deterministic assertions and calibrated LLM judges (V1/V2) against a frozen 25-case benchmark dataset.
2. **Week 7: Production HR Policy Search with Automatic Routing**: A dynamic enterprise HR assistant that routes questions between a fast, deterministic **Workflow Mode** and an iterative **ReAct Agent Mode**, enforcing 4 strict resource budgets and resilient retry logic.

```mermaid
flowchart TD
    subgraph Client ["Frontend Layer (React 18 + TypeScript + Vite)"]
        UI_Search["HR Policy Search View"]
        UI_Bench["10-Case Benchmark View"]
        UI_Judge["Week 6 Judge Evaluator View"]
        UI_Chat["Document Chat Area"]
    end

    subgraph RouterLayer ["Routing & Dispatch Layer"]
        PolicyRouter["Policy Router (Linguistic / Complexity Analysis)"]
        EvalManager["Evaluation Run Manager (Background Worker)"]
    end

    subgraph ExecutionLayer ["Execution Engine"]
        Workflow["Deterministic Policy Workflow"]
        Agent["Dynamic ReAct Policy Agent"]
        BudgetGuard["4 Strict Budgets (Iter, Token, Cost, Wall-Clock)"]
        RetryEngine["Transient Retry Engine (MAX_RETRIES=2)"]
    end

    subgraph ToolLayer ["Canonical Policy Knowledge Base & Tools"]
        T1["Tool 1: get_employee_record"]
        T2["Tool 2: search_handbook"]
        T3["Tool 3: get_jurisdiction_rules"]
        DB_Emp[("Canonical Employee DB")]
        DB_Handbook[("HR Policy Handbook")]
        DB_Jurisdiction[("Statutory Rules KB")]
    end

    UI_Search -->|POST /api/policy/search| PolicyRouter
    PolicyRouter -->|SIMPLE / MODERATE| Workflow
    PolicyRouter -->|COMPLEX / Multi-step| Agent
    Agent <--> BudgetGuard
    Agent <--> RetryEngine
    Workflow <--> RetryEngine
    Workflow --> T1 & T2
    Agent --> T1 & T2 & T3
    T1 <--> DB_Emp
    T2 <--> DB_Handbook
    T3 <--> DB_Jurisdiction
```

---

## 2. Policy Search Runtime Flow (Week 7)

When a user submits an HR policy query (e.g. *"What is Sarah Mwangi's annual leave accrual rate?"* or *"Compare statutory minimum sick leave in Kenya versus company policy for EMP005"*):

```mermaid
sequenceDiagram
    autonumber
    actor User as User / UI
    participant Router as Policy Router
    participant Engine as Retry & Execution Engine
    participant Agent as ReAct Agent / Workflow
    participant Tools as Policy Tools (Emp / Handbook / Stat)
    participant Ollama as Local Ollama / LLM

    User->>Router: Submit Question (question, emp_id, top_k, temp)
    Note over Router: Analyzes syntax, domain signals, and complexity (SIMPLE | MODERATE | COMPLEX)
    Router->>Engine: Dispatches with decision (mode, reason, complexity)

    loop Attempt 1 to 3 (Initial + max 2 retries)
        alt Mode == Workflow (Deterministic)
            Engine->>Tools: Step 1: get_employee_record(emp_id)
            Tools-->>Engine: Employee profile (tenure, status, etc.)
            Engine->>Tools: Step 2: search_handbook(query)
            Tools-->>Engine: Relevant policy sections
            Engine->>Engine: Deterministic formula calculation
        else Mode == Agent (Dynamic ReAct Loop)
            loop Iteration 1 to 5 (or until budget trap)
                Agent->>Ollama: Prompt with ReAct History + Tool Registry
                Ollama-->>Agent: Thought: <reason> / Action: <tool> / Input: <args>
                Agent->>Tools: Execute selected tool
                Tools-->>Agent: Observation: <json output>
            end
            Agent-->>Engine: Final Answer + Tool Record + Token Stats
        end

        alt Execution Success
            Engine-->>User: Final Answer + Complete Telemetry
        else Transient Error (e.g. Ollama Timeout)
            Note over Engine: Log retry_history, accumulate tokens/latency/cost, increment attempt
        end
    end
```

---

## 3. Policy Router Decision Logic

The router uses **structural linguistic signals** and domain dependency heuristics to determine execution complexity without requiring an expensive extra LLM call:

| Mode | Complexity | Decision Criteria | Example Queries |
| :--- | :--- | :--- | :--- |
| **Normal Workflow** | `SIMPLE` | Single-parameter policy lookup, deterministic single path. | *"What is the standard annual leave entitlement for EMP001?"*, *"How many days can EMP002 carry forward?"* |
| **Normal Workflow** | `MODERATE` | Two-step deterministic formula (Status check + rule lookup). | *"What notice must EMP003 provide if resigning on probation?"*, *"What severance pay is EMP007 entitled to for redundancy?"* |
| **Agent Mode** | `COMPLEX` | Cross-statutory comparisons, policy overrides, or conditional branching where the next tool depends on prior tool outputs. | *"Compare the statutory minimum sick leave in Kenya vs organisational policy for EMP005"*, *"Which jurisdiction rules override company policy for EMP006?"* |

---

## 4. The 3 Non-Overlapping Policy Tools

The system provides three tools with explicit, non-overlapping boundaries:

```mermaid
classDiagram
    class PolicyTools {
        +get_employee_record(employee_id) dict
        +search_handbook(query, top_k) list[dict]
        +get_jurisdiction_rules(jurisdiction, policy_category) dict
    }
    class EmployeeRecord {
        +string employee_id
        +string name
        +string job_title
        +string department
        +string duty_station
        +string jurisdiction
        +int tenure_months
        +string employment_status
        +int annual_leave_balance
        +float basic_salary_monthly
        +string separation_reason
    }
    class HandbookClause {
        +string section
        +string title
        +list keywords
        +string content
    }
    class JurisdictionRule {
        +string jurisdiction
        +string policy_category
        +string statutory_guideline
    }

    PolicyTools --> EmployeeRecord : queries
    PolicyTools --> HandbookClause : searches
    PolicyTools --> JurisdictionRule : resolves
```

1. **`get_employee_record`**:
   - Accesses verified canonical employee records (`EMP001` to `EMP010`).
   - Retrieves: employment status (Probation vs Confirmed), tenure in months, jurisdiction duty station, leave balance, monthly basic salary, and separation ground.
2. **`search_handbook`**:
   - Performs semantic and keyword search across verified sections of the Organizational HR Policy Manual (`HRPolicy.pdf` / Section 5.2, 5.3, 10.1, 10.5, 10.7, etc.).
3. **`get_jurisdiction_rules`**:
   - Retrieves statutory minimum standards and labor frameworks for duty stations (Kenya, Ireland, Côte d'Ivoire, Rwanda, and Global baseline).

---

## 5. The 4 Strict Budgets

To protect against runaway loops, infinite tool cycling, and cost overruns, every Agent execution is governed by 4 deterministic budget constraints:

| Budget Name | Threshold | Description | Termination Code |
| :--- | :--- | :--- | :--- |
| **Max Iterations** | `5` | Maximum ReAct observation cycles. | `BUDGET_ITERATIONS` |
| **Max Tokens** | `4,000` | Cumulative prompt + completion tokens. | `BUDGET_TOKENS` |
| **Max Cost** | `$0.05` | Max USD estimated cost (evaluated at `$2.00 / 1M` tokens). | `BUDGET_COST` |
| **Max Wall-Clock** | `30.0s` | Maximum execution time before safety timeout. | `BUDGET_WALL_CLOCK` |

---

## 6. Transient Retry Engine Contract

```mermaid
flowchart TD
    Start([Execute Attempt 1]) --> EvalResult{Result Status?}
    EvalResult -->|SUCCESS| ReturnSuccess([Return Result + Telemetry])
    EvalResult -->|Budget Exhausted / Invalid Arg| NonRetryable([Fail Immediately: Non-Retryable])
    EvalResult -->|Timeout / Network Disconnect| RetryCheck{Attempt < 3?}
    RetryCheck -->|Yes| Backoff[Log Attempt to retry_history & Accumulate Tokens] --> NextAttempt([Execute Attempt + 1 in SAME Mode])
    NextAttempt --> EvalResult
    RetryCheck -->|No| MaxRetriesExceeded([Fail: MAX_RETRIES Exceeded])
```

- **Max Retries**: `MAX_RETRIES = 2` (Allows up to 3 total attempts: Initial + 2 retries).
- **Mode Invariance**: Agent retries as **Agent**; Workflow retries as **Workflow**. The mode never mutates mid-retry.
- **Retry Accumulation**: All latency, prompt tokens, completion tokens, and dollar costs accumulate monotonically into the final response contract.
- **Classification**:
  - **Retryable**: `OLLAMA_TIMEOUT`, `OLLAMA_UNAVAILABLE`, `TRANSIENT_NETWORK`, `PROVIDER_TRANSIENT`, `MODEL_ERROR`.
  - **Non-Retryable**: `BUDGET_ITERATIONS`, `BUDGET_TOKENS`, `BUDGET_COST`, `BUDGET_WALL_CLOCK`, `INVALID_EMPLOYEE`.

---

## 7. Week 6 Evaluation vs Week 7 Policy Execution Pipelines

The system maintains strict isolation between evaluation types to ensure evaluation metrics and benchmark datasets remain uncorrupted:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        RAG APPLICATION BACKEND                         │
├───────────────────────────────────┬────────────────────────────────────┤
│              WEEK 6               │               WEEK 7               │
│     RAG & JUDGE EVALUATION        │        PRODUCTION POLICY SEARCH    │
├───────────────────────────────────┼────────────────────────────────────┤
│ • Dataset: 25 Frozen Cases        │ • Dataset: 10 Benchmark Profiles   │
│ • Deterministic Assertions (5)    │ • Dynamic ReAct Agent Loops        │
│ • LLM Judges (Judge V1 / V2)      │ • Deterministic Policy Workflow    │
│ • Metrics: HitRate, MRR, Recall   │ • Automated Linguistic Routing     │
│ • Blind Human Label Validation    │ • 4 Strict Resource Budgets        │
│ • Root-Cause Error Taxonomy       │ • Real Telemetry (Tokens, Latency) │
│ • evaluation_type:                │ • evaluation_type:                 │
│   "WEEK6_RETRIEVAL_ASSERTION"     │   "WEEK7_POLICY_EXECUTION"         │
└───────────────────────────────────┴────────────────────────────────────┘
```

---

## 8. Real Telemetry & Provenance Guarantees

The system **never fabricates metrics**. Every field returned in the API and rendered in the UI represents real execution accounting:

- **Tokens**: Recorded from live Ollama response headers (`prompt_eval_count` and `eval_count`). When offline/mocked, explicitly labeled with `token_source: "proxy_estimate"`.
- **Latency**: Measured via high-resolution monotonic timer `time.perf_counter()` from request receipt to final output serialization.
- **Estimated Cost**: Calculated from total accumulated tokens at the single-source-of-truth rate `$2.00 / 1,000,000` tokens (`TOKEN_COST_PROXY_RATE = 0.000002`).
- **Provider Cost**: Labeled `"N/A"` for local Ollama execution to accurately distinguish hardware compute from commercial API billing.
- **Run ID**: Unique UUID generated per execution for end-to-end tracing and auditing.
