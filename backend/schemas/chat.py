# backend/schemas/chat.py — Pydantic Schemas for Q&A and Chat Interactions
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class _LenientModel(BaseModel):
    """Base for request bodies: unknown keys are ignored rather than rejected."""

    model_config = ConfigDict(extra="ignore")


class AskPayload(_LenientModel):
    query: str = ""
    chunk_mode: Optional[str] = None
    top_k: Optional[int] = None
    temperature: Optional[float] = None
    turn_id: Optional[str] = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
    )
    run_id: Optional[str] = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
    )


AskRequest = AskPayload


class SourceMetadata(BaseModel):
    filename: str
    section: Optional[str] = None
    page: Optional[int] = None
    score: Optional[float] = None
    chunk_mode: Optional[str] = None
    text: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: Optional[float] = None
    latency_ms: Optional[float] = None
    trace_id: Optional[str] = None


class ClearResponse(BaseModel):
    ok: bool = True
    warning: Optional[str] = None


class StatusDocument(BaseModel):
    filename: str
    doc_id: str
    chunk_count: int
    method: str
    openable: bool


class StatusResponse(BaseModel):
    total_chunks: int
    documents: List[StatusDocument]
    methods: List[str]
    mode: str
    vector_backend: str


class HealthzResponse(BaseModel):
    status: str
    embeddings_configured: bool
    chat_configured: bool
    chat_backend: str
    embeddings_backend: str
    retrieval_mode: str
    vector_backend: str
    active_sessions: int


class ReadyzResponse(BaseModel):
    ready: bool
    checks: Dict[str, bool]
