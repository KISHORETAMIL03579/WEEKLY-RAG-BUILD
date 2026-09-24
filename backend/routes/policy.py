# backend/routes/policy.py — FastAPI Routes for HR Policy Assistant (Agent vs Workflow)
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.config import BASE_DIR, logger
from backend.schemas.policy import (
    BenchmarkCase,
    EmployeeRecord,
    PolicyOutputContract,
    PolicyQueryRequest,
)
from backend.services.policy_agent import run_agent_case
from backend.services.policy_tools import CANONICAL_EMPLOYEES
from backend.services.policy_workflow import run_workflow_case

router = APIRouter(prefix="/api/policy", tags=["policy"])


def _load_benchmark_cases() -> List[Dict[str, Any]]:
    """Loads benchmark cases from benchmarks/policy_execution/cases.json."""
    cases_file = BASE_DIR / "benchmarks" / "policy_execution" / "cases.json"
    if cases_file.exists():
        try:
            with open(cases_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load benchmark cases from {cases_file}: {e}")
    return []


@router.get("/cases", response_model=List[Dict[str, Any]])
def get_benchmark_cases():
    """Retrieve the standard 10 verified HR policy benchmark cases."""
    cases = _load_benchmark_cases()
    return JSONResponse(content=cases)


@router.get("/employees")
def get_canonical_employees():
    """Retrieve canonical employee records for testing policy execution."""
    employees = [emp.model_dump() for emp in CANONICAL_EMPLOYEES.values()]
    return JSONResponse(content=employees)


@router.post("/agent", response_model=PolicyOutputContract)
def execute_policy_agent(payload: PolicyQueryRequest):
    """
    Execute the Dynamic ReAct HR Policy Agent on an employee entitlement question.
    Enforces the 4 strict budgets (iterations, tokens, cost, wall-clock).
    """
    try:
        result = run_agent_case(
            case_id=payload.case_id or "custom_agent_case",
            employee_id=payload.employee_id,
            question=payload.question,
        )
        return result
    except Exception as e:
        logger.exception(f"Policy agent execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workflow", response_model=PolicyOutputContract)
def execute_policy_workflow(payload: PolicyQueryRequest):
    """
    Execute the Fixed 3-Step Deterministic HR Policy Workflow on an employee entitlement question.
    """
    try:
        result = run_workflow_case(
            case_id=payload.case_id or "custom_wf_case",
            employee_id=payload.employee_id,
            question=payload.question,
        )
        return result
    except Exception as e:
        logger.exception(f"Policy workflow execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/benchmark")
def run_benchmark_comparison():
    """
    Execute the full 10-case benchmark comparison between Policy Agent and Policy Workflow.
    Returns scorecard metrics (pass rate, p50 latency, token totals, cost) and detailed rows.
    """
    cases = _load_benchmark_cases()
    if not cases:
        raise HTTPException(status_code=404, detail="Benchmark cases not found at benchmarks/policy_execution/cases.json")

    agent_results: List[PolicyOutputContract] = []
    workflow_results: List[PolicyOutputContract] = []

    for c in cases:
        cid = c.get("case_id", "")
        empid = c.get("employee_id", "")
        q = c.get("question", "")
        crit = c.get("deterministic_pass_criteria", [])

        # Run Agent
        a_res = run_agent_case(cid, empid, q, deterministic_pass_criteria=crit)
        agent_results.append(a_res)

        # Run Workflow
        w_res = run_workflow_case(cid, empid, q, deterministic_pass_criteria=crit)
        workflow_results.append(w_res)

    def _summarize(results: List[PolicyOutputContract]) -> Dict[str, Any]:
        n = len(results)
        passed = sum(1 for r in results if r.passed)
        lats = sorted([r.latency_ms for r in results])
        p50 = lats[n // 2] if n else 0.0
        tot_tok = sum(r.total_tokens for r in results)
        tot_cost = sum(r.cost_usd for r in results)
        cost_per_q = tot_cost / n if n else 0.0
        return {
            "pass_rate_pct": round((passed / n) * 100, 1) if n else 0.0,
            "passed_count": passed,
            "total_cases": n,
            "p50_latency_ms": round(p50, 3),
            "total_tokens": tot_tok,
            "cost_per_question_usd": round(cost_per_q, 6),
        }

    summary = {
        "agent": _summarize(agent_results),
        "workflow": _summarize(workflow_results),
    }

    return JSONResponse(
        content={
            "summary": summary,
            "agent_results": [r.model_dump() for r in agent_results],
            "workflow_results": [r.model_dump() for r in workflow_results],
        }
    )


@router.get("/benchmark/latest")
def get_latest_benchmark_results():
    """Retrieve the saved results.csv rows from the last benchmark run."""
    csv_file = BASE_DIR / "benchmarks" / "policy_execution" / "results.csv"
    if not csv_file.exists():
        return JSONResponse(content={"rows": []})

    rows = []
    try:
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
    except Exception as e:
        logger.error(f"Error reading benchmark results CSV: {e}")

    return JSONResponse(content={"rows": rows})
