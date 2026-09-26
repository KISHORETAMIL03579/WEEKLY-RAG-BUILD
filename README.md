# Ask My Docs

Ask My Docs is a document-grounded question-answering and evaluation
application. It combines a React/TypeScript web client with a FastAPI backend,
hybrid lexical/vector retrieval, pluggable model providers, and separate
Week 6, Week 7, and Week 8 evaluation surfaces.

This README describes the checked-in application, not a claim that every
production deployment or live-provider benchmark has been verified. The
repository's current Week 8 live measurements and limitations are recorded
below. Never commit `.env`, provider credentials, uploaded documents, runtime
traces, or generated benchmark results.

## Contents

- [Architecture](#architecture)
- [End-to-end request flows](#end-to-end-request-flows)
- [Weeks 6, 7, and 8](#weeks-6-7-and-8)
- [Local setup](#local-setup)
- [Docker Compose](#docker-compose)
- [Configuration](#configuration)
- [HTTP API overview](#http-api-overview)
- [Data lifecycle and session cleanup](#data-lifecycle-and-session-cleanup)
- [Testing and live verification](#testing-and-live-verification)
- [Repository audit and known limitations](#repository-audit-and-known-limitations)
- [Troubleshooting](#troubleshooting)

## Architecture

```text
React + TypeScript SPA (frontend/src)
  ├─ chat, sources, viewer, evaluation and policy views
  └─ typed HTTP client (frontend/src/services/api.ts)
                 │ HTTP / JSON
                 ▼
FastAPI application (backend/main.py)
  ├─ routes/       HTTP validation, authorization and serialization
  ├─ schemas/      request and response contracts
  ├─ services/     retrieval, provider calls, policy execution and run managers
  ├─ evaluation/   Week 6 assertions, metrics, judges and retrieval runner
  └─ storage/      vector stores, sessions, SQLite coordination and traces
        ├─ Qdrant or in-memory vector store
        ├─ source files and per-session manifests
        ├─ SQLite shared run/session metadata
        └─ append-only trace and orphan records
```

`backend.main:create_app()` is the application factory and `backend.main:app`
is the ASGI application. The root [`app.py`](app.py) remains a compatibility
facade for older imports and launch/deployment references; it re-exports
backend symbols and should not be treated as a second implementation.

| Area | Main code |
| --- | --- |
| Chat and document status/reset | `backend/routes/chat.py` |
| Upload, URL indexing and document removal | `backend/routes/ingestion.py` |
| Source document viewing | `backend/routes/documents.py` |
| Week 6 evaluation APIs | `backend/routes/evaluation.py` |
| Week 7 policy search and benchmark APIs | `backend/routes/policy.py` |
| Provider adapters and answer generation | `backend/services/llm.py` |
| Chunking, retrieval and ranking | `backend/services/chunker.py`, `backend/services/search.py` |
| Agent, workflow and automatic routing | `backend/services/policy_agent.py`, `policy_workflow.py`, `policy_router.py` |
| Session stores and vector backends | `backend/storage/session_manager.py`, `vector_store.py`, `qdrant_store.py` |
| Browser UI | `frontend/src/components/`, `pages/`, `services/api.ts` |

The UI already reuses shared controls for evaluation progress, model selection,
parameters, metric cards, buttons, icons, and status presentation. A repository
audit found no confirmed dead implementation safe to delete: the apparent
overlaps include legacy compatibility exports, alternate memory/Qdrant
implementations, and tested evaluation contracts. See the audit notes below.

## End-to-end request flows

### Document ingestion and grounded chat

1. The browser stages an upload and submits it to `POST /upload` with the
   session cookie and selected chunk strategy.
2. FastAPI validates supported upload extensions (`.pdf`, `.txt`, `.md`),
   extracts document text, chunks it, and requests embeddings when configured.
3. Chunks and metadata are stored in the session's vector store. Qdrant uses a
   collection named `chunks_<session_id>`; the memory backend stays in-process.
4. `GET /status` reads the active session store and returns indexed documents,
   chunks, retrieval mode, and vector backend.
5. `POST /ask` retrieves lexical and, when configured, dense candidates; fuses
   rankings; applies context limits and answer-generation rules; and returns
   sources and telemetry. The chat trace is recorded separately.
6. The frontend renders the answer with its grounded source list. Stop requests
   cancellation; it does not disable typing in the composer.

The text extractor has additional internal readers, but the upload route's
allowlist is the supported upload contract. It currently accepts PDF, plain
text, and Markdown files.

### Week 6 evaluation

The evaluation UI sends the selected cases, model, Top-K, temperature, and
execution options to the evaluation routes. Background runs are assigned run
IDs, persisted, polled for progress, and can be cancelled. The Judge path
executes deterministic assertions and optionally configured LLM judges;
retrieval benchmarking reports retrieval metrics and per-case evidence. Keep
the canonical cases and labels under `week6/` unchanged when evaluating
implementation behavior.

### Week 7 policy execution

The Policy Search UI sends the employee, question, selected model, Top-K,
temperature, retry configuration, and optional forced execution mode to
`/api/policy/search`. Automatic routing chooses the deterministic Workflow or
the bounded Agent. Responses include execution mode, routing reason, tool
calls, retries, provider token provenance, latency, termination reason, and
the unchanged deterministic case result. Long-running policy benchmarks have
persisted run state and cancellation endpoints.

### Week 8 trajectory evaluation

The Week 8 CLI runs the unchanged ten canonical Week 7 policy cases with live
Groq Agent calls. It stores per-case results, required tool ordering, extra and
duplicate tool calls, termination reason, actual provider tokens, latency,
and a clearly labeled token-cost proxy. New evidence also shows each existing
deterministic answer criterion as matched/unmatched; these diagnostics do not
change the pass predicate or benchmark truth.

The recorded baseline had 3/10 successful provider executions, 3/10 valid
required tool sequences, and 0/10 answer passes; 7 runs ended in HTTP 429. The
single recorded mitigation was bounded Groq retry honoring `Retry-After` and
the existing request time budget. The same cases then had 10/10 completed
executions, 10/10 valid required tool sequences, and 2/10 answer passes. Median
latency increased from about 1.10 seconds to 17.16 seconds. Eight answers still
failed the existing deterministic criteria. These measurements demonstrate
improved transient-failure handling, not complete answer correctness or
production readiness. See
[`docs/training/week8/README.md`](docs/training/week8/README.md) for the
methodology and evidence limitations.

To run fresh live evidence, configure a valid, private Groq key and use a new
output path (the runner refuses to overwrite evidence):

```powershell
python -m benchmarks.policy_execution.trajectory_eval run baseline `
  --output benchmarks/policy_execution/trajectory_baseline_new.json
# Review baseline before changing one mitigation.
python -m benchmarks.policy_execution.trajectory_eval run mitigation `
  --output benchmarks/policy_execution/trajectory_mitigation_new.json
python -m benchmarks.policy_execution.trajectory_eval compare `
  benchmarks/policy_execution/trajectory_baseline_new.json `
  benchmarks/policy_execution/trajectory_mitigation_new.json
```

Live runs call the provider and may incur cost and rate limits. Keep generated
evidence local unless deliberately publishing approved, non-sensitive results.

## Local setup

### Prerequisites

- Python 3.11 or newer (the Docker image uses Python 3.11).
- Node.js/npm supported by the frontend lockfile.
- Qdrant and/or Ollama only when selected by the configuration.

### Install and configure

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` locally. For the configured Groq chat path, set a freshly rotated
`GROQ_API_KEY`; never paste credentials into source files, README, logs, or
commits. Configure embeddings separately (the example uses Ollama). Set a
stable `SECRET_KEY` for sessions, especially when running multiple workers.

Build the browser application and start FastAPI:

```powershell
Push-Location frontend
npm ci
npm run build
Pop-Location
python -m uvicorn backend.main:app --host 127.0.0.1 --port 5000
```

Open `http://127.0.0.1:5000`. The interactive API docs are available at
`/docs`; liveness and readiness endpoints are `/healthz` and `/readyz`.
Alternatively, `python app.py` is the compatibility launch entrypoint and
ensures the frontend build is present.

For local Ollama, start Ollama and pull the configured embedding and vision
models. A chat model is needed when `CHAT_BACKEND=ollama`. Docker Compose
contains a one-shot model initializer for those configured local models.

## Docker Compose

The Compose stack defines the FastAPI app, Qdrant, Ollama, and an Ollama model
initializer:

```powershell
Copy-Item .env.example .env
# Set SECRET_KEY and any provider credentials in .env before starting.
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

The app is published on loopback port 5000; Qdrant and Ollama are also bound
to loopback by default. Docker's internal service URLs are
`http://qdrant:6333` and `http://ollama:11434`. Named volumes persist Qdrant
data, Ollama model files, and app state; `./uploads`, `./vectorstore`, and
`./traces` are mounted from the repository host. `docker compose down` stops
services without deleting volumes. `docker compose down -v` deletes named
volumes and is destructive.

Compose forwards Groq API configuration (`GROQ_API_KEY`, `GROQ_URL`,
`GROQ_MODEL`, and `GROQ_AGENT_MODELS`) into the app container. Keep the API key
in the ignored local `.env`; do not put it in the Compose file. The default
Compose profile still starts Ollama for local embedding/vision configurations.
For a changed provider combination, confirm effective values through the
application's health/configuration surface and exercise a real request.

This is a single-host deployment arrangement. SQLite, local files, and
file-lock coordination are not a distributed multi-node storage design. Use
shared database and object/file storage before horizontally scaling across
hosts.

## Configuration

`.env.example` documents the variables. Relevant settings:

| Variable | Purpose |
| --- | --- |
| `CHAT_BACKEND` | Chat provider: `groq`, `ollama`, or `xai`. |
| `GROQ_API_KEY` | Private API credential required for Groq requests and model discovery. |
| `GROQ_URL` | Groq OpenAI-compatible API base URL. |
| `LLM_MODEL` / `GROQ_MODEL` | Selected chat model. The example selects `openai/gpt-oss-20b`. |
| `GROQ_AGENT_MODELS` | Allowlist used for Groq Agent-mode models. |
| `EMBED_BACKEND` | Embeddings provider, independently configurable from chat. |
| `VISION_BACKEND` | OCR provider for image extraction. |
| `OLLAMA_URL` | Ollama URL; use Docker service DNS from inside Compose. |
| `OLLAMA_EMBED_MODEL`, `OLLAMA_VISION_MODEL`, `OLLAMA_CHAT_MODEL` | Local Ollama model names. |
| `VECTOR_BACKEND` | `qdrant` or `memory`; `.env.example` configures Qdrant. |
| `QDRANT_URL`, `QDRANT_API_KEY` | Qdrant endpoint and optional cloud credential. |
| `QDRANT_TIMEOUT`, `QDRANT_CANDIDATE_POOL`, `QDRANT_SCROLL_LIMIT` | Qdrant operation and retrieval limits. |
| `TOP_K`, `MAX_CONTEXT_TOKENS` | Retrieval and answer context limits. |
| `RETRIEVAL_MODE`, `RRF_K`, `HYBRID_ALPHA` | Retrieval strategy and fusion tuning. |
| `RERANK_ENABLED`, `QUERY_REWRITE_ENABLED` | Optional model-assisted retrieval steps. |
| `APP_STATE_DB` | SQLite file for shared session/run metadata. |
| `SECRET_KEY` | Signs browser session cookies; use a stable random secret in production. |
| `SESSION_COOKIE_SECURE` | Set true only when HTTPS/TLS is used. |
| `ADMIN_API_KEY` | Optional credential for documented administrative endpoints. |
| `TRACE_LOG_PATH`, `LOG_LEVEL`, `HOST`, `PORT`, `APP_DEBUG` | Logging and server settings. |

The Python configuration defaults are not identical to `.env.example` or
Docker Compose defaults; verify which environment source is active. An empty
inherited environment variable may differ from an unset variable. Never
publish effective secrets when diagnosing configuration.

## HTTP API overview

FastAPI's `/docs` and `/openapi.json` expose the current, complete contract.
Main routes include:

| Method | Route | Function |
| --- | --- | --- |
| `POST` | `/upload` | Upload and index allowed files for the browser session. |
| `POST` | `/upload-cancel` | Request cancellation of an in-flight upload. |
| `POST` | `/load-url` | Fetch and index a supported web page. |
| `POST` | `/ask` | Retrieve grounded context and generate an answer. |
| `POST` | `/ask/{run_id}/cancel` | Cancel an active chat request. |
| `GET` | `/status` | Return current session document/index status. |
| `POST` | `/remove` | Remove a document from the current session. |
| `POST` | `/clear` | Clear indexed data/files for the current session. |
| `GET` | `/file/{doc_id}/raw`, `/pages` | Stream an uploaded file or extracted page text. |
| `POST` | `/eval/run` | Run the retrieval evaluation matrix. |
| `POST` | `/api/evaluation/runs` | Start a Week 6 background evaluation. |
| `GET` | `/api/evaluation/runs/{run_id}` | Read persisted evaluation progress/results. |
| `POST` | `/api/evaluation/runs/{run_id}/cancel` | Request evaluation cancellation. |
| `POST` | `/api/evaluation/judges` | Run the Week 6 Judge evaluation. |
| `GET` | `/api/policy/models` | Discover available policy chat models. |
| `POST` | `/api/policy/search` | Run auto-routed Week 7 Policy Search. |
| `POST` | `/api/policy/benchmark/start` | Start a persisted policy benchmark run. |
| `GET` | `/healthz`, `/readyz` | Liveness and dependency readiness checks. |
| `GET` | `/traces`, `POST /replay/{trace_id}` | Inspect/replay traces subject to session/admin access. |
| `GET` | `/orphans` | Inspect failed ingestion cleanup records subject to authorization. |

Some older Week 6 routes remain aliases for compatibility. Consult OpenAPI for
exact request/response schemas, route aliases, constraints, and error formats.

## Data lifecycle and session cleanup

- The session cookie is browser-managed and configured for a 14-day maximum
  age; that cookie lifetime is not the vector-data retention period.
- Session activity is tracked in SQLite. The session store expires inactive
  sessions after one hour and enforces a maximum active-session count.
- Qdrant collection names are session-scoped (`chunks_<session_id>`). Current
  session clear deletes its collection through the existing Clear route.
- With `VECTOR_BACKEND=qdrant`, the backend sweeps collections that no longer
  have recent activity records, at startup activity/request opportunities and
  periodically while the application is running. Failed deletions are logged
  and retried on a later sweep. Closing a browser does not send an immediate
  session-end signal; cleanup follows the inactivity TTL and sweep interval.
- Local source files and manifests are removed with session cleanup. SQLite
  metadata coordinates workers on one host; it does not contain vector
  embeddings.

Do not manually delete collections while a session is active. For a live
cleanup problem, check the application's effective `VECTOR_BACKEND` and
`QDRANT_URL`, backend logs, session cookie continuity, Qdrant collection names,
and `/status` from the same browser session.

## Testing and live verification

Install Python requirements, then run:

```powershell
python -m pytest
python -m pytest tests\test_policy_trajectory_evaluation.py tests\test_policy_execution.py
python -m pytest tests\test_shared_state.py tests\test_qdrant_session_cleanup.py
Push-Location frontend
npm ci
npm run typecheck
npm run build
Pop-Location
```

Most automated tests use local fixtures/mocks and do not prove that a live
Groq, Ollama, or Qdrant service is available. For runtime verification, start
the configured services, check `/healthz` and `/readyz`, then exercise upload →
`/status` → `/ask` → `/remove` or `/clear` using one persistent browser/client
session. For a vector backend, inspect Qdrant for the corresponding
`chunks_<session_id>` collection and verify it is absent after a successful
clear or after session expiry and a subsequent cleanup sweep.

Full test/build/runtime results should be reported from the current run; do not
infer them from an earlier commit or from this README.

## Repository audit and known limitations

A repository-wide source audit found **no confirmed unused component or safe
dead-code deletion**. In particular:

- `app.py` is a compatibility facade still used by tests and legacy imports.
- `VectorStore` and `QdrantVectorStore` are alternate implementations of a
  shared interface, not redundant copies.
- Session lifecycle in `session_manager.py` and durable shared state in
  `shared_state.py` are coupled; refactoring them needs concurrency and
  persistence regression tests.
- Existing shared evaluation components are reused across views. The large
  Policy Assistant view may merit decomposition, but file size alone is not
  proof of duplicated behavior.
- Week 6 aliases and standalone Week 6 assets remain tested compatibility and
  ground-truth surfaces.

The audit recommends targeted, test-backed work rather than deleting code
based on names or visual similarity. Remaining architecture constraints:

- SQLite and local file locks support a single host/shared volume, not
  multi-host coordination.
- Qdrant cleanup does not immediately detect browser closure; it is TTL based.
- The Week 8 retry mitigation improved execution and tool ordering but only
  2/10 answers passed the unchanged deterministic criteria in the recorded
  run. Eight answer-quality failures and increased latency remain real issues.
- No Week 9 implementation is included in this repository documentation or
  scope.

## Troubleshooting

**Groq model list or chat requests fail**
Check `CHAT_BACKEND=groq`, a valid rotated `GROQ_API_KEY`, the API base URL,
and the selected `LLM_MODEL`/`GROQ_MODEL`. In Docker, confirm the Groq variables
were passed into the app container without printing the secret. HTTP 429 is a
provider rate-limit response; bounded retry can improve completion rates but
adds latency and cannot guarantee capacity.

**Ollama is unreachable from the backend container**
Inside Compose, the service hostname is `ollama`, not `localhost`. From the
host, use the published loopback port. Confirm `OLLAMA_URL` matches where the
backend process runs and that the required model was initialized.

**Qdrant contains chunks but the current UI lists no documents**
The collection may belong to a different browser session. `/status` is scoped
to the session cookie; it does not list every Qdrant collection. Verify the
same browser session and its cookie before treating the data as missing.
Inactive collections are removed after the one-hour session TTL and the
periodic sweep; a stopped backend cannot run that sweep until it starts again.

**Clear reports an error or warning**
Do not interpret a failed Qdrant deletion as success. Check the backend error
and Qdrant availability, then retry cleanup after restoring connectivity.

**The evaluation process stops when the backend shuts down**
In-process workers belong to their application process. A successful HTTP
response that creates a run does not guarantee the run will survive termination
of that process; inspect persisted run status after restart.
