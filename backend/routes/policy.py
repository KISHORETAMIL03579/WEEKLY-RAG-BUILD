# backend/routes/policy.py — FastAPI Routes for HR Policy Assistant (Week 7)
# Week 7 Responsibilities:
#   - /api/policy/search   → auto-routes to workflow or agent based on question complexity
#   - /api/policy/agent    → direct agent execution (for explicit/benchmark use)
#   - /api/policy/workflow → direct workflow execution (for explicit/benchmark use)
#   - /api/policy/benchmark* → 10-case benchmark comparison runs
#
# Week 6 is handled separately by backend/routes/evaluation.py
from __future__ import annotations

import csv
import json
import socket
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.config import BASE_DIR, OLLAMA_CHAT_MODEL, OLLAMA_URL, logger
from backend.schemas.policy import (
    MAX_RETRIES,
    MAX_COST,
    MAX_TOKENS,
    MAX_WALL_CLOCK_SECONDS,
    TOKEN_COST_PROXY_RATE,
    BenchmarkCase,
    EmployeeRecord,
    PolicyOutputContract,
    PolicyQueryRequest,
)
from backend.services.policy_agent import run_agent_case
from backend.services.policy_benchmark_runner import (
    PolicyBenchmarkRunManager,
    PolicyBenchmarkRunState,
)
from backend.services.policy_router import (
    route_policy_question,
    MODE_WORKFLOW,
    MODE_AGENT,
)
from backend.services.policy_tools import CANONICAL_EMPLOYEES
from backend.services.policy_workflow import run_workflow_case

router = APIRouter(prefix="/api/policy", tags=["policy"])


# ── Non-retryable error reasons ──────────────────────────────────────────────
_NON_RETRYABLE_TERMINATION_REASONS = {
    "BUDGET_ITERATIONS",
    "BUDGET_TOKENS",
    "BUDGET_COST",
    "BUDGET_WALL_CLOCK",
    "INVALID_EMPLOYEE",
    "INVALID_ARGUMENTS",
}

_RETRYABLE_REASONS = {
    "OLLAMA_TIMEOUT",
    "OLLAMA_UNAVAILABLE",
    "TRANSIENT_NETWORK",
    "PROVIDER_TRANSIENT",
    "MODEL_ERROR",
    "TOOL_ERROR",
}


def _is_retryable(termination_reason: str) -> bool:
    """Return True only for transient, retryable failures."""
    return termination_reason in _RETRYABLE_REASONS


def _run_with_retries(
    mode: str,
    employee_id: str,
    question: str,
    case_id: str,
    top_k: int,
    temperature: float,
    model: str,
    max_retries: int = MAX_RETRIES,
    max_wall_clock: float = MAX_WALL_CLOCK_SECONDS,
) -> tuple[PolicyOutputContract, list[dict]]:
    """
    Execute workflow or agent with automatic retry for transient failures.

    Retry contract:
      - Initial attempt is attempt=1
      - Maximum retries = MAX_RETRIES (2), so maximum total attempts = 3
      - Non-retryable failures (budget exhausted, invalid data) are NOT retried
      - Mode does NOT change during retry (agent retries as agent)
      - All token/latency/cost from retries accumulate in total
    """
    retry_history: list[dict] = []
    accumulated_tokens = 0
    accumulated_prompt_tokens = 0
    accumulated_completion_tokens = 0
    accumulated_cost = 0.0
    accumulated_latency = 0.0
    accumulated_llm_calls: list[dict] = []
    accumulated_token_source = "unavailable"
    max_total_attempts = 1 + max_retries  # initial + retries
    execution_started = time.perf_counter()

    last_result: Optional[PolicyOutputContract] = None

    if type(max_retries) is not int or not 0 <= max_retries <= MAX_RETRIES:
        raise ValueError(f"max_retries must be between 0 and {MAX_RETRIES}")

    for attempt in range(1, max_total_attempts + 1):
        remaining_wall_clock = max_wall_clock - (
            time.perf_counter() - execution_started
        )
        remaining_tokens = MAX_TOKENS - accumulated_tokens
        remaining_cost = MAX_COST - accumulated_cost
        budget_reason = (
            "BUDGET_WALL_CLOCK"
            if remaining_wall_clock <= 0
            else (
                "BUDGET_TOKENS"
                if remaining_tokens <= 0
                else "BUDGET_COST" if remaining_cost <= 0 else None
            )
        )
        if budget_reason:
            budget_explanations = {
                "BUDGET_WALL_CLOCK": "Policy execution stopped because its wall-clock budget was exhausted.",
                "BUDGET_TOKENS": "Policy execution stopped because its token budget was exhausted.",
                "BUDGET_COST": "Policy execution stopped because its cost budget was exhausted.",
            }
            retry_history.append(
                {
                    "attempt": attempt,
                    "status": "BUDGET_EXHAUSTED",
                    "latency_ms": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost": 0.0,
                    "is_retry": attempt > 1,
                    "retryable": False,
                    "retry_reason": budget_reason,
                }
            )
            failed_result = PolicyOutputContract(
                case_id=case_id,
                employee_id=employee_id,
                question=question,
                entitlement_value="",
                rule_cited="",
                explanation=budget_explanations[budget_reason],
                passed=False,
                implementation=mode,
                execution_mode=mode,
                termination_reason=budget_reason,
                latency_ms=round((time.perf_counter() - execution_started) * 1000, 3),
                prompt_tokens=accumulated_prompt_tokens,
                completion_tokens=accumulated_completion_tokens,
                total_tokens=accumulated_tokens,
                cost_usd=accumulated_cost,
                attempt=max(1, attempt - 1),
                total_attempts=max(1, attempt - 1),
                retry_history=retry_history,
                llm_calls=accumulated_llm_calls,
                token_source=accumulated_token_source,
                top_k=top_k,
                temperature=temperature,
                model=model,
            )
            return failed_result, retry_history

        attempt_start = time.perf_counter()
        is_retry = attempt > 1
        retry_reason = None

        try:
            if mode == MODE_WORKFLOW:
                result = run_workflow_case(
                    case_id=case_id,
                    employee_id=employee_id,
                    question=question,
                    top_k=top_k,
                )
            else:
                result = run_agent_case(
                    case_id=case_id,
                    employee_id=employee_id,
                    question=question,
                    top_k=top_k,
                    temperature=temperature,
                    model=model,
                    max_tokens=remaining_tokens,
                    max_cost=remaining_cost,
                    max_wall_clock=remaining_wall_clock,
                )

            attempt_ms = (time.perf_counter() - attempt_start) * 1000
            accumulated_prompt_tokens += result.prompt_tokens
            accumulated_completion_tokens += result.completion_tokens
            accumulated_tokens += result.total_tokens
            accumulated_cost += result.cost_usd
            accumulated_latency += attempt_ms
            if result.token_source == "ollama_live":
                accumulated_token_source = "ollama_live"
            elif (
                result.token_source == "proxy_estimate"
                and accumulated_token_source == "unavailable"
            ):
                accumulated_token_source = "proxy_estimate"
            call_index_base = len(accumulated_llm_calls)
            accumulated_llm_calls.extend(
                {
                    **call,
                    "call_index": call_index_base + index + 1,
                    "attempt": attempt,
                    "is_retry": is_retry,
                }
                for index, call in enumerate(result.llm_calls)
            )

            if time.perf_counter() - execution_started >= max_wall_clock:
                result.termination_reason = "BUDGET_WALL_CLOCK"
                result.passed = False
                result.entitlement_value = ""
                result.rule_cited = ""
                result.explanation = "Policy execution stopped because its wall-clock budget was exhausted."

            result_ok = result.termination_reason == "SUCCESS"
            retryable = False if result_ok else _is_retryable(result.termination_reason)
            will_retry = retryable and attempt < max_total_attempts
            retry_history.append(
                {
                    "attempt": attempt,
                    "status": (
                        "SUCCESS"
                        if result_ok
                        else ("RETRY" if will_retry else "FAILED")
                    ),
                    "latency_ms": round(attempt_ms, 3),
                    "input_tokens": result.prompt_tokens,
                    "output_tokens": result.completion_tokens,
                    "total_tokens": result.total_tokens,
                    "estimated_cost": round(result.cost_usd, 8),
                    "is_retry": is_retry,
                    "retryable": retryable,
                    "retry_reason": None if result_ok else result.termination_reason,
                }
            )

            if result_ok or not will_retry:
                result.total_tokens = accumulated_tokens
                result.prompt_tokens = accumulated_prompt_tokens
                result.completion_tokens = accumulated_completion_tokens
                result.cost_usd = accumulated_cost
                result.latency_ms = round(accumulated_latency, 3)
                result.llm_calls = accumulated_llm_calls
                result.token_source = accumulated_token_source
                result.attempt = attempt
                result.total_attempts = attempt
                result.retry_history = retry_history
                last_result = result
                return result, retry_history

            last_result = result
            logger.warning(
                f"Attempt {attempt} failed ({result.termination_reason}), retrying... "
                f"({max_total_attempts - attempt} remaining)"
            )
            continue

        except Exception as exc:
            attempt_ms = (time.perf_counter() - attempt_start) * 1000
            # Determine if this is retryable
            exc_str = str(exc).upper()
            if "TIMEOUT" in exc_str:
                retry_reason = "OLLAMA_TIMEOUT"
                retryable = True
            elif "CONNECTION" in exc_str or "NETWORK" in exc_str:
                retry_reason = "TRANSIENT_NETWORK"
                retryable = True
            elif "BUDGET" in exc_str:
                retry_reason = exc_str
                retryable = False
            else:
                retry_reason = "MODEL_ERROR"
                retryable = True
            if time.perf_counter() - execution_started >= max_wall_clock:
                retry_reason = "BUDGET_WALL_CLOCK"
                retryable = False
            else:
                retryable = _is_retryable(retry_reason)

            retry_history.append(
                {
                    "attempt": attempt,
                    "status": (
                        "RETRY"
                        if (retryable and attempt < max_total_attempts)
                        else "FAILED"
                    ),
                    "latency_ms": round(attempt_ms, 3),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost": 0.0,
                    "is_retry": is_retry,
                    "retryable": retryable,
                    "retry_reason": retry_reason,
                }
            )

            accumulated_latency += attempt_ms

            if not retryable or attempt >= max_total_attempts:
                logger.exception(
                    "Policy execution failed after %d attempt(s) (%s)",
                    attempt,
                    retry_reason,
                )
                if retry_reason == "OLLAMA_TIMEOUT":
                    safe_message = (
                        "The model provider timed out before generating an answer."
                    )
                elif retry_reason == "TRANSIENT_NETWORK":
                    safe_message = "A required provider or tool could not be reached."
                else:
                    safe_message = "The policy request failed because the model provider returned an error."
                failed_result = PolicyOutputContract(
                    case_id=case_id,
                    employee_id=employee_id,
                    question=question,
                    entitlement_value="",
                    rule_cited="",
                    explanation=safe_message,
                    passed=False,
                    implementation=mode,
                    execution_mode=mode,
                    termination_reason=(retry_reason or "MODEL_ERROR"),
                    latency_ms=round(accumulated_latency, 3),
                    prompt_tokens=accumulated_prompt_tokens,
                    completion_tokens=accumulated_completion_tokens,
                    total_tokens=accumulated_tokens,
                    cost_usd=accumulated_cost,
                    llm_calls=accumulated_llm_calls,
                    token_source=accumulated_token_source,
                    attempt=attempt,
                    total_attempts=attempt,
                    retry_history=retry_history,
                    top_k=top_k,
                    temperature=temperature,
                    model=model,
                )
                return failed_result, retry_history

            logger.warning(
                f"Attempt {attempt} failed ({retry_reason}), retrying... ({max_total_attempts - attempt} remaining)"
            )

    # Should not reach here, but safety net
    return (
        last_result
        or PolicyOutputContract(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            entitlement_value="",
            rule_cited="",
            explanation="Unexpected retry exhaustion",
            passed=False,
            implementation=mode,
            termination_reason="MAX_RETRIES",
        ),
        retry_history,
    )


class PolicyBenchmarkStartRequest(BaseModel):
    top_k: int = Field(default=5, ge=1, le=20)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    model: Optional[str] = OLLAMA_CHAT_MODEL
    background: bool = Field(default=False)
    cases: Optional[List[Dict[str, Any]]] = None


class PolicySearchRequest(BaseModel):
    """Request for auto-routed HR policy search."""

    employee_id: str = Field(..., description="Employee ID, e.g. EMP001")
    question: str = Field(..., description="HR policy question")
    case_id: Optional[str] = None
    top_k: Optional[int] = Field(5, ge=1, le=20)
    temperature: Optional[float] = Field(0.3, ge=0.0, le=1.0)
    model: Optional[str] = OLLAMA_CHAT_MODEL
    max_retries: Optional[int] = Field(MAX_RETRIES, ge=0, le=MAX_RETRIES)
    force_mode: Optional[str] = None  # "workflow" | "agent" | None (auto-route)


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


@router.get("/models")
def get_available_ollama_models():
    """Return the installed Ollama models that can be used for chat execution."""
    request = urllib.request.Request(
        f"{OLLAMA_URL.rstrip('/')}/api/tags",
        headers={"User-Agent": "AskMyDocs-ModelList"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("Ollama model list returned HTTP %d", exc.code)
        raise HTTPException(
            status_code=503, detail="Unable to load installed Ollama models."
        ) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        logger.warning(
            "Ollama model list request failed (error_type=%s)",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503, detail="Unable to load installed Ollama models."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error("Ollama returned an invalid model list response")
        raise HTTPException(
            status_code=502, detail="Ollama returned an invalid model list."
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        logger.error("Ollama model list response omitted its models array")
        raise HTTPException(
            status_code=502, detail="Ollama returned an invalid model list."
        )

    models = []
    agent_models = []
    for item in payload["models"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        capabilities = item.get("capabilities")
        if isinstance(capabilities, list) and "embedding" in capabilities:
            if not any(
                capability in {"completion", "tools"} for capability in capabilities
            ):
                continue
        models.append(item["name"])
        if isinstance(capabilities, list) and "tools" in capabilities:
            agent_models.append(item["name"])

    return {
        "default_model": OLLAMA_CHAT_MODEL,
        "models": list(dict.fromkeys(models)),
        "agent_models": list(dict.fromkeys(agent_models)),
    }


# ── Policy Search Endpoint (Auto-Routed) ──────────────────────────────────────


@router.post("/search")
def policy_search(payload: PolicySearchRequest):
    """
    Auto-routed HR policy search.

    Flow:
      USER QUESTION → POLICY ROUTER → WORKFLOW or AGENT → FINAL ANSWER + TELEMETRY

    The router automatically decides based on question complexity and execution-path
    characteristics. The routing decision, mode, reason, retries, tokens, latency,
    and estimated cost are all returned in the response.

    NEVER fabricates metrics. All telemetry is real.
    """
    request_start = time.perf_counter()
    run_id = f"search_{uuid.uuid4().hex[:12]}"

    top_k = payload.top_k or 5
    temperature = payload.temperature if payload.temperature is not None else 0.3
    model = payload.model or OLLAMA_CHAT_MODEL
    max_retries = (
        payload.max_retries if payload.max_retries is not None else MAX_RETRIES
    )
    case_id = payload.case_id or f"search_{payload.employee_id}"

    # ── 1. Router ─────────────────────────────────────────────────────────────
    if payload.force_mode in (MODE_WORKFLOW, MODE_AGENT):
        # Explicit mode override (for testing/debugging only)
        mode = payload.force_mode
        routing_decision = route_policy_question(payload.question, payload.employee_id)
        routing_decision.mode = mode
        routing_decision.reason = f"Mode explicitly forced to '{mode}' by caller."
    else:
        routing_decision = route_policy_question(payload.question, payload.employee_id)
        mode = routing_decision.mode

    # ── 2. Execute with retry ─────────────────────────────────────────────────
    result, retry_history = _run_with_retries(
        mode=mode,
        employee_id=payload.employee_id,
        question=payload.question,
        case_id=case_id,
        top_k=top_k,
        temperature=temperature,
        model=model,
        max_retries=max_retries,
    )

    # ── 3. Attach routing and provenance metadata ─────────────────────────────
    total_ms = (time.perf_counter() - request_start) * 1000

    result.run_id = run_id
    result.evaluation_type = "WEEK7_POLICY_EXECUTION"
    result.execution_mode = mode
    result.routing_reason = routing_decision.reason
    result.complexity = routing_decision.complexity
    result.routing_ms = round(routing_decision.routing_ms, 3)
    result.latency_ms = round(total_ms, 3)
    result.mode_history = [mode]
    result.top_k = top_k
    result.temperature = temperature if mode == MODE_AGENT else None
    result.model = model if mode == MODE_AGENT else None
    result.max_retries = max_retries
    result.provider_cost = "N/A"

    response = result.model_dump()
    response["routing"] = routing_decision.to_dict()
    response["run_id"] = run_id

    return JSONResponse(content=response)


# ── Existing Endpoints (preserved exactly) ────────────────────────────────────


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
    evaluation_type = WEEK7_POLICY_EXECUTION
    """
    try:
        top_k_val = getattr(payload, "top_k", 5) or 5
        temp_val = getattr(payload, "temperature", 0.3)
        if temp_val is None:
            temp_val = 0.3
        model_val = getattr(payload, "model", OLLAMA_CHAT_MODEL) or OLLAMA_CHAT_MODEL

        result = run_agent_case(
            case_id=payload.case_id or "custom_agent_case",
            employee_id=payload.employee_id,
            question=payload.question,
            top_k=top_k_val,
            temperature=temp_val,
            model=model_val,
        )
        result.run_id = f"agent_{uuid.uuid4().hex[:8]}"
        result.evaluation_type = "WEEK7_POLICY_EXECUTION"
        result.execution_mode = "agent"
        return result
    except Exception as e:
        logger.exception(f"Policy agent execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workflow", response_model=PolicyOutputContract)
def execute_policy_workflow(payload: PolicyQueryRequest):
    """
    Execute the Fixed 3-Step Deterministic HR Policy Workflow.
    evaluation_type = WEEK7_POLICY_EXECUTION
    """
    try:
        top_k_val = getattr(payload, "top_k", 5) or 5
        result = run_workflow_case(
            case_id=payload.case_id or "custom_wf_case",
            employee_id=payload.employee_id,
            question=payload.question,
            top_k=top_k_val,
        )
        result.run_id = f"wf_{uuid.uuid4().hex[:8]}"
        result.evaluation_type = "WEEK7_POLICY_EXECUTION"
        result.execution_mode = "workflow"
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
    evaluation_type = WEEK7_POLICY_EXECUTION
    """
    req = payload or PolicyBenchmarkStartRequest()
    cases = req.cases if req.cases else _load_benchmark_cases()
    if not cases:
        raise HTTPException(status_code=404, detail="Benchmark cases not found")

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
        run_id=f"bench_sync_{uuid.uuid4().hex[:8]}",
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
    req = payload or PolicyBenchmarkStartRequest(background=True)
    cases = req.cases if req.cases else _load_benchmark_cases()
    if not cases:
        raise HTTPException(status_code=404, detail="Benchmark cases not found")

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
        raise HTTPException(
            status_code=400, detail=f"Could not cancel benchmark run {run_id}"
        )
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


@router.get("/router/classify")
def classify_question(
    question: str = Query(...), employee_id: Optional[str] = Query(None)
):
    """
    Preview the routing decision for a given question without executing it.
    Useful for testing and UI previews.
    """
    decision = route_policy_question(question, employee_id)
    return JSONResponse(content=decision.to_dict())
