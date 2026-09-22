# backend/services/embeddings.py — Embedding Generation Services
import math
import time
import json
import urllib.request
import urllib.error
from typing import List

from backend.config import (
    EMBED_BACKEND,
    EMBED_BATCH,
    EMBED_MODEL,
    GEMINI_API_KEY,
    GEMINI_URL,
    OLLAMA_EMBED_MODEL,
    OLLAMA_URL,
    logger,
)


def _gemini_embed_batch(texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts using Gemini's batchEmbedContents endpoint."""
    url = f"{GEMINI_URL}/models/{EMBED_MODEL}:batchEmbedContents?key={GEMINI_API_KEY}"
    model_name = f"models/{EMBED_MODEL}"
    payload = {
        "requests": [
            {
                "model": model_name,
                "content": {"parts": [{"text": t}]},
            }
            for t in texts
        ]
    }

    max_retries = 5
    base_delay = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            t0 = time.time()
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0
            vectors = [e["values"] for e in data["embeddings"]]
            logger.info("🧠 Gemini Embedding batch of %d chunks succeeded in %.2fs (vector dim: %d)",
                        len(texts), elapsed, len(vectors[0]) if vectors else 0)
            return vectors
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 503) and attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning("⏳ Gemini Embeddings rate-limited (HTTP %d). Retrying in %.1fs (attempt %d/%d)...",
                               exc.code, delay, attempt, max_retries)
                time.sleep(delay)
            else:
                logger.error("❌ Gemini Embeddings batch failed with HTTP %d: %s", exc.code, exc)
                raise
        except Exception as exc:
            logger.error("❌ Gemini Embeddings batch exception: %s", exc, exc_info=True)
            raise


def _ollama_embed_batch(texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts via a locally-running Ollama server."""
    url = f"{OLLAMA_URL}/api/embed"
    payload = {"model": OLLAMA_EMBED_MODEL, "input": texts}
    try:
        t0 = time.time()
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - t0
        vectors = data.get("embeddings", [])
        logger.info("🧠 Ollama embedding batch of %d chunks succeeded in %.2fs (vector dim: %d, model: %s)",
                    len(texts), elapsed, len(vectors[0]) if vectors else 0, OLLAMA_EMBED_MODEL)
        return vectors
    except urllib.error.URLError as exc:
        logger.error(
            "❌ Could not reach Ollama at %s — is `ollama serve` running and `%s` pulled? (%s)",
            OLLAMA_URL, OLLAMA_EMBED_MODEL, exc,
        )
        raise
    except Exception as exc:
        logger.error("❌ Ollama embedding batch exception: %s", exc, exc_info=True)
        raise


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Batch-embed texts via whichever backend EMBED_BACKEND selects."""
    if not texts:
        return []
    out: List[List[float]] = []
    total_batches = math.ceil(len(texts) / EMBED_BATCH)
    backend_label = "Ollama (local)" if EMBED_BACKEND == "ollama" else "Gemini"
    logger.info("🧠 Starting batch embedding for %d total chunks (%d batch(es) of max %d) via %s",
                len(texts), total_batches, EMBED_BATCH, backend_label)
    for idx, i in enumerate(range(0, len(texts), EMBED_BATCH), start=1):
        batch = texts[i:i + EMBED_BATCH]
        logger.info("🧠 Processing embedding batch %d/%d (%d chunks)...", idx, total_batches, len(batch))
        vectors = (_ollama_embed_batch(batch) if EMBED_BACKEND == "ollama" else _gemini_embed_batch(batch))
        out.extend(vectors)
    return out


def embed_text(text: str) -> List[float]:
    """Generate embedding vector for a single string."""
    return embed_texts([text])[0]


def embeddings_configured() -> bool:
    """True if the selected embeddings backend is usable."""
    if EMBED_BACKEND == "ollama":
        return True
    return bool(GEMINI_API_KEY)


_embeddings_configured = embeddings_configured
_embed_text = embed_text
_embed_texts = embed_texts

