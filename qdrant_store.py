"""
qdrant_store.py — Backwards-compatibility re-export module.
Authoritative implementation is in backend.storage.qdrant_store.
"""
from backend.storage.exceptions import RetrievalBackendError
from backend.storage.qdrant_store import (
    QdrantVectorStore,
    get_qdrant_client,
)

_client = get_qdrant_client

__all__ = [
    "QdrantVectorStore",
    "RetrievalBackendError",
    "get_qdrant_client",
    "_client",
]