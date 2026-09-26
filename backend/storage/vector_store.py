# backend/storage/vector_store.py — Persistent In-Memory Vector Store
import math
import pickle
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.config import VECTOR_FOLDER, get_app_symbol, logger


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: List[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def cosine(a: List[float], b: List[float]) -> float:
    denom = _norm(a) * _norm(b)
    return 0.0 if denom == 0 else _dot(a, b) / denom


class VectorStore:
    """A tiny persistent vector index: chunk metadata + embedding vectors."""

    def __init__(
        self, sid: str, index_builder: Optional[Callable[[List[dict]], dict]] = None
    ):
        self.sid = sid
        self.chunks: List[dict] = []
        self.vectors: List[List[float]] = []
        self._path_override: Optional[Path] = None
        self._tfidf_index_cache: Optional[dict] = None
        self._index_builder = index_builder
        self.last_backend_error: Optional[str] = None

    @property
    def path(self) -> Path:
        if self._path_override is not None:
            return self._path_override
        folder = get_app_symbol("VECTOR_FOLDER", VECTOR_FOLDER)
        return Path(folder) / f"{self.sid}.pkl"

    @path.setter
    def path(self, val: Path) -> None:
        self._path_override = val

    def set_index_builder(self, builder: Callable[[List[dict]], dict]) -> None:
        self._index_builder = builder

    def load(self) -> None:
        if self.path.exists():
            try:
                data = pickle.loads(self.path.read_bytes())
                self.chunks = data["chunks"]
                self.vectors = data["vectors"]
                self._tfidf_index_cache = None
            except Exception:
                logger.warning(
                    "Corrupted vector store at %s — starting fresh",
                    self.path,
                    exc_info=True,
                )
                self.chunks, self.vectors = [], []

    def save(self) -> None:
        self.path.write_bytes(
            pickle.dumps({"chunks": self.chunks, "vectors": self.vectors})
        )

    def add(self, chunks: List[dict], vectors: List[List[float]]) -> None:
        self.chunks.extend(chunks)
        self.vectors.extend(vectors)
        self._tfidf_index_cache = None
        self.save()

    def get_tfidf_index(self) -> dict:
        """Return this store's TF-IDF index, building it once and caching it until mutation."""
        if self._tfidf_index_cache is None:
            if self._index_builder:
                self._tfidf_index_cache = self._index_builder(self.chunks)
            else:
                from backend.services.search import build_index

                self._tfidf_index_cache = build_index(self.chunks)
        return self._tfidf_index_cache

    def query(
        self, vector: List[float], top_k: int = 5, min_score: float = 0.0
    ) -> List[dict]:
        scored = [(i, cosine(vector, v)) for i, v in enumerate(self.vectors)]
        scored = [(i, s) for i, s in scored if s >= min_score]
        scored.sort(key=lambda x: -x[1])
        return [{**self.chunks[i], "score": s} for i, s in scored[:top_k]]

    def query_scores(self, vector: List[float]) -> List[float]:
        """Cosine similarity of `vector` against every chunk, unfiltered and in chunk order."""
        return [cosine(vector, v) for v in self.vectors]

    def clear(self) -> None:
        self.chunks, self.vectors = [], []
        self._tfidf_index_cache = None
        self.path.unlink(missing_ok=True)

    def remove_doc(self, doc_id: str) -> int:
        """Remove all chunks + vectors for a doc. Returns how many were removed."""
        before = len(self.chunks)
        kept = [
            (c, v) for c, v in zip(self.chunks, self.vectors) if c["doc_id"] != doc_id
        ]
        self.chunks = [c for c, _ in kept]
        self.vectors = [v for _, v in kept]
        removed = before - len(self.chunks)
        if removed:
            self._tfidf_index_cache = None
            self.save()
        return removed

    def filtered_by_method(self, method: str) -> "VectorStore":
        """Return an ephemeral view containing only chunks indexed under given chunking strategy."""
        view = VectorStore(f"{self.sid}__view", index_builder=self._index_builder)
        has_vectors = len(self.vectors) == len(self.chunks)
        matched = [i for i, c in enumerate(self.chunks) if c.get("method") == method]
        view.chunks = [self.chunks[i] for i in matched]
        view.vectors = [self.vectors[i] for i in matched] if has_vectors else []
        return view
