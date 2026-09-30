# backend/services/policy_benchmark_runner.py — background benchmark: agent vs workflow
#
# Runs every case of a suite through the ReAct agent and the fixed workflow, one
# after the other, over the chunks the user uploaded. Progress is persisted after each
# step (so any worker can serve it), cancellation is honoured between steps, and the
# finished run is written to benchmarks/policy_execution/runs/<run_id>.csv.
from __future__ import annotations

import csv
import json
import logging
import os
import statistics
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.config import BASE_DIR, CHAT_BACKEND, LLM_MODEL
from backend.errors import ConflictError
from backend.mcp.registry import get_tool_registry
from backend.schemas.policy import PolicyOutputContract
from backend.services import policy_retrieval, policy_trajectory
from backend.services.policy_agent import run_agent_case
from backend.services.policy_workflow import run_workflow_case
from backend.storage.shared_state import (
    ActiveSharedRunError,
    create_background_run,
    get_active_background_run_id,
    get_background_run,
    request_background_run_cancellation,
    save_background_run,
)

logger = logging.getLogger("ask_my_docs.policy_benchmark_runner")

BENCH_DIR = BASE_DIR / "benchmarks" / "policy_execution"
SUITE_FILES = {"canonical": "cases.json", "branching": "cases_branching.json"}
KINDS = ("agent", "workflow")


def load_suite(suite: str) -> List[Dict[str, Any]]:
    """Cases of ``canonical``, ``branching`` or ``all`` (both, canonical first)."""
    names = list(SUITE_FILES) if suite == "all" else [suite]
    unknown = [name for name in names if name not in SUITE_FILES]
    if unknown:
        raise ValueError(f"Unknown suite {suite!r}; use canonical, branching or all")
    cases: List[Dict[str, Any]] = []
    for name in names:
        cases.extend(json.loads((BENCH_DIR / SUITE_FILES[name]).read_text(encoding="utf-8")))
    return cases


def _criteria(case: Dict[str, Any]) -> List[str]:
    if case.get("deterministic_pass_criteria"):
        return list(case["deterministic_pass_criteria"])
    expected = case.get("expected_value") or case.get("expected_answer")
    return [expected] if expected else []


class PolicyBenchmarkRunState:
    """Live state of one benchmark run (also rebuilt from a persisted snapshot)."""

    def __init__(
        self,
        run_id: str,
        cases: List[Dict[str, Any]],
        top_k: int = 5,
        temperature: float = 0.3,
        model: Optional[str] = LLM_MODEL,
        context: Optional[policy_retrieval.PolicyContext] = None,
    ):
        self.run_id = run_id
        self.top_k = top_k
        self.temperature = temperature
        self.model = model
        self.context = context  # never persisted or serialised: it carries the session id
        self.status: str = "RUNNING"  # RUNNING | CANCELLING | COMPLETED | CANCELLED | ERROR
        self.total_cases = len(cases)
        self.completed_cases = 0
        self.current_case_id: Optional[str] = cases[0].get("case_id") if cases else None
        self.current_question: Optional[str] = cases[0].get("question") if cases else None
        self.current_agent_stage: Optional[str] = f"Calling {CHAT_BACKEND.title()}"
        self.current_workflow_stage: Optional[str] = "Step 1: Employee lookup"
        self.agent_completed_count = 0
        self.workflow_completed_count = 0
        self.start_time = time.time()
        self.elapsed_seconds = 0.0
        self.cancellation_requested = False
        self.error_message: Optional[str] = None
        self.lock = threading.Lock()
        self.cases_status: List[Dict[str, Any]] = [
            {
                "case_id": case.get("case_id", ""),
                "employee_id": case.get("employee_id") or "",
                "question": case.get("question", ""),
                "ground_truth": case.get("expected_value") or case.get("expected_answer", ""),
                "source_section": case.get("source_section", ""),
                "pass_criteria": _criteria(case),
                "requires_tools": case.get("requires_tools", []),
                "path_dependency": case.get("path_dependency"),
                "status": "WAITING",  # WAITING | RUNNING | PASS | FAIL | ERROR | SKIPPED
                "skip_reason": None,
                **{f"{kind}_status": "WAITING" for kind in KINDS},
                **{
                    f"{kind}_{field}": None
                    for kind in KINDS
                    for field in (
                        "entitlement", "rule", "explanation", "passed", "latency_ms",
                        "tokens", "cost_usd", "tool_sequence", "result",
                    )
                },
                "agent_tool_retries": None,
                "agent_model_retries": None,
                "agent_rejected_calls": None,
                "agent_selection_ok": None,
            }
            for case in cases
        ]
        self.summary: Optional[Dict[str, Any]] = None
        self.trajectory: Optional[Dict[str, Any]] = None
        self.raw_agent_results: List[PolicyOutputContract] = []
        self.raw_workflow_results: List[PolicyOutputContract] = []

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            live = self.status in ("RUNNING", "CANCELLING")
            elapsed = time.time() - self.start_time if live else self.elapsed_seconds
            return {
                "run_id": self.run_id,
                "status": self.status,
                "top_k": self.top_k,
                "temperature": self.temperature,
                "model": self.model,
                "total_cases": self.total_cases,
                "completed_cases": self.completed_cases,
                "progress_pct": round(self.completed_cases / self.total_cases * 100, 1)
                if self.total_cases
                else 0.0,
                "current_case_id": self.current_case_id,
                "current_question": self.current_question,
                "current_agent_stage": self.current_agent_stage,
                "current_workflow_stage": self.current_workflow_stage,
                "agent_completed_count": self.agent_completed_count,
                "workflow_completed_count": self.workflow_completed_count,
                "elapsed_seconds": round(elapsed, 1),
                "cancellation_requested": self.cancellation_requested,
                "cases_status": [dict(case) for case in self.cases_status],
                "summary": self.summary,
                "trajectory": self.trajectory,
                "error_message": self.error_message,
                "agent_results": [r.model_dump() for r in self.raw_agent_results],
                "workflow_results": [r.model_dump() for r in self.raw_workflow_results],
            }

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any]) -> "PolicyBenchmarkRunState":
        statuses = snapshot.get("cases_status", [])
        cases = [
            {
                "case_id": case.get("case_id", ""),
                "employee_id": case.get("employee_id", ""),
                "question": case.get("question", ""),
                "expected_value": case.get("ground_truth", ""),
                "source_section": case.get("source_section", ""),
                "deterministic_pass_criteria": case.get("pass_criteria", []),
            }
            for case in statuses
        ]
        run = cls(
            run_id=snapshot["run_id"],
            cases=cases,
            top_k=snapshot.get("top_k", 5),
            temperature=snapshot.get("temperature", 0.3),
            model=snapshot.get("model"),
        )
        with run.lock:
            for key in (
                "status", "total_cases", "completed_cases", "current_case_id",
                "current_question", "current_agent_stage", "current_workflow_stage",
                "agent_completed_count", "workflow_completed_count", "elapsed_seconds",
                "cancellation_requested", "error_message", "summary", "trajectory",
            ):
                if key in snapshot:
                    setattr(run, key, snapshot[key])
            run.start_time = time.time() - run.elapsed_seconds
            run.cases_status = [dict(case) for case in statuses]
            run.raw_agent_results = [
                PolicyOutputContract.model_validate(r) for r in snapshot.get("agent_results", [])
            ]
            run.raw_workflow_results = [
                PolicyOutputContract.model_validate(r) for r in snapshot.get("workflow_results", [])
            ]
        return run

    def cases_for_scoring(self) -> List[Dict[str, Any]]:
        return [
            {"case_id": c["case_id"], "employee_id": c["employee_id"], "question": c["question"]}
            for c in self.cases_status
        ]

    def trajectory_report(self) -> Dict[str, Any]:
        """Score the agent's runs against the expected tool paths (Week 8)."""
        expected = policy_trajectory.load_expected_trajectories()
        cases = {case["case_id"]: case for case in self.cases_for_scoring()}
        records = [
            policy_trajectory.evaluate_case(cases[r.case_id], r, expected[r.case_id])
            for r in self.raw_agent_results
            if r.case_id in expected and r.case_id in cases
        ]
        return {
            "run_id": self.run_id,
            "model": self.model,
            "summary": policy_trajectory.summarize(records),
            "cases": records,
        }


class PolicyBenchmarkRunManager:
    """Singleton owning active benchmark runs and their worker threads."""

    _instance: Optional["PolicyBenchmarkRunManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._runs: Dict[str, PolicyBenchmarkRunState] = {}
        self._active_run_id: Optional[str] = None
        self._manager_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "PolicyBenchmarkRunManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def get_active_run(self) -> Optional[PolicyBenchmarkRunState]:
        run_id = get_active_background_run_id("policy_benchmark")
        with self._manager_lock:
            self._active_run_id = run_id
        return self.get_run(run_id) if run_id else None

    def get_run(self, run_id: str) -> Optional[PolicyBenchmarkRunState]:
        snapshot = get_background_run("policy_benchmark", run_id)
        if snapshot is None:
            return None
        restored = PolicyBenchmarkRunState.from_snapshot(snapshot)
        with self._manager_lock:
            # keep the live object (it owns the session context) while the run is active
            live = self._runs.get(run_id)
            if live is not None and snapshot.get("status") in {"RUNNING", "CANCELLING"}:
                return live
            self._runs[run_id] = restored
            if snapshot.get("status") not in {"RUNNING", "CANCELLING"} and self._active_run_id == run_id:
                self._active_run_id = None
        return restored

    @staticmethod
    def _persist_run(run_state: PolicyBenchmarkRunState) -> None:
        saved = save_background_run(
            "policy_benchmark", run_state.run_id, run_state.status, run_state.to_dict()
        )
        if saved != run_state.status:
            with run_state.lock:
                run_state.status = saved
                run_state.cancellation_requested = saved in {"CANCELLING", "CANCELLED"}

    def _refresh_cancellation(self, run_state: PolicyBenchmarkRunState) -> bool:
        snapshot = get_background_run("policy_benchmark", run_state.run_id)
        if snapshot and snapshot.get("cancellation_requested"):
            with run_state.lock:
                run_state.cancellation_requested = True
                run_state.status = "CANCELLING"
        return run_state.cancellation_requested

    def cancel_run(self, run_id: str) -> bool:
        if request_background_run_cancellation("policy_benchmark", run_id) is None:
            return False
        with self._manager_lock:
            run = self._runs.get(run_id)
        if run:
            with run.lock:
                run.cancellation_requested = True
                run.status = "CANCELLING"
            self._persist_run(run)
        return True

    def start_benchmark(
        self,
        cases: List[Dict[str, Any]],
        top_k: int = 5,
        temperature: float = 0.3,
        model: Optional[str] = LLM_MODEL,
        context: Optional[policy_retrieval.PolicyContext] = None,
    ) -> PolicyBenchmarkRunState:
        with self._manager_lock:
            run_id = f"bench_{uuid.uuid4().hex[:12]}"
            run_state = PolicyBenchmarkRunState(run_id, cases, top_k, temperature, model, context)
            try:
                create_background_run("policy_benchmark", run_id, run_state.status, run_state.to_dict())
            except ActiveSharedRunError as exc:
                raise ConflictError(
                    "A policy benchmark is already active",
                    code="BENCHMARK_ACTIVE",
                    details={"active_run_id": exc.run_id},
                ) from exc
            self._runs[run_id] = run_state
            self._active_run_id = run_id
        worker = threading.Thread(
            target=self._execute_benchmark_worker,
            args=(run_state, cases),
            daemon=True,
            name=f"PolicyBenchmark-{run_id}",
        )
        try:
            worker.start()
        except Exception:
            logger.exception("Could not start policy benchmark worker %s", run_id)
            with run_state.lock:
                run_state.status = "ERROR"
                run_state.error_message = "Policy benchmark worker could not be started."
                run_state.elapsed_seconds = time.time() - run_state.start_time
            self._persist_run(run_state)
            raise
        return run_state

    # -- worker ------------------------------------------------------------

    @staticmethod
    def _error_result(kind: str, case: Dict[str, Any], run_state: PolicyBenchmarkRunState) -> PolicyOutputContract:
        return PolicyOutputContract(
            case_id=case.get("case_id", ""),
            employee_id=case.get("employee_id", ""),
            question=case.get("question", ""),
            entitlement_value="",
            rule_cited="",
            explanation=f"{kind.title()} execution failed unexpectedly.",
            passed=False,
            implementation=kind,
            execution_mode=kind,
            iterations=0,
            termination_reason="ERROR",
            top_k=run_state.top_k,
            temperature=run_state.temperature,
            model=run_state.model,
        )

    def _run_case(
        self,
        kind: str,
        case: Dict[str, Any],
        run_state: PolicyBenchmarkRunState,
        on_stage: Callable[[str], None],
    ) -> PolicyOutputContract:
        runner = run_agent_case if kind == "agent" else run_workflow_case
        try:
            return runner(
                case_id=case.get("case_id", ""),
                employee_id=case.get("employee_id", ""),
                question=case.get("question", ""),
                deterministic_pass_criteria=_criteria(case),
                criteria_aliases=case.get("criteria_aliases"),
                forbidden_phrases=case.get("forbidden_phrases"),
                headline_criteria=case.get("headline_criteria"),
                top_k=run_state.top_k,
                temperature=run_state.temperature,
                model=run_state.model or LLM_MODEL,
                context=run_state.context,
                on_stage=on_stage,
            )
        except Exception:
            logger.exception("%s execution failed on case %s", kind, case.get("case_id"))
            return self._error_result(kind, case, run_state)

    def _record(
        self, run_state: PolicyBenchmarkRunState, idx: int, kind: str, result: PolicyOutputContract
    ) -> None:
        row = run_state.cases_status[idx]
        audit = result.tool_audit or {}
        row[f"{kind}_status"] = (
            "PASS" if result.passed else "ERROR" if result.termination_reason == "ERROR" else "FAIL"
        )
        row[f"{kind}_entitlement"] = result.entitlement_value
        row[f"{kind}_rule"] = result.rule_cited
        row[f"{kind}_explanation"] = result.explanation
        row[f"{kind}_passed"] = result.passed
        row[f"{kind}_latency_ms"] = result.latency_ms
        row[f"{kind}_tokens"] = result.total_tokens
        row[f"{kind}_cost_usd"] = result.cost_usd
        row[f"{kind}_tool_sequence"] = [c["tool_name"] for c in result.tool_calls]
        row[f"{kind}_result"] = result.model_dump()
        if kind == "agent":
            retries = audit.get("retries", {})
            row["agent_tool_retries"] = retries.get("total_tool_retries", 0)
            row["agent_model_retries"] = retries.get("model_call_retries", 0)
            row["agent_rejected_calls"] = len(result.rejected_tool_calls)
            row["agent_selection_ok"] = audit.get("selection_ok")

    def _execute_benchmark_worker(
        self, run_state: PolicyBenchmarkRunState, cases: List[Dict[str, Any]]
    ) -> None:
        """Run every case through the agent then the workflow, persisting progress."""
        logger.info("Starting policy benchmark %s (%d cases)", run_state.run_id, len(cases))
        try:
            try:
                available = {spec.name for spec in get_tool_registry().list_tools()}
            except Exception:
                logger.exception("Tool discovery failed; cases needing extra tools will be skipped")
                available = set()

            for idx, case in enumerate(cases):
                self._refresh_cancellation(run_state)
                with run_state.lock:
                    if run_state.cancellation_requested or run_state.status == "CANCELLED":
                        logger.info("Benchmark %s cancelled at case %d", run_state.run_id, idx + 1)
                        break
                    run_state.current_case_id = case.get("case_id")
                    run_state.current_question = case.get("question", "")
                    missing = [t for t in case.get("requires_tools", []) if t not in available]
                    row = run_state.cases_status[idx]
                    if missing:
                        row.update(
                            status="SKIPPED",
                            skip_reason=(
                                "Needs tools not provided by any connected MCP server: "
                                + ", ".join(missing)
                            ),
                            agent_status="SKIPPED",
                            workflow_status="SKIPPED",
                        )
                        run_state.completed_cases += 1
                    else:
                        row.update(status="RUNNING", agent_status="RUNNING", workflow_status="RUNNING")
                self._persist_run(run_state)
                if missing:
                    continue

                def stage(kind: str) -> Callable[[str], None]:
                    def callback(text: str) -> None:
                        with run_state.lock:
                            setattr(run_state, f"current_{kind}_stage", text)
                        self._persist_run(run_state)

                    return callback

                results: Dict[str, PolicyOutputContract] = {}
                cancelled = False
                for kind in KINDS:
                    results[kind] = self._run_case(kind, case, run_state, stage(kind))
                    with run_state.lock:
                        getattr(run_state, f"raw_{kind}_results").append(results[kind])
                        count = getattr(run_state, f"{kind}_completed_count")
                        setattr(run_state, f"{kind}_completed_count", count + 1)
                        self._record(run_state, idx, kind, results[kind])
                    self._persist_run(run_state)
                    if kind == "agent" and self._refresh_cancellation(run_state):
                        cancelled = True
                        break
                if cancelled:
                    break
                with run_state.lock:
                    run_state.completed_cases += 1
                    errored = any(r.termination_reason == "ERROR" for r in results.values())
                    run_state.cases_status[idx]["status"] = (
                        "ERROR"
                        if errored
                        else "PASS"
                        if all(r.passed for r in results.values())
                        else "FAIL"
                    )
                self._persist_run(run_state)

            self._refresh_cancellation(run_state)
            with run_state.lock:
                run_state.elapsed_seconds = time.time() - run_state.start_time
                if run_state.cancellation_requested or run_state.status == "CANCELLING":
                    run_state.status = "CANCELLED"
                else:
                    run_state.status = "COMPLETED"
                    run_state.summary = self._compute_summary(
                        run_state.raw_agent_results, run_state.raw_workflow_results
                    )
            if run_state.status == "COMPLETED":
                try:
                    run_state.trajectory = run_state.trajectory_report()
                except Exception:
                    logger.exception("Trajectory scoring failed for %s", run_state.run_id)
                self._save_results_csv(run_state)
            self._persist_run(run_state)
            logger.info("Benchmark %s finished with status=%s", run_state.run_id, run_state.status)
        except Exception:
            logger.exception("Policy benchmark worker encountered an unhandled error")
            with run_state.lock:
                run_state.status = "ERROR"
                run_state.error_message = "Policy benchmark failed unexpectedly. Check server logs for details."
                run_state.elapsed_seconds = time.time() - run_state.start_time
            self._persist_run(run_state)

    # -- results -----------------------------------------------------------

    @staticmethod
    def _compute_summary(
        agent_results: List[PolicyOutputContract], workflow_results: List[PolicyOutputContract]
    ) -> Dict[str, Any]:
        def summarize(results: List[PolicyOutputContract]) -> Dict[str, Any]:
            n = len(results)
            passed = sum(1 for r in results if r.passed)
            strict = sum(1 for r in results if r.strict_passed)
            latencies = [r.latency_ms for r in results]
            costs = [r.cost_usd for r in results]
            tokens = [r.total_tokens for r in results]
            return {
                "pass_rate_pct": round(passed / n * 100, 1) if n else 0.0,
                "strict_pass_rate_pct": round(strict / n * 100, 1) if n else 0.0,
                "passed_count": passed,
                "total_cases": n,
                "p50_latency_ms": round(statistics.median(latencies), 3) if n else 0.0,
                "max_latency_ms": round(max(latencies), 3) if n else 0.0,
                "total_tokens": sum(tokens),
                "p50_tokens": round(statistics.median(tokens), 1) if n else 0.0,
                "max_tokens": max(tokens) if n else 0,
                "cost_per_question_usd": round(sum(costs) / n, 6) if n else 0.0,
                "p50_cost_usd": round(statistics.median(costs), 8) if n else 0.0,
                "max_cost_usd": round(max(costs), 8) if n else 0.0,
                "terminations": {
                    reason: sum(1 for r in results if r.termination_reason == reason)
                    for reason in sorted({r.termination_reason for r in results})
                },
            }

        return {"agent": summarize(agent_results), "workflow": summarize(workflow_results)}

    @staticmethod
    def _results_dir() -> Path:
        """Where evidence is written (tests redirect this to a temp dir)."""
        override = os.environ.get("POLICY_BENCHMARK_OUTPUT_DIR")
        return Path(override) if override else BENCH_DIR

    RESULT_FIELDNAMES = [
        "run_id", "case_id", "employee_id", "implementation", "passed", "strict_passed",
        "entitlement_value", "rule_cited", "latency_ms", "iterations", "prompt_tokens",
        "completion_tokens", "total_tokens", "cost_usd", "termination_reason",
        "tool_sequence", "tool_retries", "model_retries", "top_k", "temperature", "model",
    ]

    @staticmethod
    def _result_row(run_state: PolicyBenchmarkRunState, result: PolicyOutputContract) -> Dict[str, Any]:
        retries = (result.tool_audit or {}).get("retries", {})
        return {
            "run_id": run_state.run_id,
            "case_id": result.case_id,
            "employee_id": result.employee_id,
            "implementation": result.implementation,
            "passed": result.passed,
            "strict_passed": result.strict_passed,
            "entitlement_value": result.entitlement_value,
            "rule_cited": result.rule_cited,
            "latency_ms": result.latency_ms,
            "iterations": result.iterations,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
            "cost_usd": result.cost_usd,
            "termination_reason": result.termination_reason,
            "tool_sequence": ">".join(call["tool_name"] for call in result.tool_calls),
            "tool_retries": retries.get("total_tool_retries", 0),
            "model_retries": retries.get("model_call_retries", 0),
            "top_k": result.top_k or run_state.top_k,
            "temperature": result.temperature if result.temperature is not None else run_state.temperature,
            "model": result.model or run_state.model,
        }

    @staticmethod
    def _save_results_csv(run_state: PolicyBenchmarkRunState) -> None:
        """Archive the run as runs/<run_id>.csv and replace results.csv with it.

        ``results.csv`` therefore always holds exactly one run with one header; rows from
        different runs are never mixed.
        """
        out_dir = PolicyBenchmarkRunManager._results_dir()
        rows = [
            PolicyBenchmarkRunManager._result_row(run_state, result)
            for result in (*run_state.raw_agent_results, *run_state.raw_workflow_results)
        ]
        try:
            (out_dir / "runs").mkdir(parents=True, exist_ok=True)
            for target in (out_dir / "runs" / f"{run_state.run_id}.csv", out_dir / "results.csv"):
                tmp = target.with_suffix(".csv.tmp")
                with open(tmp, "w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=PolicyBenchmarkRunManager.RESULT_FIELDNAMES)
                    writer.writeheader()
                    writer.writerows(rows)
                tmp.replace(target)
            logger.info("Persisted benchmark results for %s", run_state.run_id)
        except Exception as exc:
            logger.error("Failed to persist benchmark results CSV: %s", exc)
