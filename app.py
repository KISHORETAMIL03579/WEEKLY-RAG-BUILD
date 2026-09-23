# app.py — Authoritative Backward-Compatible Root Facade
"""
Ask My Docs — Universal Multimodal RAG Application
This module serves as the backwards-compatible entrypoint and re-export facade,
exposing configuration, storage layers, services, evaluation metrics, and the
primary FastAPI application from the clean, modular `backend/` package.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
_ROOT_DIR = Path(__file__).resolve().parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# ─────────────────────────────────────────────────────────────────────────────
#  1. Primary FastAPI Application & Factory
# ─────────────────────────────────────────────────────────────────────────────
from backend.main import app, create_app

# ─────────────────────────────────────────────────────────────────────────────
#  2. Configuration & Environment
# ─────────────────────────────────────────────────────────────────────────────
from backend.config import (
    ADMIN_API_KEY,
    ALLOWED_EXTENSIONS,
    APP_DEBUG,
    BASE_DIR,
    BM25_B,
    BM25_K1,
    CHAT_BACKEND,
    DEFAULT_CHUNK_MODE,
    DEFAULT_CHUNK_SIZE,
    EMBED_BACKEND,
    EMBED_BATCH,
    EMBED_MIN_SCORE,
    EMBED_MODEL,
    FRONTEND_DIR,
    FRONTEND_DIST,
    GEMINI_API_KEY,
    GEMINI_URL,
    GEMINI_VISION_MODEL,
    HOST,
    HYBRID_ALPHA,
    LLM_MODEL,
    LOG_LEVEL,
    MAX_CONTENT_LENGTH,
    MAX_CONTEXT_TOKENS,
    OLLAMA_CHAT_MODEL,
    OLLAMA_EMBED_MODEL,
    OLLAMA_URL,
    OLLAMA_VISION_MODEL,
    ORPHAN_LOG_PATH,
    PORT,
    QDRANT_API_KEY,
    QDRANT_CANDIDATE_POOL,
    QDRANT_SCROLL_LIMIT,
    QDRANT_TIMEOUT,
    QDRANT_URL,
    QUERY_REWRITE_ENABLED,
    RERANK_ENABLED,
    RERANK_MIN_RELEVANCE,
    RERANK_TOP_N,
    RETRIEVAL_MODE,
    RRF_K,
    SAFETY_MIN_SCORE,
    SECRET_KEY,
    SESSION_COOKIE_MAX_AGE,
    SESSION_COOKIE_SECURE,
    TFIDF_MIN_SCORE,
    TOP_K,
    TRACE_LOG_PATH,
    UPLOAD_FOLDER,
    VECTOR_BACKEND,
    VECTOR_FOLDER,
    VISION_BACKEND,
    XAI_API_KEY,
    XAI_MODEL,
    XAI_URL,
    logger,
)

# ─────────────────────────────────────────────────────────────────────────────
#  3. Middleware & Frontend Build Assurance
# ─────────────────────────────────────────────────────────────────────────────
from backend.middleware import MaxBodySizeMiddleware, ensure_frontend_built

# ─────────────────────────────────────────────────────────────────────────────
#  4. Schemas
# ─────────────────────────────────────────────────────────────────────────────
from backend.schemas.chat import (
    AskPayload,
    AskRequest,
    AskResponse,
    ClearResponse,
    HealthzResponse,
    ReadyzResponse,
    SourceMetadata,
    StatusDocument,
    StatusResponse,
    _LenientModel,
)
from backend.schemas.document import (
    LoadUrlRequest,
    OkResponse,
    RemovePayload,
    RemoveRequest,
    RemoveResponse,
    UploadCancelPayload,
    UploadCancelRequest,
    UrlPayload,
)
from backend.schemas.evaluation import (
    EvalModeResult,
    EvalQuestion,
    EvalQuestionInput,
    EvalQuestionResult,
    EvalRunPayload,
    EvalRunRequest,
    EvalRunResponse,
    JudgeCasePayload,
    JudgeEvalPayload,
    Week6CasePayload,
    Week6EvalPayload,
)
from backend.schemas.trace import (
    ReplayResponse,
    TraceRecord,
    TracesResponse,
)

# ─────────────────────────────────────────────────────────────────────────────
#  5. Storage & Session Layers
# ─────────────────────────────────────────────────────────────────────────────
from backend.storage.exceptions import RetrievalBackendError
from backend.storage.orphan_store import (
    ORPHANED_DOCS,
    get_orphan_lock,
    is_admin_request,
    load_orphaned_docs,
    read_durable_orphans,
    record_orphaned_doc,
    resolve_orphaned_doc,
    _get_orphan_lock,
    _is_admin_request,
    _load_orphaned_docs,
    _read_durable_orphans,
    _record_orphaned_doc,
    _resolve_orphaned_doc,
)
from backend.storage.qdrant_store import QdrantVectorStore
from backend.storage.session_manager import (
    CANCELLED_UPLOADS,
    CANCELLED_UPLOAD_TTL,
    CHUNK_COUNTS,
    HASH_BY_DOC,
    HASH_STORE,
    MAX_SESSIONS,
    NoActiveSessionError,
    OptionalSessionId,
    RequiredSessionId,
    RequiredStore,
    SESSION_ACCESS,
    SESSION_FILES,
    SESSION_TTL,
    SessionId,
    VECTOR_STORE,
    _MANIFEST_MTIMES,
    _cleanup_session_files,
    _get_store,
    _load_session_manifest,
    _manifest_path,
    _save_session_manifest,
    _save_upload_to,
    _sweep_cancelled_uploads,
    _sweep_orphan_uploads,
    allowed_file,
    cleanup_session_files,
    ensure_session_id,
    evict_session_store,
    get_store,
    load_session_manifest,
    make_store,
    manifest_path,
    optional_session_id,
    require_session_id,
    require_session_store,
    save_session_manifest,
    save_upload_to,
    sweep_cancelled_uploads,
    sweep_orphan_uploads,
)
from backend.storage.trace_store import (
    QA_PROMPT_VERSION,
    RERANK_PROMPT_VERSION,
    REWRITE_PROMPT_VERSION,
    TRACES,
    TraceStore,
    get_prompt,
    redact,
    redact_deep,
    register_prompt,
)
from backend.storage.vector_store import VectorStore, cosine

# ─────────────────────────────────────────────────────────────────────────────
#  6. Services & Workflow Logic
# ─────────────────────────────────────────────────────────────────────────────
from backend.services.chunker import (
    chunk_text,
    fixed_chunk,
    structured_chunk,
    looks_like_plain_heading,
    parse_blocks,
    split_sentences,
    split_by_sentences,
)
from backend.services.embeddings import (
    embed_text,
    embed_texts,
    embeddings_configured,
)
_embeddings_configured = embeddings_configured

from backend.services.evaluation_runner import (
    EvaluationRunManager,
    EvaluationRunState,
)
from backend.services.llm import (
    chat_call,
    chat_configured,
)
_chat_configured = chat_configured
_chat_call = chat_call
from backend.services.reranker import (
    rerank_with_llm,
    rewrite_query,
)
from backend.services.search import (
    _is_dont_know,
    build_index,
    compute_tf,
    cosine_sim,
    hybrid_search,
    is_dont_know,
    reciprocal_rank_fusion,
    search_chunks,
    synthesize_answer,
    tfidf_vector,
    tokenize,
)
from backend.services.text_extractor import (
    _validate_url_is_public,
    extract_code_pages,
    extract_data_pages,
    extract_docx_pages,
    extract_document_pages,
    extract_image_pages,
    extract_pdf_pages,
    extract_txt_pages,
    fetch_web_page,
)

# ─────────────────────────────────────────────────────────────────────────────
#  7. Evaluation & Metrics
# ─────────────────────────────────────────────────────────────────────────────
from backend.evaluation.assertions import (
    handbook_version_present,
    numeric_policy_value_present,
    out_of_jurisdiction_refusal,
    policy_section_reference_present,
    policy_section_reference_resolves,
    run_all_assertions,
)
from backend.evaluation.judge import (
    call_llm_judge,
    call_llm_judge_detailed,
    check_ollama_health,
    evaluate_case_deterministically,
    evaluate_case_with_judge,
    evaluate_case_with_judge_detailed,
    parse_judge_output,
    run_judge_suite,
)
from backend.evaluation.metrics import (
    _hit_check,
    _rr_rank,
    hit_check,
    rr_rank,
)
from backend.evaluation.retrieval_runner import (
    EVAL_PRESETS,
    _run_eval_preset,
    run_eval_preset,
)

__all__ = [
    "app",
    "create_app",
    "ensure_frontend_built",
    "MaxBodySizeMiddleware",
    "VectorStore",
    "QdrantVectorStore",
    "TraceStore",
    "TRACES",
    "EvaluationRunManager",
]

# ─────────────────────────────────────────────────────────────────────────────
#  8. Root CLI Execution Entry Point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", PORT))
    host = os.environ.get("HOST", HOST)
    debug = os.environ.get("APP_DEBUG", "").lower() in ("1", "true", "yes") or APP_DEBUG

    embed_label = "Ollama (local)" if EMBED_BACKEND == "ollama" else "Gemini"
    chat_label = "Ollama (local)" if CHAT_BACKEND == "ollama" else "xAI Grok"
    mode_label = (
        f"embeddings ({embed_label}) + LLM ({chat_label})"
        if (embeddings_configured() and chat_configured())
        else "TF-IDF (offline fallback)"
    )

    print(f"\n🚀 Ask My Docs is running → http://localhost:{port}")
    print(f"   Mode: {mode_label}")
    print(f"   API docs: http://localhost:{port}/docs\n")

    ensure_frontend_built()

    uvicorn.run(
        "backend.main:app" if debug else app,
        host=host,
        port=port,
        reload=debug,
        log_level="debug" if debug else "info",
    )