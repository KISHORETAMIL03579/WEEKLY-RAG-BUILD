from __future__ import annotations

import contextvars
import hashlib
import sqlite3
import threading
import time
import uuid
from functools import wraps
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from backend.storage.shared_state import state_connection


class ChatRunCancelled(Exception):
    """Raised when a chat request has been explicitly cancelled by its client."""


class ChatRun:
    def __init__(self, run_id: str, session_hash: str):
        self.run_id = run_id
        self.session_hash = session_hash
        self.cancelled = threading.Event()
        self.completed = threading.Event()
        self._lock = threading.Lock()
        self._response: Any = None
        self.updated_at = time.monotonic()
        self._last_shared_check = 0.0
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

    def start_heartbeat(self) -> None:
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_shared_run,
            name=f"ChatRunHeartbeat-{self.run_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_shared_run(self) -> None:
        while not self._heartbeat_stop.wait(_SHARED_HEARTBEAT_INTERVAL):
            if _shared_run_cancelled(self.run_id, self.session_hash, heartbeat=True):
                self.cancel()
                return

    def check(self) -> None:
        if self.cancelled.is_set():
            raise ChatRunCancelled()
        now = time.monotonic()
        if now - self._last_shared_check >= _SHARED_POLL_INTERVAL:
            self._last_shared_check = now
            if _shared_run_cancelled(self.run_id, self.session_hash):
                self.cancelled.set()
        with self._lock:
            self.updated_at = now
        if self.cancelled.is_set():
            raise ChatRunCancelled()

    def attach_response(self, response: Any) -> None:
        with self._lock:
            self.updated_at = time.monotonic()
            self._response = response
            cancelled = self.cancelled.is_set()
        if cancelled:
            response.close()
            raise ChatRunCancelled()

    def detach_response(self, response: Any) -> None:
        with self._lock:
            if self._response is response:
                self._response = None
            self.updated_at = time.monotonic()

    def cancel(self) -> bool:
        with self._lock:
            if self.completed.is_set():
                return False
            self.cancelled.set()
            response = self._response
            self.updated_at = time.monotonic()
        if response is not None:
            response.close()
        return True

    def finish(self) -> None:
        with self._lock:
            self.completed.set()
            self.updated_at = time.monotonic()
        self._heartbeat_stop.set()
        _finish_shared_run(self.run_id)


_runs: Dict[str, ChatRun] = {}
_runs_lock = threading.Lock()
_current_run: contextvars.ContextVar[Optional[ChatRun]] = contextvars.ContextVar(
    "current_chat_run", default=None
)
_RUN_TTL_SECONDS = 300
_MAX_TRACKED_RUNS = 10_000
_SHARED_POLL_INTERVAL = 0.25
_SHARED_HEARTBEAT_INTERVAL = 30.0


def _register_shared_run(run_id: str, session_hash: str) -> None:
    now = time.time()
    with state_connection(immediate=True) as connection:
        connection.execute(
            "DELETE FROM chat_runs WHERE updated_at < ?",
            (now - _RUN_TTL_SECONDS,),
        )
        try:
            connection.execute(
                """
                INSERT INTO chat_runs (run_id, status, session_hash, updated_at)
                VALUES (?, 'active', ?, ?)
                """,
                (run_id, session_hash, now),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409, detail="Chat run ID is already in use"
            ) from exc


def _cancel_shared_run(run_id: str, session_hash: str) -> bool:
    now = time.time()
    with state_connection(immediate=True) as connection:
        cursor = connection.execute(
            """
            UPDATE chat_runs SET status = 'cancelling', updated_at = ?
            WHERE run_id = ? AND session_hash = ?
              AND status IN ('active', 'cancelling')
              AND updated_at >= ?
            """,
            (now, run_id, session_hash, now - _RUN_TTL_SECONDS),
        )
        return cursor.rowcount > 0


def _shared_run_cancelled(
    run_id: str, session_hash: str, *, heartbeat: bool = False
) -> bool:
    now = time.time()
    with state_connection(immediate=heartbeat) as connection:
        row = connection.execute(
            """
            SELECT status FROM chat_runs
            WHERE run_id = ? AND session_hash = ?
            """,
            (run_id, session_hash),
        ).fetchone()
        if heartbeat and row and row[0] == "active":
            connection.execute(
                """
                UPDATE chat_runs SET updated_at = ?
                WHERE run_id = ? AND session_hash = ? AND status = 'active'
                """,
                (now, run_id, session_hash),
            )
    return bool(row and row[0] == "cancelling")


def _finish_shared_run(run_id: str) -> None:
    with state_connection(immediate=True) as connection:
        connection.execute(
            "UPDATE chat_runs SET status = 'completed', updated_at = ? WHERE run_id = ?",
            (time.time(), run_id),
        )


def get_current_chat_run() -> Optional[ChatRun]:
    return _current_run.get()


def get_chat_run(run_id: str) -> Optional[ChatRun]:
    with _runs_lock:
        run = _runs.get(run_id)
        if run and time.monotonic() - run.updated_at > _RUN_TTL_SECONDS:
            _runs.pop(run_id, None)
            return None
        return run


def cancel_chat_run(run_id: str, session_id: Optional[str]) -> bool:
    if not session_id:
        return False
    session_hash = hashlib.sha256(session_id.encode()).hexdigest()[:16]
    if not _cancel_shared_run(run_id, session_hash):
        return False
    with _runs_lock:
        run = _runs.get(run_id)
    if run:
        run.cancel()
    return True


def _payload_from_call(args: tuple[Any, ...], kwargs: Dict[str, Any]) -> Any:
    if "payload" in kwargs:
        return kwargs["payload"]
    return next((arg for arg in reversed(args) if hasattr(arg, "run_id")), None)


def _session_from_call(args: tuple[Any, ...], kwargs: Dict[str, Any]) -> Optional[str]:
    if "sid" in kwargs:
        return kwargs["sid"]
    return next((arg for arg in args if isinstance(arg, str)), None)


def managed_chat_run(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        payload = _payload_from_call(args, kwargs)
        run_id = getattr(payload, "run_id", None) or f"run_{uuid.uuid4().hex}"
        session_id = _session_from_call(args, kwargs)
        session_hash = (
            hashlib.sha256(session_id.encode()).hexdigest()[:16] if session_id else ""
        )
        run = ChatRun(run_id, session_hash)
        now = time.monotonic()
        with _runs_lock:
            expired = [
                key
                for key, item in _runs.items()
                if now - item.updated_at > _RUN_TTL_SECONDS
            ]
            for key in expired:
                _runs.pop(key, None)
            if len(_runs) >= _MAX_TRACKED_RUNS:
                completed = [
                    key for key, item in _runs.items() if item.completed.is_set()
                ]
                for key in completed:
                    _runs.pop(key, None)
            if len(_runs) >= _MAX_TRACKED_RUNS:
                raise HTTPException(
                    status_code=503, detail="Chat capacity is temporarily full"
                )
            _register_shared_run(run_id, session_hash)
            _runs[run_id] = run

        token = _current_run.set(run)
        try:
            run.start_heartbeat()
            result = function(*args, **kwargs)
            run.check()
            if isinstance(result, dict):
                result.setdefault("run_id", run_id)
            elif isinstance(result, JSONResponse):
                result.headers.setdefault("X-Run-ID", run_id)
            return result
        except ChatRunCancelled:
            return JSONResponse(
                {"error": "Request cancelled", "run_id": run_id}, status_code=499
            )
        finally:
            run.finish()
            _current_run.reset(token)

    return wrapped
