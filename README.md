# Ask My Docs — Universal Multimodal RAG & Evaluation Framework

A production-grade Retrieval-Augmented Generation (RAG) and Agentic Evaluation framework built with **FastAPI**, **React 18**, **TypeScript**, and **pluggable local/cloud backends** (Ollama, Qdrant, Google Gemini, xAI Grok).

The system provides end-to-end multimodal document ingestion, hybrid reciprocal-rank-fusion retrieval, grounded answer generation with clickable source deep-linking, durable trace auditing, and a comprehensive **Evaluation Hub** featuring:
1. **Multi-Strategy Retrieval Benchmark** (`Hit-Rate@K`, `MRR`, ablation comparison).
2. **LLM Judge & Policy Assertions Evaluator** (Judge V1 Zero-Shot vs Judge V2 Few-Shot vs Blind Human Ground Truth & 5 Deterministic Rule Assertions).
3. **Autonomous HR Policy Assistant Race** (Autonomous ReAct Agent vs Deterministic Fixed Workflow across 4 execution budgets).
4. **Universal Q&A Dataset Management** (File import for `.json`, `.txt`, and `.md`, pre-import validation modal, in-UI manual authoring, and zero ground-truth leakage).

---

## 🏛️ Clean Architecture & Project Structure

The repository follows layered **Clean Architecture** principles, enforcing separation of concerns between API routing, business logic, persistence, and frontend presentation:

```text
WEEK-3-RAG/
├── backend/                               # 🏛️ AUTHORITATIVE BACKEND (FastAPI)
│   ├── main.py                            # FastAPI app factory, middleware, router mounts, lifespan
│   ├── config.py                          # App settings, paths, environment configuration, logger
│   ├── errors.py                          # Canonical error hierarchy & secret/path sanitization
│   ├── middleware.py                      # Request correlation (X-Request-ID) & 50MB body limiter
│   ├── evaluation/                        # Core evaluation algorithms
│   │   ├── assertions.py                  # 5 deterministic rule assertions (numeric, tenure, etc.)
│   │   ├── judge.py                       # LLM Judge V1 & V2 prompt execution & scoring
│   │   ├── metrics.py                     # Hit-Rate@K, MRR, Precision, Recall metrics
│   │   └── retrieval_runner.py            # Retrieval ablation presets & test runner
│   ├── routes/                            # Thin REST API controller layer
│   │   ├── chat.py                        # /ask endpoint, query rewriting, grounded QA
│   │   ├── documents.py                   # Document viewing, raw streaming, page text extraction
│   │   ├── evaluation.py                  # /api/evaluation/ runs, benchmarks, dataset parser
│   │   ├── ingestion.py                   # /upload, /load-url, /remove, /clear endpoints
│   │   ├── policy.py                      # /api/policy/ agent, workflow, & benchmark race
│   │   └── traces.py                      # /traces and /replay/<trace_id> endpoints
│   ├── schemas/                           # Pydantic contract boundaries
│   │   ├── api.py                         # Ingestion, chat, status schemas
│   │   ├── evaluation.py                  # Judge & retrieval benchmark schemas
│   │   └── policy.py                      # HR Policy contracts, employee schemas, budget limits
│   ├── services/                          # Core business logic & external integrations
│   │   ├── chunker.py                     # Structured, fixed, and semantic chunking
│   │   ├── embeddings.py                  # Embedding dispatchers (Ollama, Gemini)
│   │   ├── evaluation_dataset.py          # Universal Q&A dataset parser, validator, deduplicator
│   │   ├── evaluation_runner.py           # Background LLM judge execution manager
│   │   ├── llm.py                         # Chat generation dispatchers (Ollama, xAI Grok)
│   │   ├── policy_agent.py                # ReAct HR Policy Agent with 4 strict budgets
│   │   ├── policy_benchmark_runner.py     # Background Policy race execution engine
│   │   ├── policy_tools.py                # 3 Canonical Policy Agent tools (records, rules, search)
│   │   ├── policy_workflow.py             # Fixed 3-step deterministic policy workflow
│   │   ├── search.py                      # Hybrid BM25 + Dense vector search + RRF fusion
│   │   └── text_extractor.py              # Universal document & Vision OCR text extraction
│   └── storage/                           # Data persistence & external store adapters
│       ├── orphan_store.py                # Durable tracking for unindexed upload orphans
│       ├── qdrant_store.py                # Qdrant client wrapper (hybrid vector store)
│       ├── session_manager.py             # Session isolation and uploads storage
│       └── trace_store.py                 # Durable JSONL execution trace logging & replay
│
├── frontend/                              # ⚛️ AUTHORITATIVE FRONTEND (React 18 + TS + Vite)
│   ├── src/
│   │   ├── App.tsx                        # Root layout, navigation router, active tab state
│   │   ├── main.tsx                       # React DOM entry point
│   │   ├── index.css                      # Modern dark-theme enterprise CSS design system
│   │   ├── components/
│   │   │   ├── common/                    # Topbar navigation, status badges, notifications
│   │   │   ├── Chat/                      # Grounded chat UI, sources drawer, dropzone, files list
│   │   │   ├── DocumentViewer/            # Embedded PDF / text viewer with highlight navigation
│   │   │   ├── Evaluation/                # Evaluation Hub components
│   │   │   │   ├── EvaluationDatasetManager.tsx  # Universal dataset import & authoring modal
│   │   │   │   ├── EvaluationProgressCard.tsx     # Real-time progress bar & telemetry card
│   │   │   │   ├── FormView.tsx                   # Multi-strategy retrieval benchmark UI
│   │   │   │   ├── JudgeEvaluatorView.tsx         # LLM Judge & Assertions evaluation UI
│   │   │   │   ├── PolicyAssistantView.tsx        # Agent vs Workflow race dashboard & playground
│   │   │   │   └── ResultsView.tsx                # Evaluation scorecard & per-case breakdown
│   │   │   └── Traces/                    # Trace inspection drawer & replay console
│   │   ├── data/                          # Canonical test cases & benchmark questions
│   │   ├── services/
│   │   │   └── api.ts                     # Strongly typed frontend API client
│   │   └── types/                         # TypeScript interfaces (dataset, policy, eval, traces)
│   ├── package.json                       # Dependencies & build scripts
│   ├── tsconfig.json                      # Strict TypeScript compiler options
│   └── vite.config.ts                     # Vite build & local dev server config
│
├── benchmarks/                            # 📊 BENCHMARK SPECIFICATIONS & ASSETS
│   └── policy_execution/                  # 10 verified HR policy cases & historical results.csv
├── week6/                                 # 📊 WEEK 6 BENCHMARK ASSETS
│   ├── eval_cases_25.json                 # 25 canonical test cases spanning 5 failure modes
│   ├── labels_25.json                     # Blind human ground-truth labels
│   ├── judge_v1.txt                       # Zero-shot judge prompt template
│   └── judge_v2.txt                       # Few-shot disagreement-calibrated judge prompt
├── tests/                                 # 🧪 AUTOMATED TEST SUITE (32+ Unit & Integration Tests)
├── traces/                                # 📝 DURABLE RUNTIME EXECUTION TRACES (traces.jsonl)
├── uploads/                               # 📂 DOCUMENT UPLOAD STORAGE
├── vectorstore/                           # 💾 LOCAL VECTOR STORE PERSISTENCE
├── app.py                                 # 🔄 BACKWARD-COMPATIBLE RUNNER FACADE
├── docker-compose.yml                     # 🐳 PRODUCTION CONTAINER ORCHESTRATION
├── Dockerfile                             # 🐳 PRODUCTION MULTI-STAGE DOCKERFILE
└── requirements.txt                       # 📦 PINNED PYTHON DEPENDENCIES
```

---

## ⚡ Quick Start & Deployment

### Option A: Complete Docker Compose Deployment (Recommended)
Launches the entire system (FastAPI backend, React SPA, Qdrant Vector DB, Ollama inference engine with pre-pulled models) with a single command:

```bash
# 1. Copy environment template and configure secrets
cp .env.example .env

# 2. Build and launch all services in detached mode
docker compose up -d --build
```

**Services Launched:**
- **Web Application**: [http://localhost:5000](http://localhost:5000) (Serves compiled React SPA + FastAPI REST API)
- **API Documentation**: [http://localhost:5000/docs](http://localhost:5000/docs) (Swagger UI) & [http://localhost:5000/redoc](http://localhost:5000/redoc)
- **Qdrant Vector Database**: [http://localhost:6333](http://localhost:6333) / [http://localhost:6333/dashboard](http://localhost:6333/dashboard)
- **Ollama Engine**: [http://localhost:11434](http://localhost:11434) (Automatically pulls `nomic-embed-text`, `llama3.1:8b`, and `llava`)

---

### Option B: Local Development (Host Machine)

#### 1. Backend Setup
```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1  # On Windows (or 'source .venv/bin/activate' on Linux/macOS)

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
cp .env.example .env
```

#### 2. Start Local Ollama Models (Optional if using Cloud Keys)
```bash
ollama pull nomic-embed-text   # Dense embeddings (768-dim)
ollama pull llama3.1:8b        # Grounded QA, Policy Agent, and LLM Judges
ollama pull llava              # Vision OCR for scanned pages/images
ollama serve
```

#### 3. Launch the Backend
```bash
# Option 1: Standalone Runner (auto-builds frontend if needed)
python app.py

# Option 2: Direct Uvicorn with Hot Reload
uvicorn backend.main:app --host 127.0.0.1 --port 5000 --reload
```

#### 4. Launch the Frontend (Vite Dev Server)
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## 🛠️ Core RAG Pipeline Capabilities

```text
 ┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌───────────────────┐
 │ File Upload  │ ──► │ Universal Parser │ ──► │ Chunker (Struct  │ ──► │ Embedding Engine  │
 │ (PDF/DOCX/   │     │ & Vision OCR     │     │ or Fixed 128-512)│     │ (Ollama / Gemini) │
 │  TXT/Images) │     │ (PyMuPDF / LLaVA)│     └──────────────────┘     └─────────┬─────────┘
 └──────────────┘     └──────────────────┘                                        │
                                                                                  ▼
 ┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌───────────────────┐
 │ Grounded QA  │ ◄── │ LLM Answer Gen   │ ◄── │ Hybrid Retrieval │ ◄── │ Vector Database   │
 │ & Citations  │     │ (Llama3.1 / Grok)│     │ (BM25 + Dense RRF│     │ (Qdrant / Memory) │
 └──────────────┘     └──────────────────┘     └──────────────────┘     └───────────────────┘
```

1. **Universal Multimodal Ingestion**:
   - Native support for `.pdf`, `.docx`, `.txt`, `.md`, `.csv`, source code, and images (`.png`, `.jpg`, `.jpeg`).
   - Image OCR routes through multimodal vision models (local `llava` or cloud `gemini-3.7-flash`).
2. **Chunking Strategies**:
   - `structured`: Hierarchical boundary-aware chunking preserving markdown and document section context.
   - `128`, `256`, `512`: Fixed-token sliding windows with configurable overlap.
3. **Hybrid Search & Reciprocal Rank Fusion (RRF)**:
   - Combines exact BM25 keyword matching with dense vector similarity via Reciprocal Rank Fusion:
     $$RRF(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
     where $k=10$, normalizing candidate scores to a canonical $0.0 - 1.0$ confidence scale.
4. **Context Validation Gate & Re-ranking**:
   - Prevents hallucinations by rejecting chunks that fall below `EMBED_MIN_SCORE`.
   - Optional second-pass cross-encoder reranking (`RERANK_ENABLED=true`).
5. **Deep-Linked Source Citations**:
   - Chat answers output grounded markdown citation cards.
   - Clicking citation jumps directly into the built-in document viewer to the exact page and highlighted text passage.

---

## 📊 The Evaluation Hub

The application features three dedicated, enterprise-grade evaluation modules accessible via topbar tabs:

```text
       ┌────────────────────────────────────────────────────────┐
       │                 THE EVALUATION HUB                     │
       └──────────────────────────┬─────────────────────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
 ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
 │ 1. RETRIEVAL  │        │  2. WEEK 6    │        │  3. WEEK 7    │
 │   BENCHMARK   │        │  JUDGE EVAL   │        │  POLICY RACE  │
 │               │        │               │        │               │
 │ • Hit-Rate@K  │        │ • Judge V1/V2 │        │ • ReAct Agent │
 │ • MRR Scores  │        │ • Assertions  │        │ • Workflow    │
 │ • 6 Ablations │        │ • 25 Cases    │        │ • 4 Budgets   │
 └───────────────┘        └───────────────┘        └───────────────┘
```

### Module 1: Multi-Strategy Retrieval Benchmark (`/eval/retrieval`)
- Compares retrieval recall and mean reciprocal rank across 6 ablation presets:
  - `tfidf`: Pure sparse keyword baseline.
  - `hybrid_weighted_02` / `hybrid_weighted_06` / `hybrid_weighted_08`: Linear weighting variations.
  - `hybrid_rrf`: Reciprocal Rank Fusion ($k=10$).
  - `hybrid_rrf_rerank`: Hybrid RRF coupled with second-pass cross-encoder reranking.
  - `query_rewrite`: Pre-retrieval LLM question expansion.
- Outputs Hit-Rate@K, MRR, per-query rank position, and diagnostic category breakdown.

### Module 2: LLM Judge & Assertions Evaluator (`/eval/judge`)
- Rigorously benchmarks LLM Judge consistency against **Blind Human Ground Truth**:
  - **Judge V1 (Zero-Shot)**: Canonical zero-shot LLM evaluation prompt.
  - **Judge V2 (Few-Shot)**: Calibrated few-shot prompt trained on real disagreement edge cases.
- **5 Deterministic Rule Assertions**:
  1. `numeric_equality`: Verifies exact statutory numbers (e.g. 24 days leave, 6 months probation).
  2. `cross_section_completeness`: Ensures multi-section policies cite all required sub-clauses.
  3. `temporal_qualification`: Verifies qualifying time horizons and eligibility waiting periods.
  4. `multi_clause_coverage`: Flags truncation when answers drop mandatory conditions.
  5. `refusal_correctness`: Validates out-of-jurisdiction and unstated policy invariant refusals.
- **Background Execution Lifecycle**: Dispatches background evaluation jobs with real-time polling, monotonic progress bars, and cancellation controls.

### Module 3: HR Policy Assistant — ReAct Agent vs Deterministic Workflow Race (`/eval/policy`)
- Direct head-to-head race between an autonomous **ReAct HR Policy Agent** and a **Deterministic 3-Step Workflow**:
  - **ReAct Agent**: Dynamic reasoning loop using 3 external tools (`get_employee_record`, `get_jurisdiction_rules`, `search_handbook`).
  - **Deterministic Workflow**: Step 1 Employee Lookup $\to$ Step 2 Jurisdiction Rules $\to$ Step 3 Handbook Hybrid Search.
- **4 Strict Production Execution Budgets**:
  - **Max Iterations**: 5 steps.
  - **Max Tokens**: 4,000 tokens.
  - **Max Cost**: \$0.05 per query (at standard \$0.002 / 1k token proxy).
  - **Max Wall-Clock Time**: 30.0 seconds.
- **Live Visual Dashboard**: Telemetry comparison cards, latency comparison bars, cost tracking, token metrics, and an interactive **Single-Case Playground**.

---

## 📁 Universal Q&A Dataset Input & Management

Every evaluator module includes a unified dataset manager allowing users to test custom benchmarks alongside canonical data:

```text
 ┌──────────────────────┐     ┌────────────────────────────────────────────────────────┐
 │  [ Import Q&A File ] │ ──► │              Pre-Import Validation Modal               │
 │ (.json, .txt, .md)   │     │  • Total Found  • Valid Rows  • Invalid Rows  • Dups   │
 └──────────────────────┘     └──────────────────────────┬─────────────────────────────┘
                                                         │
                              ┌──────────────────────────┴─────────────────────────────┐
                              ▼                                                        ▼
                    [ Import Valid Rows ]                                          [ Cancel ]
                              │
                              ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────┐
 │                       In-UI Custom Dataset Management Drawer                        │
 │  • Add Case     • Edit Case     • Duplicate Case     • Delete Case    • View Answer │
 └─────────────────────────────────────────────────────────────────────────────────────┘
```

### Supported File Formats:
1. **JSON (`.json`)**:
   ```json
   [
     {
       "case_id": "TC_01",
       "question": "What is the probation period for new recruits?",
       "expected_answer": "Six months for all contracts exceeding 12 months",
       "employee_id": "EMP001",
       "expected_section": "Section 3.6: Probationary Period"
     }
   ]
   ```
2. **Plain Text (`.txt`)**:
   ```text
   # --- Case 01 ---
   Q: What is the standard annual leave entitlement?
   A: 24 working days per annum, accrued at 2 days per month.

   # --- Case 02 ---
   Question: What is the notice period during probation?
   Answer: 1 week written notice.
   ```
3. **Markdown (`.md`)**:
   ```markdown
   ### Case 01
   **Question:** What is the maximum duration for paternity leave?
   **Answer:** Two continuous calendar weeks paid by the company.
   **Section:** Section 5.4: Paternity Leave
   ```

### Key Dataset Features:
- **Pre-Import Validation Modal**: Inspects uploaded files and reports Total Found, Valid Cases, Invalid Cases (with specific reasons), and Duplicate IDs before committing.
- **Auto-Disambiguation**: Automatically fixes duplicate IDs (e.g. `CASE_01`, `CASE_01_2`) with non-blocking warnings.
- **In-UI Authoring**: Add, edit, delete, duplicate, and view answers without leaving the dashboard.
- **Zero Ground-Truth Leakage Guarantee**: Ground-truth answers and values are **strictly quarantined** from the LLM prompt context during retrieval and generation. Ground truth is only evaluated post-generation by deterministic assertions and scorecards.
- **Isolated Browser Persistence**: LocalStorage persistence is isolated per evaluator (`judge_custom_dataset`, `retrieval_custom_dataset`, `policy_custom_dataset`).

---

## 🌐 Complete REST API Route Reference

### 1. Ingestion & Documents
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/upload` | Uploads, chunks, embeds, and indexes document files |
| `POST` | `/load-url` | Scrapes, parses, and indexes web content |
| `POST` | `/remove` | Removes a document from active vector index |
| `POST` | `/clear` | Clears all documents and vectors for the active session |
| `GET` | `/status` | Returns session document counts and backend configuration |
| `GET` | `/file/{doc_id}` | HTML document viewer page |
| `GET` | `/file/{doc_id}/raw` | Streams raw file bytes for browser PDF plugin rendering |
| `GET` | `/file/{doc_id}/pages` | Returns extracted text pages for text viewer |

### 2. Chat & Grounded QA
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/ask` | Hybrid retrieval & grounded answering with citations |
| `GET` | `/traces` | Lists all logged execution traces |
| `POST` | `/replay/{trace_id}` | Replays an execution trace from trace parameters |

### 3. Evaluation & LLM Judges
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/evaluation/dataset/parse` | Universal parser & validator for `.json`, `.txt`, `.md` datasets |
| `GET` | `/api/evaluation/benchmark` | Loads canonical 25-case Week 6 benchmark (all PENDING) |
| `GET` | `/api/evaluation/runs/active` | Queries currently active evaluation run |
| `POST` | `/api/evaluation/runs` | Starts background evaluation run across test cases |
| `GET` | `/api/evaluation/runs/{run_id}` | Polls real-time progress and per-case status |
| `POST` | `/api/evaluation/runs/{run_id}/cancel` | Gracefully cancels an active evaluation run |
| `POST` | `/eval/run` | Executes retrieval ablation benchmark matrix across presets |

### 4. HR Policy Assistant (Week 7)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/policy/cases` | Retrieves the 10 canonical verified HR policy cases |
| `GET` | `/api/policy/employees` | Retrieves canonical employee records (`EMP001` - `EMP010`) |
| `POST` | `/api/policy/agent` | Runs the Autonomous ReAct Policy Agent on a single case |
| `POST` | `/api/policy/workflow` | Runs the Deterministic 3-Step Workflow on a single case |
| `POST` | `/api/policy/benchmark/start` | Starts asynchronous background Agent vs Workflow race |
| `GET` | `/api/policy/benchmark/runs/active` | Retrieves live active policy benchmark run state |
| `GET` | `/api/policy/benchmark/runs/{run_id}` | Polls real-time policy race progress and telemetry |
| `POST` | `/api/policy/benchmark/runs/{run_id}/cancel`| Cancels an active policy benchmark race |

### Standardized Error Response Envelope:
All application errors strictly adhere to the canonical error payload contract:
```json
{
  "success": false,
  "error": {
    "code": "BAD_REQUEST",
    "message": "Descriptive, sanitized error message without raw tracebacks",
    "request_id": "req_84c7df9a_20260925",
    "status_code": 400
  }
}
```

---

## 🛡️ Security, Tracing, & Middleware

1. **Request Correlation (`RequestCorrelationMiddleware`)**:
   - Generates or propagates `X-Request-ID` across every HTTP request (`req_<uuid>`).
   - Tags all internal log records and attaches to API error responses for zero-ambiguity debugging.
2. **Deep Credential & Path Sanitization**:
   - `sanitize_error_message()` intercepts errors before client transmission, redacting API keys (`AIzaSy...`, `sk-...`), basic auth credentials, Windows paths (`C:\Users\...`), and internal system paths.
3. **50 MB Strict Request Body Limit**:
   - `MaxBodySizeMiddleware` enforces a strict 50 MB payload cap on both `Content-Length` headers and streamed/chunked uploads.
4. **Durable Trace Auditing (`traces/traces.jsonl`)**:
   - Every `/ask` query logs a complete execution trace capturing retrieval mode, retrieved chunk IDs, raw model prompt, generated output, latency, and token metrics.

---

## 🧪 Testing & Verification

The repository contains an automated test suite executed via Python's standard `unittest` framework:

```bash
# Run all end-to-end Q&A dataset import tests
python -m unittest tests/test_qa_import_e2e.py -v

# Run evaluation run lifecycle and state-isolation tests
python -m unittest tests/test_eval_lifecycle.py -v

# Run error handling, contract verification, and secret sanitization tests
python -m unittest tests/test_error_handling.py -v

# Run policy agent, workflow, and budget enforcement tests
python -m unittest tests/test_policy_execution.py -v

# Run the complete test suite
python -m unittest discover tests -v
```

### Frontend Verification:
```bash
cd frontend

# TypeScript static type check (0 errors)
npm run typecheck

# Production Vite bundle build
npm run build
```

---

## ⚙️ Environment Variables Reference (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `EMBED_BACKEND` | `ollama` | Embedding provider (`ollama` or `gemini`) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama daemon connection URL |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model name (768-dim) |
| `GEMINI_API_KEY` | *(empty)* | Google AI API key (if `EMBED_BACKEND=gemini`) |
| `CHAT_BACKEND` | `ollama` | Answer generation provider (`ollama` or `xai`) |
| `OLLAMA_CHAT_MODEL` | `llama3.1:8b` | Ollama chat model name |
| `XAI_API_KEY` | *(empty)* | xAI Grok API key (if `CHAT_BACKEND=xai`) |
| `VECTOR_BACKEND` | `qdrant` | Vector storage (`qdrant` or `memory`) |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant database address |
| `QDRANT_API_KEY` | *(empty)* | API key for Qdrant Cloud clusters |
| `RETRIEVAL_MODE` | `hybrid` | Retrieval strategy (`hybrid`, `embed`, `bm25`) |
| `TOP_K` | `5` | Number of candidate context chunks to retrieve |
| `EMBED_MIN_SCORE` | `0.55` | Minimum RRF relevance threshold score |
| `MAX_CONTEXT_TOKENS` | `6000` | Context window token budget |
| `SECRET_KEY` | *(generated)* | Cryptographic key for session cookie signing |
| `TRACE_LOG_PATH` | `traces/traces.jsonl` | Durable execution trace log destination |
| `LOG_LEVEL` | `INFO` | Console logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## ❓ Frequently Asked Questions (FAQ)

**Q: Can I run this system with zero API keys and zero internet access?**  
**A:** Yes! Set `EMBED_BACKEND=ollama`, `CHAT_BACKEND=ollama`, and `VECTOR_BACKEND=qdrant` (or `memory`). The entire ingestion, hybrid retrieval, agentic policy race, and LLM judge workflow will execute completely offline on your local CPU/GPU.

**Q: How does the system prevent test-set answer leakage?**  
**A:** Ground-truth answers (`expected_answer` or `expected_value`) are strictly excluded from the prompt sent to the LLM during retrieval and answer generation. They are only utilized post-generation by deterministic assertions and scorecards.

**Q: Where are imported custom datasets stored?**  
**A:** Custom datasets are stored in browser localStorage under module-specific keys (`judge_custom_dataset`, `retrieval_custom_dataset`, `policy_custom_dataset`) to guarantee complete state isolation across evaluators.