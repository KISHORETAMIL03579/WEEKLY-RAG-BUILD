# backend/schemas/policy.py — Data Contracts, Enums, and Budget Definitions for Policy Agent & Workflow
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Budget Constraints & Cost Constants
# ---------------------------------------------------------------------------

MAX_ITERATIONS: int = 5
MAX_TOKENS: int = 4000
MAX_COST: float = 0.05
MAX_WALL_CLOCK_SECONDS: float = 30.0
TOKEN_COST_PROXY_RATE: float = 0.50 / 1_000_000  # $0.50 per 1M tokens


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class EmployeeRecord(BaseModel):
    employee_id: str
    name: str
    job_title: str
    department: str
    duty_station: str
    jurisdiction: JurisdictionEnum
    tenure_months: int
    employment_status: str  # "Probation" | "Confirmed"
    annual_leave_balance: int
    basic_salary_monthly: float
    separation_reason: Optional[str] = None


class ToolCallRecord(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    output: Any
    latency_ms: float = 0.0


class PolicyOutputContract(BaseModel):
    case_id: str
    employee_id: str
    question: str
    entitlement_value: str
    rule_cited: str
    explanation: str
    passed: bool = False
    implementation: str = "agent"  # "agent" | "workflow"
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    iterations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    termination_reason: str = "SUCCESS"  # "SUCCESS" | "BUDGET_ITERATIONS" | "BUDGET_TOKENS" | "BUDGET_COST" | "BUDGET_WALL_CLOCK" | "ERROR"


# Alias for backward compatibility if referenced
Week7OutputContract = PolicyOutputContract


class BenchmarkCase(BaseModel):
    case_id: str
    employee_id: str
    question: str
    source_section: str
    expected_value: str
    tenure_dependency: str
    deterministic_pass_criteria: List[str]
