# backend/schemas/policy.py — Typed Pydantic Contracts and Schemas for HR Policy Execution
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.config import LLM_MODEL

# Strict execution budgets. Hard ceilings: callers may lower them, never raise them.
# Real document chunks are far larger than the two-sentence snippets the first
# prototype used, so the token ceiling is sized for a few retrieved passages
# re-sent on every loop lap. All four are overridable through the environment.
MAX_ITERATIONS: int = int(os.environ.get("POLICY_MAX_ITERATIONS", "6"))
MAX_TOKENS: int = int(os.environ.get("POLICY_MAX_TOKENS", "24000"))
MAX_COST: float = float(os.environ.get("POLICY_MAX_COST_USD", "0.05"))
MAX_WALL_CLOCK_SECONDS: float = float(os.environ.get("POLICY_MAX_WALL_CLOCK_SECONDS", "60"))
MAX_RETRIES: int = 2  # Maximum automatic run-level retries (initial attempt + 2 = 3 total)
MAX_INVALID_TOOL_CALLS: int = 2  # Rejected model tool calls tolerated before the run fails

# Token cost proxy — single source of truth, never scattered through code.
# The token cost is a proxy, not reported provider billing.
# This proxy rate ($0.50/1M tokens) is used only for educational cost comparison.
# UI must label this "Estimated Token Cost", not "Actual Cost".
TOKEN_COST_PER_1M: float = 0.50  # dollars per 1 million tokens
TOKEN_COST_PROXY_RATE: float = TOKEN_COST_PER_1M / 1_000_000  # = 0.000000_5


class PolicyQueryRequest(BaseModel):
    employee_id: str = Field(..., description="Unique Employee ID, e.g. EMP001")
    question: str = Field(..., description="The policy entitlement or rule query")
    case_id: Optional[str] = Field(None, description="Optional benchmark case ID")
    top_k: Optional[int] = Field(5, description="Top K retrieval count")
    temperature: Optional[float] = Field(0.3, description="LLM sampling temperature")
    model: Optional[str] = Field(LLM_MODEL, description="Model name")
    document_ids: Optional[List[str]] = Field(
        None, description="Restrict retrieval to these uploaded documents (default: all)"
    )


# Telemetry record for a single LLM call (including retries)
class LLMCallRecord(BaseModel):
    call_index: int  # 1-indexed within the run (retries count separately)
    attempt: int  # 1 = initial, 2 = retry 1, 3 = retry 2
    is_retry: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    token_source: str = "unavailable"
    status: str = "SUCCESS"  # "SUCCESS" | "RETRY" | "FAILED"
    retry_reason: Optional[str] = None
    retryable: bool = True


# Retry attempt record
class RetryRecord(BaseModel):
    attempt: int  # Which attempt number (1=initial, 2=retry1, 3=retry2)
    status: str  # "SUCCESS" | "RETRY" | "FAILED" | "BUDGET_EXHAUSTED"
    retry_reason: Optional[str] = None
    retryable: bool = True
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0


class PolicyOutputContract(BaseModel):
    # Identification
    case_id: str
    employee_id: str
    question: str
    run_id: str = ""
    evaluation_type: str = "WEEK7_POLICY_EXECUTION"

    # Result
    entitlement_value: str
    rule_cited: str
    explanation: str
    passed: bool = False
    # Legacy literal-substring verdict, kept so historical numbers stay comparable.
    # ``passed`` uses the normalised scorer in backend/services/policy_scoring.py.
    strict_passed: bool = False
    answer_criteria: List[Dict[str, Any]] = Field(default_factory=list)
    # Handbook citation check on ``rule_cited`` (see backend/services/handbook_index.py).
    citation: Dict[str, Any] = Field(default_factory=dict)
    implementation: str = "agent"  # "agent" | "workflow"

    # Routing metadata
    execution_mode: str = "workflow"  # "workflow" | "agent"
    routing_reason: str = ""
    complexity: str = "SIMPLE"
    routing_ms: float = 0.0
    mode_history: List[str] = Field(default_factory=list)  # tracks mode switches

    # Execution telemetry. Each tool call records the selected tool, its arguments,
    # result, attempts/retries and the model's stated rationale for choosing it.
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    # Model tool calls refused before execution (unknown tool, bad arguments, ...).
    rejected_tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    # Selection verdict + per-tool attempts/retries (see policy_trajectory.audit_tool_selection).
    tool_audit: Dict[str, Any] = Field(default_factory=dict)
    iterations: int = 1

    # Token accounting from the configured provider when available
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_source: str = "unavailable"
    llm_calls: List[Dict[str, Any]] = Field(default_factory=list)  # per-call breakdown

    # Cost — labeled as estimated, never as actual billing
    cost_usd: float = 0.0  # estimated token cost
    provider_cost: str = "N/A"  # Actual provider billing is not reported here.

    # Latency
    latency_ms: float = 0.0  # total request latency via time.perf_counter()
    router_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0

    # Retry metadata
    attempt: int = 1  # which attempt succeeded (1 = no retry needed)
    max_retries: int = MAX_RETRIES
    total_attempts: int = 1
    retry_history: List[Dict[str, Any]] = Field(default_factory=list)

    # Termination
    termination_reason: str = "SUCCESS"

    # Config provenance
    top_k: Optional[int] = None
    temperature: Optional[float] = None
    model: Optional[str] = None


class BenchmarkCase(BaseModel):
    case_id: str
    employee_id: str
    question: str
    source_section: str
    expected_value: str
    tenure_dependency: Optional[str] = None
    deterministic_pass_criteria: List[str] = Field(default_factory=list)
    # Extra accepted phrasings per criterion (the ground-truth criteria stay untouched).
    criteria_aliases: Dict[str, List[str]] = Field(default_factory=dict)
    # Must appear in the headline ``entitlement_value`` itself (not just the explanation).
    headline_criteria: List[str] = Field(default_factory=list)
    forbidden_phrases: List[str] = Field(default_factory=list)
    # Set for cases whose tool path depends on what an earlier tool returned.
    path_dependency: Optional[str] = None
