"""Policy evidence retrieval over the chunks a user uploaded (Qdrant).

Nothing in this module (or in the policy tools built on it) contains policy
text, employee data or jurisdiction rules. Every fact a tool returns is read
from the session's indexed chunks (``chunks_<session_id>`` in Qdrant), the same
store the chat page uses. When nothing is indexed the tools say so instead of
answering from memory.

The only static data is *taxonomy* (which jurisdictions and policy categories a
tool accepts, and search hint words per category) in
``backend/data/policy_taxonomy.json``; it selects what to look for and never
supplies an answer.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from backend.config import (
    EMBED_MIN_SCORE,
    RETRIEVAL_MODE,
    SAFETY_MIN_SCORE,
    logger,
)
from backend.services.embeddings import LEXICAL_ONLY, embed_text, embeddings_configured
from backend.services.search import (
    build_index,
    reciprocal_rank_fusion,
    search_chunks,
    validate_context,
)
from backend.storage.exceptions import RetrievalBackendError
from backend.storage.session_manager import get_store

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "policy_taxonomy.json"

# Bound what a single tool observation can add to the model context.
CHUNK_TEXT_LIMIT = 1200
MAX_TOP_K = 20

# A dead embedding service must cost one fast failure, not a stall per tool call:
# embed the query with a short timeout and, after a failure, search lexically for a while.
EMBED_QUERY_TIMEOUT_SECONDS = float(os.environ.get("EMBED_QUERY_TIMEOUT_SECONDS", "8"))
EMBED_COOLDOWN_SECONDS = float(os.environ.get("EMBED_COOLDOWN_SECONDS", "60"))
_embedding_down_until = 0.0
_embedding_lock = threading.Lock()


class PolicyToolError(Exception):
    """A tool failure the model can read: stable code, message, retryability."""

    code = "POLICY_TOOL_ERROR"
    retryable = False

    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.hint = hint

    def to_error(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
        }
        if self.hint:
            payload["hint"] = self.hint
        return payload


class NoIndexedDocumentsError(PolicyToolError):
    code = "NO_INDEXED_DOCUMENTS"


class NoEvidenceError(PolicyToolError):
    """The documents are indexed but do not say anything about the request."""

    code = "NO_EVIDENCE"


class RetrievalUnavailableError(PolicyToolError):
    code = "RETRIEVAL_UNAVAILABLE"
    retryable = True


@dataclass(frozen=True)
class PolicyContext:
    """Request scope handed to tools by the host (never chosen by the model)."""

    session_id: str
    document_ids: tuple[str, ...] = ()

    @classmethod
    def from_meta(cls, meta: Optional[Dict[str, Any]]) -> Optional["PolicyContext"]:
        meta = meta or {}
        session_id = meta.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return None
        documents = meta.get("document_ids") or ()
        return cls(session_id, tuple(str(item) for item in documents))

    def to_meta(self) -> Dict[str, Any]:
        meta: Dict[str, Any] = {"session_id": self.session_id}
        if self.document_ids:
            meta["document_ids"] = list(self.document_ids)
        return meta


@lru_cache(maxsize=1)
def load_taxonomy() -> Dict[str, Any]:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def jurisdictions() -> List[str]:
    return list(load_taxonomy()["jurisdictions"])


def policy_categories() -> List[str]:
    return list(load_taxonomy()["categories"])


# ---------------------------------------------------------------------------
# Store access
# ---------------------------------------------------------------------------

# Rows of an uploaded record table look like ``EMP001 | Name: ... | Tenure (months): 18``.
# The chunker joins lines with spaces and prefixes the section title, so rows are found by
# their ``<id> | Key:`` start marker, never by line breaks.
_RECORD_START = re.compile(r"(?<![\w-])([A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*)\s*\|\s*(?=[^|:]{1,60}:)")


def iter_records(text: str):
    """Yield ``(record_id, body)`` for every ``<id> | Key: value | ...`` row in ``text``."""
    starts = list(_RECORD_START.finditer(text))
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        yield match.group(1), text[match.end():end]


def looks_like_record_table(text: str) -> bool:
    """True for chunks made mostly of record rows (people data, not policy wording)."""
    if not text.strip():
        return False
    covered = sum(len(body) for _, body in iter_records(text))
    return covered / len(text) >= 0.6


class _ScopedStore:
    """Read-only view of a session store restricted to some chunks."""

    def __init__(self, store: Any, keep: Sequence[int]):
        self._store = store
        self._keep = list(keep)
        self.chunks = [store.chunks[i] for i in self._keep]
        aligned = len(store.vectors) == len(store.chunks)
        self.vectors = [store.vectors[i] for i in self._keep] if aligned else []
        self._index: Optional[dict] = None

    def query_scores(self, vector: List[float]) -> List[float]:
        full = self._store.query_scores(vector)
        return [full[i] for i in self._keep]

    def get_tfidf_index(self) -> dict:
        if self._index is None:
            self._index = build_index(self.chunks)
        return self._index


def _session_store(ctx: Optional[PolicyContext]) -> Any:
    if ctx is None:
        raise NoIndexedDocumentsError(
            "No document scope was supplied for this tool call.",
            hint="Upload the policy document and retry from the same browser session.",
        )
    try:
        store = get_store(ctx.session_id)
    except RetrievalBackendError as exc:
        logger.error("Policy store unavailable: %s", exc)
        raise RetrievalUnavailableError(
            "The document index could not be reached.",
            hint="Retry shortly; if it persists the vector database is down.",
        ) from exc
    if not store.chunks:
        raise NoIndexedDocumentsError(
            "No documents are indexed for this session.",
            hint="Upload the HR policy document (and employee records) first.",
        )
    return store


def _scoped(store: Any, ctx: PolicyContext, *, policy_only: bool) -> _ScopedStore:
    wanted = set(ctx.document_ids)
    keep = [
        index
        for index, chunk in enumerate(store.chunks)
        if (not wanted or chunk.get("doc_id") in wanted)
        and not (policy_only and looks_like_record_table(chunk.get("text", "")))
    ]
    return _ScopedStore(store, keep)


def _public_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    text = str(chunk.get("text", ""))
    return {
        "chunk_id": chunk.get("id"),
        "filename": chunk.get("filename"),
        "page": chunk.get("page"),
        "section": chunk.get("section"),
        "score": round(float(chunk.get("score", 0.0)), 4),
        "text": text[:CHUNK_TEXT_LIMIT],
        "truncated": len(text) > CHUNK_TEXT_LIMIT,
    }


def _filenames(store: _ScopedStore) -> List[str]:
    return sorted({str(chunk.get("filename")) for chunk in store.chunks})


# ---------------------------------------------------------------------------
# Policy search
# ---------------------------------------------------------------------------


def _rank(store: _ScopedStore, query: str, top_k: int) -> Dict[str, Any]:
    global _embedding_down_until
    warnings: List[str] = []
    aligned = bool(store.vectors) and len(store.vectors) == len(store.chunks)
    semantic = (
        embeddings_configured()
        and RETRIEVAL_MODE != "tfidf"
        and aligned
        and time.monotonic() >= _embedding_down_until
    )
    if semantic:
        try:
            vector = embed_text(query, timeout=EMBED_QUERY_TIMEOUT_SECONDS)
            raw = reciprocal_rank_fusion(store, query, top_k=top_k, query_vector=vector)
            top = raw[0]["score"] if raw else 0.0
            floor = EMBED_MIN_SCORE if top < EMBED_MIN_SCORE else SAFETY_MIN_SCORE
            results = [chunk for chunk in raw if chunk["score"] >= floor]
            if results and not validate_context(results, EMBED_MIN_SCORE, query):
                results = []
            return {"results": results, "mode": "hybrid", "warnings": warnings}
        except RetrievalBackendError as exc:
            raise RetrievalUnavailableError(
                "Vector retrieval failed.", hint="Retry shortly."
            ) from exc
        except Exception as exc:  # embedding provider outage, malformed vectors, ...
            with _embedding_lock:
                _embedding_down_until = time.monotonic() + EMBED_COOLDOWN_SECONDS
            logger.warning(
                "Query embedding failed (%s); searching lexically for %.0fs",
                type(exc).__name__,
                EMBED_COOLDOWN_SECONDS,
            )
            warnings.append(
                "Embedding retrieval was unavailable; results are keyword-ranked only."
            )
    elif not LEXICAL_ONLY:
        warnings.append("Vectors are not available; results are keyword-ranked only.")
    raw = search_chunks(query, store.chunks, store.get_tfidf_index(), top_k=top_k)
    if raw and not validate_context(raw, 0.0, query):
        raw = []
    return {"results": raw, "mode": "lexical", "warnings": warnings}


def search_policy(ctx: Optional[PolicyContext], query: str, top_k: int = 5) -> Dict[str, Any]:
    """Retrieve policy passages for ``query`` from the uploaded documents."""
    top_k = max(1, min(int(top_k), MAX_TOP_K))
    store = _scoped(_session_store(ctx), ctx, policy_only=True)  # type: ignore[arg-type]
    if not store.chunks:
        raise NoIndexedDocumentsError(
            "The indexed documents contain no policy text (only record tables).",
            hint="Upload the policy handbook.",
        )
    ranked = _rank(store, query, top_k)
    return {
        "results": [_public_chunk(chunk) for chunk in ranked["results"]],
        "match_count": len(ranked["results"]),
        "no_match": not ranked["results"],
        "retrieval_mode": ranked["mode"],
        "documents_searched": _filenames(store),
        "warnings": ranked["warnings"],
    }


# ---------------------------------------------------------------------------
# Jurisdiction passages
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    return stripped.replace("’", "'").lower()


def find_jurisdiction_rules(
    ctx: Optional[PolicyContext], jurisdiction: str, policy_category: str
) -> Dict[str, Any]:
    """Passages stating rules for one jurisdiction and policy category."""
    taxonomy = load_taxonomy()
    if jurisdiction not in taxonomy["jurisdictions"]:
        raise PolicyToolError(
            f"Unknown jurisdiction {jurisdiction!r}.",
            hint=f"Use one of: {', '.join(taxonomy['jurisdictions'])}.",
        )
    if policy_category not in taxonomy["categories"]:
        raise PolicyToolError(
            f"Unknown policy_category {policy_category!r}.",
            hint=f"Use one of: {', '.join(taxonomy['categories'])}.",
        )
    session = _session_store(ctx)
    policy_scope = _scoped(session, ctx, policy_only=True)  # type: ignore[arg-type]
    hints = " ".join(taxonomy["categories"][policy_category])
    if jurisdiction == "Global":
        scope = policy_scope
    else:
        needle = _fold(jurisdiction)
        keep = [
            index
            for index, chunk in enumerate(policy_scope.chunks)
            if needle in _fold(chunk.get("text", ""))
        ]
        scope = _ScopedStore(policy_scope, keep)
    if not scope.chunks:
        raise NoEvidenceError(
            f"No passage in the uploaded documents mentions {jurisdiction}.",
            hint=(
                "Documents searched: "
                f"{', '.join(_filenames(policy_scope)) or 'none'}. "
                "Answer from search_handbook results instead, or state that no "
                f"{jurisdiction}-specific rule was provided."
            ),
        )
    query = f"{hints} {'' if jurisdiction == 'Global' else jurisdiction}".strip()
    ranked = _rank(scope, query, 3)
    return {
        "jurisdiction": jurisdiction,
        "policy_category": policy_category,
        "results": [_public_chunk(chunk) for chunk in ranked["results"]],
        "match_count": len(ranked["results"]),
        "no_match": not ranked["results"],
        "retrieval_mode": ranked["mode"],
        "documents_searched": _filenames(scope),
        "warnings": ranked["warnings"],
    }


# ---------------------------------------------------------------------------
# Employee records (rows of an uploaded roster)
# ---------------------------------------------------------------------------

def _field_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")


def _field_value(raw: str) -> Any:
    value = raw.strip()
    if value.lower() in {"", "none", "null", "n/a"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def parse_record_body(body: str) -> Dict[str, Any]:
    """``Name: X | Tenure (months): 18`` -> ``{"name": "X", "tenure_months": 18}``."""
    fields: Dict[str, Any] = {}
    for segment in body.split("|"):
        key, sep, value = segment.partition(":")
        if sep and key.strip():
            fields[_field_key(key)] = _field_value(value)
    return fields


def find_employee_record(ctx: Optional[PolicyContext], employee_id: str) -> Dict[str, Any]:
    """Return the roster row for ``employee_id`` exactly as stored in the chunks."""
    eid = (employee_id or "").strip()
    store = _scoped(_session_store(ctx), ctx, policy_only=False)  # type: ignore[arg-type]
    best: Optional[Dict[str, Any]] = None
    for chunk in store.chunks:
        for record_id, body in iter_records(str(chunk.get("text", ""))):
            if record_id.upper() != eid.upper():
                continue
            fields = parse_record_body(body)
            if fields and (best is None or len(fields) > len(best["fields"])):
                best = {"fields": fields, "chunk": chunk}
    if best is None:
        raise EmployeeNotFoundError(eid, _filenames(store))
    chunk = best["chunk"]
    return {
        "found": True,
        "employee_id": eid.upper(),
        "fields": best["fields"],
        "source": {
            "filename": chunk.get("filename"),
            "page": chunk.get("page"),
            "chunk_id": chunk.get("id"),
        },
    }


def list_employee_records(ctx: Optional[PolicyContext]) -> List[Dict[str, Any]]:
    """Every roster row present in the indexed chunks, sorted by id."""
    store = _scoped(_session_store(ctx), ctx, policy_only=False)  # type: ignore[arg-type]
    records: Dict[str, Dict[str, Any]] = {}
    for chunk in store.chunks:
        for record_id, body in iter_records(str(chunk.get("text", ""))):
            fields = parse_record_body(body)
            if fields:
                records[record_id.upper()] = {
                    "employee_id": record_id.upper(),
                    "filename": chunk.get("filename"),
                    **fields,
                }
    return sorted(records.values(), key=lambda record: record["employee_id"])


class EmployeeNotFoundError(PolicyToolError):
    code = "EMPLOYEE_NOT_FOUND"

    def __init__(self, employee_id: str, searched: List[str]):
        super().__init__(
            f"No record for employee {employee_id!r} exists in the uploaded documents.",
            hint=(
                f"Documents searched: {', '.join(searched) or 'none'}. Check the id "
                "spelling or upload the employee records file. Do not guess employee details."
            ),
        )
        self.employee_id = employee_id


# ---------------------------------------------------------------------------
# Citation validation against the uploaded document's own headings
# ---------------------------------------------------------------------------

# Headings survive chunking as "10.1Resignation" / "5.2.7 Carry forward ..." inside the text.
_SECTION_HEADING = re.compile(r"(?<![\w.])(\d{1,2}(?:\.\d{1,2}){1,3})(?=\s*[A-Z])")
_SECTION_REFERENCE = re.compile(r"(?<![\w.])(\d{1,2}(?:\.\d{1,2}){1,3})(?![\w])")


_FILE_HEADINGS_CACHE: Dict[tuple, Set[str]] = {}


def _uploaded_file_headings(session_id: str, wanted_docs: Sequence[str]) -> Set[str]:
    """Headings found in the session's own uploaded files (cached by path and mtime).

    The chunker merges small neighbouring blocks under one label, so a correct citation
    can be missing from chunk headings; the source file still has it.
    """
    from backend.services.text_extractor import extract_pdf_pages, extract_txt_pages
    from backend.storage import session_manager

    try:
        session_manager.load_session_manifest(session_id)
        files = dict(session_manager.SESSION_FILES.get(session_id, {}))
    except Exception:
        logger.debug("Uploaded-file lookup failed for citation index", exc_info=True)
        return set()
    found: Set[str] = set()
    for doc_id, info in files.items():
        path = Path(info["path"])
        if (wanted_docs and doc_id not in wanted_docs) or not path.exists():
            continue
        key = (str(path), path.stat().st_mtime_ns)
        if key not in _FILE_HEADINGS_CACHE:
            try:
                pages = extract_pdf_pages(str(path)) if path.suffix.lower() == ".pdf" else extract_txt_pages(str(path))
            except Exception:
                logger.debug("Could not read %s for citation index", path, exc_info=True)
                pages = []
            _FILE_HEADINGS_CACHE[key] = set(
                _SECTION_HEADING.findall("\n".join(str(page.get("text", "")) for page in pages))
            )
        found |= _FILE_HEADINGS_CACHE[key]
    return found


def known_sections(ctx: Optional[PolicyContext]) -> Set[str]:
    """Section numbers that head a section in the user's documents (chunks and source files)."""
    store = _scoped(_session_store(ctx), ctx, policy_only=True)  # type: ignore[arg-type]
    found: Set[str] = set()
    for chunk in store.chunks:
        found.update(_SECTION_HEADING.findall(str(chunk.get("text", ""))))
        found.update(_SECTION_HEADING.findall(str(chunk.get("section") or "")))
    found |= _uploaded_file_headings(ctx.session_id, ctx.document_ids)  # type: ignore[union-attr]
    return found


def check_citation(rule_cited: str, known: Set[str]) -> Dict[str, Any]:
    """Resolve section numbers in ``rule_cited`` against ``known`` (indexed headings)."""
    cited: List[str] = []
    for match in _SECTION_REFERENCE.finditer(rule_cited or ""):
        if match.group(1) not in cited:
            cited.append(match.group(1))
    resolved = [number for number in cited if number in known]
    unresolved = [number for number in cited if number not in known]
    return {
        "cited_sections": cited,
        "resolved_sections": resolved,
        "unresolved_sections": unresolved,
        "has_citation": bool(cited),
        "all_resolve": bool(cited) and not unresolved,
    }
