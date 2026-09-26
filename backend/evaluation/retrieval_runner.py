# backend/evaluation/retrieval_runner.py — Multi-Strategy Retrieval Benchmark Runner
from typing import Any, Dict, List, Optional

from backend.evaluation.metrics import rr_rank
from backend.services.embeddings import embed_text, embeddings_configured
from backend.services.reranker import rerank_with_llm, rewrite_query
from backend.services.search import hybrid_search, reciprocal_rank_fusion, search_chunks

EVAL_PRESETS = {
    "tfidf": {"force_tfidf": True, "mode": None, "rerank": False, "rewrite": False},
    "bm25-qdrant-blend": {
        "force_tfidf": False,
        "mode": "hybrid-legacy",
        "rerank": False,
        "rewrite": False,
    },
    "bm25-qdrant-rrf": {
        "force_tfidf": False,
        "mode": "hybrid",
        "rerank": False,
        "rewrite": False,
    },
    "rrf-rerank": {
        "force_tfidf": False,
        "mode": "hybrid",
        "rerank": True,
        "rewrite": False,
    },
    "rrf-rerank-rewrite": {
        "force_tfidf": False,
        "mode": "hybrid",
        "rerank": True,
        "rewrite": True,
    },
}


def retrieve_for_eval(
    active_store: Any,
    query: str,
    k: int,
    mode: Optional[str],
    force_tfidf: bool = False,
) -> List[dict]:
    """Runs retrieval through the real system's pipeline for benchmarking."""
    has_embeddings = (
        embeddings_configured()
        and active_store.vectors
        and len(active_store.vectors) == len(active_store.chunks)
    )
    if has_embeddings and not force_tfidf:
        if mode == "hybrid-legacy":
            return hybrid_search(active_store, query, top_k=k)
        if mode == "embed":
            return active_store.query(embed_text(query), top_k=k, min_score=0.0)
        return reciprocal_rank_fusion(active_store, query, top_k=k)
    index = active_store.get_tfidf_index()
    return search_chunks(query, active_store.chunks, index, top_k=k)


def run_eval_preset(
    active_store: Any,
    q_id: str,
    question: str,
    expected: str,
    k: int,
    preset: dict,
    expected_doc: str = "",
    expected_section: str = "",
) -> dict:
    search_q = rewrite_query(question) if preset.get("rewrite") else question
    retrieved = retrieve_for_eval(
        active_store, search_q, k, preset.get("mode"), preset.get("force_tfidf", False)
    )
    rerank_score = None
    if preset.get("rerank") and len(retrieved) > 1:
        retrieved, rerank_score = rerank_with_llm(question, retrieved)
    hit, rr, rank = rr_rank(
        retrieved,
        expected=expected,
        expected_doc=expected_doc,
        expected_section=expected_section,
    )
    failure_type = "Success" if hit else "Retrieval Failure"
    return {
        "id": q_id,
        "question": question,
        "search_query": search_q if search_q != question else None,
        "expected": expected or expected_section or expected_doc,
        "expected_doc": expected_doc or None,
        "expected_section": expected_section or None,
        "hit": hit,
        "reciprocal_rank": round(rr, 4),
        "rank": rank,
        "failure_type": failure_type,
        "rerank_score": rerank_score,
        "retrieved": [
            {
                "section": r.get("section"),
                "filename": r.get("filename"),
                "score": round(r.get("score", 0.0), 4),
                "embed_score": (
                    round(r["embed_score"], 4) if "embed_score" in r else None
                ),
                "bm25_score": (
                    round(r["keyword_score"], 4) if "keyword_score" in r else None
                ),
            }
            for r in retrieved
        ],
    }


_retrieve_for_eval = retrieve_for_eval
_run_eval_preset = run_eval_preset
