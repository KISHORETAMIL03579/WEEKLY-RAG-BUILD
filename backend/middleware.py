# backend/middleware.py — Custom Middleware & Frontend Build Checks
import os
import sys
import subprocess
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
        print(f"[ERROR] frontend/package.json not found at {FRONTEND_DIR}", file=sys.stderr)
        logger.error("frontend/package.json not found at %s", FRONTEND_DIR)
        raise SystemExit(1)

    npm_cmd = "npm.cmd" if sys.platform.startswith("win") else "npm"
    logger.info("[BUILD] React frontend not built. Executing '%s run build' in %s...", npm_cmd, FRONTEND_DIR)
    print(f"\n[BUILD] Building React 18 + Vite frontend ({npm_cmd} run build)...")

    try:
        res = subprocess.run(
            [npm_cmd, "run", "build"],
            cwd=str(FRONTEND_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            print(f"[ERROR] Frontend build failed (exit code {res.returncode}):\n", file=sys.stderr)
            if res.stdout:
                print(res.stdout, file=sys.stderr)
            if res.stderr:
                print(res.stderr, file=sys.stderr)
            logger.error("Frontend build failed:\n%s\n%s", res.stdout, res.stderr)
            raise SystemExit(1)

        if not index_html.exists():
            print("[ERROR] Frontend build finished with code 0 but frontend/dist/index.html was not generated.", file=sys.stderr)
            logger.error("Frontend build did not create %s", index_html)
            raise SystemExit(1)

        print("[OK] Frontend build completed successfully!\n")
        logger.info("[OK] Frontend build completed.")
        return True
    except FileNotFoundError:
        print(
            f"[ERROR] '{npm_cmd}' was not found in PATH.\n"
            f"   Node.js and npm are required to build the frontend when frontend/dist is missing.\n"
            f"   Please install Node.js 18+ or run 'npm run build' inside frontend/.",
            file=sys.stderr,
        )
        logger.error("'%s' not found in PATH when building frontend.", npm_cmd)
        raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[ERROR] Unexpected error while building frontend: {exc}", file=sys.stderr)
        logger.error("Unexpected error during frontend build: %s", exc, exc_info=True)
        raise SystemExit(1)


def register_middleware(app: FastAPI) -> None:
    """Registers standard application middleware (SessionMiddleware, MaxBodySizeMiddleware)."""
    # Note: Starlette executes middleware in reverse addition order
    app.add_middleware(MaxBodySizeMiddleware, max_body_size=MAX_CONTENT_LENGTH)
    app.add_middleware(
        SessionMiddleware,
        secret_key=SECRET_KEY,
        max_age=SESSION_COOKIE_MAX_AGE,
        https_only=SESSION_COOKIE_SECURE,
        same_site="lax",
    )
