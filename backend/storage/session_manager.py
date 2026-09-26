# backend/storage/session_manager.py — Multi-Session VectorStore Lifecycle & Dependencies
from __future__ import annotations

import os
import time
import json
import uuid
import shutil
import hashlib
from functools import wraps
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Set, Tuple
from fastapi import Depends, HTTPException, Request
from filelock import FileLock, Timeout
from starlette.datastructures import UploadFile

from backend.config import (
    ALLOWED_EXTENSIONS,
    BASE_DIR,
    MAX_CONTENT_LENGTH,
    UPLOAD_FOLDER,
    VECTOR_BACKEND,
    VECTOR_FOLDER,
    get_app_symbol,
    logger,
)
from backend.storage.vector_store import VectorStore
from backend.storage.qdrant_store import QdrantVectorStore
from backend.storage.shared_state import (
    get_active_session_access,
    load_session_metadata,
    remove_session_state,
    save_session_metadata,
    sweep_upload_cancellations,
    touch_session,
)

# Per-session stores
VECTOR_STORE: Dict[str, Any] = {}
SESSION_ACCESS: Dict[str, float] = {}
HASH_STORE: Dict[str, Set[Tuple[str, str]]] = {}
HASH_BY_DOC: Dict[str, Dict[str, Tuple[str, str]]] = {}
SESSION_FILES: Dict[str, Dict[str, dict]] = {}
CHUNK_COUNTS: Dict[str, Dict[str, int]] = {}

CANCELLED_UPLOADS: Dict[str, float] = {}
CANCELLED_UPLOAD_TTL = 10 * 60  # 10 minutes

SESSION_TTL = 60 * 60  # 1 hour
MAX_SESSIONS = 20

_MANIFEST_MTIMES: Dict[str, float] = {}
_SESSION_VERSIONS: Dict[str, int] = {}


def manifest_path(sid: str) -> Path:
    folder = get_app_symbol("UPLOAD_FOLDER", UPLOAD_FOLDER)
    return folder / f"{sid}.manifest.json"


def save_session_manifest(sid: str) -> None:
    files_map = get_app_symbol("SESSION_FILES", SESSION_FILES)
    mtimes_map = get_app_symbol("_MANIFEST_MTIMES", _MANIFEST_MTIMES)
    versions_map = get_app_symbol("_SESSION_VERSIONS", _SESSION_VERSIONS)
    files = files_map.get(sid)
    mpath = manifest_path(sid)
    if files:
        tmp_path = mpath.with_name(f"{mpath.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(
                {
                    doc_id: {"path": str(info["path"]), "name": info["name"]}
                    for doc_id, info in files.items()
                }
            ),
            encoding="utf-8",
        )
        tmp_path.replace(mpath)
        mtimes_map[sid] = mpath.stat().st_mtime
    else:
        mpath.unlink(missing_ok=True)
        mtimes_map.pop(sid, None)
    persist_session_metadata(sid)


def persist_session_metadata(sid: str) -> None:
    hash_by_doc_map = get_app_symbol("HASH_BY_DOC", HASH_BY_DOC)
    chunk_counts_map = get_app_symbol("CHUNK_COUNTS", CHUNK_COUNTS)
    hash_by_doc = {
        doc_id: list(value)
        for doc_id, value in hash_by_doc_map.get(sid, {}).items()
    }
    save_session_metadata(sid, hash_by_doc, chunk_counts_map.get(sid, {}))


def serialize_session_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        sid = kwargs.get("sid") or next(
            (arg for arg in args if isinstance(arg, str)), None
        )
        if not sid:
            return function(*args, **kwargs)
        folder = get_app_symbol("UPLOAD_FOLDER", UPLOAD_FOLDER)
        folder.mkdir(parents=True, exist_ok=True)
        lock_id = hashlib.sha256(sid.encode()).hexdigest()
        lock = FileLock(str(folder / f".session-{lock_id}.lock"))
        try:
            with lock.acquire(timeout=30):
                return function(*args, **kwargs)
        except Timeout as exc:
            raise HTTPException(
                status_code=409,
                detail="Another request is currently updating this session",
            ) from exc

    return wrapped


def load_session_manifest(sid: str) -> None:
    manifest = manifest_path(sid)
    if not manifest.exists():
        files_map = get_app_symbol("SESSION_FILES", SESSION_FILES)
        files_map.pop(sid, None)
        return
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        logger.warning(
            "Corrupted session manifest at %s — ignoring", manifest, exc_info=True
        )
        return
    files: Dict[str, dict] = {}
    for doc_id, meta in data.items():
        p = Path(meta.get("path", ""))
        if p.exists():
            files[doc_id] = {"path": p, "name": meta.get("name", p.name)}
    files_map = get_app_symbol("SESSION_FILES", SESSION_FILES)
    if files or sid in files_map:
        files_map[sid] = files


def cleanup_session_files(sid: str) -> None:
    files_map = get_app_symbol("SESSION_FILES", SESSION_FILES)
    files = files_map.pop(sid, None)
    if files:
        for info in files.values():
            info["path"].unlink(missing_ok=True)
    manifest_path(sid).unlink(missing_ok=True)


def sweep_orphan_uploads() -> None:
    folder = get_app_symbol("UPLOAD_FOLDER", UPLOAD_FOLDER)
    referenced: Set[str] = set()
    for manifest in folder.glob("*.manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(
                "Corrupted manifest during sweep: %s", manifest, exc_info=True
            )
            continue
        for meta in data.values():
            referenced.add(str(Path(meta.get("path", "")).resolve()))
    for f in folder.iterdir():
        if (
            f.name.endswith(".manifest.json")
            or f.name.endswith(".jsonl")
            or f.name.endswith(".lock")
        ):
            continue
        if str(f.resolve()) not in referenced:
            f.unlink(missing_ok=True)


def sweep_cancelled_uploads() -> None:
    now = time.time()
    cancelled_map = get_app_symbol("CANCELLED_UPLOADS", CANCELLED_UPLOADS)
    for uid in [u for u, t in cancelled_map.items() if now - t > CANCELLED_UPLOAD_TTL]:
        cancelled_map.pop(uid, None)
    sweep_upload_cancellations(CANCELLED_UPLOAD_TTL)


def make_store(sid: str):
    vec_backend = get_app_symbol("VECTOR_BACKEND", VECTOR_BACKEND)
    if vec_backend == "qdrant":
        store = QdrantVectorStore(sid)
    else:
        store = VectorStore(sid)
    store.load()
    return store


def evict_session_store(sid: str) -> None:
    vec_folder = get_app_symbol("VECTOR_FOLDER", VECTOR_FOLDER)
    vec_backend = get_app_symbol("VECTOR_BACKEND", VECTOR_BACKEND)
    (vec_folder / f"{sid}.pkl").unlink(missing_ok=True)
    if vec_backend == "qdrant":
        try:
            QdrantVectorStore(sid).clear()
        except Exception:
            logger.warning(
                "Failed to release Qdrant collection for evicted session %s",
                sid,
                exc_info=True,
            )


def get_store(sid: str) -> Any:
    vector_store_map = get_app_symbol("VECTOR_STORE", VECTOR_STORE)
    hash_store_map = get_app_symbol("HASH_STORE", HASH_STORE)
    hash_by_doc_map = get_app_symbol("HASH_BY_DOC", HASH_BY_DOC)
    chunk_counts_map = get_app_symbol("CHUNK_COUNTS", CHUNK_COUNTS)
    files_map = get_app_symbol("SESSION_FILES", SESSION_FILES)
    mtimes_map = get_app_symbol("_MANIFEST_MTIMES", _MANIFEST_MTIMES)
    versions_map = get_app_symbol("_SESSION_VERSIONS", _SESSION_VERSIONS)
    session_access_map = get_app_symbol("SESSION_ACCESS", SESSION_ACCESS)

    for removed_sid in touch_session(sid, SESSION_TTL, MAX_SESSIONS):
        vector_store_map.pop(removed_sid, None)
        session_access_map.pop(removed_sid, None)
        hash_store_map.pop(removed_sid, None)
        hash_by_doc_map.pop(removed_sid, None)
        chunk_counts_map.pop(removed_sid, None)
        mtimes_map.pop(removed_sid, None)
        versions_map.pop(removed_sid, None)
        evict_session_store(removed_sid)
        cleanup_session_files(removed_sid)
    session_access_map.clear()
    session_access_map.update(get_active_session_access())

    metadata = load_session_metadata(sid)
    if metadata is not None:
        hash_by_doc_map[sid] = {
            doc_id: tuple(value)
            for doc_id, value in metadata["hash_by_doc"].items()
        }
        hash_store_map[sid] = set(hash_by_doc_map[sid].values())
        chunk_counts_map[sid] = metadata["chunk_counts"]
    else:
        hash_by_doc_map.pop(sid, None)
        hash_store_map.pop(sid, None)
        chunk_counts_map.pop(sid, None)

    manifest = manifest_path(sid)
    current_mtime = None
    if manifest.exists():
        try:
            current_mtime = manifest.stat().st_mtime
        except OSError:
            pass

    store = vector_store_map.get(sid)
    if store is None:
        load_session_manifest(sid)
        store = make_store(sid)
        vector_store_map[sid] = store
        if metadata is not None:
            versions_map[sid] = metadata["revision"]
        if current_mtime is not None:
            mtimes_map[sid] = current_mtime
    else:
        last_mtime = mtimes_map.get(sid)
        version_changed = metadata is not None and (
            versions_map.get(sid) != metadata["revision"]
        )
        manifest_changed = current_mtime is not None and (
            last_mtime is None or current_mtime != last_mtime
        )
        if version_changed or manifest_changed:
            load_session_manifest(sid)
            store.load()
            if current_mtime is not None:
                mtimes_map[sid] = current_mtime
            if metadata is not None:
                versions_map[sid] = metadata["revision"]
        elif current_mtime is None and last_mtime is not None:
            files_map.pop(sid, None)
            mtimes_map.pop(sid, None)
            store.chunks, store.vectors = [], []
            store._tfidf_index_cache = None

    if metadata is None:
        files = files_map.get(sid, {})
        recovered_hashes: Dict[str, Tuple[str, str]] = {}
        for doc_id, info in files.items():
            path = Path(info["path"])
            if not path.exists():
                continue
            with path.open("rb") as uploaded:
                content_hash = hashlib.sha256(uploaded.read()).hexdigest()
            doc_chunks = [c for c in store.chunks if c.get("doc_id") == doc_id]
            chunk_mode = doc_chunks[0].get("method", "structured") if doc_chunks else "structured"
            recovered_hashes[doc_id] = (content_hash, chunk_mode)
        hash_by_doc_map[sid] = recovered_hashes
        hash_store_map[sid] = set(recovered_hashes.values())
        chunk_counts_map.setdefault(sid, {})
        versions_map[sid] = save_session_metadata(
            sid,
            {doc_id: list(value) for doc_id, value in recovered_hashes.items()},
            chunk_counts_map[sid],
        )
    return store


# Session Dependency Classes
class NoActiveSessionError(Exception):
    """Raised when caller has no session cookie."""


def ensure_session_id(request: Request) -> str:
    sid = request.session.get("session_id")
    if not sid:
        sid = str(uuid.uuid4())
        request.session["session_id"] = sid
    return sid


def require_session_id(request: Request) -> str:
    sid = request.session.get("session_id")
    if not sid:
        raise NoActiveSessionError()
    return sid


def optional_session_id(request: Request) -> Optional[str]:
    return request.session.get("session_id")


def require_session_store(sid: Annotated[str, Depends(require_session_id)]) -> Any:
    fn = get_app_symbol("_get_store", get_store)
    return fn(sid)


SessionId = Annotated[str, Depends(ensure_session_id)]
RequiredSessionId = Annotated[str, Depends(require_session_id)]
OptionalSessionId = Annotated[Optional[str], Depends(optional_session_id)]
RequiredStore = Annotated[Any, Depends(require_session_store)]


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload_to(upload: UploadFile, destination: Path) -> None:
    upload.file.seek(0)
    with open(destination, "wb") as out:
        shutil.copyfileobj(upload.file, out, length=1024 * 1024)
    upload.file.seek(0)


_get_store = get_store
_save_session_manifest = save_session_manifest
_load_session_manifest = load_session_manifest
_cleanup_session_files = cleanup_session_files
_sweep_cancelled_uploads = sweep_cancelled_uploads
_sweep_orphan_uploads = sweep_orphan_uploads
_save_upload_to = save_upload_to
_manifest_path = manifest_path
