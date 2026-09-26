# backend/middleware.py — Custom Middleware & Frontend Build Checks
import os
import sys
import subprocess
import uuid
from pathlib import Path
from typing import Any
from starlette.datastructures import Headers
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi import FastAPI

from backend.config import (
    FRONTEND_DIR,
    FRONTEND_DIST,
    MAX_CONTENT_LENGTH,
    SECRET_KEY,
    SESSION_COOKIE_MAX_AGE,
    SESSION_COOKIE_SECURE,
    logger,
)


class _BodyTooLarge(BaseException):
    """Raised from the wrapped `receive` once a request body exceeds the cap."""


def _too_large_response() -> JSONResponse:
    return JSONResponse({"error": "File too large (max 50 MB)"}, status_code=413)


class MaxBodySizeMiddleware:
    """Enforces a hard cap on request body size (FastAPI equivalent of Flask's MAX_CONTENT_LENGTH)."""

    def __init__(self, app: ASGIApp, max_body_size: int = MAX_CONTENT_LENGTH) -> None:
        self.app = app
        self.max_body_size = max_body_size

    def _declares_oversized_body(self, scope: Scope) -> bool:
        declared = Headers(scope=scope).get("content-length")
        if declared is None:
            return False
        try:
            return int(declared) > self.max_body_size
        except ValueError:
            return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self._declares_oversized_body(scope):
            await _too_large_response()(scope, receive, send)
            return

        received = 0
        exceeded = False
        response_started = False
        replaced = False

        async def limited_receive() -> Any:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_size:
                    exceeded = True
                    raise _BodyTooLarge()
            return message

        async def send_wrapper(message: Any) -> None:
            nonlocal response_started, replaced
            if replaced:
                return
            if message["type"] == "http.response.start":
                if exceeded:
                    replaced = True
                    await _too_large_response()(scope, receive, send)
                    return
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except _BodyTooLarge:
            if not response_started and not replaced:
                await _too_large_response()(scope, receive, send)


class RequestCorrelationMiddleware:
    """
    ASGI middleware ensuring every HTTP request has a unique correlation request_id (req_...).
    - Reads incoming 'X-Request-ID' header or generates a new one.
    - Sets request.state.request_id.
    - Adds 'X-Request-ID' header to all outgoing responses.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        async def send_with_request_id(message: Any) -> None:
            if message["type"] == "http.response.start":
                res_headers = list(message.get("headers", []))
                has_req_id = False
                for i, (k, v) in enumerate(res_headers):
                    if k.lower() == b"x-request-id":
                        res_headers[i] = (k, request_id.encode("latin-1"))
                        has_req_id = True
                        break
                if not has_req_id:
                    res_headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = res_headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)


def ensure_frontend_built(force: bool = False) -> bool:
    """
    Ensures that the React 18 + TypeScript + Vite production build exists.
    Executes 'npm.cmd run build' (Windows) or 'npm run build' (Linux/macOS) in frontend/.
    """
    index_html = FRONTEND_DIST / "index.html"
    if index_html.exists() and not force:
        return True

    package_json = FRONTEND_DIR / "package.json"
    if not package_json.exists():
        logger.warning("frontend/package.json not found at %s", FRONTEND_DIR)
        return False

    npm_cmd = "npm.cmd" if sys.platform.startswith("win") else "npm"
    logger.info(
        "[BUILD] React frontend not built. Executing '%s run build' in %s...",
        npm_cmd,
        FRONTEND_DIR,
    )

    try:
        res = subprocess.run(
            [npm_cmd, "run", "build"],
            cwd=str(FRONTEND_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            logger.warning("Frontend build returned code %d:\n%s\n%s", res.returncode, res.stdout, res.stderr)
            return False

        if not index_html.exists():
            logger.warning("Frontend build finished but %s was not created.", index_html)
            return False

        logger.info("[OK] Frontend build completed.")
        return True
    except FileNotFoundError:
        logger.warning("'%s' not found in PATH when building frontend.", npm_cmd)
        return False
    except Exception as exc:
        logger.warning("Unexpected error during frontend build: %s", exc)
        return False


def register_middleware(app: FastAPI) -> None:
    """Registers standard application middleware (RequestCorrelationMiddleware, SessionMiddleware, MaxBodySizeMiddleware)."""
    # Note: Starlette executes middleware in reverse addition order
    app.add_middleware(MaxBodySizeMiddleware, max_body_size=MAX_CONTENT_LENGTH)
    app.add_middleware(
        SessionMiddleware,
        secret_key=SECRET_KEY,
        max_age=SESSION_COOKIE_MAX_AGE,
        https_only=SESSION_COOKIE_SECURE,
        same_site="lax",
    )
    app.add_middleware(RequestCorrelationMiddleware)
