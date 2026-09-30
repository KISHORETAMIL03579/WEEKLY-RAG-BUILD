# backend/routes/policy.py — HR policy assistant API (Weeks 7-9)
#
#   /api/policy/search      auto-routes a question to the fixed workflow or the ReAct agent
#   /api/policy/agent       run the agent directly
#   /api/policy/workflow    run the fixed workflow directly
#   /api/policy/benchmark*  race agent vs workflow over a case suite
#   /api/policy/trajectory* expected tool paths and trajectory scoring (Week 8)
#
# Every tool reads the chunks the user uploaded (Qdrant, per browser session); none of
# these endpoints answers from built-in data. Week 6 lives in routes/evaluation.py.
from __future__ import annotations

import csv
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.config import (
    CHAT_BACKEND,
    GROQ_AGENT_MODELS,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_URL,
    LLM_MODEL,
    logger,
)
from backend.errors import ConflictError, DependencyError, NotFoundError, ValidationError
from backend.mcp.registry import get_tool_registry
from backend.schemas.policy import (
    MAX_COST,
    MAX_RETRIES,
    MAX_TOKENS,
    MAX_WALL_CLOCK_SECONDS,
    PolicyOutputContract,
    PolicyQueryRequest,
)
from backend.services import policy_retrieval, policy_trajectory
from backend.services.embeddings import LEXICAL_ONLY, embeddings_configured
from backend.services.policy_agent import run_agent_case
from backend.services.policy_benchmark_runner import (
    PolicyBenchmarkRunManager,
    PolicyBenchmarkRunState,
    load_suite,
)
from backend.services.policy_router import MODE_AGENT, MODE_WORKFLOW, route_policy_question
from backend.services.policy_workflow import run_workflow_case
from backend.storage.exceptions import RetrievalBackendError
from backend.storage.session_manager import OptionalSessionId, get_store

router = APIRouter(prefix="/api/policy", tags=["policy"])

# Run-level retries (whole agent/workflow run again). Budgets, bad input and "nothing
# indexed" are never retried; provider/tool/model failures may be.
_RETRYABLE_TERMINATIONS = {
    "PROVIDER_TRANSIENT",
    "GROQ_UNAVAILABLE",
    "TOOL_ERROR",
    "MODEL_ERROR",
}


# ── Session scope ─────────────────────────────────────────────────────────────


def _session_store(sid: Optional[str]):
    if not sid:
        raise ConflictError(
            "Upload the HR policy documents first: policy tools only read uploaded documents.",
            code="NO_INDEXED_DOCUMENTS",
        )
    try:
        return get_store(sid)
    except RetrievalBackendError as exc:
        logger.error("Policy store unavailable: %s", exc)
        raise DependencyError("The document index is unreachable.") from exc


def _context(sid: Optional[str], document_ids: Optional[List[str]] = None) -> policy_retrieval.PolicyContext:
    """Session scope for a request; 409 when nothing has been uploaded and indexed."""
    store = _session_store(sid)
    if not store.chunks:
        raise ConflictError(
            "No documents are indexed for this session. Upload the HR policy documents first.",
            code="NO_INDEXED_DOCUMENTS",
        )
    return policy_retrieval.PolicyContext(sid, tuple(document_ids or ()))  # type: ignore[arg-type]


# ── Run-level retry wrapper ───────────────────────────────────────────────────


def _run_with_retries(
    mode: str,
    employee_id: str,
    question: str,
    case_id: str,
    top_k: int,
    temperature: float,
    model: str,
    context: policy_retrieval.PolicyContext,
    max_retries: int = MAX_RETRIES,
    max_wall_clock: float = MAX_WALL_CLOCK_SECONDS,
) -> tuple[PolicyOutputContract, list[dict]]:
    """Run the workflow or agent, retrying only transient failures.

    Contract: attempt 1 is the initial run; at most ``max_retries`` (<= MAX_RETRIES)
    further attempts follow a retryable termination. The mode never changes between
    attempts. Tokens, cost and latency accumulate, and the four budgets apply to the
    sum of all attempts. The returned result carries the final attempt's tool trace;
    every attempt (reason, tokens, tool sequence, tool/model retries) is in
    ``retry_history``.
    """
    if type(max_retries) is not int or not 0 <= max_retries <= MAX_RETRIES:
        raise ValidationError(f"max_retries must be between 0 and {MAX_RETRIES}")
    history: list[dict] = []
    totals = {"prompt": 0, "completion": 0, "tokens": 0, "cost": 0.0}
    llm_calls: list[dict] = []
    started = time.perf_counter()
    result: Optional[PolicyOutputContract] = None

    for attempt in range(1, max_retries + 2):
        remaining_time = max_wall_clock - (time.perf_counter() - started)
        remaining_tokens = MAX_TOKENS - totals["tokens"]
        remaining_cost = MAX_COST - totals["cost"]
        exhausted = (
            "BUDGET_WALL_CLOCK"
            if remaining_time <= 0
            else "BUDGET_TOKENS"
            if remaining_tokens <= 0
            else "BUDGET_COST"
            if remaining_cost <= 0
            else None
        )
        if exhausted:
            history.append(
                {"attempt": attempt, "status": "BUDGET_EXHAUSTED", "retry_reason": exhausted, "retryable": False}
            )
            assert result is not None  # attempt 1 always runs: budgets start full
            result.termination_reason = exhausted
            result.passed = False
            break

        common: Dict[str, Any] = dict(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            top_k=top_k,
            temperature=temperature,
            model=model,
            context=context,
            max_wall_clock=remaining_time,
            max_cost=remaining_cost,
        )
        attempt_started = time.perf_counter()
        if mode == MODE_WORKFLOW:
            result = run_workflow_case(max_tokens=remaining_tokens, **common)
        else:
            result = run_agent_case(max_tokens=remaining_tokens, **common)
        attempt_ms = (time.perf_counter() - attempt_started) * 1000

        totals["prompt"] += result.prompt_tokens
        totals["completion"] += result.completion_tokens
        totals["tokens"] += result.total_tokens
        totals["cost"] += result.cost_usd
        base = len(llm_calls)
        llm_calls.extend(
            {**call, "call_index": base + index + 1, "attempt": attempt, "is_retry": attempt > 1}
            for index, call in enumerate(result.llm_calls)
        )
        ok = result.termination_reason == "SUCCESS"
        retryable = not ok and result.termination_reason in _RETRYABLE_TERMINATIONS
        will_retry = retryable and attempt <= max_retries
        retries = (result.tool_audit or {}).get("retries", {})
        history.append(
            {
                "attempt": attempt,
                "status": "SUCCESS" if ok else ("RETRY" if will_retry else "FAILED"),
                "retry_reason": None if ok else result.termination_reason,
                "retryable": retryable,
                "latency_ms": round(attempt_ms, 3),
                "input_tokens": result.prompt_tokens,
                "output_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
                "estimated_cost": round(result.cost_usd, 8),
                "tool_sequence": [call["tool_name"] for call in result.tool_calls],
                "tool_retries": retries.get("tool_retries", {}),
                "model_call_retries": retries.get("model_call_retries", 0),
                "is_retry": attempt > 1,
            }
        )
        if not will_retry:
            break
        logger.warning(
            "policy %s attempt %d failed (%s); retrying (%d left)",
            mode,
            attempt,
            result.termination_reason,
            max_retries + 1 - attempt,
        )

    assert result is not None
    final_attempt = len([h for h in history if h["status"] != "BUDGET_EXHAUSTED"])
    result.prompt_tokens = totals["prompt"]
    result.completion_tokens = totals["completion"]
    result.total_tokens = totals["tokens"]
    result.cost_usd = round(totals["cost"], 8)
    result.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    result.llm_calls = llm_calls
    result.attempt = result.total_attempts = final_attempt
    result.retry_history = history
    if result.tool_audit.get("retries") is not None:
        result.tool_audit["retries"]["run_attempts"] = final_attempt
        result.tool_audit["retries"]["run_retries"] = max(0, final_attempt - 1)
    return result, history


# ── Request models ────────────────────────────────────────────────────────────


class PolicyBenchmarkStartRequest(BaseModel):
    top_k: int = Field(default=5, ge=1, le=20)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    model: Optional[str] = LLM_MODEL
    background: bool = Field(default=False)
    suite: str = Field(default="canonical", description="canonical | branching | all")
    cases: Optional[List[Dict[str, Any]]] = None
    document_ids: Optional[List[str]] = None


class PolicySearchRequest(BaseModel):
    """Request for an auto-routed HR policy question."""

    employee_id: str = Field(..., description="Employee ID, e.g. EMP001")
    question: str = Field(..., description="HR policy question")
    case_id: Optional[str] = None
    top_k: Optional[int] = Field(5, ge=1, le=20)
    temperature: Optional[float] = Field(0.3, ge=0.0, le=1.0)
    model: Optional[str] = LLM_MODEL
    max_retries: Optional[int] = Field(MAX_RETRIES, ge=0, le=MAX_RETRIES)
    force_mode: Optional[str] = None  # "workflow" | "agent" | None (auto-route)
    document_ids: Optional[List[str]] = None


class TrajectoryEvaluateRequest(BaseModel):
    run_id: Optional[str] = None
    baseline_run_id: Optional[str] = None


# ── Models / readiness ────────────────────────────────────────────────────────


@router.get("/models")
def get_available_models():
    """Models the configured Groq account can use; ``agent_models`` support tool calling."""
    if CHAT_BACKEND != "groq":
        raise DependencyError("The policy features require CHAT_BACKEND=groq.")
    if not GROQ_API_KEY:
        raise DependencyError("GROQ_API_KEY is not configured.")
    try:
        response = httpx.get(
            f"{GROQ_URL.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Groq model list returned HTTP %d", exc.response.status_code)
        raise DependencyError("Unable to load available Groq models.") from exc
    except httpx.RequestError as exc:
        logger.warning("Groq model list request failed (%s)", type(exc).__name__)
        raise DependencyError("Unable to load available Groq models.") from exc
    except ValueError as exc:
        raise DependencyError("Groq returned an invalid model list.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise DependencyError("Groq returned an invalid model list.")
    models = sorted(
        {item["id"] for item in payload["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)}
    )
    return {
        "provider": "groq",
        "default_model": GROQ_MODEL,
        "models": models,
        "agent_models": [model for model in models if model in GROQ_AGENT_MODELS],
    }


@router.get("/readiness")
def policy_readiness(sid: OptionalSessionId):
    """What the policy features can use right now: model, indexed documents, tools."""
    documents: Dict[str, Dict[str, Any]] = {}
    chunks = 0
    semantic = False
    if sid:
        store = _session_store(sid)
        semantic = bool(store.vectors) and len(store.vectors) == len(store.chunks)
        for chunk in store.chunks:
            chunks += 1
            entry = documents.setdefault(
                chunk["doc_id"], {"doc_id": chunk["doc_id"], "filename": chunk["filename"], "chunks": 0}
            )
            entry["chunks"] += 1
    try:
        tools = get_tool_registry().discovery_report()
    except Exception as exc:  # report, don't hide: the UI shows why tools are missing
        tools = {"error": f"{type(exc).__name__}: {exc}", "tool_count": 0, "tool_names": [], "servers": []}
    return {
        "chat_backend": CHAT_BACKEND,
        "groq_configured": bool(GROQ_API_KEY),
        "retrieval_mode": "hybrid" if semantic and embeddings_configured() and not LEXICAL_ONLY else "lexical",
        "documents": list(documents.values()),
        "document_count": len(documents),
        "chunk_count": chunks,
        "ready": bool(GROQ_API_KEY) and chunks > 0 and tools.get("tool_count", 0) > 0,
        "tools": {"tool_count": tools.get("tool_count", 0), "tool_names": tools.get("tool_names", [])},
    }


# ── Auto-routed question ──────────────────────────────────────────────────────


@router.post("/search")
def policy_search(payload: PolicySearchRequest, sid: OptionalSessionId):
    """
    USER QUESTION -> ROUTER -> WORKFLOW or AGENT -> ANSWER + FULL TRACE.

    The response carries the routing decision, the selected tools with arguments,
    results and attempts, the tool-selection audit and every retry attempt. All
    telemetry is measured; nothing is estimated except the labelled token-cost proxy.
    """
    request_start = time.perf_counter()
    run_id = f"search_{uuid.uuid4().hex[:12]}"
    context = _context(sid, payload.document_ids)
    top_k = payload.top_k or 5
    temperature = payload.temperature if payload.temperature is not None else 0.3
    model = payload.model or LLM_MODEL
    max_retries = payload.max_retries if payload.max_retries is not None else MAX_RETRIES

    routing = route_policy_question(payload.question, payload.employee_id)
    if payload.force_mode in (MODE_WORKFLOW, MODE_AGENT):
        routing.mode = payload.force_mode
        routing.requires_agent = payload.force_mode == MODE_AGENT
        routing.reason = f"Mode explicitly forced to '{payload.force_mode}' by caller."
    mode = routing.mode

    result, _ = _run_with_retries(
        mode=mode,
        employee_id=payload.employee_id,
        question=payload.question,
        case_id=payload.case_id or f"search_{payload.employee_id}",
        top_k=top_k,
        temperature=temperature,
        model=model,
        context=context,
        max_retries=max_retries,
    )
    result.run_id = run_id
    result.evaluation_type = "WEEK7_POLICY_EXECUTION"
    result.execution_mode = mode
    result.routing_reason = routing.reason
    result.complexity = routing.complexity
    result.routing_ms = round(routing.routing_ms, 3)
    result.latency_ms = round((time.perf_counter() - request_start) * 1000, 3)
    result.mode_history = [mode]
    result.max_retries = max_retries

    response = result.model_dump()
    response["routing"] = routing.to_dict()
    response["run_id"] = run_id
    return JSONResponse(content=response)


@router.get("/router/classify")
def classify_question(question: str = Query(...), employee_id: Optional[str] = Query(None)):
    """Preview the routing decision without executing anything."""
    return JSONResponse(content=route_policy_question(question, employee_id).to_dict())


# ── Direct agent / workflow ───────────────────────────────────────────────────


def _direct_run(mode: str, payload: PolicyQueryRequest, sid: Optional[str], prefix: str) -> PolicyOutputContract:
    context = _context(sid, payload.document_ids)
    kwargs: Dict[str, Any] = dict(
        case_id=payload.case_id or f"custom_{mode}_case",
        employee_id=payload.employee_id,
        question=payload.question,
        top_k=payload.top_k or 5,
        temperature=payload.temperature if payload.temperature is not None else 0.3,
        model=payload.model or LLM_MODEL,
        context=context,
    )
    result = run_agent_case(**kwargs) if mode == MODE_AGENT else run_workflow_case(**kwargs)
    result.run_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
    result.evaluation_type = "WEEK7_POLICY_EXECUTION"
    result.execution_mode = mode
    return result


@router.post("/agent", response_model=PolicyOutputContract)
def execute_policy_agent(payload: PolicyQueryRequest, sid: OptionalSessionId):
    """Run the ReAct agent (four hard budgets enforced) on one employee question."""
    return _direct_run(MODE_AGENT, payload, sid, "agent")


@router.post("/workflow", response_model=PolicyOutputContract)
def execute_policy_workflow(payload: PolicyQueryRequest, sid: OptionalSessionId):
    """Run the fixed workflow (no loop, one model call) on one employee question."""
    return _direct_run(MODE_WORKFLOW, payload, sid, "wf")


# ── Cases, employees ──────────────────────────────────────────────────────────


@router.get("/cases", response_model=List[Dict[str, Any]])
def get_benchmark_cases(suite: str = Query("canonical")):
    """Benchmark cases: ``canonical`` (10 single-path), ``branching`` (path depends on data) or ``all``."""
    try:
        return JSONResponse(content=load_suite(suite))
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.get("/employees")
def get_employees(sid: OptionalSessionId):
    """Employee records found in the uploaded roster (rows of ``ID | key: value | ...``)."""
    context = _context(sid)
    return JSONResponse(content=policy_retrieval.list_employee_records(context))


# ── Benchmark ─────────────────────────────────────────────────────────────────


def _benchmark_cases(req: PolicyBenchmarkStartRequest) -> List[Dict[str, Any]]:
    try:
        cases = req.cases if req.cases else load_suite(req.suite)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if not cases:
        raise NotFoundError("Benchmark cases not found", code="CASES_NOT_FOUND")
    return cases


@router.post("/benchmark")
def start_or_run_benchmark(sid: OptionalSessionId, payload: Optional[PolicyBenchmarkStartRequest] = None):
    """Start (``background: true``) or synchronously run the agent-vs-workflow benchmark."""
    req = payload or PolicyBenchmarkStartRequest()
    cases = _benchmark_cases(req)
    context = _context(sid, req.document_ids)
    manager = PolicyBenchmarkRunManager.get_instance()
    if req.background:
        run_state = manager.start_benchmark(
            cases=cases, top_k=req.top_k, temperature=req.temperature, model=req.model, context=context
        )
        return JSONResponse(content=run_state.to_dict())
    run_state = PolicyBenchmarkRunState(
        run_id=f"bench_sync_{uuid.uuid4().hex[:8]}",
        cases=cases,
        top_k=req.top_k,
        temperature=req.temperature,
        model=req.model,
        context=context,
    )
    manager._execute_benchmark_worker(run_state, cases)
    return JSONResponse(content=run_state.to_dict())


@router.post("/benchmark/start")
def start_benchmark_background(sid: OptionalSessionId, payload: Optional[PolicyBenchmarkStartRequest] = None):
    """Start an asynchronous benchmark run and return its initial state."""
    req = payload or PolicyBenchmarkStartRequest(background=True)
    cases = _benchmark_cases(req)
    context = _context(sid, req.document_ids)
    run_state = PolicyBenchmarkRunManager.get_instance().start_benchmark(
        cases=cases, top_k=req.top_k, temperature=req.temperature, model=req.model, context=context
    )
    return JSONResponse(content=run_state.to_dict())


@router.get("/benchmark/runs/active")
def get_active_benchmark_run():
    active = PolicyBenchmarkRunManager.get_instance().get_active_run()
    return JSONResponse(content={"active": bool(active), "run": active.to_dict() if active else None})


@router.get("/benchmark/runs/{run_id}")
def get_benchmark_run_status(run_id: str):
    run_state = PolicyBenchmarkRunManager.get_instance().get_run(run_id)
    if not run_state:
        raise NotFoundError(f"Benchmark run {run_id} not found")
    return JSONResponse(content=run_state.to_dict())


@router.post("/benchmark/runs/{run_id}/cancel")
def cancel_benchmark_run(run_id: str):
    if not PolicyBenchmarkRunManager.get_instance().cancel_run(run_id):
        raise NotFoundError(f"Could not cancel benchmark run {run_id}")
    return JSONResponse(content={"cancelled": True, "run_id": run_id})


@router.get("/benchmark/latest")
def get_latest_benchmark_results():
    """Rows of the last completed run (results.csv always holds exactly one run)."""
    csv_file = PolicyBenchmarkRunManager._results_dir() / "results.csv"
    if not csv_file.exists():
        return JSONResponse(content={"rows": []})
    try:
        with open(csv_file, "r", encoding="utf-8") as handle:
            return JSONResponse(content={"rows": list(csv.DictReader(handle))})
    except OSError as exc:
        logger.error("Error reading benchmark results CSV: %s", exc)
        raise DependencyError("Could not read the latest benchmark results.") from exc


# ── Trajectory (Week 8) ───────────────────────────────────────────────────────


@router.get("/trajectory/expected")
def get_expected_trajectories(suite: str = Query("all")):
    """Expected tool paths per case; cases with several entries accept any of them."""
    try:
        cases = load_suite(suite)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    expected = policy_trajectory.load_expected_trajectories()
    return JSONResponse(
        content=[
            {"case_id": case["case_id"], "employee_id": case["employee_id"], "question": case["question"], **expected[case["case_id"]]}
            for case in cases
            if case["case_id"] in expected
        ]
    )


def _trajectory_for(run_id: str) -> Dict[str, Any]:
    run_state = PolicyBenchmarkRunManager.get_instance().get_run(run_id)
    if not run_state:
        raise NotFoundError(f"Benchmark run {run_id} not found")
    if run_state.status not in {"COMPLETED", "CANCELLED"}:
        raise ConflictError("The benchmark run has not finished yet.", code="RUN_NOT_FINISHED")
    return run_state.trajectory_report()



@router.post("/trajectory/evaluate")
def evaluate_trajectory(payload: TrajectoryEvaluateRequest):
    """Trajectory report for a finished run; with ``baseline_run_id`` also the before/after comparison."""
    if not payload.run_id:
        raise ValidationError("run_id is required")
    report = _trajectory_for(payload.run_id)
    if payload.baseline_run_id:
        baseline = _trajectory_for(payload.baseline_run_id)
        report["comparison"] = {
            "baseline_run_id": payload.baseline_run_id,
            **policy_trajectory.compare(baseline["summary"], report["summary"]),
        }
    return JSONResponse(content=report)
