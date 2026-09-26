# backend/schemas/policy.py — Typed Pydantic Contracts and Schemas for HR Policy Execution
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# Strict Execution Budgets & Constants
MAX_ITERATIONS: int = 5
MAX_TOKENS: int = 4000
MAX_COST: float = 0.05
MAX_WALL_CLOCK_SECONDS: float = 45.0
MAX_RETRIES: int = 2                     # Maximum automatic retries (initial attempt + 2 = 3 total)

# Token cost proxy — single source of truth, never scattered through code.
# Local Ollama has no direct provider billing cost.
# This proxy rate ($0.50/1M tokens) is used only for educational cost comparison.
# UI must label this "Estimated Token Cost", not "Actual Cost".
TOKEN_COST_PER_1M: float = 0.50          # dollars per 1 million tokens
TOKEN_COST_PROXY_RATE: float = TOKEN_COST_PER_1M / 1_000_000  # = 0.000000_5


class JurisdictionEnum(str, Enum):
    KENYA = "Kenya"
    IRELAND = "Ireland"
    COTE_D_IVOIRE = "Cote d'Ivoire"
    RWANDA = "Rwanda"
    GLOBAL = "Global"


class PolicyCategoryEnum(str, Enum):
    LEAVE = "leave"
    NOTICE_AND_SEPARATION = "notice_and_separation"
    BENEFITS_AND_PENSION = "benefits_and_pension"
    HOLIDAYS_AND_WORKING_HOURS = "holidays_and_working_hours"
    CONDUCT_AND_DISCIPLINE = "conduct_and_discipline"


class EmployeeRecord(BaseModel):
    employee_id: str
    name: str
    job_title: str
    department: str
    duty_station: str
    jurisdiction: JurisdictionEnum
    tenure_months: int
    employment_status: str
    annual_leave_balance: int = 0
    basic_salary_monthly: float = 0.0
    separation_reason: Optional[str] = None


class PolicyQueryRequest(BaseModel):
    employee_id: str = Field(..., description="Unique Employee ID, e.g. EMP001")
    question: str = Field(..., description="The policy entitlement or rule query")
    case_id: Optional[str] = Field(None, description="Optional benchmark case ID")
    top_k: Optional[int] = Field(5, description="Top K retrieval count")
    temperature: Optional[float] = Field(0.3, description="LLM sampling temperature")
    model: Optional[str] = Field("llama3.1:8b", description="Model name")


# Telemetry record for a single LLM call (including retries)
class LLMCallRecord(BaseModel):
    call_index: int                  # 1-indexed within the run (retries count separately)
    attempt: int                     # 1 = initial, 2 = retry 1, 3 = retry 2
    is_retry: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    token_source: str = "ollama_live"  # "ollama_live" | "proxy_estimate" | "unavailable"
    status: str = "SUCCESS"           # "SUCCESS" | "RETRY" | "FAILED"
    retry_reason: Optional[str] = None
    retryable: bool = True


# Retry attempt record
class RetryRecord(BaseModel):
    attempt: int                     # Which attempt number (1=initial, 2=retry1, 3=retry2)
    status: str                      # "SUCCESS" | "RETRY" | "FAILED" | "BUDGET_EXHAUSTED"
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
    implementation: str = "agent"      # "agent" | "workflow"

    # Routing metadata
    execution_mode: str = "workflow"   # "workflow" | "agent"
    routing_reason: str = ""
    complexity: str = "SIMPLE"
    routing_ms: float = 0.0
    mode_history: List[str] = Field(default_factory=list)  # tracks mode switches

    # Execution telemetry
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    iterations: int = 1

    # Token accounting — real Ollama metadata preferred
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_source: str = "unavailable"  # "ollama_live" | "proxy_estimate" | "unavailable"
    llm_calls: List[Dict[str, Any]] = Field(default_factory=list)  # per-call breakdown

    # Cost — labeled as estimated, never as actual billing
    cost_usd: float = 0.0              # estimated token cost
    provider_cost: str = "N/A"         # always "N/A" for local Ollama

    # Latency
    latency_ms: float = 0.0            # total request latency via time.perf_counter()
    router_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0

    # Retry metadata
    attempt: int = 1                   # which attempt succeeded (1 = no retry needed)
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
