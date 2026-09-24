# backend/routes/chat.py — Conversational RAG, Status & Health Endpoints
from __future__ import annotations

import time
import uuid
import hashlib
import urllib.request
import urllib.error
from typing import Any, Optional
from fastapi import APIRouter, Body, Response
from fastapi.responses import JSONResponse

from backend.config import (
    CHAT_BACKEND,
    EMBED_BACKEND,
    EMBED_MIN_SCORE,
    LLM_MODEL,
    MAX_CONTEXT_TOKENS,
    OLLAMA_URL,
    QUERY_REWRITE_ENABLED,
    RERANK_ENABLED,
    RETRIEVAL_MODE,
    SAFETY_MIN_SCORE,
    TFIDF_MIN_SCORE,
    TOP_K,
    VECTOR_BACKEND,
    get_app_symbol,
    logger,
)
from backend.schemas.chat import (
    AskPayload,
    ClearResponse,
    HealthzResponse,
    ReadyzResponse,
    StatusResponse,
)
from backend.services.embeddings import embed_text, embeddings_configured
from backend.services.llm import chat_configured, RAGTracer
from backend.services.reranker import rerank_with_llm, rewrite_query
from backend.services.search import (
    fit_to_token_budget,
    generate_answer,
    hybrid_search,
    is_dont_know,
    reciprocal_rank_fusion,
    search_chunks,
    synthesize_answer,
    validate_context,
)
from backend.storage.exceptions import RetrievalBackendError
from backend.storage.orphan_store import ORPHANED_DOCS, resolve_orphaned_doc
from backend.storage.session_manager import (
    CHUNK_COUNTS,
    HASH_BY_DOC,
    HASH_STORE,
    OptionalSessionId,
    SESSION_ACCESS,
    SESSION_FILES,
    VECTOR_STORE,
    cleanup_session_files,
    get_store,
)
from backend.storage.trace_store import (
    QA_PROMPT_VERSION,
    TRACES,
    redact,
    redact_deep,
)

# Backward-compatibility alias
AskRequest = AskPayload

router = APIRouter(tags=["chat"])


@router.post("/ask")
def ask(sid: OptionalSessionId, payload: Optional[AskPayload] = Body(default=None)):
    if not sid:
        return JSONResponse({"error": "No documents uploaded yet"}, status_code=400)

    payload = payload or AskPayload()
    query = (payload.query or "").strip()
    method_filter = (payload.chunk_mode or "").strip() or None

    # Dynamic TOP_K and TEMPERATURE from request payload (fallback to env/defaults).
    top_k = max(1, min(20, payload.top_k)) if payload.top_k is not None else get_app_symbol("TOP_K", TOP_K)
    temperature = max(0.0, min(1.0, payload.temperature)) if payload.temperature is not None else get_app_symbol("DEFAULT_TEMPERATURE", 0.3)

    trace_id = str(uuid.uuid4())
    _t0 = time.time()

    fn_get_store = get_app_symbol("_get_store", get_store)
    fn_embeddings_configured = get_app_symbol("_embeddings_configured", embeddings_configured)
    fn_chat_configured = get_app_symbol("_chat_configured", chat_configured)
    fn_rrf = get_app_symbol("reciprocal_rank_fusion", reciprocal_rank_fusion)
    fn_hybrid = get_app_symbol("hybrid_search", hybrid_search)
    fn_rerank = get_app_symbol("rerank_with_llm", rerank_with_llm)
    fn_rewrite = get_app_symbol("rewrite_query", rewrite_query)
    fn_generate = get_app_symbol("generate_answer", generate_answer)
    fn_synthesize = get_app_symbol("synthesize_answer", synthesize_answer)
    fn_validate = get_app_symbol("validate_context", validate_context)
    fn_is_dont_know = get_app_symbol("_is_dont_know", is_dont_know)

    traces_store = get_app_symbol("TRACES", TRACES)
    embed_min_score_val = get_app_symbol("EMBED_MIN_SCORE", EMBED_MIN_SCORE)
    safety_min_score_val = get_app_symbol("SAFETY_MIN_SCORE", SAFETY_MIN_SCORE)
    tfidf_min_score_val = get_app_symbol("TFIDF_MIN_SCORE", TFIDF_MIN_SCORE)
    retrieval_mode_val = get_app_symbol("RETRIEVAL_MODE", RETRIEVAL_MODE)
    rerank_enabled_val = get_app_symbol("RERANK_ENABLED", RERANK_ENABLED)
    query_rewrite_val = get_app_symbol("QUERY_REWRITE_ENABLED", QUERY_REWRITE_ENABLED)
    llm_model_val = get_app_symbol("LLM_MODEL", LLM_MODEL)
    max_context_tokens_val = get_app_symbol("MAX_CONTEXT_TOKENS", MAX_CONTEXT_TOKENS)

    store = fn_get_store(sid)
    search_query = fn_rewrite(query) if query_rewrite_val else query

    def log_ask_trace(
        *,
        retrieval_mode: str,
        retrieved: list[dict],
        valid_context: bool,
        model: Optional[str],
        temperature: Optional[float],
        prompt_version: Optional[str],
        raw_output: Optional[str],
        answer: str,
        found: bool,
        rerank_score: Optional[float] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Writes one durable, replayable /ask trace record with strict PII redaction."""
        record = {
            "trace_id": trace_id,
            "session_id_hash": hashlib.sha256(sid.encode()).hexdigest()[:16],
            "question": redact(query),
            "search_query": redact(search_query) if search_query != query else None,
            "chunk_mode_filter": method_filter,
            "retrieval_mode": retrieval_mode,
            "top_k": top_k,
            "embed_min_score": embed_min_score_val,
            "rerank_enabled": rerank_enabled_val,
            "rerank_score": rerank_score,
            "retrieved": redact_deep([
                {
                    "chunk_id": r.get("id"),
                    "doc_id": r.get("doc_id"),
                    "filename": r.get("filename"),
                    "page": r.get("page"),
                    "section": r.get("section"),
                    "score": round(r["score"], 4) if r.get("score") is not None else None,
                    "text": r.get("text"),
                }
                for r in (retrieved or [])
            ]),
            "valid_context": valid_context,
            "model": model,
            "temperature": temperature,
            "prompt_version": prompt_version,
            "raw_output": redact(raw_output),
            "answer": redact(answer),
            "found": found,
            "latency_ms": round((time.time() - _t0) * 1000, 1),
        }
        if extra:
            record.update(redact_deep(extra))
        traces_store.log(record)

    RAGTracer.trace("RETRIEVAL", 1, 6, "Question Received", {
        "User Question": query,
        "Session ID": sid[:8],
        "Strategy Filter": method_filter or "All",
        "Total Session Chunks": len(store.chunks),
        "Top-K": top_k,
        "Temperature": temperature,
    })

    if query_rewrite_val and search_query != query:
        RAGTracer.trace("RETRIEVAL", 2, 6, "Query Rewriting", {
            "Original Question": query,
            "Rewritten Search Query": search_query,
        })

    def annotate_openable(results: list[dict]) -> list[dict]:
        files_map = get_app_symbol("SESSION_FILES", SESSION_FILES)
        files = files_map.get(sid, {})
        for r in results:
            r["openable"] = r["doc_id"] in files
        return results

    if not store.chunks:
        return {
            "found": False,
            "answer": "No documents have been uploaded yet. Please upload a PDF, text file, or web page first.",
            "sources": [],
            "top_k": top_k,
            "temperature": temperature,
        }

    active_store = store
    if method_filter:
        active_store = store.filtered_by_method(method_filter)
        if not active_store.chunks:
            return {
                "found": False,
                "answer": (
                    f"No documents are indexed under the '{method_filter}' chunking "
                    f"strategy yet. Upload one under that strategy first, or ask "
                    f"without a strategy filter to search everything indexed."
                ),
                "sources": [],
                "top_k": top_k,
                "temperature": temperature,
            }

    # Path 1: embeddings + LLM (if configured and vectors exist)
    if fn_embeddings_configured() and fn_chat_configured() and active_store.vectors and len(active_store.vectors) == len(active_store.chunks):
        try:
            if retrieval_mode_val == "hybrid-legacy":
                raw_results = fn_hybrid(active_store, search_query, top_k=top_k)
            elif retrieval_mode_val == "embed":
                q_vec = embed_text(search_query)
                raw_results = active_store.query(q_vec, top_k=top_k, min_score=0.0)
            else:  # "hybrid" (default) — Reciprocal Rank Fusion
                raw_results = fn_rrf(active_store, search_query, top_k=top_k)
            near_miss = raw_results[0] if raw_results else None

            # Bounded Safety Threshold: If the top match clears EMBED_MIN_SCORE (confirming topical relevance),
            # admit supporting context candidates down to SAFETY_MIN_SCORE (default 0.40) to prevent candidate starvation.
            if near_miss and near_miss.get("score", 0.0) >= embed_min_score_val:
                results = [r for r in raw_results if r["score"] >= safety_min_score_val]
            else:
                results = [r for r in raw_results if r["score"] >= embed_min_score_val]

            RAGTracer.trace("RETRIEVAL", 3, 6, "Hybrid Retrieval & RRF Fusion", {
                "Retrieval Mode": retrieval_mode_val,
                "Top-K Requested": top_k,
                "Raw Candidates Returned": len(raw_results),
                "Above Min Threshold (" + str(embed_min_score_val) + ")": len(results),
                "Admitted Candidates": len(results),
                "Top Match Score": f"{near_miss['score']:.4f}" if near_miss else "0.0000",
                "Top Source File": near_miss["filename"] if near_miss else "None",
            })

            rerank_score = None
            if rerank_enabled_val and len(results) > 1:
                results, rerank_score = fn_rerank(query, results)
                RAGTracer.trace("RETRIEVAL", 4, 6, "LLM Reranker Evaluation", {
                    "Reranker Status": "Active",
                    "Candidates Evaluated": len(results),
                    "Top Relevance Score": f"{rerank_score:.1f}/10" if rerank_score else "N/A",
                })

            results = fit_to_token_budget(results, max_context_tokens_val)
            valid = fn_validate(results, embed_min_score_val, query, rerank_score)

            RAGTracer.trace("RETRIEVAL", 5, 6, "Context Validation Gate", {
                "Threshold Gate": "PASSED" if valid else "FAILED",
                "Min Required Score": embed_min_score_val,
                "Context Token Budget": f"{max_context_tokens_val} tokens",
                "Valid Grounding Chunks": len(results),
            })

            if not valid:
                log_ask_trace(
                    retrieval_mode=retrieval_mode_val,
                    retrieved=raw_results,
                    valid_context=False,
                    model=llm_model_val,
                    temperature=temperature,
                    prompt_version=None,
                    raw_output=None,
                    answer="I don't know — no document content matched your question closely enough.",
                    found=False,
                    rerank_score=rerank_score,
                )
                return {
                    "found": False,
                    "answer": "I don't know — no document content matched your question closely enough.",
                    "sources": [],
                    "trace_id": trace_id,
                    "top_k": top_k,
                    "temperature": temperature,
                    "closest_match": ({
                        "filename": near_miss["filename"],
                        "section": near_miss.get("section"),
                        "page": near_miss.get("page"),
                        "score": round(near_miss["score"], 4),
                        "threshold": embed_min_score_val,
                    } if near_miss else None),
                }

            answer = fn_generate(query, results, temperature=temperature)
            RAGTracer.trace("RETRIEVAL", 6, 6, "LLM Answer Generation", {
                "Model Identifier": llm_model_val,
                "Temperature": temperature,
                "Sources Grounded": len(results),
                "Answer Character Count": len(answer),
            })
            log_ask_trace(
                retrieval_mode=retrieval_mode_val,
                retrieved=results,
                valid_context=True,
                model=llm_model_val,
                temperature=temperature,
                prompt_version=QA_PROMPT_VERSION,
                raw_output=answer,
                answer=answer or "I don't know.",
                found=not fn_is_dont_know(answer),
                rerank_score=rerank_score,
            )
            return {
                "found": not fn_is_dont_know(answer),
                "answer": answer or "I don't know.",
                "sources": annotate_openable(results),
                "trace_id": trace_id,
                "top_k": top_k,
                "temperature": temperature,
            }
        except RetrievalBackendError as exc:
            logger.error("❌ Vector database retrieval failed in /ask: %s", exc, exc_info=True)
            return JSONResponse({
                "error": f"Vector database retrieval failed: {exc}",
                "status": 503,
            }, status_code=503)
        except urllib.error.HTTPError as exc:
            reason = {
                400: "Bad request — check your API key format and model name.",
                401: "Invalid or expired API key — check API credentials.",
                403: "Access forbidden — verify your API key has the required permissions.",
                429: "Rate limited by API — too many requests too quickly.",
            }.get(exc.code, f"Unexpected HTTP {exc.code} from LLM/Embedding API.")
            logger.warning(
                "Embeddings/LLM path failed for a query — falling back to TF-IDF-only. %s",
                reason, exc_info=True,
            )
        except Exception:
            logger.warning(
                "Embeddings/LLM path failed for a query — falling back to TF-IDF-only.",
                exc_info=True,
            )

    # Path 2: offline TF-IDF fallback
    chunks = active_store.chunks
    index = active_store.get_tfidf_index()
    results = search_chunks(search_query, chunks, index, top_k=top_k)
    results = fit_to_token_budget(results, max_context_tokens_val)
    if not fn_validate(results, tfidf_min_score_val, query):
        near_miss = results[0] if results else None
        log_ask_trace(
            retrieval_mode="tfidf",
            retrieved=results,
            valid_context=False,
            model="tfidf-template",
            temperature=None,
            prompt_version=None,
            raw_output=None,
            answer="I don't know — no document content matched your question closely enough.",
            found=False,
        )
        return {
            "found": False,
            "answer": "I don't know — no document content matched your question closely enough.",
            "sources": [],
            "trace_id": trace_id,
            "top_k": top_k,
            "temperature": temperature,
            "closest_match": ({
                "filename": near_miss["filename"],
                "section": near_miss.get("section"),
                "page": near_miss.get("page"),
                "score": round(near_miss["score"], 4),
                "threshold": tfidf_min_score_val,
            } if near_miss else None),
        }

    resp = fn_synthesize(query, results)
    resp["sources"] = annotate_openable(resp.get("sources", []))
    resp["trace_id"] = trace_id
    resp["top_k"] = top_k
    resp["temperature"] = temperature
    log_ask_trace(
        retrieval_mode="tfidf",
        retrieved=results,
        valid_context=True,
        model="tfidf-template",
        temperature=None,
        prompt_version=None,
        raw_output=resp.get("answer"),
        answer=resp.get("answer"),
        found=resp.get("found", True),
    )
    return resp


@router.get("/status", response_model=StatusResponse)
def status(sid: OptionalSessionId):
    fn_get_store = get_app_symbol("_get_store", get_store)
    fn_embeddings_configured = get_app_symbol("_embeddings_configured", embeddings_configured)
    files_map = get_app_symbol("SESSION_FILES", SESSION_FILES)
    retrieval_mode_val = get_app_symbol("RETRIEVAL_MODE", RETRIEVAL_MODE)
    vec_backend_val = get_app_symbol("VECTOR_BACKEND", VECTOR_BACKEND)

    chunks = fn_get_store(sid).chunks if sid else []
    session_files = files_map.get(sid, {})

    docs_seen: dict[str, dict] = {}
    for c in chunks:
        if c["doc_id"] not in docs_seen:
            docs_seen[c["doc_id"]] = {
                "filename": c["filename"],
                "doc_id": c["doc_id"],
                "chunk_count": 0,
                "method": c["method"],
                "openable": c["doc_id"] in session_files,
            }
        docs_seen[c["doc_id"]]["chunk_count"] += 1

    return StatusResponse(
        total_chunks=len(chunks),
        documents=list(docs_seen.values()),
        methods=sorted({c["method"] for c in chunks}),
        mode=(retrieval_mode_val if fn_embeddings_configured() else "tfidf-only"),
        vector_backend=vec_backend_val,
    )


@router.post("/clear", response_model=ClearResponse, response_model_exclude_none=True)
def clear(sid: OptionalSessionId):
    backend_error = None
    fn_get_store = get_app_symbol("_get_store", get_store)
    fn_resolve_orphan = get_app_symbol("_resolve_orphaned_doc", resolve_orphaned_doc)
    orphans_map = get_app_symbol("ORPHANED_DOCS", ORPHANED_DOCS)
    vector_store_map = get_app_symbol("VECTOR_STORE", VECTOR_STORE)
    hash_store_map = get_app_symbol("HASH_STORE", HASH_STORE)
    hash_by_doc_map = get_app_symbol("HASH_BY_DOC", HASH_BY_DOC)
    chunk_counts_map = get_app_symbol("CHUNK_COUNTS", CHUNK_COUNTS)

    if sid:
        store = fn_get_store(sid)
        store.clear()
        backend_error = getattr(store, "last_backend_error", None)
        if not backend_error:
            orphans = list(orphans_map.get(sid, []))
            for o in orphans:
                if o.get("doc_id"):
                    fn_resolve_orphan(sid, o["doc_id"])
        vector_store_map.pop(sid, None)
        SESSION_ACCESS.pop(sid, None)
        hash_store_map.pop(sid, None)
        hash_by_doc_map.pop(sid, None)
        chunk_counts_map.pop(sid, None)
        cleanup_session_files(sid)
    resp = ClearResponse(ok=True)
    if backend_error:
        resp.warning = (
            f"Cleared locally, but the vector database delete "
            f"failed: {backend_error}. The data may still exist in the backend."
        )
    return resp


@router.get("/healthz", response_model=HealthzResponse)
def healthz():
    """Liveness endpoint for deployment monitoring."""
    fn_embeddings_configured = get_app_symbol("_embeddings_configured", embeddings_configured)
    fn_chat_configured = get_app_symbol("_chat_configured", chat_configured)
    retrieval_mode_val = get_app_symbol("RETRIEVAL_MODE", RETRIEVAL_MODE)
    vec_backend_val = get_app_symbol("VECTOR_BACKEND", VECTOR_BACKEND)

    return HealthzResponse(
        status="ok",
        embeddings_configured=fn_embeddings_configured(),
        chat_configured=fn_chat_configured(),
        chat_backend=CHAT_BACKEND,
        embeddings_backend=EMBED_BACKEND,
        retrieval_mode=retrieval_mode_val if fn_embeddings_configured() else "tfidf-only",
        vector_backend=vec_backend_val,
        active_sessions=len(SESSION_ACCESS),
    )


@router.get("/readyz", response_model=ReadyzResponse)
def readyz(response: Response):
    """Readiness endpoint: verifies external dependencies are reachable without expensive LLM inference."""
    checks = {"app": True}
    status_code = 200
    vec_backend_val = get_app_symbol("VECTOR_BACKEND", VECTOR_BACKEND)

    if vec_backend_val == "qdrant":
        try:
            from backend.storage.qdrant_store import _client
            _client().get_collections()
            checks["qdrant"] = True
        except Exception as exc:
            logger.warning("Readiness check: Qdrant unreachable: %s", exc)
            checks["qdrant"] = False
            status_code = 503

    if EMBED_BACKEND == "ollama" or CHAT_BACKEND == "ollama":
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", headers={"User-Agent": "AskMyDocs-Readyz"})
            with urllib.request.urlopen(req, timeout=2.0) as r:
                if r.status == 200:
                    checks["ollama"] = True
                else:
                    checks["ollama"] = False
                    status_code = 503
        except Exception as exc:
            logger.warning("Readiness check: Ollama unreachable at %s: %s", OLLAMA_URL, exc)
            checks["ollama"] = False
            status_code = 503

    response.status_code = status_code
    return ReadyzResponse(ready=status_code == 200, checks=checks)

