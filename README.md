# Ask My Docs

Upload documents, ask questions, and evaluate the answers. A React + TypeScript client sits on a
FastAPI backend with Qdrant for chunks, **Groq** for chat, the HR policy agent and the judge, and an
**MCP** host that gives the agent its tools.

This repository is the working build for Weeks 6 to 9 of the course:

| Week | Topic | What you can do with it | Detail |
| --- | --- | --- | --- |
| 6 | Validate the judge | 25 labelled cases, assertions vs judge, agreement % (Judge Evaluator tab) | [docs/training/week6](docs/training/week6/README.md) |
| 7 | Agent vs fixed workflow | Policy Search (auto-routed) and Policy Assistant (race + 4 numbers) | [docs/training/week7](docs/training/week7/README.md) |
| 8 | Trajectory evaluation | Score the tool path: accuracy, argument validity, step efficiency, cost p50/max, outcome-vs-trajectory gap | [docs/training/week8](docs/training/week8/README.md) |
| 9 | MCP | Add an HRIS tool server by config only; raw wire log | [docs/training/week9](docs/training/week9/README.md) |

**Start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**: one diagram per week, how data flows, where every
piece lives, the JSON trace explained, and a live demo script.

> **The one rule:** the policy tools read **only the chunks you uploaded** (Qdrant). No policy text, employee
> data or country rule is typed into the code. If the documents are silent the tools say so and the answer says so.

## Quick start (Groq only)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env          # then edit .env
Push-Location frontend; npm ci; npm run build; Pop-Location
python -m uvicorn backend.main:app --host 127.0.0.1 --port 5000
```

Minimum `.env` (see [`.env.example`](.env.example) for everything):

```dotenv
CHAT_BACKEND=groq
GROQ_API_KEY=<your rotated key>
LLM_MODEL=openai/gpt-oss-20b
GROQ_AGENT_MODELS=openai/gpt-oss-20b
EMBED_BACKEND=none                    # see below
VECTOR_BACKEND=qdrant
QDRANT_URL=<your Qdrant endpoint>
QDRANT_API_KEY=<your Qdrant key>
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
```

**Why `EMBED_BACKEND=none`?** Groq has no embeddings API. In this lexical mode chunks are stored in Qdrant and
searched with BM25; chat and every policy tool still use Groq. To get semantic hybrid search instead, set
`EMBED_BACKEND=ollama` (run `ollama serve`, `ollama pull nomic-embed-text`) or `gemini` (`GEMINI_API_KEY`).
Mixing modes inside one session is not supported; re-upload after changing it.

Open `http://127.0.0.1:5000` (API docs at `/docs`, health at `/healthz`, readiness at `/readyz`).

## Try it live (5 minutes)

1. **Chat page:** upload `WEEKLY_RAG_TASK/HRPolicy.pdf` **and** `backend/data/samples/employee_records.md`.
2. **Policy Search:** the banner lists the indexed documents, retrieval mode and tool count. Ask
   *"How much written notice must EMP003 provide if they decide to resign while on probation?"* and read the tool trace.
3. **MCP tab:** 2 servers, 5 tools, the raw JSON-RPC frames.
4. **Policy Assistant:** run the `canonical` suite, then `all`, and open the Trajectory panel.
5. Import any question file from [`docs/questions/`](docs/questions/README.md) to run a week's cases.

CLI alternatives (no browser): `scripts/index_documents.py`, `benchmarks/policy_execution/trajectory_eval.py`,
`scripts/mcp_week9_evidence.py`; each file's docstring shows the commands.

## How it fits together

```text
Browser (React)            chat, policy search, benchmark, trajectory, MCP, judge
   │  HTTP/JSON
FastAPI (backend/main.py)
   ├─ routes/ingestion.py   upload -> extract -> chunk -> Qdrant (chunks_<session>)
   ├─ routes/policy.py      /api/policy/*  router -> workflow | agent -> full JSON trace
   ├─ routes/mcp.py         /api/mcp/*     discovered servers, tools, wire log
   ├─ services/             policy_agent, policy_workflow, policy_router,
   │                        policy_retrieval, policy_scoring, policy_trajectory, policy_run
   ├─ mcp/                  host: registry, client, schema validation, 2 servers
   └─ storage/              Qdrant store, sessions, SQLite run state, traces
Groq (chat, agent, judge) · Qdrant (chunks) · config/mcp_servers.json (which tool servers exist)
```

`backend.main:app` is the ASGI app; root `app.py` is a compatibility facade older imports still use.

## Configuration

Everything is in `.env` ([`.env.example`](.env.example) is the documented template).

| Variable | Purpose |
| --- | --- |
| `CHAT_BACKEND` | `groq` is required for the agent, workflow, trajectory and MCP features (`ollama`/`xai` only serve plain chat). |
| `GROQ_API_KEY`, `GROQ_URL`, `LLM_MODEL`, `GROQ_AGENT_MODELS` | Groq access, default model, allow-list of tool-calling models. |
| `EMBED_BACKEND` | `none` (lexical, recommended with Groq only), `ollama`, or `gemini`. |
| `VECTOR_BACKEND`, `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_TIMEOUT` | Chunk store (`qdrant` or in-process `memory`). |
| `RETRIEVAL_MODE`, `TOP_K`, `EMBED_MIN_SCORE`, `MAX_CONTEXT_TOKENS` | Retrieval tuning (semantic mode uses hybrid RRF; lexical mode uses BM25). |
| `POLICY_MAX_ITERATIONS`, `POLICY_MAX_TOKENS`, `POLICY_MAX_COST_USD`, `POLICY_MAX_WALL_CLOCK_SECONDS` | The four agent budgets (hard ceilings). |
| `MCP_CONFIG_PATH` | Which tool servers exist (`config/mcp_servers.json`). Adding a server is a config change. |
| `MCP_TOOL_MAX_RETRIES`, `MCP_TOOL_RETRY_BACKOFF_SECONDS`, `MCP_TOOL_TIMEOUT_SECONDS`, `MCP_AUDIT_LOG_PATH` | Tool-call retry bounds and the audit log. |
| `HRIS_DATA_PATH` | Data file for the stand-in HRIS server (point it at a real export). |
| `EMBED_QUERY_TIMEOUT_SECONDS`, `EMBED_COOLDOWN_SECONDS` | Semantic mode only: fail fast, then fall back to keyword search. |
| `APP_STATE_DB`, `SECRET_KEY`, `SESSION_COOKIE_SECURE`, `ADMIN_API_KEY`, `TRACE_LOG_PATH`, `LOG_LEVEL`, `HOST`, `PORT` | Sessions, security, logging, server. |

Never commit `.env`, credentials, uploads, traces or generated evidence (all git-ignored).

## HTTP API overview

FastAPI's `/docs` has the exact schemas. Main routes:

| Method | Route | Function |
| --- | --- | --- |
| `POST` | `/upload`, `/load-url`, `/remove`, `/clear` | Index, list-reset documents for the browser session |
| `POST` | `/ask`, `GET /status` | Grounded chat; indexed documents and retrieval mode |
| `GET` | `/api/policy/readiness` | Indexed documents, retrieval mode, tools, whether the policy features are ready |
| `GET` | `/api/policy/employees` | Roster rows parsed from the uploaded employee file |
| `POST` | `/api/policy/search` | Auto-routed question -> answer + full trace (`force_mode`, `max_retries`) |
| `POST` | `/api/policy/agent`, `/workflow` | Run one implementation directly |
| `GET` | `/api/policy/cases?suite=canonical\|branching\|all` | Benchmark cases |
| `POST` | `/api/policy/benchmark/start`, `GET .../runs/{id}`, `POST .../runs/{id}/cancel` | Background race with progress and cancel |
| `GET`/`POST` | `/api/policy/trajectory/expected`, `/api/policy/trajectory/evaluate` | Week 8 expected paths; scoring and before/after comparison |
| `GET` | `/api/policy/models` | Groq models (and which support tool calling) |
| `GET`/`POST` | `/api/mcp/status`, `/api/mcp/wire`, `/api/mcp/reload` | Discovered servers/tools, raw frames, config reload |
| `POST` | `/api/evaluation/runs`, `GET .../runs/{id}` | Week 6 judge evaluation |
| `GET` | `/healthz`, `/readyz`, `/traces` | Operations |

Policy endpoints return **409 `NO_INDEXED_DOCUMENTS`** until the session has indexed chunks.

## Testing

```powershell
python -m pytest                       # 340 tests, no live provider needed
Push-Location frontend
npm run typecheck; npm run build
Pop-Location
```

What the tests cover: the tools on chunk-shaped data, every agent stop condition and budget, rejected model calls,
retry accounting at all four layers (including a deliberately flaky MCP server and a killed subprocess), the
zero-code-change server swap, secret isolation for the subprocess, trajectory scoring, lexical mode, the HTTP API,
and the Week 6 lifecycle. Tests use a temporary state database and evidence directory and never read your
`.env` embedding setting.

Live verification is separate: start the app, upload, then follow the demo above. A green test run is not evidence
that Groq, Qdrant or your documents behave; the readiness banner and a real question are.

## Docker Compose

```powershell
Copy-Item .env.example .env            # set SECRET_KEY, GROQ_API_KEY, Qdrant settings
docker compose up -d --build           # app + Qdrant; Groq for the LLM; EMBED_BACKEND=none
docker compose --profile ollama up -d  # optional: also start Ollama (then set EMBED_BACKEND=ollama)
```

The app binds to loopback port 5000; Qdrant is loopback-only. Named volumes hold Qdrant data and app state;
`./uploads`, `./vectorstore` and `./traces` are host mounts. `docker compose down -v` deletes volumes.
SQLite and local file locks are a single-host design; scaling out needs shared storage.

## Data lifecycle

- Uploaded files and manifests live in `uploads/`; chunks in Qdrant collection `chunks_<session_id>`.
- Sessions expire after one hour idle; idle collections are swept on a timer (not when the tab closes).
- Benchmark evidence: `benchmarks/policy_execution/runs/<run_id>.csv` per run and `results.csv` = latest run only.
- A benchmark interrupted by a restart is marked `ERROR` at startup; it cannot leave a stuck lock.
- Audit: `traces/mcp_audit.jsonl` (one line per tool call, hashed session, no returned values).

## Troubleshooting

**Uploads fail with an embedding error.** Your `EMBED_BACKEND` points at a provider that is not running
(typically Ollama). Use `EMBED_BACKEND=none` or start the provider.

**Policy pages say "Upload the HR policy documents first" (HTTP 409).** The policy tools only read the current
browser session's chunks. Upload on the Chat page in the same browser; check `GET /api/policy/readiness`.

**An employee is "not found".** The roster must be uploaded (`backend/data/samples/employee_records.md` is the
format: one `ID | Key: value | ...` line per employee). Ids are matched case-insensitively.

**A country question answers "documents do not cover it".** That is the intended behaviour: the handbook is silent
on that country. The tool returns `NO_EVIDENCE` and the model must not quote outside law.

**Slow answers / many "model retries" in the trace.** Groq returned HTTP 429; the client waits `Retry-After` and
retries up to 3 times. It shows up as `provider_retries`, not as a failure. Use a model/account with more quota.

**The HRIS tools are missing in the MCP tab.** Check `config/mcp_servers.json` and `GET /api/mcp/status` (a server
that fails to start shows `status: error` with the reason; the other server keeps working). `POST /api/mcp/reload`
re-reads the config.

**Qdrant has chunks but the UI lists no documents.** `/status` is scoped to the session cookie. Use the same browser
session; inactive collections are removed after the one-hour TTL.

**Clear reports an error.** A failed Qdrant deletion is never reported as success; fix connectivity and retry.
