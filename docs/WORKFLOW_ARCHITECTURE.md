# Application Architecture and Production-Readiness Plan

## Current architecture

The application is a single-host FastAPI + React/Vite service with explicit
boundaries between HTTP routes, business services, persistence, and UI:

```text
Browser (React/TypeScript)
  ├─ pages and shared components
  └─ frontend/src/services/api.ts
       ↓ HTTP / JSON
FastAPI (backend/main.py)
  ├─ routes/       validation, HTTP status and serialization
  ├─ services/     RAG, LLM, evaluation, workflow and agent orchestration
  ├─ schemas/      request/response contracts
  └─ storage/
       ├─ QdrantVectorStore   embeddings and indexed chunks
       ├─ uploads/manifests   source files and per-session document metadata
       ├─ shared_state.py     SQLite coordination and run snapshots
       └─ trace_store.py      append-only JSONL request traces
```

### Data ownership

| Data                                    | Owner                                | Purpose                                                                                                 |
| --------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| Uploaded source files                   | `uploads/`                           | Preserve files used for extraction and document viewing                                                 |
| Embeddings and indexed chunks           | Qdrant / configured vector backend   | Semantic and hybrid retrieval                                                                           |
| Session manifests and document metadata | Session storage plus SQLite metadata | Track session documents, hashes, chunk counts, revisions, and worker activity                           |
| Shared run state                        | `APP_STATE_DB` SQLite file           | Coordinate chat/upload cancellation and persist evaluation/policy-run snapshots across Gunicorn workers |
| Request traces                          | `TRACE_LOG_PATH` JSONL file          | Diagnostics and replayable request telemetry                                                            |

SQLite is the Python-standard-library database engine, not a Docker service or
image. It creates a local database file automatically and applies schema
migrations during application startup. It does **not** hold vector embeddings or
uploaded source files. Evaluation and policy run snapshots can include case
questions, answers, retrieved context, and telemetry; protect and retain the
database accordingly. Chat coordination stores run identifiers and a one-way
session hash, not the chat transcript.

Local development defaults to `vectorstore/app_state.sqlite3`. Docker Compose
sets `APP_STATE_DB=/app/state/app_state.sqlite3` on the persistent `app_state`
named volume. This lets workers in one container coordinate state and
cancellation despite having separate Python memory. SQLite and local file
locks are single-host mechanisms; horizontal multi-node deployment requires
shared database and document/vector/trace storage services.

### Request lifecycles

- **RAG chat:** request validation → session document lookup → hybrid/vector
  retrieval → context budget → model generation → grounded sources and
  telemetry. The chat run ID is shared with the client; Stop persists a
  cancellation request so the worker executing the request can observe it.
- **Ingestion:** validate and stage files → extract/chunk/embed → index → commit
  session metadata. Duplicate-content claims and cancellation markers are
  shared across workers; failed ingestion must not be represented as committed.
- **Week 6 evaluation:** create a persisted run snapshot → retrieve at the
  requested K → evaluate deterministic assertions and configured judge
  provenance → persist case and run progress/results. Benchmark labels remain
  independent of implementation results.
- **Week 7 policy:** route a query to the normal workflow or bounded agent →
  execute policy tools → produce a response with actual mode and telemetry →
  persist benchmark progress and results.

## Implementation and verification plan

Work through these gates in order; do not report a gate complete without the
listed evidence.

1. **Baseline and scope:** confirm branch, worktree ownership, architecture,
   runtime configuration, and frozen evaluation assets. Separate application
   changes from generated traces, benchmark outputs, credentials, and local
   office lock files.
2. **Frontend correctness and reuse:** inspect every `frontend/src` page and
   component for duplicated controls, stale state, cancellation/polling,
   responsive overflow, and default browser styling. Reuse existing common
   components first; add one only where no equivalent exists and verify the
   rendered DOM and appearance.
3. **Chat and sources:** verify typing during generation, Send/Stop transitions,
   actual request cancellation, edit-in-place/retry identity, exact copy, and
   response-scoped grounded sources.
4. **API and shared-state correctness:** trace every route through service and
   storage code; test validation, errors, timeouts, cancellation, idempotency,
   session isolation, concurrent workers, restart recovery, and secret-safe
   diagnostics. Ensure persisted snapshots do not mask an unavailable provider.
5. **RAG and evaluation truthfulness:** trace ingestion through retrieval and
   generation. Verify K/temperature propagation, final context provenance,
   judge provenance, run isolation, progress/cancellation, and unchanged
   benchmark labels. Distinguish provider failures from valid evaluation
   outcomes.
6. **Policy workflow/agent:** verify routing mode/reason, tool schemas,
   iteration and cost/token/time budgets, retry accounting, and actual telemetry.
   A hard budget termination must not trigger another retry.
7. **Infrastructure and documentation:** validate environment examples,
   Docker/Compose volumes, startup/shutdown, health checks, logging and
   deployment limitations. Document data owners and recovery/retention.
8. **Final evidence:** run focused tests, the full backend suite, frontend
   TypeScript and production build, then runtime smoke tests where services are
   available. Review the full diff and worktree; exclude secrets and generated
   data before staging, committing, or publishing.

### Current constraints to preserve

- Week 6 benchmark inputs and labels are frozen; do not tune them to improve
  scores.
- Ollama/Qdrant outages must remain explicit failures, not success-shaped
  fallbacks or fabricated metrics.
- Local estimated/proxy cost must not be described as an actual provider bill.
- SQLite and local filesystem coordination support one host only.
- A committed code change or successful build is not evidence that all
  production and multi-service runtime checks have passed.

## Implementation status and remaining verification

This section records evidence available for the current implementation; it is
not a claim that every production-readiness gate above has passed.

### Completed and verified

- Browser-facing Week 7 model choices are sourced from installed Ollama models,
  with tool-capable models separated for Agent mode.
- The Week 6 Judge UI passes its selected model along with Top-K and
  Temperature to the evaluation run API.
- A missing Ollama model is surfaced as `MODEL_NOT_FOUND` and is not retried.
- Policy Search reports failed results as failures rather than success.
- The shared frontend API handler preserves successful JSON arrays.
- The deterministic Workflow path was exercised successfully and reports model
  and temperature as not applicable.
- A captured response from the installed local model returned handbook `top_k`
  as the string `"5"` despite the integer tool schema. Model tool-call parsing
  now converts only ASCII decimal strings for schema-declared integer
  arguments, then applies the existing type and range validation. This narrowly
  accommodates the observed Ollama behavior without weakening external
  request/tool validation.
- Active chat runs now heartbeat their shared-state row periodically, so a
  healthy request lasting longer than the five-minute cleanup window remains
  cancellable from another worker. The heartbeat updates only active rows and
  does not overwrite a concurrent cancellation state.
- Shared run snapshot and active-run lookups use deferred/read transactions;
  write locks remain reserved for mutations and abandoned-run recovery.
- Week 6 Judge health checks now probe the host and port from the configured
  `OLLAMA_URL`, including Compose service DNS, rather than assuming
  `127.0.0.1:11434`. Its stop sequence no longer terminates generation on the
  JSON closing brace. An LLM-engine run with any non-LLM judge result now ends
  in `ERROR` with case/judge provenance instead of reporting a successful run.
- Live Week 6 verification completed two benchmark cases through
  `POST /api/evaluation/runs` using `llama3.1:8b`, Top-K 5, and temperature
  0.3. Run `eval_91322d6190f7` completed all 2/2 cases in 30.2 seconds; all
  four V1/V2 results reported `source=LLM`, `llm_completed=true`, and complete
  JSON verdicts. The selected model, K, and temperature were persisted.
- After an API process was stopped mid-run, its persisted run was recovered as
  `ERROR` on the next read, with the worker-exited explanation, rather than
  remaining indefinitely active.
- After this correction, the Agent regression suite passed (13 tests), Policy
  execution tests passed (13 tests), and the non-route benchmark tests passed
  (4 tests). The isolated Week 6 retrieval-K and Temperature tests passed
  (2 tests). Chat cancellation/heartbeat tests passed (2 tests), and shared
  state tests passed (2 tests).
- The focused judge URL, JSON-stop, and failed-LLM-run regressions completed
  cleanly when pytest was launched as a waited child process: `3 passed`,
  process exit code 0. Direct native invocation through the interactive
  PowerShell tool had previously reported exit code 1 despite the same passing
  output; that was a command-harness status artifact, not a pytest teardown
  failure.
- Frontend TypeScript checking and the production Vite build passed after the
  latest changes.

### Still to complete or re-verify

- Re-run the new regression tests and execute a live Week 7 Agent request after
  integer normalization. A live Agent success has not yet been established.
- Exercise Retrieval Benchmark with indexed test documents; the currently
  observed environment has no indexed chunks, so its successful retrieval
  path remains unverified.
- Resolve the backend route-test stall during policy benchmark active-run
  polling and a separate consecutive-evaluation-run test stall, then complete
  the full backend test suite. The route stall persists with the full
  ten-case scripted worker; the active endpoint responds in an isolated
  one-case test. The existing unit portions of benchmark progress/cancellation
  do pass.
- Perform a final full diff/artifact review and runtime verification for the
  remaining application flows before claiming complete production readiness.

Current known limitations are environment-dependent: successful Retrieval
Benchmark verification requires indexed content and live model execution
requires an installed chat model with tool calling. No benchmark labels or
ground-truth data should be changed to work around either limitation.
