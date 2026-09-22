# backend/services/search.py — Lexical (TF-IDF/BM25), Hybrid (RRF), and Generation Pipeline
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.config import (
    BM25_B,
    BM25_K1,
    HYBRID_ALPHA,
    MAX_CONTEXT_TOKENS,
    RRF_K,
    logger,
)
from backend.services.chunker import split_sentences
from backend.services.embeddings import embed_text
from backend.services.llm import chat_call
from backend.storage.trace_store import QA_PROMPT_VERSION, register_prompt

STOPWORDS: Set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "up", "about", "into", "through",
    "and", "but", "or", "if", "while", "when", "where", "who", "which",
    "that", "this", "these", "those", "it", "its", "all", "each", "both",
    "more", "most", "other", "some", "no", "not", "only", "same", "than",
    "too", "very", "just", "your", "you", "they", "we", "he", "she", "i",
    "my", "their", "our", "his", "her", "also", "how", "what", "so", "as",
}

_simple_tokenizer = re.compile(r"[\w]+")


def tokenize(text: str) -> List[str]:
    """Lowercase, extract word tokens (incl. Unicode/CJK), remove stopwords."""
    tokens = _simple_tokenizer.findall(text.lower())
    return [t for t in tokens if len(t) > 2 and t not in STOPWORDS]


def compute_tf(tokens: List[str]) -> Dict[str, float]:
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {t: c / total for t, c in counts.items()}


def compute_idf(corpus_tokens: List[List[str]]) -> Dict[str, float]:
    n = len(corpus_tokens)
    doc_freq: Dict[str, int] = {}
    for tokens in corpus_tokens:
        for t in set(tokens):
            doc_freq[t] = doc_freq.get(t, 0) + 1
    return {t: math.log((1 + n) / (1 + df)) + 1.0 for t, df in doc_freq.items()}


def tfidf_vector(tf: Dict[str, float], idf: Dict[str, float]) -> Dict[str, float]:
    return {t: tf_val * idf.get(t, 1.0) for t, tf_val in tf.items()}


def cosine_sim(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    common = set(vec_a) & set(vec_b)
    if not common:
        return 0.0
    dot = sum(vec_a[t] * vec_b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_index(chunks: List[dict]) -> dict:
    corpus_tokens = [tokenize(c["text"]) for c in chunks]
    doc_lengths = [len(tokens) for tokens in corpus_tokens]
    avg_doc_length = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 0.0
    n = len(corpus_tokens)
    doc_freq: Dict[str, int] = {}
    for tokens in corpus_tokens:
        for t in set(tokens):
            doc_freq[t] = doc_freq.get(t, 0) + 1
    bm25_idf = {t: math.log((n - df + 0.5) / (df + 0.5) + 1) for t, df in doc_freq.items()}
    return {
        "corpus_tokens": corpus_tokens,
        "idf": compute_idf(corpus_tokens),
        "doc_lengths": doc_lengths,
        "avg_doc_length": avg_doc_length,
        "bm25_idf": bm25_idf,
    }


def bm25_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    doc_length: int,
    avg_doc_length: float,
    bm25_idf: Dict[str, float],
) -> float:
    if avg_doc_length == 0:
        return 0.0
    doc_tf = Counter(doc_tokens)
    score = 0.0
    length_norm = 1 - BM25_B + BM25_B * (doc_length / avg_doc_length)
    for t in query_tokens:
        f = doc_tf.get(t, 0)
        if f == 0:
            continue
        idf = bm25_idf.get(t, 0.0)
        score += idf * (f * (BM25_K1 + 1)) / (f + BM25_K1 * length_norm)
    return score


def bm25_scores_for_corpus(query: str, index: dict) -> List[float]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return [0.0] * len(index["corpus_tokens"])
    return [
        bm25_score(
            query_tokens,
            doc_tokens,
            index["doc_lengths"][i],
            index["avg_doc_length"],
            index["bm25_idf"],
        )
        for i, doc_tokens in enumerate(index["corpus_tokens"])
    ]


def search_chunks(query: str, chunks: List[dict], index: dict, top_k: int = 4) -> List[dict]:
    if not chunks:
        return []
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    raw_scores = bm25_scores_for_corpus(query, index)
    max_score = max(raw_scores) if raw_scores else 0.0
    scored = []
    for chunk, score in zip(chunks, raw_scores):
        normalized = (score / max_score) if max_score > 0 else 0.0
        if normalized >= 0.05:
            scored.append({**chunk, "score": normalized})

    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


def reciprocal_rank_fusion(store: Any, query: str, top_k: int = 5) -> List[dict]:
    """Combines embedding-based ranking and BM25 ranking via Reciprocal Rank Fusion."""
    if not store.chunks:
        return []
    n = len(store.chunks)

    embed_scores = (
        store.query_scores(embed_text(query))
        if store.vectors and len(store.vectors) == len(store.chunks)
        else [0.0] * n
    )
    embed_order = sorted(range(n), key=lambda i: -embed_scores[i])
    embed_rank = {chunk_i: rank for rank, chunk_i in enumerate(embed_order)}

    index = store.get_tfidf_index()
    keyword_scores = bm25_scores_for_corpus(query, index)
    keyword_order = sorted(range(n), key=lambda i: -keyword_scores[i])
    keyword_rank = {chunk_i: rank for rank, chunk_i in enumerate(keyword_order)}

    max_possible = 2.0 / (RRF_K + 1)
    rrf_scores = [
        (1.0 / (RRF_K + embed_rank[i] + 1) + 1.0 / (RRF_K + keyword_rank[i] + 1)) / max_possible
        for i in range(n)
    ]

    ranked = sorted(range(n), key=lambda i: -rrf_scores[i])[:top_k]
    return [
        {
            **store.chunks[i],
            "score": rrf_scores[i],
            "embed_score": embed_scores[i],
            "keyword_score": keyword_scores[i],
        }
        for i in ranked
    ]


def hybrid_search(store: Any, query: str, top_k: int = 5, alpha: float = HYBRID_ALPHA) -> List[dict]:
    """Weighted blend of embedding similarity and TF-IDF similarity."""
    if not store.chunks:
        return []

    embed_scores = (
        store.query_scores(embed_text(query))
        if store.vectors and len(store.vectors) == len(store.chunks)
        else [0.0] * len(store.chunks)
    )

    index = store.get_tfidf_index()
    q_vec = tfidf_vector(compute_tf(tokenize(query)), index["idf"])
    tfidf_scores = [
        cosine_sim(q_vec, tfidf_vector(compute_tf(tokens), index["idf"]))
        for tokens in index["corpus_tokens"]
    ]

    combined = [alpha * e + (1 - alpha) * t for e, t in zip(embed_scores, tfidf_scores)]
    ranked = sorted(range(len(combined)), key=lambda i: -combined[i])[:top_k]

    return [
        {
            **store.chunks[i],
            "score": combined[i],
            "embed_score": embed_scores[i],
            "tfidf_score": tfidf_scores[i],
        }
        for i in ranked
    ]


_DONT_KNOW_MARKERS = (
    "i don't know", "i do not know", "cannot answer", "can't answer",
    "not enough information", "doesn't contain", "does not contain",
    "not available in the", "no information",
)


def _stem_lite(token: str) -> str:
    for suffix in ("ing", "es", "ed", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def validate_context(
    results: List[dict],
    min_score: float,
    query: Optional[str] = None,
    rerank_score: Optional[float] = None,
) -> bool:
    """Reject retrieval when nothing clears the similarity bar or relevance threshold."""
    if not results:
        return False
    top_score = results[0].get("score", 0.0)
    if top_score < min_score:
        return False
    if rerank_score is not None:
        return rerank_score >= 5.0
    if query is not None:
        META_QUESTION_WORDS = {
            "meaning", "mean", "definition", "define", "explain", "explanation",
            "describe", "description", "overview", "detail", "details", "tell",
            "show", "give", "list", "state", "clarify", "understand", "concept",
            "purpose", "reason", "procedure", "process", "rule", "rules"
        }
        query_tokens = set(tokenize(query))
        if query_tokens:
            chunk_tokens = set(tokenize(results[0]["text"]))
            query_stems = {_stem_lite(t) for t in query_tokens}
            chunk_stems = {_stem_lite(t) for t in chunk_tokens}
            shared = query_stems & chunk_stems

            content_stems = {s for s in query_stems if s not in META_QUESTION_WORDS}

            if top_score >= 0.75:
                required = 1
            elif content_stems:
                required = min(2, len(content_stems))
            else:
                required = min(2, len(query_stems))

            if len(shared) < required:
                return False
    return True


def is_dont_know(answer: Optional[str]) -> bool:
    if not answer or not answer.strip():
        return True
    a = answer.lower().strip()
    if a.rstrip(".").strip() in ("i don't know", "i do not know"):
        return True
    word_count = len(a.split())
    return word_count <= 12 and any(m in a for m in _DONT_KNOW_MARKERS)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def fit_to_token_budget(results: List[dict], max_tokens: int = MAX_CONTEXT_TOKENS) -> List[dict]:
    kept: List[dict] = []
    used = 0
    for r in results:
        t = estimate_tokens(r.get("text", ""))
        if kept and used + t > max_tokens:
            break
        kept.append(r)
        used += t
    return kept


QA_SYSTEM_PROMPT = register_prompt(
    QA_PROMPT_VERSION,
    (
        "You are a grounded question-answering assistant. Answer using ONLY the "
        "document excerpts provided. Cite every fact with its source number like "
        "[1] or [2]. If the excerpts do not contain enough information to answer "
        "the question, reply exactly with: \"I don't know.\" Do not use outside "
        "knowledge. Match your answer's length to what the question actually "
        "needs — a short, direct sentence or two for a simple factual question, "
        "but a longer, complete answer (including every item, if the source "
        "material itself lists several, such as a numbered or lettered list) "
        "for a question that calls for it. Never omit relevant details from the "
        "excerpts just to keep the answer short; completeness for the specific "
        "question asked matters more than brevity."
    ),
)


def build_qa_user_prompt(query: str, results: List[dict]) -> str:
    context_blocks = []
    for i, r in enumerate(results, start=1):
        loc = f"{r['filename']} (page {r['page']})"
        if r.get("section"):
            loc += f", section: {r['section']}"
        context_blocks.append(f"[{i}] {loc}\n{r['text']}")
    return "DOCUMENTS:\n\n" + "\n\n".join(context_blocks) + f"\n\nQUESTION: {query}\n\nANSWER:"


def generate_answer(query: str, results: List[dict], temperature: float = 0.0) -> str:
    system = QA_SYSTEM_PROMPT
    user = build_qa_user_prompt(query, results)
    try:
        return chat_call(system, user, temperature=temperature)
    except Exception:
        return ""


def synthesize_answer(query: str, results: List[dict]) -> dict:
    """Template-based answer for the offline fallback path."""
    if not results:
        return {
            "found": False,
            "answer": (
                "I don't know — I couldn't find a relevant answer in the uploaded "
                "documents. Try uploading more documents or rephrasing your question."
            ),
            "sources": [],
        }

    seen: Set[str] = set()
    sources = []
    all_text = " ".join(r["text"] for r in results)

    for r in results:
        key = r["id"]
        if key not in seen:
            seen.add(key)
            sources.append(r)

    query_words = set(tokenize(query))
    sentences = split_sentences(all_text)

    scored_sents = []
    for s in sentences:
        s = s.strip()
        if len(s) < 20:
            continue
        s_words = set(tokenize(s))
        overlap = len(query_words & s_words)
        scored_sents.append((overlap, s))

    scored_sents.sort(key=lambda x: -x[0])

    seen_sents: Set[str] = set()
    top_sents = []
    for overlap, s in scored_sents:
        if overlap <= 0:
            break
        if s not in seen_sents:
            seen_sents.add(s)
            top_sents.append(s)
        if len(top_sents) >= 8:
            break

    answer = " ".join(top_sents) if top_sents else results[0]["text"][:500] + "…"

    return {"found": True, "answer": answer, "sources": sources}


_is_dont_know = is_dont_know
_synthesize_answer = synthesize_answer
_validate_context = validate_context
_fit_to_token_budget = fit_to_token_budget
_generate_answer = generate_answer
_tokenize = tokenize
_compute_tf = compute_tf
_compute_idf = compute_idf
_bm25_score = bm25_score
_bm25_scores_for_corpus = bm25_scores_for_corpus
_build_index = build_index
build_tfidf_index = build_index
_build_tfidf_index = build_index
_search_chunks = search_chunks
_reciprocal_rank_fusion = reciprocal_rank_fusion
_hybrid_search = hybrid_search
_estimate_tokens = estimate_tokens
_build_qa_user_prompt = build_qa_user_prompt



