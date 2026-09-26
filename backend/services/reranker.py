# backend/services/reranker.py — LLM-Powered Reranking & Query Rewriting
import re
import json
from typing import List, Optional, Tuple

from backend.config import (
    RERANK_MIN_RELEVANCE,
    RERANK_TOP_N,
    logger,
)
from backend.services.llm import chat_call, chat_configured
from backend.storage.trace_store import (
    QA_PROMPT_VERSION,
    RERANK_PROMPT_VERSION,
    REWRITE_PROMPT_VERSION,
    register_prompt,
)

RERANK_SYSTEM_PROMPT = register_prompt(
    RERANK_PROMPT_VERSION,
    (
        "You score search results for relevance to a question. Given a "
        "question and numbered candidate excerpts, respond with ONLY a "
        'JSON array of objects, one per candidate, each with "index" '
        'and "score" (0-10, where 10 means the excerpt directly and '
        "fully answers the question, 0 means completely unrelated — "
        "judge genuine relevance, not just shared words). Order the "
        "array from highest score to lowest. No other text — just the "
        'JSON array, e.g. [{"index":2,"score":9},{"index":0,"score":3}].'
    ),
)

REWRITE_SYSTEM_PROMPT = register_prompt(
    REWRITE_PROMPT_VERSION,
    (
        "Rewrite the user's question into a short, keyword-rich search "
        "query optimized for retrieving relevant passages from a "
        "document — not a natural-language answer, not a rephrased "
        "question, just the core searchable terms. Respond with ONLY "
        "the rewritten query, nothing else."
    ),
)


def rerank_with_llm(
    query: str, results: List[dict]
) -> Tuple[List[dict], Optional[float]]:
    """Second-pass reranker over candidate list using LLM scoring."""
    if not results or not chat_configured():
        return results, None

    candidates = results[:RERANK_TOP_N]
    numbered = "\n\n".join(f"[{i}] {c['text'][:600]}" for i, c in enumerate(candidates))
    system = RERANK_SYSTEM_PROMPT
    user = f"Question: {query}\n\nCandidates:\n{numbered}"
    try:
        raw = chat_call(system, user, temperature=0, max_tokens=300)
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        scored = json.loads(raw)
        indices = sorted(item["index"] for item in scored)
        if indices != list(range(len(candidates))):
            raise ValueError("LLM did not score every candidate exactly once")
        scored.sort(key=lambda item: -item["score"])
        reranked = [candidates[item["index"]] for item in scored]
        top_score = float(scored[0]["score"])
        return reranked + results[RERANK_TOP_N:], top_score
    except Exception:
        logger.warning(
            "LLM reranking failed — falling back to original order.", exc_info=True
        )
        return results, None


def rewrite_query(query: str) -> str:
    """Rewrites a conversational question into a cleaner search query before retrieval."""
    if not query.strip() or not chat_configured():
        return query
    system = REWRITE_SYSTEM_PROMPT
    try:
        rewritten = chat_call(system, query, temperature=0, max_tokens=60).strip('"')
        return rewritten if rewritten else query
    except Exception:
        logger.warning(
            "Query rewriting failed — using original question as-is.", exc_info=True
        )
        return query


_rerank_with_llm = rerank_with_llm
_rewrite_query = rewrite_query
