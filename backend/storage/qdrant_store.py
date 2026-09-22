# backend/storage/qdrant_store.py — Qdrant-backed VectorStore
from typing import Any, Callable, Dict, List, Optional
import uuid as _uuid
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from backend.config import (
    QDRANT_API_KEY,
    QDRANT_CANDIDATE_POOL,
    QDRANT_SCROLL_LIMIT,
    QDRANT_TIMEOUT,
    QDRANT_URL,
    logger,
)
from backend.storage.exceptions import RetrievalBackendError


class _QdrantSingleton:
    client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    if _QdrantSingleton.client is None:
        _QdrantSingleton.client = QdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY,
            timeout=QDRANT_TIMEOUT,
            prefer_grpc=False,
        )
    return _QdrantSingleton.client


class QdrantVectorStore:
    """Same public interface as VectorStore: load, save, add, query, query_scores,
    get_tfidf_index, clear, remove_doc, filtered_by_method."""

    def __init__(self, sid: str, method_filter: Optional[str] = None, index_builder: Optional[Callable[[List[dict]], dict]] = None):
        self.sid = sid
        self.collection = f"chunks_{sid}"
        self.method_filter = method_filter
        self.chunks: List[dict] = []
        self.vectors: List[List[float]] = []
        self._tfidf_index_cache: Optional[dict] = None
        self._index_builder = index_builder
        self.last_backend_error: Optional[str] = None

    def _collection_exists(self) -> bool:
        client = get_qdrant_client()
        names = [c.name for c in client.get_collections().collections]
        return self.collection in names

    def _ensure_collection(self, dim: int) -> None:
        client = get_qdrant_client()
        if not self._collection_exists():
            client.create_collection(
                collection_name=self.collection,
                vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
            )
        for field_name in ("doc_id", "method"):
            try:
                client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema="keyword",
                )
            except Exception as exc:
                err_msg = str(exc).lower()
                if "already exists" in err_msg or "already indexed" in err_msg:
                    logger.debug("Payload index on %s already exists in %s", field_name, self.collection)
                else:
                    logger.warning("Failed to create Qdrant payload index on %s (%s): %s",
                                   field_name, self.collection, exc)

    def _qdrant_filter(self):
        if not self.method_filter:
            return None
        return qmodels.Filter(must=[
            qmodels.FieldCondition(key="method", match=qmodels.MatchValue(value=self.method_filter))
        ])

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(_uuid.uuid5(_uuid.NAMESPACE_URL, chunk_id))

    def load(self) -> None:
        """Rehydrate the local chunk/vector mirror from Qdrant with controlled pagination."""
        try:
            if not self._collection_exists():
                return
            chunks, vectors = [], []
            offset = None
            client = get_qdrant_client()
            while True:
                points, offset = client.scroll(
                    collection_name=self.collection, with_payload=True, with_vectors=True,
                    limit=QDRANT_SCROLL_LIMIT, offset=offset,
                )
                for p in points:
                    chunks.append(p.payload)
                    vectors.append(p.vector)
                if offset is None:
                    break
            self.chunks, self.vectors = chunks, vectors
            self._tfidf_index_cache = None
        except Exception as exc:
            self.last_backend_error = f"Qdrant load failed: {exc}"
            logger.error("Qdrant load failed for collection %s: %s", self.collection, exc, exc_info=True)
            raise RetrievalBackendError(f"Failed to load collection from Qdrant: {exc}") from exc

    def save(self) -> None:
        pass  # Qdrant persists on every upsert; nothing to flush locally

    def add(self, chunks: List[dict], vectors: List[List[float]]) -> None:
        if not chunks:
            return
        if not vectors:
            raise ValueError(
                "QdrantVectorStore requires non-empty embedding vectors for all chunks. "
                "Vectorless / TF-IDF-only inserts cannot be durably persisted in Qdrant."
            )
        if len(chunks) != len(vectors):
            raise ValueError(
                f"Chunk/vector length mismatch: {len(chunks)} chunks vs {len(vectors)} vectors"
            )

        self._ensure_collection(dim=len(vectors[0]))
        points = [
            qmodels.PointStruct(id=self._point_id(c["id"]), vector=v, payload=c)
            for c, v in zip(chunks, vectors)
        ]
        get_qdrant_client().upsert(collection_name=self.collection, points=points)

        self.chunks.extend(chunks)
        self.vectors.extend(vectors)
        self._tfidf_index_cache = None

    def remove_doc(self, doc_id: str) -> int:
        """Consistency-first deletion: deletes from Qdrant first, then updates local mirror."""
        before = len(self.chunks)
        self.last_backend_error = None
        try:
            if self._collection_exists():
                get_qdrant_client().delete(
                    collection_name=self.collection,
                    points_selector=qmodels.FilterSelector(filter=qmodels.Filter(must=[
                        qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id))
                    ])),
                )
        except Exception as exc:
            self.last_backend_error = f"Qdrant delete failed: {exc}"
            logger.error("Qdrant delete-by-doc_id failed for %s: %s", doc_id, exc, exc_info=True)
            raise RetrievalBackendError(f"Failed to delete document from Qdrant: {exc}") from exc

        kept = [(c, v) for c, v in zip(self.chunks, self.vectors) if c["doc_id"] != doc_id]
        self.chunks = [c for c, _ in kept]
        self.vectors = [v for _, v in kept]
        removed = before - len(self.chunks)
        if removed:
            self._tfidf_index_cache = None
        return removed

    def clear(self) -> None:
        """Consistency-first clear: drops collection from Qdrant first, then clears local mirror."""
        self.last_backend_error = None
        try:
            if self._collection_exists():
                get_qdrant_client().delete_collection(self.collection)
        except Exception as exc:
            self.last_backend_error = f"Qdrant delete_collection failed: {exc}"
            logger.error("Qdrant delete_collection failed for %s: %s", self.collection, exc, exc_info=True)
            raise RetrievalBackendError(f"Failed to clear Qdrant collection: {exc}") from exc

        self.chunks, self.vectors = [], []
        self._tfidf_index_cache = None

    def get_tfidf_index(self) -> dict:
        if self._tfidf_index_cache is None:
            if self._index_builder:
                self._tfidf_index_cache = self._index_builder(self.chunks)
            else:
                from backend.services.search import build_index
                self._tfidf_index_cache = build_index(self.chunks)
        return self._tfidf_index_cache

    def query(self, vector: List[float], top_k: int = 5, min_score: float = 0.0) -> List[dict]:
        try:
            if not self._collection_exists():
                return []
            response = get_qdrant_client().query_points(
                collection_name=self.collection, query=vector,
                query_filter=self._qdrant_filter(),
                limit=top_k, score_threshold=min_score,
            )
            hits = response.points
        except Exception as exc:
            self.last_backend_error = f"Qdrant query failed: {exc}"
            logger.error("Qdrant retrieval query failed for collection %s: %s", self.collection, exc, exc_info=True)
            raise RetrievalBackendError(f"Vector retrieval failed: {exc}") from exc
        return [{**h.payload, "score": h.score} for h in hits]

    def query_scores(self, vector: List[float]) -> List[float]:
        try:
            if not self._collection_exists():
                return [0.0] * len(self.chunks)
            response = get_qdrant_client().query_points(
                collection_name=self.collection, query=vector,
                query_filter=self._qdrant_filter(),
                limit=QDRANT_CANDIDATE_POOL,
            )
            hits = response.points
        except Exception as exc:
            self.last_backend_error = f"Qdrant query_scores failed: {exc}"
            logger.error("Qdrant query_scores failed for collection %s: %s", self.collection, exc, exc_info=True)
            raise RetrievalBackendError(f"Vector hybrid scoring failed: {exc}") from exc
        score_by_id = {h.payload["id"]: h.score for h in hits}
        return [score_by_id.get(c["id"], 0.0) for c in self.chunks]

    def filtered_by_method(self, method: str) -> "QdrantVectorStore":
        view = QdrantVectorStore(self.sid, method_filter=method, index_builder=self._index_builder)
        has_vectors = len(self.vectors) == len(self.chunks)
        matched = [i for i, c in enumerate(self.chunks) if c.get("method") == method]
        view.chunks = [self.chunks[i] for i in matched]
        view.vectors = [self.vectors[i] for i in matched] if has_vectors else []
        return view

