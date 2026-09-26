# backend/errors.py — Production-Grade Error Hierarchy & Exception Handlers
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.config import logger

# Common regex patterns to sanitize implementation and environment leaks
_SECRET_PATTERNS = [
    re.compile(
        r"(?i)(api[_-]?key|secret|password|token|bearer\s+[a-zA-Z0-9_\-\.]+)\s*[:=]?\s*['\"]?([^\s'\"]+)"
    ),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z-_]{20,}"),
    re.compile(r"https?://[^:]+:[^@]+@[^\s/]+"),  # URLs with embedded basic auth
    re.compile(r"[a-zA-Z]:\\[^\n\r]+"),  # Windows absolute file paths
    re.compile(
        r"/(?:Users|home|var|tmp|etc|opt|app|usr)/[^\n\r]+"
    ),  # Unix absolute file paths
]


def sanitize_error_message(msg: str) -> str:
    """Removes file paths, secret keys, URLs with credentials, and tracebacks from error messages."""
    if not msg:
        return "An error occurred processing the request."
    cleaned = str(msg)
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    # Avoid exposing raw Python exception prefixes
    cleaned = re.sub(
        r"^(?:Exception|RuntimeError|ValueError|KeyError|TypeError):\s*", "", cleaned
    )
    return cleaned.strip() or "An error occurred processing the request."


def build_error_payload(
    code: str,
    message: str,
    request_id: str,
    retryable: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generates the authoritative production JSON error structure."""
    safe_msg = sanitize_error_message(message)
    error_obj: Dict[str, Any] = {
        "code": code,
        "message": safe_msg,
        "request_id": request_id,
        "retryable": retryable,
    }
    if details is not None:
        error_obj["details"] = details

    return {
        "success": False,
        "error": error_obj,
        "message": safe_msg,
    }


def get_request_id(request: Request) -> str:
    """Extracts existing request_id from request state or header, or generates a fresh one."""
    if hasattr(request, "state") and hasattr(request.state, "request_id"):
        return str(request.state.request_id)
    header_id = request.headers.get("X-Request-ID")
    if header_id:
        return header_id
    new_id = f"req_{uuid.uuid4().hex[:12]}"
    if hasattr(request, "state"):
        request.state.request_id = new_id
    return new_id


class AppError(Exception):
    """Base application exception supporting structured error codes, retryability, and safe details."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_SERVER_ERROR",
        status_code: int = 500,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.details = details


class NotFoundError(AppError):
    def __init__(
        self,
        message: str,
        code: str = "NOT_FOUND",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message, code=code, status_code=404, retryable=False, details=details
        )


class ValidationError(AppError):
    def __init__(
        self,
        message: str,
        code: str = "VALIDATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message, code=code, status_code=422, retryable=False, details=details
        )


class BadRequestError(AppError):
    def __init__(
        self,
        message: str,
        code: str = "BAD_REQUEST",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message, code=code, status_code=400, retryable=False, details=details
        )


class AuthenticationError(AppError):
    def __init__(
        self,
        message: str = "Authentication required",
        code: str = "UNAUTHORIZED",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message, code=code, status_code=401, retryable=False, details=details
        )


class ConflictError(AppError):
    def __init__(
        self,
        message: str,
        code: str = "CONFLICT",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message, code=code, status_code=409, retryable=False, details=details
        )


class RateLimitError(AppError):
    def __init__(
        self,
        message: str = "Rate limit or execution budget exceeded",
        code: str = "RATE_LIMIT_EXCEEDED",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message, code=code, status_code=429, retryable=True, details=details
        )


class DependencyError(AppError):
    def __init__(
        self,
        message: str,
        code: str = "SERVICE_UNAVAILABLE",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message, code=code, status_code=503, retryable=True, details=details
        )


def register_exception_handlers(app: FastAPI) -> None:
    """Registers standard FastAPI exception handlers returning uniform safe error payloads."""
    try:
        from backend.storage.session_manager import NoActiveSessionError
    except ImportError:
        NoActiveSessionError = None

    if NoActiveSessionError:

        @app.exception_handler(NoActiveSessionError)
        async def no_active_session_handler(request: Request, exc: Any) -> JSONResponse:
            req_id = get_request_id(request)
            logger.info(
                "[%s] NoActiveSessionError: Session ID missing or expired", req_id
            )
            return JSONResponse(
                content={"error": "No active session"},
                status_code=400,
                headers={"X-Request-ID": req_id},
            )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        req_id = get_request_id(request)
        if exc.status_code >= 500:
            logger.error(
                "[%s] AppError: %s (code=%s, status=%d)",
                req_id,
                exc.message,
                exc.code,
                exc.status_code,
                exc_info=True,
            )
        else:
            logger.info(
                "[%s] Client error: %s (code=%s, status=%d)",
                req_id,
                exc.message,
                exc.code,
                exc.status_code,
            )

        payload = build_error_payload(
            code=exc.code,
            message=exc.message,
            request_id=req_id,
            retryable=exc.retryable,
            details=exc.details,
        )
        return JSONResponse(
            content=payload,
            status_code=exc.status_code,
            headers={"X-Request-ID": req_id},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        req_id = get_request_id(request)
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMIT_EXCEEDED",
            500: "INTERNAL_SERVER_ERROR",
            503: "SERVICE_UNAVAILABLE",
        }
        code = code_map.get(exc.status_code, "HTTP_ERROR")
        retryable = exc.status_code in (429, 502, 503, 504)
        msg = str(exc.detail) if exc.detail else "HTTP request failed"

        if exc.status_code >= 500:
            logger.error(
                "[%s] HTTPException %d: %s", req_id, exc.status_code, msg, exc_info=True
            )
        else:
            logger.info("[%s] HTTPException %d: %s", req_id, exc.status_code, msg)

        payload = build_error_payload(
            code=code,
            message=msg,
            request_id=req_id,
            retryable=retryable,
        )
        return JSONResponse(
            content=payload,
            status_code=exc.status_code,
            headers={"X-Request-ID": req_id},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        req_id = get_request_id(request)
        logger.info("[%s] RequestValidationError: %s", req_id, exc.errors())

        safe_details = []
        field_keys = {}
        for err in exc.errors():
            loc = ".".join(
                str(p) for p in err.get("loc", ()) if str(p) not in ("body",)
            )
            reason = sanitize_error_message(err.get("msg", "Invalid value"))
            safe_details.append(
                {
                    "field": loc or "body",
                    "reason": reason,
                }
            )
            if loc:
                field_keys[loc] = reason

        field_summary = "; ".join(f"{d['field']}: {d['reason']}" for d in safe_details)
        payload = build_error_payload(
            code="VALIDATION_ERROR",
            message=(
                f"Invalid request parameters: {field_summary}"
                if field_summary
                else "Invalid request parameters"
            ),
            request_id=req_id,
            retryable=False,
            details={"fields": safe_details} if safe_details else None,
        )
        # Inject field keys directly into error dict for backward compatibility test assertions
        for k, v in field_keys.items():
            payload["error"][k] = v

        payload["detail"] = jsonable_encoder(exc.errors())
        return JSONResponse(
            content=payload, status_code=422, headers={"X-Request-ID": req_id}
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        req_id = get_request_id(request)
        logger.exception("[%s] Unhandled server exception: %s", req_id, exc)

        payload = build_error_payload(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred. Please try again.",
            request_id=req_id,
            retryable=True,
        )
        return JSONResponse(
            content=payload, status_code=500, headers={"X-Request-ID": req_id}
        )
