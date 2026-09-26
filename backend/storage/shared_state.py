from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from backend.config import BASE_DIR

_configured_path = Path(
    os.environ.get(
        "APP_STATE_DB", str(Path(BASE_DIR) / "vectorstore" / "app_state.sqlite3")
    )
)
APP_STATE_DB = (
    _configured_path
    if _configured_path.is_absolute()
    else Path(BASE_DIR) / _configured_path
)
_schema_lock = threading.Lock()
_schema_ready = False
_schema_ready_path: Optional[Path] = None


class ActiveSharedRunError(Exception):
    def __init__(self, run_id: str):
        super().__init__(run_id)
        self.run_id = run_id


def initialize_shared_state() -> None:
    with state_connection():
        return


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _recover_abandoned_run(
    connection: sqlite3.Connection, namespace: str, run_id: str, owner_pid: int
) -> None:
    if _process_is_alive(owner_pid):
        return
    row = connection.execute(
        """
        SELECT status, snapshot FROM background_runs
        WHERE namespace = ? AND run_id = ?
        """,
        (namespace, run_id),
    ).fetchone()
    if not row or row["status"] not in {"RUNNING", "CANCELLING"}:
        return
    snapshot = json.loads(row["snapshot"])
    snapshot["status"] = "ERROR"
    snapshot["error_message"] = "The worker process exited before the run completed."
    snapshot["updated_at"] = time.time()
    connection.execute(
        """
        UPDATE background_runs SET status = 'ERROR', snapshot = ?, updated_at = ?
        WHERE namespace = ? AND run_id = ?
        """,
        (json.dumps(snapshot), time.time(), namespace, run_id),
    )
    connection.execute(
        "DELETE FROM active_background_runs WHERE namespace = ? AND run_id = ?",
        (namespace, run_id),
    )


def _initialize(connection: sqlite3.Connection) -> None:
    global _schema_ready, _schema_ready_path
    if _schema_ready and _schema_ready_path == APP_STATE_DB:
        return
    with _schema_lock:
        if _schema_ready and _schema_ready_path == APP_STATE_DB:
            return
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS session_activity (
                session_id TEXT PRIMARY KEY,
                last_access REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_metadata (
                session_id TEXT PRIMARY KEY,
                hash_by_doc TEXT NOT NULL DEFAULT '{}',
                chunk_counts TEXT NOT NULL DEFAULT '{}',
                revision INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS session_hashes (
                session_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                chunk_mode TEXT NOT NULL,
                doc_id TEXT,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (session_id, content_hash, chunk_mode)
            );
            CREATE TABLE IF NOT EXISTS upload_cancellations (
                upload_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                session_hash TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS background_runs (
                namespace TEXT NOT NULL,
                run_id TEXT NOT NULL,
                status TEXT NOT NULL,
                snapshot TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                owner_pid INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (namespace, run_id)
            );
            CREATE INDEX IF NOT EXISTS background_runs_updated
                ON background_runs (namespace, updated_at);
            CREATE TABLE IF NOT EXISTS active_background_runs (
                namespace TEXT PRIMARY KEY,
                run_id TEXT NOT NULL
            );
            """)
        run_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(background_runs)")
        }
        if "owner_pid" not in run_columns:
            connection.execute(
                "ALTER TABLE background_runs ADD COLUMN owner_pid INTEGER NOT NULL DEFAULT 0"
            )
        metadata_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(session_metadata)")
        }
        if "revision" not in metadata_columns:
            connection.execute(
                "ALTER TABLE session_metadata ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
            )
        _schema_ready = True
        _schema_ready_path = APP_STATE_DB


@contextmanager
def state_connection(immediate: bool = False) -> Iterator[sqlite3.Connection]:
    APP_STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(APP_STATE_DB, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    _initialize(connection)
    if immediate:
        connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
        try:
            os.chmod(APP_STATE_DB, 0o600)
        except OSError:
            pass


def touch_session(session_id: str, ttl_seconds: int, max_sessions: int) -> List[str]:
    now = time.time()
    removed: List[str] = []
    with state_connection(immediate=True) as connection:
        expired = connection.execute(
            "SELECT session_id FROM session_activity WHERE last_access < ?",
            (now - ttl_seconds,),
        ).fetchall()
        removed.extend(row["session_id"] for row in expired)
        connection.executemany(
            "DELETE FROM session_activity WHERE session_id = ?",
            ((row["session_id"],) for row in expired),
        )
        _clear_session_metadata(connection, [row["session_id"] for row in expired])
        connection.executemany(
            "DELETE FROM session_hashes WHERE session_id = ?",
            ((row["session_id"],) for row in expired),
        )
        connection.execute(
            """
            INSERT INTO session_activity (session_id, last_access) VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET last_access = excluded.last_access
            """,
            (session_id, now),
        )
        active = connection.execute("""
            SELECT session_id FROM session_activity
            ORDER BY last_access DESC, session_id
            """).fetchall()
        evicted = [
            row["session_id"]
            for row in active[max_sessions:]
            if row["session_id"] != session_id
        ]
        if evicted:
            removed.extend(evicted)
            connection.executemany(
                "DELETE FROM session_activity WHERE session_id = ?",
                ((sid,) for sid in evicted),
            )
            _clear_session_metadata(connection, evicted)
            connection.executemany(
                "DELETE FROM session_hashes WHERE session_id = ?",
                ((sid,) for sid in evicted),
            )
    return removed


def _clear_session_metadata(
    connection: sqlite3.Connection, session_ids: List[str]
) -> None:
    for session_id in session_ids:
        connection.execute(
            """
            INSERT INTO session_metadata
                (session_id, hash_by_doc, chunk_counts, revision)
            VALUES (?, '{}', '{}', 1)
            ON CONFLICT(session_id) DO UPDATE SET
                hash_by_doc = '{}', chunk_counts = '{}',
                revision = session_metadata.revision + 1
            """,
            (session_id,),
        )


def get_active_session_access() -> Dict[str, float]:
    now = time.time()
    with state_connection() as connection:
        rows = connection.execute(
            "SELECT session_id, last_access FROM session_activity"
        ).fetchall()
    return {
        row["session_id"]: row["last_access"]
        for row in rows
        if row["last_access"] <= now
    }


def remove_session_state(session_id: str) -> None:
    with state_connection(immediate=True) as connection:
        current = connection.execute(
            "SELECT revision FROM session_metadata WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        revision = (current["revision"] if current else 0) + 1
        connection.execute(
            """
            INSERT INTO session_metadata (session_id, hash_by_doc, chunk_counts, revision)
            VALUES (?, '{}', '{}', ?)
            ON CONFLICT(session_id) DO UPDATE SET
                hash_by_doc = '{}', chunk_counts = '{}', revision = excluded.revision
            """,
            (session_id, revision),
        )
        connection.execute(
            "DELETE FROM session_hashes WHERE session_id = ?", (session_id,)
        )


def save_session_metadata(
    session_id: str,
    hash_by_doc: Dict[str, Any],
    chunk_counts: Dict[str, Any],
) -> int:
    with state_connection(immediate=True) as connection:
        current = connection.execute(
            "SELECT revision FROM session_metadata WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        revision = (current["revision"] if current else 0) + 1
        connection.execute(
            """
            INSERT INTO session_metadata
                (session_id, hash_by_doc, chunk_counts, revision)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                hash_by_doc = excluded.hash_by_doc,
                chunk_counts = excluded.chunk_counts,
                revision = excluded.revision
            """,
            (
                session_id,
                json.dumps(hash_by_doc),
                json.dumps(chunk_counts),
                revision,
            ),
        )
        connection.execute(
            """
            DELETE FROM session_hashes
            WHERE session_id = ? AND status = 'committed'
            """,
            (session_id,),
        )
        connection.executemany(
            """
            INSERT INTO session_hashes
                (session_id, content_hash, chunk_mode, doc_id, status, created_at)
            VALUES (?, ?, ?, ?, 'committed', ?)
            ON CONFLICT(session_id, content_hash, chunk_mode) DO UPDATE SET
                doc_id = excluded.doc_id, status = 'committed'
            """,
            (
                (session_id, value[0], value[1], doc_id, time.time())
                for doc_id, value in hash_by_doc.items()
            ),
        )
    return revision


def load_session_metadata(session_id: str) -> Optional[Dict[str, Any]]:
    with state_connection() as connection:
        row = connection.execute(
            """
            SELECT hash_by_doc, chunk_counts, revision FROM session_metadata
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "hash_by_doc": json.loads(row["hash_by_doc"]),
        "chunk_counts": json.loads(row["chunk_counts"]),
        "revision": row["revision"],
    }


def claim_session_hash(session_id: str, content_hash: str, chunk_mode: str) -> bool:
    now = time.time()
    with state_connection(immediate=True) as connection:
        connection.execute(
            """
            DELETE FROM session_hashes
            WHERE session_id = ? AND content_hash = ? AND chunk_mode = ?
              AND status = 'pending' AND created_at < ?
            """,
            (session_id, content_hash, chunk_mode, now - 600),
        )
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO session_hashes
                (session_id, content_hash, chunk_mode, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (session_id, content_hash, chunk_mode, now),
        )
    return cursor.rowcount == 1


def commit_session_hash(
    session_id: str, content_hash: str, chunk_mode: str, doc_id: str
) -> None:
    with state_connection(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO session_hashes
                (session_id, content_hash, chunk_mode, doc_id, status, created_at)
            VALUES (?, ?, ?, ?, 'committed', ?)
            ON CONFLICT(session_id, content_hash, chunk_mode) DO UPDATE SET
                doc_id = excluded.doc_id, status = 'committed'
            """,
            (session_id, content_hash, chunk_mode, doc_id, time.time()),
        )


def release_session_hash(
    session_id: str,
    content_hash: str,
    chunk_mode: str,
) -> None:
    with state_connection(immediate=True) as connection:
        connection.execute(
            """
            DELETE FROM session_hashes
            WHERE session_id = ? AND content_hash = ? AND chunk_mode = ?
            """,
            (session_id, content_hash, chunk_mode),
        )


def remove_session_document_hash(session_id: str, doc_id: str) -> None:
    with state_connection(immediate=True) as connection:
        connection.execute(
            "DELETE FROM session_hashes WHERE session_id = ? AND doc_id = ?",
            (session_id, doc_id),
        )


def active_session_count() -> int:
    with state_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM session_activity WHERE last_access >= ?",
            (time.time() - 3600,),
        ).fetchone()
    return int(row["count"])


def request_upload_cancellation(upload_id: str) -> None:
    with state_connection(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO upload_cancellations (upload_id, created_at) VALUES (?, ?)
            ON CONFLICT(upload_id) DO UPDATE SET created_at = excluded.created_at
            """,
            (upload_id, time.time()),
        )


def upload_cancellation_requested(upload_id: str) -> bool:
    with state_connection() as connection:
        row = connection.execute(
            "SELECT created_at FROM upload_cancellations WHERE upload_id = ?",
            (upload_id,),
        ).fetchone()
    return bool(row and time.time() - row["created_at"] <= 600)


def clear_upload_cancellation(upload_id: str) -> None:
    with state_connection(immediate=True) as connection:
        connection.execute(
            "DELETE FROM upload_cancellations WHERE upload_id = ?", (upload_id,)
        )


def sweep_upload_cancellations(ttl_seconds: int = 600) -> None:
    with state_connection(immediate=True) as connection:
        connection.execute(
            "DELETE FROM upload_cancellations WHERE created_at < ?",
            (time.time() - ttl_seconds,),
        )


def create_background_run(
    namespace: str, run_id: str, status: str, snapshot: Dict[str, Any]
) -> None:
    now = time.time()
    with state_connection(immediate=True) as connection:
        active = connection.execute(
            "SELECT run_id FROM active_background_runs WHERE namespace = ?",
            (namespace,),
        ).fetchone()
        if active:
            current = connection.execute(
                """
                SELECT status, owner_pid FROM background_runs
                WHERE namespace = ? AND run_id = ?
                """,
                (namespace, active["run_id"]),
            ).fetchone()
            if current and current["status"] in {"RUNNING", "CANCELLING"}:
                _recover_abandoned_run(
                    connection, namespace, active["run_id"], current["owner_pid"]
                )
                current = connection.execute(
                    """
                    SELECT status FROM background_runs
                    WHERE namespace = ? AND run_id = ?
                    """,
                    (namespace, active["run_id"]),
                ).fetchone()
            if current and current["status"] in {"RUNNING", "CANCELLING"}:
                raise ActiveSharedRunError(active["run_id"])
            connection.execute(
                "DELETE FROM active_background_runs WHERE namespace = ?",
                (namespace,),
            )
        connection.execute(
            """
            INSERT INTO background_runs
                (namespace, run_id, status, snapshot, created_at, updated_at, owner_pid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (namespace, run_id, status, json.dumps(snapshot), now, now, os.getpid()),
        )
        connection.execute(
            """
            INSERT INTO active_background_runs (namespace, run_id) VALUES (?, ?)
            ON CONFLICT(namespace) DO UPDATE SET run_id = excluded.run_id
            """,
            (namespace, run_id),
        )


def save_background_run(
    namespace: str, run_id: str, status: str, snapshot: Dict[str, Any]
) -> str:
    now = time.time()
    with state_connection(immediate=True) as connection:
        current = connection.execute(
            """
            SELECT status, snapshot FROM background_runs
            WHERE namespace = ? AND run_id = ?
            """,
            (namespace, run_id),
        ).fetchone()
        if current and current["status"] == "CANCELLING":
            snapshot = dict(snapshot)
            snapshot["cancellation_requested"] = True
            if status in {"RUNNING", "CANCELLING"}:
                status = "CANCELLING"
                snapshot["status"] = status
            elif status == "COMPLETED":
                status = "CANCELLED"
                snapshot["status"] = status
        connection.execute(
            """
            UPDATE background_runs SET status = ?, snapshot = ?, updated_at = ?
            WHERE namespace = ? AND run_id = ?
            """,
            (status, json.dumps(snapshot), now, namespace, run_id),
        )
        if status not in {"RUNNING", "CANCELLING"}:
            connection.execute(
                """
                DELETE FROM active_background_runs
                WHERE namespace = ? AND run_id = ?
                """,
                (namespace, run_id),
            )
    return status


def request_background_run_cancellation(
    namespace: str, run_id: str
) -> Optional[Dict[str, Any]]:
    with state_connection(immediate=True) as connection:
        row = connection.execute(
            """
            SELECT status, snapshot FROM background_runs
            WHERE namespace = ? AND run_id = ?
            """,
            (namespace, run_id),
        ).fetchone()
        if not row or row["status"] not in {"RUNNING", "CANCELLING"}:
            return None
        snapshot = json.loads(row["snapshot"])
        snapshot["status"] = "CANCELLING"
        snapshot["cancellation_requested"] = True
        connection.execute(
            """
            UPDATE background_runs SET status = 'CANCELLING', snapshot = ?, updated_at = ?
            WHERE namespace = ? AND run_id = ?
            """,
            (json.dumps(snapshot), time.time(), namespace, run_id),
        )
        return snapshot


def get_background_run(namespace: str, run_id: str) -> Optional[Dict[str, Any]]:
    with state_connection() as connection:
        row = connection.execute(
            """
            SELECT snapshot, status, owner_pid FROM background_runs
            WHERE namespace = ? AND run_id = ?
            """,
            (namespace, run_id),
        ).fetchone()
        if row and row["status"] in {"RUNNING", "CANCELLING"}:
            _recover_abandoned_run(connection, namespace, run_id, row["owner_pid"])
            row = connection.execute(
                """
                SELECT snapshot FROM background_runs
                WHERE namespace = ? AND run_id = ?
                """,
                (namespace, run_id),
            ).fetchone()
    return json.loads(row["snapshot"]) if row else None


def get_active_background_run_id(namespace: str) -> Optional[str]:
    with state_connection() as connection:
        row = connection.execute(
            """
            SELECT active_background_runs.run_id, background_runs.status,
                   background_runs.owner_pid
            FROM active_background_runs
            JOIN background_runs USING (namespace, run_id)
            WHERE namespace = ? AND background_runs.status IN ('RUNNING', 'CANCELLING')
            """,
            (namespace,),
        ).fetchone()
        if row and row["status"] in {"RUNNING", "CANCELLING"}:
            _recover_abandoned_run(
                connection, namespace, row["run_id"], row["owner_pid"]
            )
            active = connection.execute(
                "SELECT run_id FROM active_background_runs WHERE namespace = ?",
                (namespace,),
            ).fetchone()
            return active["run_id"] if active else None
    return row["run_id"] if row else None


def list_background_runs(namespace: str) -> List[Dict[str, Any]]:
    with state_connection() as connection:
        active = connection.execute(
            """
            SELECT a.run_id, b.owner_pid
            FROM active_background_runs a
            JOIN background_runs b USING (namespace, run_id)
            WHERE a.namespace = ? AND b.status IN ('RUNNING', 'CANCELLING')
            """,
            (namespace,),
        ).fetchone()
        if active:
            _recover_abandoned_run(
                connection, namespace, active["run_id"], active["owner_pid"]
            )
        rows = connection.execute(
            """
            SELECT snapshot FROM background_runs
            WHERE namespace = ? ORDER BY created_at DESC
            """,
            (namespace,),
        ).fetchall()
    return [json.loads(row["snapshot"]) for row in rows]
