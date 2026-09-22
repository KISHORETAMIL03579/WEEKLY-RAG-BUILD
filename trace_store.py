"""
trace_store.py — Backwards-compatibility re-export module.
Authoritative implementation is in backend.storage.trace_store.
"""
from backend.storage.trace_store import (
    PROMPT_REGISTRY,
    PROMPTS_DIR,
    QA_PROMPT_VERSION,
    RERANK_PROMPT_VERSION,
    REWRITE_PROMPT_VERSION,
    TRACES,
    TraceStore,
    get_prompt,
    redact,
    redact_deep,
    register_prompt,
)

__all__ = [
    "PROMPT_REGISTRY",
    "PROMPTS_DIR",
    "QA_PROMPT_VERSION",
    "RERANK_PROMPT_VERSION",
    "REWRITE_PROMPT_VERSION",
    "TRACES",
    "TraceStore",
    "get_prompt",
    "redact",
    "redact_deep",
    "register_prompt",
]