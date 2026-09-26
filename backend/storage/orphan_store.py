# backend/storage/orphan_store.py — Durable Orphaned Document Registry
from __future__ import annotations

import os
import json
import hmac
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from filelock import FileLock
from fastapi import Request

from backend.config import ORPHAN_LOG_PATH, ADMIN_API_KEY, get_app_symbol, logger

_ORPHAN_LOCK = threading.Lock()
ORPHANED_DOCS: Dict[str, List[dict]] = (
    {}
)  # In-memory index: sid -> list of orphan records


def is_admin_request(req: Request) -> bool:
    """Validate administrative authorization via ADMIN_API_KEY (Bearer token or X-Admin-Key)."""
    admin_key = get_app_symbol("ADMIN_API_KEY", ADMIN_API_KEY)
    if not admin_key:
        return False
    auth_header = req.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    admin_header = req.headers.get("X-Admin-Key", "").strip()
    candidate = token or admin_header
    if not candidate:
        return False
    return hmac.compare_digest(candidate, admin_key)


_is_admin_request = is_admin_request


def get_orphan_lock(path: Optional[Path] = None) -> FileLock:
    """Acquire a cross-process file lock for the orphan log."""
    target = path or get_app_symbol("ORPHAN_LOG_PATH", ORPHAN_LOG_PATH)
    lock_path = str(target) + ".lock"
    return FileLock(lock_path, timeout=10)


_get_orphan_lock = get_orphan_lock


def record_orphaned_doc(
    sid: str,
    doc_id: str,
    filename: str,
    error: str,
    stored_path: Optional[Path | str] = None,
) -> dict:
    """Durably record an orphaned document in orphans.jsonl and in-memory registry."""
    log_path = get_app_symbol("ORPHAN_LOG_PATH", ORPHAN_LOG_PATH)
    orphans_map = get_app_symbol("ORPHANED_DOCS", ORPHANED_DOCS)

    record = {
        "session_id": sid,
        "doc_id": doc_id,
        "filename": filename,
        "error": str(error),
        "stored_path": str(stored_path) if stored_path else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "orphaned",
    }
    with _ORPHAN_LOCK:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with get_orphan_lock(log_path):
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    f.flush()
                    if hasattr(os, "fsync"):
                        try:
                            os.fsync(f.fileno())
                        except OSError as fsync_err:
                            raise OSError(
                                f"Orphan log fsync failed: {fsync_err}"
                            ) from fsync_err
        except Exception as exc:
            record["reconciliation_persistence_failed"] = True
            logger.critical(
                "❌ CRITICAL OPERATIONAL FAILURE: Failed to write orphan reconciliation record to %s "
                "for doc %s (session %s): %s.",
                log_path,
                doc_id,
                sid,
                exc,
                exc_info=True,
            )

        orphans_map.setdefault(sid, []).append(record)
    return record


def resolve_orphaned_doc(sid: str, doc_id: str) -> bool:
    """Mark an orphan record as resolved when successful cleanup occurs."""
    log_path = get_app_symbol("ORPHAN_LOG_PATH", ORPHAN_LOG_PATH)
    orphans_map = get_app_symbol("ORPHANED_DOCS", ORPHANED_DOCS)

    with _ORPHAN_LOCK:
        in_memory_match = any(
            o.get("doc_id") == doc_id for o in orphans_map.get(sid, [])
        )
        if not in_memory_match:
            durable_records = read_durable_orphans(log_path)
            if not any(o.get("doc_id") == doc_id for o in durable_records.get(sid, [])):
                return False

        record = {
            "session_id": sid,
            "doc_id": doc_id,
            "status": "resolved",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with get_orphan_lock(log_path):
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    f.flush()
                    if hasattr(os, "fsync"):
                        try:
                            os.fsync(f.fileno())
                        except OSError as fsync_err:
                            raise OSError(
                                f"Orphan log fsync failed during resolution: {fsync_err}"
                            ) from fsync_err
        except Exception as exc:
            logger.critical(
                "❌ CRITICAL OPERATIONAL FAILURE: Failed to write orphan resolution to %s for doc %s (session %s): %s.",
                log_path,
                doc_id,
                sid,
                exc,
                exc_info=True,
            )
            return False

        if sid in orphans_map:
            orphans_map[sid] = [
                o for o in orphans_map[sid] if o.get("doc_id") != doc_id
            ]

        return True


def read_durable_orphans(path: Optional[Path] = None) -> Dict[str, List[dict]]:
    """Read and validate all durable orphan log records from disk."""
    log_path = path or get_app_symbol("ORPHAN_LOG_PATH", ORPHAN_LOG_PATH)
    if not log_path.exists():
        return {}

    orphans_by_sid: Dict[str, List[dict]] = {}
    try:
        with get_orphan_lock(log_path):
            with log_path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as err:
                        logger.warning(
                            "Corrupted orphan log line %d in %s: %s",
                            line_no,
                            log_path,
                            err,
                        )
                        continue

                    if not isinstance(record, dict):
                        continue

                    sid = record.get("session_id")
                    doc_id = record.get("doc_id")
                    status = record.get("status")

                    if (
                        not isinstance(sid, str)
                        or not sid.strip()
                        or not isinstance(doc_id, str)
                        or not doc_id.strip()
                    ):
                        continue

                    if status == "resolved":
                        if sid in orphans_by_sid:
                            orphans_by_sid[sid] = [
                                o
                                for o in orphans_by_sid[sid]
                                if o.get("doc_id") != doc_id
                            ]
                    elif status == "orphaned":
                        orphans_by_sid.setdefault(sid, []).append(record)
    except Exception as exc:
        logger.error(
            "Failed to read durable orphan records from %s: %s",
            log_path,
            exc,
            exc_info=True,
        )

    return orphans_by_sid


def load_orphaned_docs() -> None:
    """Load durable orphan records from disk into the in-memory cache on startup."""
    log_path = get_app_symbol("ORPHAN_LOG_PATH", ORPHAN_LOG_PATH)
    orphans_map = get_app_symbol("ORPHANED_DOCS", ORPHANED_DOCS)

    with _ORPHAN_LOCK:
        orphans_map.clear()
        durable = read_durable_orphans(log_path)
        for sid, records in durable.items():
            orphans_map[sid] = list(records)


_load_orphaned_docs = load_orphaned_docs
_record_orphaned_doc = record_orphaned_doc
_resolve_orphaned_doc = resolve_orphaned_doc
_read_durable_orphans = read_durable_orphans

# Initialize in-memory cache on module load
load_orphaned_docs()
