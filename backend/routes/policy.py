# backend/routes/policy.py — FastAPI Routes for HR Policy Assistant (Agent vs Workflow)
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.config import BASE_DIR, logger
from backend.schemas.policy import (
    BenchmarkCase,
    EmployeeRecord,
    PolicyOutputContract,
    PolicyQueryRequest,
)
from backend.services.policy_agent import run_agent_case
from backend.services.policy_benchmark_runner import PolicyBenchmarkRunManager, PolicyBenchmarkRunState
from backend.services.policy_tools import CANONICAL_EMPLOYEES
from backend.services.policy_workflow import run_workflow_case

router = APIRouter(prefix="/api/policy", tags=["policy"])


class PolicyBenchmarkStartRequest(BaseModel):
    top_k: int = Field(default=5, ge=1, le=20)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    model: Optional[str] = "llama3.1:8b"
    background: bool = Field(default=False)


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
        top_k_val = getattr(payload, "top_k", 5) or 5
        temp_val = getattr(payload, "temperature", 0.3)
        if temp_val is None:
            temp_val = 0.3
        model_val = getattr(payload, "model", "llama3.1:8b") or "llama3.1:8b"

        result = run_agent_case(
            case_id=payload.case_id or "custom_agent_case",
            employee_id=payload.employee_id,
            question=payload.question,
            top_k=top_k_val,
            temperature=temp_val,
            model=model_val,
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
        top_k_val = getattr(payload, "top_k", 5) or 5
        result = run_workflow_case(
            case_id=payload.case_id or "custom_wf_case",
            employee_id=payload.employee_id,
            question=payload.question,
            top_k=top_k_val,
        )
        return result
    except Exception as e:
        logger.exception(f"Policy workflow execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/benchmark")
def start_or_run_benchmark(payload: Optional[PolicyBenchmarkStartRequest] = None):
    """
    Execute or start the 10-case policy benchmark comparison.
    If payload.background is True, starts a background thread and returns run_id immediately.
    Otherwise runs synchronously and returns completed summary and case records.
    """
    cases = _load_benchmark_cases()
    if not cases:
        raise HTTPException(status_code=404, detail="Benchmark cases not found at benchmarks/policy_execution/cases.json")

    req = payload or PolicyBenchmarkStartRequest()
    manager = PolicyBenchmarkRunManager.get_instance()

    if req.background:
        run_state = manager.start_benchmark(
            cases=cases,
            top_k=req.top_k,
            temperature=req.temperature,
            model=req.model,
        )
        return JSONResponse(content=run_state.to_dict())

    # Synchronous execution
    run_state = PolicyBenchmarkRunState(
        run_id=f"bench_sync_{Path('.').resolve().name}",
        cases=cases,
        top_k=req.top_k,
        temperature=req.temperature,
        model=req.model,
    )
    manager._execute_benchmark_worker(run_state, cases)
    return JSONResponse(content=run_state.to_dict())


@router.post("/benchmark/start")
def start_benchmark_background(payload: Optional[PolicyBenchmarkStartRequest] = None):
    """Explicit endpoint to start an asynchronous background benchmark run."""
    cases = _load_benchmark_cases()
    if not cases:
        raise HTTPException(status_code=404, detail="Benchmark cases not found at benchmarks/policy_execution/cases.json")

    req = payload or PolicyBenchmarkStartRequest(background=True)
    manager = PolicyBenchmarkRunManager.get_instance()
    run_state = manager.start_benchmark(
        cases=cases,
        top_k=req.top_k,
        temperature=req.temperature,
        model=req.model,
    )
    return JSONResponse(content=run_state.to_dict())


@router.get("/benchmark/runs/active")
def get_active_benchmark_run():
    """Retrieve the currently running policy benchmark state, if any."""
    manager = PolicyBenchmarkRunManager.get_instance()
    active_run = manager.get_active_run()
    if active_run:
        return JSONResponse(content={"active": True, "run": active_run.to_dict()})
    return JSONResponse(content={"active": False, "run": None})


@router.get("/benchmark/runs/{run_id}")
def get_benchmark_run_status(run_id: str):
    """Poll live execution status and case-by-case progress for a specific benchmark run."""
    manager = PolicyBenchmarkRunManager.get_instance()
    run_state = manager.get_run(run_id)
    if not run_state:
        raise HTTPException(status_code=404, detail=f"Benchmark run {run_id} not found")
    return JSONResponse(content=run_state.to_dict())


@router.post("/benchmark/runs/{run_id}/cancel")
def cancel_benchmark_run(run_id: str):
    """Cancel an in-flight benchmark run."""
    manager = PolicyBenchmarkRunManager.get_instance()
    success = manager.cancel_run(run_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Could not cancel benchmark run {run_id}")
    return JSONResponse(content={"cancelled": True, "run_id": run_id})


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
