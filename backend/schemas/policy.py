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
TOKEN_COST_PROXY_RATE: float = 0.000002

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

class PolicyOutputContract(BaseModel):
    case_id: str
    employee_id: str
    question: str
    entitlement_value: str
    rule_cited: str
    explanation: str
    passed: bool = False
    implementation: str = "agent"
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    iterations: int = 1
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    termination_reason: str = "SUCCESS"
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
