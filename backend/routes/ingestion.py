# backend/routes/ingestion.py — Document Upload, URL Fetching, and Deletion Endpoints
from __future__ import annotations

import time
import uuid
import hashlib
import urllib.parse
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Body, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from werkzeug.utils import secure_filename

from backend.config import UPLOAD_FOLDER, VECTOR_BACKEND, get_app_symbol, logger
from backend.schemas.document import (
    OkResponse,
    RemovePayload,
    RemoveResponse,
    UploadCancelPayload,
    UrlPayload,
)
from backend.services.chunker import chunk_text
from backend.services.embeddings import embed_texts, embeddings_configured
from backend.services.llm import RAGTracer
from backend.services.text_extractor import (
    extract_pdf_pages,
    extract_txt_pages,
    fetch_web_page,
)
from backend.storage.orphan_store import (
    is_admin_request,
    read_durable_orphans,
    record_orphaned_doc,
    resolve_orphaned_doc,
)
from backend.storage.session_manager import (
    CANCELLED_UPLOADS,
    CHUNK_COUNTS,
    HASH_BY_DOC,
    HASH_STORE,
    OptionalSessionId,
    RequiredSessionId,
    SESSION_FILES,
    SessionId,
    allowed_file,
    get_store,
    save_session_manifest,
    save_upload_to,
    sweep_cancelled_uploads,
    persist_session_metadata,
    serialize_session_mutation,
)
from backend.storage.shared_state import (
    claim_session_hash,
    clear_upload_cancellation,
    commit_session_hash,
    release_session_hash,
    remove_session_document_hash,
    request_upload_cancellation,
    upload_cancellation_requested,
)

# Backward-compatibility aliases
UploadCancelRequest = UploadCancelPayload
LoadUrlRequest = UrlPayload
RemoveRequest = RemovePayload

router = APIRouter(tags=["ingestion"])


@router.post("/upload-cancel", response_model=OkResponse)
def upload_cancel(payload: Optional[UploadCancelPayload] = Body(default=None)):
    """Signals that an in-flight /upload call should be cancelled."""
    sweep_cancelled_uploads()
    cancelled_map = get_app_symbol("CANCELLED_UPLOADS", CANCELLED_UPLOADS)
    upload_id = ((payload.upload_id if payload else None) or "").strip()
    if upload_id:
        request_upload_cancellation(upload_id)
        cancelled_map[upload_id] = time.time()
    return OkResponse()


@router.post("/upload")
@serialize_session_mutation
def upload(
    sid: SessionId,
    files: list[UploadFile] = File(default=[]),
    chunk_mode: str = Form(default="structured"),
    upload_id: str = Form(default=""),
):
    upload_id = (upload_id or "").strip()
    sweep_cancelled_uploads()

    upload_folder = get_app_symbol("UPLOAD_FOLDER", UPLOAD_FOLDER)
    vec_backend_val = get_app_symbol("VECTOR_BACKEND", VECTOR_BACKEND)
    fn_get_store = get_app_symbol("_get_store", get_store)
    fn_embeddings_configured = get_app_symbol(
        "_embeddings_configured", embeddings_configured
    )
    fn_embed_texts = get_app_symbol("embed_texts", embed_texts)
    fn_save_manifest = get_app_symbol("_save_session_manifest", save_session_manifest)
    fn_record_orphan = get_app_symbol("_record_orphaned_doc", record_orphaned_doc)
    fn_resolve_orphan = get_app_symbol("_resolve_orphaned_doc", resolve_orphaned_doc)

    hash_store_map = get_app_symbol("HASH_STORE", HASH_STORE)
    hash_by_doc_map = get_app_symbol("HASH_BY_DOC", HASH_BY_DOC)
    session_files_map = get_app_symbol("SESSION_FILES", SESSION_FILES)
    chunk_counts_map = get_app_symbol("CHUNK_COUNTS", CHUNK_COUNTS)
    cancelled_map = get_app_symbol("CANCELLED_UPLOADS", CANCELLED_UPLOADS)

    if not files:
        return JSONResponse({"error": "No files provided"}, status_code=400)

    logger.info(
        "📤 Upload request received: %d file(s) (chunk_mode: %s, session: %s)",
        len(files),
        chunk_mode,
        sid[:8],
    )
    store = fn_get_store(sid)
    hashes = hash_store_map.setdefault(sid, set())
    embedding_ok = fn_embeddings_configured()
    results = []
    pending: list[dict] = []

    RAGTracer.trace(
        "INGESTION",
        1,
        5,
        "Upload Request Received",
        {
            "Files Count": len(files),
            "Chunk Strategy": chunk_mode,
            "Session ID": sid[:8],
            "Embeddings Enabled": embedding_ok,
        },
    )

    for f in files:
        if not f or not allowed_file(f.filename or ""):
            logger.warning(
                "⚠️ Unsupported file type uploaded: %s", getattr(f, "filename", "?")
            )
            results.append(
                {
                    "filename": getattr(f, "filename", "?") or "?",
                    "error": "Unsupported file type (allowed: PDF, TXT, MD)",
                }
            )
            continue

        original_name = f.filename
        ext = (original_name.rsplit(".", 1)[1] if "." in original_name else "").lower()

        safe_name = secure_filename(original_name) or "document"
        if not safe_name.lower().endswith("." + ext):
            safe_name = f"{safe_name}.{ext}"
        filepath = upload_folder / f"{uuid.uuid4()}_{safe_name}"

        dedupe_key = None
        try:
            save_upload_to(f, filepath)
            with open(filepath, "rb") as fh:
                content_hash = hashlib.sha256(fh.read()).hexdigest()
            dedupe_key = (content_hash, chunk_mode)

            if not claim_session_hash(sid, content_hash, chunk_mode):
                filepath.unlink(missing_ok=True)
                logger.info(
                    "ℹ️ Duplicate upload skipped for '%s' under mode '%s'",
                    original_name,
                    chunk_mode,
                )
                results.append(
                    {
                        "filename": original_name,
                        "error": (
                            f"Already indexed under the '{chunk_mode}' strategy — "
                            f"pick a different chunking strategy to compare, or remove "
                            f"the existing one first."
                        ),
                    }
                )
                continue
            hashes.add(dedupe_key)

            doc_id = str(uuid.uuid4())[:8]
            doc_info = {"doc_id": doc_id, "filename": original_name}

            pages = (
                extract_pdf_pages(str(filepath))
                if ext == "pdf"
                else extract_txt_pages(str(filepath))
            )

            if not pages:
                filepath.unlink(missing_ok=True)
                hashes.discard(dedupe_key)
                release_session_hash(sid, *dedupe_key)
                reason = (
                    "No extractable text (password-protected or scanned PDF?)"
                    if ext == "pdf"
                    else "Empty file"
                )
                logger.warning(
                    "⚠️ Text extraction returned empty for '%s': %s",
                    original_name,
                    reason,
                )
                results.append({"filename": original_name, "error": reason})
                continue

            new_chunks = chunk_text(doc_info, pages, chunk_mode)
            if not new_chunks:
                filepath.unlink(missing_ok=True)
                hashes.discard(dedupe_key)
                release_session_hash(sid, *dedupe_key)
                logger.warning("⚠️ Chunking produced 0 chunks for '%s'", original_name)
                results.append(
                    {"filename": original_name, "error": "No chunks produced"}
                )
                continue

            RAGTracer.trace(
                "INGESTION",
                2,
                5,
                "Text Extraction & Chunking",
                {
                    "File Name": original_name,
                    "Format": ext.upper(),
                    "Pages Extracted": len(pages),
                    "Chunks Generated": len(new_chunks),
                    "Doc ID": doc_id,
                },
            )

            chunk_counts_map.setdefault(sid, {})
            for mode in ("structured", "128", "256", "512"):
                chunk_counts_map[sid][mode] = len(chunk_text(doc_info, pages, mode))

            pending.append(
                {
                    "filepath": filepath,
                    "doc_id": doc_id,
                    "filename": original_name,
                    "ext": ext,
                    "chunks": new_chunks,
                    "hash": dedupe_key,
                    "result": {
                        "filename": original_name,
                        "pages": len(pages),
                        "chunks": len(new_chunks),
                        "method": chunk_mode,
                    },
                }
            )
        except Exception as exc:
            filepath.unlink(missing_ok=True)
            if dedupe_key is not None:
                hashes.discard(dedupe_key)
                release_session_hash(sid, *dedupe_key)
            logger.error(
                "❌ Exception during processing '%s': %s",
                original_name,
                exc,
                exc_info=True,
            )
            results.append(
                {"filename": original_name, "error": f"Failed to index: {exc}"}
            )

    if not pending:
        return JSONResponse(
            {
                "ok": False,
                "error": "No valid documents were indexed.",
                "documents": results,
            },
            status_code=400,
        )

    committed_doc_ids: list[str] = []
    was_cancelled = False

    for item in pending:
        if upload_id and (
            upload_id in cancelled_map
            or upload_cancellation_requested(upload_id)
        ):
            was_cancelled = True
            item["filepath"].unlink(missing_ok=True)
            hashes.discard(item["hash"])
            release_session_hash(sid, *item["hash"])
            logger.warning("🚫 Upload cancelled by client for upload_id %s", upload_id)
            continue

        added_to_store = False
        stored_path = None
        try:
            embedding_degraded = False
            if vec_backend_val == "qdrant":
                if not embedding_ok:
                    raise ValueError(
                        "Qdrant vector backend requires embeddings. "
                        "Configure an embedding backend (e.g. GEMINI_API_KEY or OLLAMA) first."
                    )
                try:
                    vectors = fn_embed_texts([c["text"] for c in item["chunks"]])
                except Exception as embed_exc:
                    raise ValueError(
                        f"Embedding generation failed on Qdrant backend: {embed_exc}"
                    ) from embed_exc
            else:
                if embedding_ok:
                    try:
                        vectors = fn_embed_texts([c["text"] for c in item["chunks"]])
                    except Exception as embed_exc:
                        logger.warning(
                            "⚠️ Embedding failed for '%s', indexing without vectors "
                            "(keyword search only for this document): %s",
                            item["filename"],
                            embed_exc,
                        )
                        vectors = []
                        embedding_degraded = True
                else:
                    vectors = []

            store.add(item["chunks"], vectors)
            added_to_store = True

            stored_path = upload_folder / f"{sid}__{item['doc_id']}.{item['ext']}"
            item["filepath"].replace(stored_path)
            session_files_map.setdefault(sid, {})[item["doc_id"]] = {
                "path": stored_path,
                "name": item["filename"],
            }
            hash_by_doc_map.setdefault(sid, {})[item["doc_id"]] = item["hash"]
            commit_session_hash(sid, *item["hash"], item["doc_id"])
            fn_save_manifest(sid)

            item["result"]["doc_id"] = item["doc_id"]
            item["result"]["openable"] = True
            if embedding_degraded:
                item["result"]["warning"] = (
                    "Indexed with keyword search only — embeddings failed "
                    "(check EMBED_BACKEND config / Ollama server). Semantic "
                    "search won't work for this document until re-uploaded."
                )
            results.append(item["result"])
            committed_doc_ids.append(item["doc_id"])
            RAGTracer.trace(
                "INGESTION",
                5,
                5,
                "Store Commit Completed",
                {
                    "File Name": item["filename"],
                    "Doc ID": item["doc_id"],
                    "Chunks Indexed": len(item["chunks"]),
                    "Vector Backend": vec_backend_val,
                    "Total Session Chunks": len(store.chunks),
                },
            )
            logger.info(
                "✅ Indexed '%s' (%d chunks, vectors: %s, total store: %d chunks)",
                item["filename"],
                len(item["chunks"]),
                "yes" if bool(vectors) else "no",
                len(store.chunks),
            )
        except Exception as exc:
            cleanup_complete = True
            cleanup_error = None
            orphan_rec = None
            if added_to_store:
                try:
                    store.remove_doc(item["doc_id"])
                    fn_resolve_orphan(sid, item["doc_id"])
                except Exception as rb_exc:
                    cleanup_complete = False
                    cleanup_error = f"Vector store rollback failed: {rb_exc}"
                    logger.error(
                        "❌ CRITICAL: Failed to rollback vector store for doc %s ('%s'): %s. Vector may be orphaned.",
                        item["doc_id"],
                        item["filename"],
                        rb_exc,
                        exc_info=True,
                    )
                    orphan_rec = fn_record_orphan(
                        sid=sid,
                        doc_id=item["doc_id"],
                        filename=item["filename"],
                        error=str(rb_exc),
                        stored_path=stored_path or item["filepath"],
                    )
            if stored_path and stored_path.exists():
                stored_path.unlink(missing_ok=True)
            item["filepath"].unlink(missing_ok=True)
            hashes.discard(item["hash"])
            release_session_hash(sid, *item["hash"])
            session_files_map.get(sid, {}).pop(item["doc_id"], None)
            hash_by_doc_map.get(sid, {}).pop(item["doc_id"], None)
            fn_save_manifest(sid)
            logger.error(
                "❌ Failed to index '%s': %s", item["filename"], exc, exc_info=True
            )
            doc_res = {
                "filename": item["filename"],
                "error": f"Failed to index: {exc}",
                "cleanup_complete": cleanup_complete,
            }
            if not cleanup_complete:
                doc_res["cleanup_error"] = cleanup_error
                doc_res["doc_id"] = item["doc_id"]
                if orphan_rec and orphan_rec.get("reconciliation_persistence_failed"):
                    doc_res["reconciliation_persistence_failed"] = True
            results.append(doc_res)

    if upload_id and (
        upload_id in cancelled_map or upload_cancellation_requested(upload_id)
    ):
        was_cancelled = True
    if was_cancelled:
        logger.warning(
            "🚫 Rolling back %d committed doc(s) due to upload cancellation",
            len(committed_doc_ids),
        )
        failed_rollbacks = []
        for doc_id in committed_doc_ids:
            rollback_ok = False
            try:
                store.remove_doc(doc_id)
                rollback_ok = True
                fn_resolve_orphan(sid, doc_id)
            except Exception as rb_err:
                logger.error(
                    "❌ Failed to remove doc %s from store during cancellation: %s",
                    doc_id,
                    rb_err,
                    exc_info=True,
                )
                file_info = session_files_map.get(sid, {}).get(doc_id)
                orphan_rec = fn_record_orphan(
                    sid=sid,
                    doc_id=doc_id,
                    filename=file_info.get("name") if file_info else "unknown",
                    error=str(rb_err),
                    stored_path=file_info.get("path") if file_info else None,
                )
                failed_rollbacks.append(
                    {
                        "doc_id": doc_id,
                        "error": str(rb_err),
                        "reconciliation_persistence_failed": bool(
                            orphan_rec.get("reconciliation_persistence_failed")
                        ),
                    }
                )

            if rollback_ok:
                info = session_files_map.get(sid, {}).pop(doc_id, None)
                if info:
                    info["path"].unlink(missing_ok=True)
                doc_hash = hash_by_doc_map.get(sid, {}).pop(doc_id, None)
                if doc_hash is not None:
                    hashes.discard(doc_hash)
                    release_session_hash(sid, *doc_hash)
            else:
                if sid in session_files_map and doc_id in session_files_map[sid]:
                    session_files_map[sid][doc_id]["orphan"] = True
                    session_files_map[sid][doc_id]["rollback_error"] = str(
                        failed_rollbacks[-1]["error"]
                    )

        fn_save_manifest(sid)
        cancelled_map.pop(upload_id, None)
        clear_upload_cancellation(upload_id)
        persist_session_metadata(sid)

        if failed_rollbacks:
            return {
                "ok": False,
                "cancelled": True,
                "cleanup_complete": False,
                "error": f"Upload cancelled but cleanup was incomplete: failed to remove {len(failed_rollbacks)} document(s) from vector store.",
                "failed_cleanup": failed_rollbacks,
                "documents": [],
            }
        else:
            return {
                "ok": False,
                "cancelled": True,
                "cleanup_complete": True,
                "error": "Upload cancelled — nothing was indexed.",
                "documents": [],
            }

    return {
        "ok": True,
        "documents": results,
        "total_chunks": len(store.chunks),
        "chunk_comparison": chunk_counts_map.get(sid, {}),
    }


@router.post("/load-url")
@serialize_session_mutation
def load_url(sid: SessionId, payload: Optional[UrlPayload] = Body(default=None)):
    payload = payload or UrlPayload()
    url = (payload.url or "").strip()
    chunk_mode = payload.chunk_mode or "structured"

    if not url:
        return JSONResponse({"error": "Empty URL"}, status_code=400)

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return JSONResponse(
            {"error": "URL must start with http:// or https://"}, status_code=400
        )

    fn_embeddings_configured = get_app_symbol(
        "_embeddings_configured", embeddings_configured
    )
    fn_embed_texts = get_app_symbol("embed_texts", embed_texts)
    fn_fetch_web_page = get_app_symbol("fetch_web_page", fetch_web_page)
    fn_get_store = get_app_symbol("_get_store", get_store)
    vec_backend_val = get_app_symbol("VECTOR_BACKEND", VECTOR_BACKEND)
    chunk_counts_map = get_app_symbol("CHUNK_COUNTS", CHUNK_COUNTS)

    embedding_ok = fn_embeddings_configured()

    try:
        title, text = fn_fetch_web_page(url)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to fetch URL: {exc}"}, status_code=400)

    if len(text.split()) < 20:
        return JSONResponse(
            {"error": "Page returned too little text to index."}, status_code=400
        )

    doc_id = str(uuid.uuid4())[:8]
    doc_info = {"doc_id": doc_id, "filename": title[:80] or parsed.netloc}
    pages = [{"page": 1, "text": text}]

    new_chunks = chunk_text(doc_info, pages, chunk_mode)
    if not new_chunks:
        return JSONResponse(
            {"error": "No chunks produced from this page."}, status_code=400
        )

    store = fn_get_store(sid)
    if vec_backend_val == "qdrant":
        if not embedding_ok:
            return JSONResponse(
                {
                    "error": "Qdrant vector backend requires embeddings. Configure an embedding backend first."
                },
                status_code=503,
            )
        try:
            vectors = fn_embed_texts([c["text"] for c in new_chunks])
            store.add(new_chunks, vectors)
        except Exception as exc:
            return JSONResponse(
                {"error": f"Embedding/indexing failed on Qdrant backend: {exc}"},
                status_code=503,
            )
    else:
        if embedding_ok:
            try:
                vectors = fn_embed_texts([c["text"] for c in new_chunks])
                store.add(new_chunks, vectors)
            except Exception as exc:
                return JSONResponse(
                    {"error": f"Embedding failed: {exc}"}, status_code=500
                )
        else:
            store.add(new_chunks, [])

    chunk_counts_map.setdefault(sid, {})
    for mode in ("structured", "128", "256", "512"):
        chunk_counts_map[sid][mode] = len(chunk_text(doc_info, pages, mode))
    persist_session_metadata(sid)

    return {
        "ok": True,
        "documents": [
            {
                "filename": doc_info["filename"],
                "doc_id": doc_id,
                "openable": False,
                "pages": 1,
                "chunks": len(new_chunks),
                "method": chunk_mode,
            }
        ],
        "total_chunks": len(store.chunks),
        "chunk_comparison": chunk_counts_map.get(sid, {}),
    }


@router.post("/remove", response_model=RemoveResponse, response_model_exclude_none=True)
@serialize_session_mutation
def remove_doc(
    sid: RequiredSessionId, payload: Optional[RemovePayload] = Body(default=None)
):
    """Remove a single document: its chunks, file, manifest entry, and deduplication hash."""
    doc_id = ((payload.doc_id if payload else None) or "").strip()
    if not doc_id:
        return JSONResponse({"error": "Missing doc_id"}, status_code=400)

    fn_get_store = get_app_symbol("_get_store", get_store)
    fn_save_manifest = get_app_symbol("_save_session_manifest", save_session_manifest)
    fn_resolve_orphan = get_app_symbol("_resolve_orphaned_doc", resolve_orphaned_doc)
    session_files_map = get_app_symbol("SESSION_FILES", SESSION_FILES)
    hash_by_doc_map = get_app_symbol("HASH_BY_DOC", HASH_BY_DOC)
    hash_store_map = get_app_symbol("HASH_STORE", HASH_STORE)

    removed_chunks = 0
    store = fn_get_store(sid)
    if any(c["doc_id"] == doc_id for c in store.chunks):
        removed_chunks = store.remove_doc(doc_id)
        backend_error = getattr(store, "last_backend_error", None)
        if not backend_error:
            fn_resolve_orphan(sid, doc_id)

    files = session_files_map.get(sid, {})
    info = files.pop(doc_id, None)
    if info:
        info["path"].unlink(missing_ok=True)
    fn_save_manifest(sid)

    doc_hash = hash_by_doc_map.get(sid, {}).pop(doc_id, None)
    if doc_hash is not None:
        hash_store_map.get(sid, set()).discard(doc_hash)
    remove_session_document_hash(sid, doc_id)
    persist_session_metadata(sid)

    resp = RemoveResponse(ok=True, removed_chunks=removed_chunks)
    backend_error = getattr(store, "last_backend_error", None)
    if backend_error:
        resp.warning = (
            f"Removed locally, but the vector database delete "
            f"failed: {backend_error}. The data may still exist in the backend."
        )
    return resp


@router.get("/orphans")
def list_orphans(
    request: Request,
    sid: OptionalSessionId,
    session_id: Optional[str] = Query(
        default=None,
        description="Admin-only: filter orphans to one session id.",
    ),
):
    """Operational reconciliation endpoint: returns currently unresolved orphaned documents."""
    fn_is_admin = get_app_symbol("_is_admin_request", is_admin_request)
    fn_read_durable = get_app_symbol("_read_durable_orphans", read_durable_orphans)
    is_admin = fn_is_admin(request)

    if not is_admin and not sid:
        return JSONResponse(
            {"error": "Unauthorized: active session or admin credentials required."},
            status_code=401,
        )

    durable_orphans = fn_read_durable()

    if is_admin:
        if session_id:
            raw_records = list(durable_orphans.get(session_id, []))
        else:
            raw_records = [item for items in durable_orphans.values() for item in items]
        return {
            "count": len(raw_records),
            "admin": True,
            "orphans": raw_records,
        }

    records = list(durable_orphans.get(sid, []))
    safe_records = [
        {
            "doc_id": r.get("doc_id"),
            "filename": r.get("filename"),
            "error": "Vector store cleanup failed",
            "timestamp": r.get("timestamp"),
            "status": r.get("status", "orphaned"),
        }
        for r in records
    ]
    return {
        "count": len(safe_records),
        "admin": False,
        "orphans": safe_records,
    }
