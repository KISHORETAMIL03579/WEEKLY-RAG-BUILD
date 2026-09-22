# backend/schemas/evaluation.py — Pydantic Schemas for Retrieval & Judge Evaluations
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class _LenientModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EvalQuestion(_LenientModel):
    id: Optional[str] = None
    question: Optional[str] = None
    expected: Optional[str] = None
    expected_doc: Optional[str] = None
    expected_section: Optional[str] = None


EvalQuestionInput = EvalQuestion


class EvalRunPayload(_LenientModel):
    questions: List[EvalQuestion] = Field(default_factory=list)
    top_k: Optional[int] = None
    k: int = 3
    strategy_filter: Optional[str] = None
    chunk_mode: Optional[str] = None
    presets: Optional[List[str]] = None
    modes: Optional[List[str]] = None  # legacy alias for `presets`


EvalRunRequest = EvalRunPayload


class EvalQuestionResult(BaseModel):
    id: str
    question: str
    expected: Optional[str] = None
    expected_doc: Optional[str] = None
    expected_section: Optional[str] = None
    hit: bool
    rank: Optional[int] = None


class EvalModeResult(BaseModel):
    hit_rate: float
    mrr: float
    hits: int
    total: int
    results: List[EvalQuestionResult]


class EvalRunResponse(BaseModel):
    k: int
    modes: Dict[str, EvalModeResult]
    error: Optional[str] = None


# Judge Evaluation Schemas
class Week6CasePayload(BaseModel):
    case_id: Optional[str] = None
    trace_id: Optional[str] = None
    question: str
    answer: str
    retrieved_context: Optional[str] = ""
    handbook_version: Optional[str] = "2018"
    section_info: Optional[str] = ""
    taxonomy_mode: Optional[str] = "General"
    human_label: Optional[int] = 1
    expected_numeric: Optional[str] = None
    out_of_jurisdiction: bool = False
    failure_category: Optional[str] = None
    failure_type: Optional[str] = None
    failure_reason: Optional[str] = None
    resolution: Optional[str] = None


class Week6EvalPayload(BaseModel):
    cases: Optional[List[Week6CasePayload]] = None
    run_llm: bool = True


JudgeCasePayload = Week6CasePayload
JudgeEvalPayload = Week6EvalPayload

