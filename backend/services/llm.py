# backend/services/llm.py — LLM Chat Providers & Generation Router
import time
import json
import socket
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

from backend.services.chat_runs import ChatRunCancelled, get_current_chat_run
from backend.config import (
    CHAT_BACKEND,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_URL,
    OLLAMA_CHAT_MODEL,
    OLLAMA_URL,
    XAI_API_KEY,
    XAI_MODEL,
    XAI_URL,
    logger,
)


class ChatProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


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
            with urllib.request.urlopen(
                req, timeout=90 if not cancellation else 1
            ) as resp:
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


def groq_chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0,
    max_tokens: Optional[int] = None,
    timeout: float = 90,
    tools: Optional[list[dict]] = None,
    max_retries: int = 3,
) -> dict:
    """Call Groq's OpenAI-compatible API for text generation or tool calling."""
    if not GROQ_API_KEY:
        raise ChatProviderError("Groq", "GROQ_API_KEY is not configured")

    target_model = model or GROQ_MODEL
    payload: dict = {
        "model": target_model,
        "messages": messages,
        "temperature": temperature,
    }
    if target_model.startswith("openai/gpt-oss-"):
        payload["reasoning_effort"] = "low"
        payload["include_reasoning"] = False
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools

    cancellation = get_current_chat_run() if not tools else None
    if cancellation:
        payload["stream"] = True

    endpoint = f"{GROQ_URL.rstrip('/')}/chat/completions"
    deadline = time.monotonic() + max(0.001, timeout)
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, max(1, max_retries) + 1):
        started = time.perf_counter()
        request_timeout = deadline - time.monotonic()
        if request_timeout <= 0:
            raise TimeoutError("Groq request exceeded its execution time budget")
        timeout_config = httpx.Timeout(
            request_timeout,
            connect=min(10.0, request_timeout),
        )
        try:
            with httpx.Client(timeout=timeout_config) as client:
                if cancellation:
                    with client.stream(
                        "POST", endpoint, headers=headers, json=payload
                    ) as response:
                        response.raise_for_status()
                        cancellation.attach_response(response)
                        try:
                            pieces: list[str] = []
                            for line in response.iter_lines():
                                cancellation.check()
                                if not line.startswith("data:"):
                                    continue
                                event_text = line[5:].strip()
                                if event_text == "[DONE]":
                                    break
                                try:
                                    event = json.loads(event_text)
                                except json.JSONDecodeError:
                                    continue
                                choices = event.get("choices", [])
                                if choices:
                                    content = (
                                        choices[0].get("delta", {}).get("content")
                                    )
                                    if isinstance(content, str):
                                        pieces.append(content)
                            data = {
                                "choices": [
                                    {"message": {"content": "".join(pieces)}}
                                ]
                            }
                        finally:
                            cancellation.detach_response(response)
                else:
                    response = client.post(
                        endpoint, headers=headers, json=payload
                    )
                    response.raise_for_status()
                    data = response.json()

            if not isinstance(data, dict) or not isinstance(
                data.get("choices"), list
            ):
                raise ChatProviderError("Groq", "Groq returned an invalid response")
            data["_provider_attempts"] = attempt
            logger.info(
                "Groq chat call succeeded in %.2fs (model: %s)",
                time.perf_counter() - started,
                target_model,
            )
            return data
        except ChatRunCancelled:
            raise
        except httpx.HTTPStatusError as exc:
            if cancellation and cancellation.cancelled.is_set():
                raise ChatRunCancelled() from None
            status_code = exc.response.status_code
            if status_code in {429, 500, 502, 503, 504} and attempt < max_retries:
                retry_after = _retry_after_seconds(exc.response)
                delay = retry_after if retry_after is not None else min(
                    2 ** (attempt - 1), 8
                )
                remaining = deadline - time.monotonic()
                if delay >= remaining:
                    raise ChatProviderError(
                        "Groq",
                        "Groq retry delay exceeds the remaining request budget",
                        status_code,
                    ) from exc
                logger.warning(
                    "Groq request returned HTTP %d; retrying in %.2fs (%d/%d)",
                    status_code,
                    delay,
                    attempt,
                    max_retries,
                )
                if cancellation:
                    if delay > 0 and cancellation.cancelled.wait(delay):
                        raise ChatRunCancelled() from None
                    if delay == 0:
                        cancellation.check()
                elif delay > 0:
                    time.sleep(delay)
                continue
            logger.error("Groq request failed with HTTP %d", status_code)
            raise ChatProviderError(
                "Groq", f"Groq request failed with HTTP {status_code}", status_code
            ) from exc
        except httpx.TimeoutException as exc:
            if cancellation and cancellation.cancelled.is_set():
                raise ChatRunCancelled() from None
            if attempt < max_retries:
                delay = min(2 ** (attempt - 1), 8)
                logger.warning(
                    "Groq request timed out; retrying in %ds (%d/%d)",
                    delay,
                    attempt,
                    max_retries,
                )
                if cancellation:
                    if cancellation.cancelled.wait(delay):
                        raise ChatRunCancelled() from None
                else:
                    time.sleep(delay)
                continue
            raise TimeoutError("Groq request timed out") from exc
        except httpx.RequestError as exc:
            if cancellation and cancellation.cancelled.is_set():
                raise ChatRunCancelled() from None
            if attempt < max_retries:
                delay = min(2 ** (attempt - 1), 8)
                logger.warning(
                    "Groq network request failed (%s); retrying in %ds (%d/%d)",
                    type(exc).__name__,
                    delay,
                    attempt,
                    max_retries,
                )
                if cancellation:
                    if cancellation.cancelled.wait(delay):
                        raise ChatRunCancelled() from None
                else:
                    time.sleep(delay)
                continue
            raise ChatProviderError("Groq", "Groq network request failed") from exc
        except Exception as exc:
            if cancellation and cancellation.cancelled.is_set():
                raise ChatRunCancelled() from None
            if isinstance(exc, ChatProviderError):
                raise
            logger.error(
                "Groq request failed (error_type=%s)", type(exc).__name__
            )
            raise ChatProviderError("Groq", "Groq request failed") from exc

    raise ChatProviderError("Groq", "Groq request failed after retries")


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
        with urllib.request.urlopen(
            req, timeout=180 if not cancellation else 1
        ) as resp:
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
    """Single entry point for chat generation across the configured provider."""
    if CHAT_BACKEND == "ollama":
        return _ollama_chat_call(
            system, user, temperature=temperature, max_tokens=max_tokens, model=model
        )
    if CHAT_BACKEND == "groq":
        response = groq_chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        result_text = (
            response["choices"][0].get("message", {}).get("content") or ""
        ).strip()
        if not result_text:
            raise ChatProviderError("Groq", "Groq returned empty content")
        return result_text
    if CHAT_BACKEND == "xai":
        return _xai_chat_call(
            system, user, temperature=temperature, max_tokens=max_tokens, model=model
        )
    raise RuntimeError(f"Unsupported CHAT_BACKEND: {CHAT_BACKEND}")


def chat_configured() -> bool:
    """True if the selected chat backend is usable."""
    if CHAT_BACKEND == "ollama":
        return True
    if CHAT_BACKEND == "xai":
        return bool(XAI_API_KEY)
    if CHAT_BACKEND == "groq":
        return bool(GROQ_API_KEY)
    return False


_chat_call = chat_call
_chat_configured = chat_configured
