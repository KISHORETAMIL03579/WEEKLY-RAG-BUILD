# backend/services/evaluation_runner.py — Background Evaluation Run Manager & State Store
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import BASE_DIR, logger
from backend.evaluation.assertions import run_all_assertions
from backend.evaluation.judge import (
    evaluate_case_deterministically,
    evaluate_case_with_judge_detailed,
)

logger = logging.getLogger("ask_my_docs.evaluation_runner")


class EvaluationRunState:
    def __init__(
        self,
        run_id: str,
        cases: List[Dict[str, Any]],
        eval_engine: str = "llm",
    ):
        self.run_id = run_id
        self.eval_engine = eval_engine
        self.status: str = "RUNNING"  # PENDING | RUNNING | COMPLETED | CANCELLED | ERROR
        self.total_cases = len(cases)
        self.completed_cases = 0
        self.current_case_id: Optional[str] = cases[0].get("case_id") if cases else None
        self.current_question: Optional[str] = cases[0].get("question") if cases else None
        self.created_at = time.time()
        self.updated_at = time.time()
        self.start_time = time.time()
        self.elapsed_seconds = 0.0
        self.v1_agreements = 0
        self.v2_agreements = 0
        self.judge_v1_agreement_pct: Optional[float] = None
        self.judge_v2_agreement_pct: Optional[float] = None
        self.cancellation_requested = False
        self.error_message: Optional[str] = None
        self.lock = threading.Lock()

        # Initialize clean cases with strict PENDING state
        self.cases: List[Dict[str, Any]] = []
        for c in cases:
            self.cases.append({
                "case_id": c.get("case_id"),
                "trace_id": c.get("trace_id", ""),
                "question": c.get("question", ""),
                "answer": c.get("answer", ""),
                "retrieved_context": c.get("retrieved_context", ""),
                "handbook_version": c.get("handbook_version", "2018"),
                "section_info": c.get("section_info", ""),
                "taxonomy_mode": c.get("taxonomy_mode", "HR Policy"),
                "human_label": c.get("human_label", 1),
                "expected_numeric": c.get("expected_numeric"),
                "out_of_jurisdiction": c.get("out_of_jurisdiction", False),
                "status": "PENDING",
                "evaluation_run_id": run_id,
                "judge_v1_verdict": None,
                "judge_v1_agreed": None,
                "judge_v1_raw": None,
                "judge_v1_source": None,
                "judge_v1_latency_ms": None,
                "judge_v1_llm_completed": None,
                "judge_v2_verdict": None,
                "judge_v2_agreed": None,
                "judge_v2_raw": None,
                "judge_v2_source": None,
                "judge_v2_latency_ms": None,
                "judge_v2_llm_completed": None,
                "source": None,
                "latency_ms": None,
                "llm_completed": None,
                "assertions": None,
                "failure_category": None,
                "failure_type": None,
                "failure_reason": None,
                "resolution": None,
            })

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            elapsed = time.time() - self.start_time if self.status == "RUNNING" else self.elapsed_seconds
            return {
                "evaluation_run_id": self.run_id,
                "status": self.status,
                "eval_engine": self.eval_engine,
                "total_cases": self.total_cases,
                "completed_cases": self.completed_cases,
                "current_case_id": self.current_case_id,
                "current_question": self.current_question,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "elapsed_seconds": round(elapsed, 1),
                "v1_agreements": self.v1_agreements,
                "v2_agreements": self.v2_agreements,
                "judge_v1_agreement_pct": self.judge_v1_agreement_pct,
                "judge_v2_agreement_pct": self.judge_v2_agreement_pct,
                "error_message": self.error_message,
                "cases": [dict(c) for c in self.cases],
                "results": [dict(c) for c in self.cases],
            }


class EvaluationRunManager:
    """Singleton manager overseeing background evaluation threads and lifecycle states."""
    _instance: Optional[EvaluationRunManager] = None
    _lock = threading.Lock()

    def __init__(self):
        self._runs: Dict[str, EvaluationRunState] = {}
        self._active_run_id: Optional[str] = None
        self._manager_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> EvaluationRunManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def get_active_run_id(self) -> Optional[str]:
        with self._manager_lock:
            return self._active_run_id

    def get_run(self, run_id: str) -> Optional[EvaluationRunState]:
        with self._manager_lock:
            return self._runs.get(run_id)

    def cancel_run(self, run_id: str) -> bool:
        with self._manager_lock:
            run = self._runs.get(run_id)
            if not run:
                return False
            with run.lock:
                run.cancellation_requested = True
                if run.status == "RUNNING":
                    run.status = "CANCELLED"
                    run.elapsed_seconds = time.time() - run.start_time
            if self._active_run_id == run_id:
                self._active_run_id = None
            return True

    def start_run(
        self,
        cases: List[Dict[str, Any]],
        eval_engine: str = "llm",
        v1_template: str = "",
        v2_template: str = "",
        labels: Optional[Dict[str, int]] = None,
    ) -> EvaluationRunState:
        run_id = f"eval_{uuid.uuid4().hex[:12]}"
        run_state = EvaluationRunState(run_id=run_id, cases=cases, eval_engine=eval_engine)

        with self._manager_lock:
            self._runs[run_id] = run_state
            self._active_run_id = run_id

        thread = threading.Thread(
            target=self._run_worker,
            args=(run_state, v1_template, v2_template, labels or {}),
            name=f"EvalWorker-{run_id}",
            daemon=True,
        )
        thread.start()
        return run_state

    def _run_worker(
        self,
        run: EvaluationRunState,
        v1_template: str,
        v2_template: str,
        labels: Dict[str, int],
    ):
        logger.info("Starting background evaluation run: %s (%d cases, engine=%s)", run.run_id, run.total_cases, run.eval_engine)
        try:
            total = len(run.cases)
            for idx in range(total):
                if run.cancellation_requested:
                    logger.info("Evaluation run %s cancelled by user at case %d/%d", run.run_id, idx, total)
                    with run.lock:
                        run.status = "CANCELLED"
                        run.elapsed_seconds = time.time() - run.start_time
                    break

                # Mark current case as RUNNING
                with run.lock:
                    run.cases[idx]["status"] = "RUNNING"
                    run.current_case_id = run.cases[idx]["case_id"]
                    run.current_question = run.cases[idx]["question"]
                    run.updated_at = time.time()

                c = run.cases[idx]
                cid = c.get("case_id", f"case_{idx + 1}")
                h_label = labels.get(cid, c.get("human_label", 1))
                assertions = run_all_assertions(c)

                v1_verdict = 1
                v2_verdict = 1
                v1_raw = "OFFLINE_DETERMINISTIC"
                v2_raw = "OFFLINE_DETERMINISTIC"
                v1_src = "DETERMINISTIC"
                v2_src = "DETERMINISTIC"
                v1_lat = 0.0
                v2_lat = 0.0
                v1_completed = False
                v2_completed = False

                if run.eval_engine == "llm" and v1_template and v2_template:
                    try:
                        v1_verdict, v1_raw, v1_src, v1_lat, v1_completed = evaluate_case_with_judge_detailed(c, v1_template)
                        v2_verdict, v2_raw, v2_src, v2_lat, v2_completed = evaluate_case_with_judge_detailed(c, v2_template)
                    except Exception as e:
                        logger.warning("LLM Judge evaluation failed for %s: %s", cid, e)
                        v1_verdict = evaluate_case_deterministically(c, is_strict_section=True)
                        v2_verdict = evaluate_case_deterministically(c, is_strict_section=False)
                        v1_src = "ERROR"
                        v2_src = "ERROR"
                else:
                    v1_verdict = evaluate_case_deterministically(c, is_strict_section=True)
                    v2_verdict = evaluate_case_deterministically(c, is_strict_section=False)

                is_v1_agreed = (v1_verdict == h_label)
                is_v2_agreed = (v2_verdict == h_label)

                # Dynamically derive failure metadata strictly based on current evaluation outcome
                if is_v2_agreed and h_label == 1:
                    fail_cat = "pass"
                    fail_type = ""
                    fail_reason = ""
                    res_text = ""
                elif not assertions.get("policy_section_reference_resolves"):
                    fail_cat = "code_issue"
                    fail_type = "unresolvable_section_reference"
                    fail_reason = "Policy section cited in answer failed to resolve against handbook hierarchy."
                    res_text = "Fix section reference resolver or verify handbook page numbering."
                elif h_label == 0:
                    if "truncat" in c.get("taxonomy_mode", "").lower():
                        fail_cat = "pipeline"
                        fail_type = "low_k_truncation"
                        fail_reason = "Retrieval budget truncated mandatory qualifying conditions from policy context."
                        res_text = "Increase retrieval depth K or implement parent-document context expansion."
                    elif "dispersal" in c.get("taxonomy_mode", "").lower():
                        fail_cat = "pipeline"
                        fail_type = "information_dispersal"
                        fail_reason = "Cross-section information dispersal caused generator to miss dispersed clause."
                        res_text = "Enable multi-query reciprocal rank fusion across dispersed document sections."
                    else:
                        fail_cat = "llm_model"
                        fail_type = "generator_misinterpretation"
                        fail_reason = "Generator produced an ungrounded or incomplete interpretation."
                        res_text = "Refine prompt system instructions and structured citation constraints."
                else:
                    fail_cat = "llm_model"
                    fail_type = "judge_disagreement"
                    fail_reason = "Judge rejected answer despite human ground truth agreement."
                    res_text = "Calibrate judge rubric with balanced multi-clause criteria."

                with run.lock:
                    c["status"] = "COMPLETED"
                    c["human_label"] = h_label
                    c["assertions"] = assertions
                    c["judge_v1_verdict"] = v1_verdict
                    c["judge_v1_agreed"] = is_v1_agreed
                    c["judge_v1_raw"] = v1_raw
                    c["judge_v1_source"] = v1_src
                    c["judge_v1_latency_ms"] = round(v1_lat, 2)
                    c["judge_v1_llm_completed"] = v1_completed
                    c["judge_v2_verdict"] = v2_verdict
                    c["judge_v2_agreed"] = is_v2_agreed
                    c["judge_v2_raw"] = v2_raw
                    c["judge_v2_source"] = v2_src
                    c["judge_v2_latency_ms"] = round(v2_lat, 2)
                    c["judge_v2_llm_completed"] = v2_completed
                    c["source"] = v2_src
                    c["latency_ms"] = round(v2_lat, 2)
                    c["llm_completed"] = v2_completed
                    c["failure_category"] = fail_cat
                    c["failure_type"] = fail_type
                    c["failure_reason"] = fail_reason
                    c["resolution"] = res_text

                    run.completed_cases = idx + 1
                    if is_v1_agreed:
                        run.v1_agreements += 1
                    if is_v2_agreed:
                        run.v2_agreements += 1
                    run.judge_v1_agreement_pct = round((run.v1_agreements / run.completed_cases) * 100, 1)
                    run.judge_v2_agreement_pct = round((run.v2_agreements / run.completed_cases) * 100, 1)
                    run.updated_at = time.time()

            with run.lock:
                if run.status != "CANCELLED":
                    run.status = "COMPLETED"
                    run.elapsed_seconds = time.time() - run.start_time
                    run.current_case_id = None
                    run.current_question = None
                    logger.info("Evaluation run %s COMPLETED in %.1fs. V1=%.1f%%, V2=%.1f%%", run.run_id, run.elapsed_seconds, run.judge_v1_agreement_pct or 0, run.judge_v2_agreement_pct or 0)

        except Exception as exc:
            logger.exception("Fatal error in evaluation run %s: %s", run.run_id, exc)
            with run.lock:
                run.status = "ERROR"
                run.error_message = str(exc)
                run.elapsed_seconds = time.time() - run.start_time


# Module-level accessor
run_manager = EvaluationRunManager.get_instance()

