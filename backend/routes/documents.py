# backend/routes/documents.py — Document Inspection & Raw Streaming Endpoints
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from backend.config import FRONTEND_DIST
from backend.services.text_extractor import extract_document_pages
from backend.storage.session_manager import (
    RequiredSessionId,
    RequiredStore,
    SESSION_FILES,
    load_session_manifest,
)

router = APIRouter(tags=["documents"])


@router.get("/file/{doc_id}", include_in_schema=False)
def serve_file(request: Request, doc_id: str, store: RequiredStore):
    """View an uploaded document in the React Single Page Application."""
    sid = request.session.get("session_id")
    info = SESSION_FILES.get(sid, {}).get(doc_id) if sid else None
    doc_chunks = [c for c in store.chunks if c["doc_id"] == doc_id]

    if not info and not doc_chunks:
        return JSONResponse(
            {"error": "File not found or no longer available"}, status_code=404
        )

    index_html = FRONTEND_DIST / "index.html"
    if index_html.exists():
        return FileResponse(str(index_html))

    return JSONResponse(
        {
            "message": "React frontend not built. Run 'npm run build' in the frontend/ directory."
        },
        status_code=503,
    )


@router.get("/file/{doc_id}/raw")
def serve_file_raw(doc_id: str, sid: RequiredSessionId):
    """Stream the raw PDF bytes (used by the viewer page's embedded viewer)."""
    load_session_manifest(sid)
    info = SESSION_FILES.get(sid, {}).get(doc_id)
    if not info or not info["path"].exists():
        return JSONResponse(
            {"error": "File not found or no longer available"}, status_code=404
        )

    return FileResponse(
        info["path"],
        filename=info["name"],
        content_disposition_type="inline",
    )


@router.get("/file/{doc_id}/pages")
def serve_file_pages(doc_id: str, sid: RequiredSessionId, store: RequiredStore):
    """Return the extracted pages (for the text viewer) of an uploaded document."""
    info = SESSION_FILES.get(sid, {}).get(doc_id)
    doc_chunks = [c for c in store.chunks if c["doc_id"] == doc_id]

    if not info and not doc_chunks:
        return JSONResponse(
            {"error": "File not found or no longer available"}, status_code=404
        )

    if info and info["path"].exists():
        name = info["name"]
        ext = (name.rsplit(".", 1)[1] if "." in name else "").lower()
        try:
            pages = extract_document_pages(str(info["path"]), ext)
        except Exception as exc:
            return JSONResponse(
                {"error": f"Could not read document: {exc}"}, status_code=500
            )
    else:
        name = doc_chunks[0]["filename"] if doc_chunks else "Document"
        ext = "txt"
        combined_text = "\n\n".join(c["text"] for c in doc_chunks)
        pages = [{"page": 1, "text": combined_text}]

    return {
        "filename": name,
        "ext": ext,
        "total_pages": len(pages),
        "pages": [
            {"num": i + 1, "text": p.get("text", "")} for i, p in enumerate(pages)
        ],
    }
