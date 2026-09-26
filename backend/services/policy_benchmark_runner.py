# backend/services/policy_benchmark_runner.py — Production Background Benchmark Engine with Live Progress & Cancellation
from __future__ import annotations

import csv
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.config import BASE_DIR, logger
from backend.schemas.policy import PolicyOutputContract, TOKEN_COST_PROXY_RATE
from backend.services.policy_agent import run_agent_case
from backend.services.policy_workflow import run_workflow_case

logger = logging.getLogger("ask_my_docs.policy_benchmark_runner")


class PolicyBenchmarkRunState:
    """Encapsulates the live state of a 10-case policy benchmark run."""

    def __init__(
        self,
        run_id: str,
        cases: List[Dict[str, Any]],
        top_k: int = 5,
        temperature: float = 0.3,
        model: Optional[str] = "llama3.1:8b",
    ):
        self.run_id = run_id
        self.top_k = top_k
        self.temperature = temperature
        self.model = model
        self.status: str = "RUNNING"  # RUNNING | COMPLETED | CANCELLED | ERROR
        self.total_cases: int = len(cases)
        self.completed_cases: int = 0
        self.current_case_id: Optional[str] = cases[0].get("case_id") if cases else None
        self.current_question: Optional[str] = (
            cases[0].get("question") if cases else None
        )
        self.current_agent_stage: Optional[str] = "Calling Ollama"
        self.current_workflow_stage: Optional[str] = "Step 1: Employee lookup"
        self.agent_completed_count: int = 0
        self.workflow_completed_count: int = 0
        self.start_time: float = time.time()
        self.elapsed_seconds: float = 0.0
        self.cancellation_requested: bool = False
        self.error_message: Optional[str] = None
        self.lock = threading.Lock()

        # Per-case live state array
        self.cases_status: List[Dict[str, Any]] = []
        for c in cases:
            self.cases_status.append(
                {
                    "case_id": c.get("case_id", ""),
                    "employee_id": c.get("employee_id") or "EMP001",
                    "question": c.get("question", ""),
                    "ground_truth": c.get("expected_value")
                    or c.get("expected_answer", ""),
                    "source_section": c.get("source_section", ""),
                    "pass_criteria": c.get("deterministic_pass_criteria")
                    or (
                        [c.get("expected_value") or c.get("expected_answer")]
                        if (c.get("expected_value") or c.get("expected_answer"))
                        else []
                    ),
                    "status": "WAITING",  # WAITING | RUNNING | PASS | FAIL | ERROR
                    "agent_status": "WAITING",
                    "workflow_status": "WAITING",
                    "agent_entitlement": None,
                    "workflow_entitlement": None,
                    "agent_rule": None,
                    "workflow_rule": None,
                    "agent_explanation": None,
                    "workflow_explanation": None,
                    "agent_passed": None,
                    "workflow_passed": None,
                    "agent_latency_ms": None,
                    "workflow_latency_ms": None,
                    "agent_tokens": None,
                    "workflow_tokens": None,
                    "agent_cost_usd": None,
                    "workflow_cost_usd": None,
                    "agent_result": None,
                    "workflow_result": None,
                }
            )

        self.summary: Optional[Dict[str, Any]] = None
        self.raw_agent_results: List[PolicyOutputContract] = []
        self.raw_workflow_results: List[PolicyOutputContract] = []

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            elapsed = (
                time.time() - self.start_time
                if self.status == "RUNNING"
                else self.elapsed_seconds
            )
            progress_pct = (
                round((self.completed_cases / self.total_cases * 100), 1)
                if self.total_cases > 0
                else 0.0
            )
            return {
                "run_id": self.run_id,
                "status": self.status,
                "top_k": self.top_k,
                "temperature": self.temperature,
                "model": self.model,
                "total_cases": self.total_cases,
                "completed_cases": self.completed_cases,
                "progress_pct": progress_pct,
                "current_case_id": self.current_case_id,
                "current_question": self.current_question,
                "current_agent_stage": self.current_agent_stage,
                "current_workflow_stage": self.current_workflow_stage,
                "agent_completed_count": self.agent_completed_count,
                "workflow_completed_count": self.workflow_completed_count,
                "elapsed_seconds": round(elapsed, 1),
                "cases_status": [dict(c) for c in self.cases_status],
                "summary": self.summary,
                "error_message": self.error_message,
                "agent_results": [r.model_dump() for r in self.raw_agent_results],
                "workflow_results": [r.model_dump() for r in self.raw_workflow_results],
            }


class PolicyBenchmarkRunManager:
    """Singleton managing active benchmark runs and execution workers."""

    _instance: Optional[PolicyBenchmarkRunManager] = None
    _lock = threading.Lock()

    def __init__(self):
        self._runs: Dict[str, PolicyBenchmarkRunState] = {}
        self._active_run_id: Optional[str] = None
        self._manager_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> PolicyBenchmarkRunManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def get_active_run(self) -> Optional[PolicyBenchmarkRunState]:
        with self._manager_lock:
            if self._active_run_id:
                return self._runs.get(self._active_run_id)
            return None

    def get_run(self, run_id: str) -> Optional[PolicyBenchmarkRunState]:
        with self._manager_lock:
            return self._runs.get(run_id)

    def cancel_run(self, run_id: str) -> bool:
        with self._manager_lock:
            run = self._runs.get(run_id)
            if not run:
                return False
            with run.lock:
                if run.status == "RUNNING":
                    run.cancellation_requested = True
                    run.status = "CANCELLED"
                    run.elapsed_seconds = time.time() - run.start_time
                    logger.info(
                        f"Cancellation requested for policy benchmark run {run_id}"
                    )
                    return True
            return False

    def start_benchmark(
        self,
        cases: List[Dict[str, Any]],
        top_k: int = 5,
        temperature: float = 0.3,
        model: Optional[str] = "llama3.1:8b",
    ) -> PolicyBenchmarkRunState:
        with self._manager_lock:
            # If there's an existing running job, request cancellation
            if self._active_run_id:
                existing = self._runs.get(self._active_run_id)
                if existing and existing.status == "RUNNING":
                    with existing.lock:
                        existing.cancellation_requested = True
                        existing.status = "CANCELLED"
                        existing.elapsed_seconds = time.time() - existing.start_time

            run_id = f"bench_{uuid.uuid4().hex[:12]}"
            run_state = PolicyBenchmarkRunState(
                run_id=run_id,
                cases=cases,
                top_k=top_k,
                temperature=temperature,
                model=model,
            )
            self._runs[run_id] = run_state
            self._active_run_id = run_id

            worker = threading.Thread(
                target=self._execute_benchmark_worker,
                args=(run_state, cases),
                daemon=True,
                name=f"PolicyBenchmark-{run_id}",
            )
            worker.start()
            return run_state

    def _execute_benchmark_worker(
        self,
        run_state: PolicyBenchmarkRunState,
        cases: List[Dict[str, Any]],
    ) -> None:
        """Executes the benchmark across all 10 cases sequentially with atomic updates."""
        logger.info(
            f"Starting policy benchmark worker run {run_state.run_id} ({len(cases)} cases)"
        )
        try:
            for idx, c in enumerate(cases):
                # Check cancellation
                with run_state.lock:
                    if (
                        run_state.cancellation_requested
                        or run_state.status == "CANCELLED"
                    ):
                        logger.info(
                            f"Policy benchmark run {run_state.run_id} cancelled at case {idx+1}"
                        )
                        break

                    cid = c.get("case_id", f"case_{idx+1}")
                    empid = c.get("employee_id") or "EMP001"
                    q = c.get("question", "")
                    crit = c.get("deterministic_pass_criteria") or (
                        [c.get("expected_value") or c.get("expected_answer")]
                        if (c.get("expected_value") or c.get("expected_answer"))
                        else []
                    )

                    run_state.current_case_id = cid
                    run_state.current_question = q
                    run_state.cases_status[idx]["status"] = "RUNNING"
                    run_state.cases_status[idx]["agent_status"] = "RUNNING"
                    run_state.cases_status[idx]["workflow_status"] = "RUNNING"

                # Define stage update callbacks
                def make_agent_stage_cb(case_idx: int):
                    def cb(stage: str):
                        with run_state.lock:
                            run_state.current_agent_stage = stage

                    return cb

                def make_wf_stage_cb(case_idx: int):
                    def cb(stage: str):
                        with run_state.lock:
                            run_state.current_workflow_stage = stage

                    return cb

                # 1. Run Agent
                try:
                    a_res = run_agent_case(
                        case_id=cid,
                        employee_id=empid,
                        question=q,
                        deterministic_pass_criteria=crit,
                        top_k=run_state.top_k,
                        temperature=run_state.temperature,
                        model=run_state.model or "llama3.1:8b",
                        on_stage=make_agent_stage_cb(idx),
                    )
                except Exception as a_err:
                    logger.error(f"Agent execution failed on case {cid}: {a_err}")
                    a_res = PolicyOutputContract(
                        case_id=cid,
                        employee_id=empid,
                        question=q,
                        entitlement_value="ERROR",
                        rule_cited="None",
                        explanation=f"Error: {str(a_err)}",
                        passed=False,
                        implementation="agent",
                        tool_calls=[],
                        iterations=1,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        cost_usd=0.0,
                        latency_ms=0.0,
                        termination_reason="ERROR",
                        top_k=run_state.top_k,
                        temperature=run_state.temperature,
                        model=run_state.model,
                    )

                with run_state.lock:
                    run_state.agent_completed_count += 1
                    run_state.cases_status[idx]["agent_status"] = (
                        "PASS"
                        if a_res.passed
                        else (
                            "ERROR" if a_res.termination_reason == "ERROR" else "FAIL"
                        )
                    )
                    run_state.cases_status[idx][
                        "agent_entitlement"
                    ] = a_res.entitlement_value
                    run_state.cases_status[idx]["agent_rule"] = a_res.rule_cited
                    run_state.cases_status[idx]["agent_explanation"] = a_res.explanation
                    run_state.cases_status[idx]["agent_passed"] = a_res.passed
                    run_state.cases_status[idx]["agent_latency_ms"] = a_res.latency_ms
                    run_state.cases_status[idx]["agent_tokens"] = a_res.total_tokens
                    run_state.cases_status[idx]["agent_cost_usd"] = a_res.cost_usd
                    run_state.cases_status[idx]["agent_result"] = a_res.model_dump()
                    run_state.raw_agent_results.append(a_res)

                # Check cancellation between agent and workflow
                with run_state.lock:
                    if (
                        run_state.cancellation_requested
                        or run_state.status == "CANCELLED"
                    ):
                        break

                # 2. Run Workflow
                try:
                    w_res = run_workflow_case(
                        case_id=cid,
                        employee_id=empid,
                        question=q,
                        deterministic_pass_criteria=crit,
                        top_k=run_state.top_k,
                        on_stage=make_wf_stage_cb(idx),
                    )
                except Exception as w_err:
                    logger.error(f"Workflow execution failed on case {cid}: {w_err}")
                    w_res = PolicyOutputContract(
                        case_id=cid,
                        employee_id=empid,
                        question=q,
                        entitlement_value="ERROR",
                        rule_cited="None",
                        explanation=f"Error: {str(w_err)}",
                        passed=False,
                        implementation="workflow",
                        tool_calls=[],
                        iterations=1,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        cost_usd=0.0,
                        latency_ms=0.0,
                        termination_reason="ERROR",
                        top_k=run_state.top_k,
                        temperature=None,
                        model=None,
                    )

                with run_state.lock:
                    run_state.workflow_completed_count += 1
                    run_state.completed_cases += 1
                    run_state.cases_status[idx]["workflow_status"] = (
                        "PASS"
                        if w_res.passed
                        else (
                            "ERROR" if w_res.termination_reason == "ERROR" else "FAIL"
                        )
                    )
                    run_state.cases_status[idx][
                        "workflow_entitlement"
                    ] = w_res.entitlement_value
                    run_state.cases_status[idx]["workflow_rule"] = w_res.rule_cited
                    run_state.cases_status[idx][
                        "workflow_explanation"
                    ] = w_res.explanation
                    run_state.cases_status[idx]["workflow_passed"] = w_res.passed
                    run_state.cases_status[idx][
                        "workflow_latency_ms"
                    ] = w_res.latency_ms
                    run_state.cases_status[idx]["workflow_tokens"] = w_res.total_tokens
                    run_state.cases_status[idx]["workflow_cost_usd"] = w_res.cost_usd
                    run_state.cases_status[idx]["workflow_result"] = w_res.model_dump()
                    run_state.raw_workflow_results.append(w_res)

                    # Overall case status: PASS if both passed, FAIL if either failed, ERROR if either errored
                    if (
                        a_res.termination_reason == "ERROR"
                        or w_res.termination_reason == "ERROR"
                    ):
                        run_state.cases_status[idx]["status"] = "ERROR"
                    elif a_res.passed and w_res.passed:
                        run_state.cases_status[idx]["status"] = "PASS"
                    elif not a_res.passed or not w_res.passed:
                        run_state.cases_status[idx]["status"] = (
                            "FAIL" if (a_res.passed or w_res.passed) else "FAIL"
                        )

            # Finalize summary
            with run_state.lock:
                if run_state.status != "CANCELLED":
                    run_state.status = "COMPLETED"
                    run_state.elapsed_seconds = time.time() - run_state.start_time
                    run_state.summary = self._compute_summary(
                        run_state.raw_agent_results,
                        run_state.raw_workflow_results,
                    )

            # Persist results to CSV if completed
            if run_state.status == "COMPLETED":
                self._save_results_csv(run_state)

            logger.info(
                f"Policy benchmark run {run_state.run_id} finished with status={run_state.status}"
            )

        except Exception as exc:
            logger.exception(
                f"Policy benchmark worker encountered unhandled error: {exc}"
            )
            with run_state.lock:
                run_state.status = "ERROR"
                run_state.error_message = str(exc)
                run_state.elapsed_seconds = time.time() - run_state.start_time

    @staticmethod
    def _compute_summary(
        agent_results: List[PolicyOutputContract],
        workflow_results: List[PolicyOutputContract],
    ) -> Dict[str, Any]:
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

        return {
            "agent": _summarize(agent_results),
            "workflow": _summarize(workflow_results),
        }

    @staticmethod
    def _save_results_csv(run_state: PolicyBenchmarkRunState) -> None:
        """Persist execution rows into benchmarks/policy_execution/results.csv."""
        csv_file = BASE_DIR / "benchmarks" / "policy_execution" / "results.csv"
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "run_id",
            "case_id",
            "employee_id",
            "implementation",
            "passed",
            "entitlement_value",
            "rule_cited",
            "latency_ms",
            "iterations",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cost_usd",
            "termination_reason",
            "top_k",
            "temperature",
            "model",
        ]
        try:
            write_header = not csv_file.exists() or csv_file.stat().st_size == 0
            with open(csv_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()

                for r in run_state.raw_agent_results:
                    row = {
                        "run_id": run_state.run_id,
                        "case_id": r.case_id,
                        "employee_id": r.employee_id,
                        "implementation": "agent",
                        "passed": r.passed,
                        "entitlement_value": r.entitlement_value,
                        "rule_cited": r.rule_cited,
                        "latency_ms": r.latency_ms,
                        "iterations": r.iterations,
                        "prompt_tokens": r.prompt_tokens,
                        "completion_tokens": r.completion_tokens,
                        "total_tokens": r.total_tokens,
                        "cost_usd": r.cost_usd,
                        "termination_reason": r.termination_reason,
                        "top_k": r.top_k or run_state.top_k,
                        "temperature": (
                            r.temperature
                            if r.temperature is not None
                            else run_state.temperature
                        ),
                        "model": r.model or run_state.model,
                    }
                    writer.writerow(row)

                for r in run_state.raw_workflow_results:
                    row = {
                        "run_id": run_state.run_id,
                        "case_id": r.case_id,
                        "employee_id": r.employee_id,
                        "implementation": "workflow",
                        "passed": r.passed,
                        "entitlement_value": r.entitlement_value,
                        "rule_cited": r.rule_cited,
                        "latency_ms": r.latency_ms,
                        "iterations": r.iterations,
                        "prompt_tokens": r.prompt_tokens,
                        "completion_tokens": r.completion_tokens,
                        "total_tokens": r.total_tokens,
                        "cost_usd": r.cost_usd,
                        "termination_reason": r.termination_reason,
                        "top_k": r.top_k or run_state.top_k,
                        "temperature": "",
                        "model": "",
                    }
                    writer.writerow(row)
            logger.info(f"Persisted benchmark results to {csv_file}")
        except Exception as e:
            logger.error(f"Failed to persist benchmark results CSV: {e}")
