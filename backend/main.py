# backend/main.py — FastAPI Application Factory & Lifecycles
from __future__ import annotations

import os
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

from backend.config import (
    APP_DEBUG,
    CHAT_BACKEND,
    EMBED_BACKEND,
    FRONTEND_DIST,
    HOST,
    MAX_CONTENT_LENGTH,
    PORT,
    SECRET_KEY,
    SESSION_COOKIE_MAX_AGE,
    SESSION_COOKIE_SECURE,
    logger,
)
from backend.errors import register_exception_handlers
from backend.middleware import (
    MaxBodySizeMiddleware,
    RequestCorrelationMiddleware,
    ensure_frontend_built,
)
from backend.routes.chat import router as chat_router
from backend.routes.documents import router as documents_router
from backend.routes.evaluation import router as evaluation_router
from backend.routes.ingestion import router as ingestion_router
from backend.routes.policy import router as policy_router
from backend.routes.traces import router as traces_router
from backend.services.embeddings import embeddings_configured
from backend.services.llm import chat_configured
from backend.storage.orphan_store import load_orphaned_docs
from backend.storage.session_manager import SessionId


def create_app() -> FastAPI:
    """Factory creating and configuring the primary FastAPI application."""
    app = FastAPI(
        title="Ask My Docs",
        description=(
            "Universal multimodal RAG: upload documents, retrieve with hybrid "
            "BM25 + embedding search fused by RRF, and answer with grounded citations."
        ),
        version="5.0.0",
        middleware=[
            Middleware(MaxBodySizeMiddleware, max_body_size=MAX_CONTENT_LENGTH),
            Middleware(
                SessionMiddleware,
                secret_key=SECRET_KEY,
                session_cookie="session",
                max_age=SESSION_COOKIE_MAX_AGE,
                same_site="lax",
                https_only=SESSION_COOKIE_SECURE,
            ),
            Middleware(RequestCorrelationMiddleware),
        ],
    )

    # Mount static assets if available
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # Standardized application exception handlers
    register_exception_handlers(app)

    # Core Page Routes
    @app.get("/", include_in_schema=False)
    @app.get("/eval", include_in_schema=False)
    @app.get("/eval/judge", include_in_schema=False)
    @app.get("/eval/retrieval", include_in_schema=False)
    @app.get("/eval/policy", include_in_schema=False)
    @app.get("/eval/{subpath:path}", include_in_schema=False)
    def index(request: Request, sid: SessionId, subpath: str = ""):
        index_html = FRONTEND_DIST / "index.html"
        if index_html.exists():
            return FileResponse(str(index_html))
        return JSONResponse(
            {
                "message": "React frontend not built. Run 'npm run build' in the frontend/ directory."
            },
            status_code=503,
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        for path in (
            FRONTEND_DIST / "favicon.ico",
            FRONTEND_DIST / "rag.svg",
        ):
            if path.exists():
                media_type = (
                    "image/x-icon" if path.suffix == ".ico" else "image/svg+xml"
                )
                return FileResponse(path, media_type=media_type)
        return JSONResponse({"error": "Favicon not found"}, status_code=404)

    # Register all modular routers
    for r in (
        chat_router,
        ingestion_router,
        documents_router,
        traces_router,
        evaluation_router,
        policy_router,
    ):
        app.include_router(r)

    # Startup event to load orphans
    @app.on_event("startup")
    def startup_event():
        load_orphaned_docs()

    return app


app = create_app()


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
