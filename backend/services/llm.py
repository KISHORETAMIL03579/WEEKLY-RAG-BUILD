# backend/services/llm.py — LLM Chat Providers & Generation Router
import time
import json
import socket
import urllib.request
import urllib.error
from typing import Optional

from backend.services.chat_runs import ChatRunCancelled, get_current_chat_run
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

    cancellation = get_current_chat_run()
    max_retries = 5
    base_delay = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            if cancellation:
                cancellation.check()
            t0 = time.time()
            if cancellation:
                payload["stream"] = True
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + XAI_API_KEY,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90 if not cancellation else 1) as resp:
                if cancellation:
                    cancellation.attach_response(resp)
                    try:
                        pieces = []
                        deadline = time.monotonic() + 90
                        while True:
                            cancellation.check()
                            if time.monotonic() >= deadline:
                                raise TimeoutError("xAI response timed out")
                            try:
                                line = resp.readline()
                            except (socket.timeout, TimeoutError):
                                continue
                            if not line:
                                break
                            text = line.decode("utf-8").strip()
                            if not text.startswith("data:"):
                                continue
                            text = text[5:].strip()
                            if text == "[DONE]":
                                break
                            try:
                                event = json.loads(text)
                            except json.JSONDecodeError:
                                continue
                            choices = event.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if isinstance(content, str):
                                    pieces.append(content)
                        result_text = "".join(pieces).strip()
                        data = {"choices": [{"message": {"content": result_text}}]}
                    finally:
                        cancellation.detach_response(resp)
                else:
                    data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0
            choices = data.get("choices", [])
            if not choices:
                logger.error("xAI response contained no choices")
                raise RuntimeError("xAI response contained no choices")
            result_text = (choices[0].get("message", {}).get("content") or "").strip()
            if not result_text:
                logger.error("xAI response contained empty content")
                raise RuntimeError("xAI response contained empty content")
            logger.info(
                "🤖 xAI (Grok) LLM call succeeded in %.2fs (model: %s)",
                elapsed,
                target_model,
            )
            return result_text
        except urllib.error.HTTPError as exc:
            if cancellation and cancellation.cancelled.is_set():
                raise ChatRunCancelled() from None
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
                logger.error("❌ xAI LLM call failed with HTTP %d", exc.code)
                raise
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            if cancellation and cancellation.cancelled.is_set():
                raise ChatRunCancelled() from None
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                if cancellation:
                    if cancellation.cancelled.wait(delay):
                        raise ChatRunCancelled() from None
                    continue
                logger.warning(
                    "⏳ xAI LLM network failure (%s). Retrying in %.1fs (attempt %d/%d)...",
                    type(exc).__name__,
                    delay,
                    attempt,
                    max_retries,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "❌ xAI LLM network call failed after %d attempts (%s)",
                    max_retries,
                    type(exc).__name__,
                )
                raise
        except Exception as exc:
            if cancellation and cancellation.cancelled.is_set():
                raise ChatRunCancelled() from None
            logger.error("❌ xAI LLM call failed (error_type=%s)", type(exc).__name__)
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
        "stream": get_current_chat_run() is not None,
        "options": options,
    }
    cancellation = get_current_chat_run()
    try:
        t0 = time.time()
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180 if not cancellation else 1) as resp:
            if cancellation:
                cancellation.attach_response(resp)
                try:
                    pieces = []
                    deadline = time.monotonic() + 180
                    while True:
                        cancellation.check()
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Ollama response timed out")
                        try:
                            line = resp.readline()
                        except (socket.timeout, TimeoutError):
                            continue
                        if not line:
                            break
                        data_line = json.loads(line.decode("utf-8"))
                        message = data_line.get("message", {})
                        content = message.get("content", "")
                        if isinstance(content, str):
                            pieces.append(content)
                        if data_line.get("done"):
                            break
                    result_text = "".join(pieces).strip()
                    data = {"message": {"content": result_text}}
                finally:
                    cancellation.detach_response(resp)
            else:
                data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - t0
        result_text = (data.get("message", {}).get("content") or "").strip()
        logger.info("🤖 Ollama (%s) LLM call succeeded in %.2fs", target_model, elapsed)
        return result_text
    except urllib.error.URLError as exc:
        if cancellation and cancellation.cancelled.is_set():
            raise ChatRunCancelled() from None
        logger.error(
            "❌ Could not reach Ollama at %s — is `ollama serve` running and `%s` pulled? (%s)",
            OLLAMA_URL,
            target_model,
            exc,
        )
        raise
    except Exception as exc:
        if cancellation and cancellation.cancelled.is_set():
            raise ChatRunCancelled() from None
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
