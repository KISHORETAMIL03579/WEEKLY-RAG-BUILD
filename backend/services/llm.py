# backend/services/llm.py — LLM Chat Providers & Generation Router
import time
import json
import socket
import urllib.request
import urllib.error
from typing import Optional

from backend.config import (
    CHAT_BACKEND,
    OLLAMA_CHAT_MODEL,
    OLLAMA_URL,
    XAI_API_KEY,
    XAI_MODEL,
    XAI_URL,
    logger,
)


class RAGTracer:
    """Provides formatted step-by-step trace logging for document ingestion and retrieval pipelines."""

    @staticmethod
    def trace(pipeline: str, step: int, total_steps: int, name: str, details: dict):
        header = f"\033[1;35m[TRACE | {pipeline}] \033[1;36mStep {step}/{total_steps}: {name}\033[0m"
        lines = [header]
        for key, value in details.items():
            lines.append(f"  \033[33m├─ {key:<24}\033[0m: \033[1;32m{value}\033[0m")
        logger.info("\n" + "\n".join(lines))


def _xai_chat_call(
    system: str,
    user: str,
    temperature: float = 0,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> str:
    """Call xAI's OpenAI-compatible /v1/chat/completions endpoint with exponential backoff."""
    url = f"{XAI_URL}/chat/completions"
    target_model = model or XAI_MODEL
    payload: dict = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    max_retries = 5
    base_delay = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            t0 = time.time()
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {XAI_API_KEY}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0
            choices = data.get("choices", [])
            if not choices:
                logger.warning("⚠️ xAI response has no choices (raw: %s)", data)
                return ""
            result_text = (choices[0].get("message", {}).get("content") or "").strip()
            logger.info(
                "🤖 xAI (Grok) LLM call succeeded in %.2fs (model: %s)",
                elapsed,
                target_model,
            )
            return result_text
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 503) and attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "⏳ xAI LLM rate-limited (HTTP %d). Retrying in %.1fs (attempt %d/%d)...",
                    exc.code,
                    delay,
                    attempt,
                    max_retries,
                )
                time.sleep(delay)
            else:
                logger.error("❌ xAI LLM call failed with HTTP %d: %s", exc.code, exc)
                raise
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "⏳ xAI LLM network timeout (%s). Retrying in %.1fs (attempt %d/%d)...",
                    exc,
                    delay,
                    attempt,
                    max_retries,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "❌ xAI LLM network call timed out after %d attempts: %s",
                    max_retries,
                    exc,
                )
                raise
        except Exception as exc:
            logger.error("❌ xAI LLM call exception: %s", exc, exc_info=True)
            raise


def _ollama_chat_call(
    system: str,
    user: str,
    temperature: float = 0,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> str:
    """Call a locally-running Ollama chat model via /api/chat."""
    url = f"{OLLAMA_URL}/api/chat"
    target_model = model or OLLAMA_CHAT_MODEL
    options: dict = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    payload = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": options,
    }
    try:
        t0 = time.time()
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - t0
        result_text = (data.get("message", {}).get("content") or "").strip()
        logger.info("🤖 Ollama (%s) LLM call succeeded in %.2fs", target_model, elapsed)
        return result_text
    except urllib.error.URLError as exc:
        logger.error(
            "❌ Could not reach Ollama at %s — is `ollama serve` running and `%s` pulled? (%s)",
            OLLAMA_URL,
            target_model,
            exc,
        )
        raise
    except Exception as exc:
        logger.error("❌ Ollama LLM call exception: %s", exc, exc_info=True)
        raise


def chat_call(
    system: str,
    user: str,
    temperature: float = 0,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> str:
    """Single entry point for chat generation — routes to xAI or Ollama per CHAT_BACKEND."""
    if CHAT_BACKEND == "ollama":
        return _ollama_chat_call(
            system, user, temperature=temperature, max_tokens=max_tokens, model=model
        )
    return _xai_chat_call(
        system, user, temperature=temperature, max_tokens=max_tokens, model=model
    )


def chat_configured() -> bool:
    """True if the selected chat backend is usable."""
    if CHAT_BACKEND == "ollama":
        return True
    return bool(XAI_API_KEY)


_chat_call = chat_call
_chat_configured = chat_configured
