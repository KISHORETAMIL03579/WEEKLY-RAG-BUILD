# backend/schemas/trace.py — Pydantic Schemas for Tracing & Auditing
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TracesResponse(BaseModel):
    count: int
    trace_ids: List[str] = Field(default_factory=list)


class TraceRecord(BaseModel):
    trace_id: str
    session_id: str
    timestamp: float
    query: str
    answer: str
    confidence: Optional[float] = None
    retrieval_strategy: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    durations_ms: Dict[str, float] = Field(default_factory=dict)


class ReplayResponse(BaseModel):
    trace_id: str
    original: Dict[str, Any]
    replayed: Dict[str, Any]
    match: bool
