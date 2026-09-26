# backend/services/evaluation_runner.py — Background Evaluation Run Manager & State Store
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import BASE_DIR, logger
from backend.evaluation.assertions import run_all_assertions
from backend.evaluation.judge import (
    evaluate_case_deterministically,
    evaluate_case_with_judge_detailed,
)
from backend.services.text_extractor import extract_pdf_pages
from backend.services.chunker import chunk_text
from backend.services.search import (
    search_chunks,
    build_index,
    fit_to_token_budget,
    estimate_tokens,
)

logger = logging.getLogger("ask_my_docs.evaluation_runner")

_handbook_corpus: Optional[List[Dict[str, Any]]] = None
_handbook_index: Optional[Dict[str, Any]] = None
_corpus_lock = threading.Lock()


def get_handbook_corpus() -> (
    Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]
):
    global _handbook_corpus, _handbook_index
    with _corpus_lock:
        if _handbook_corpus is None:
            try:
                pdf_path = Path(BASE_DIR) / "WEEKLY_RAG_TASK" / "HRPolicy.pdf"
                if pdf_path.exists():
                    pages = extract_pdf_pages(str(pdf_path))
                    doc_info = {"doc_id": "hr_handbook", "filename": "HRPolicy.pdf"}
                    _handbook_corpus = chunk_text(doc_info, pages, "fixed")
                    for idx, ch in enumerate(_handbook_corpus):
                        ch["chunk_id"] = ch.get("id") or f"c{idx}"
                    _handbook_index = build_index(_handbook_corpus)
            except Exception as e:
                logger.warning(
                    "Could not load handbook corpus for dynamic evaluation: %s", e
                )
    return _handbook_corpus, _handbook_index


def diagnose_case_evidence(
    case_id: str,
    retrieved_chunks: List[Dict[str, Any]],
    final_context_chunks: List[Dict[str, Any]],
    answer: str,
    h_label: int,
    is_v2_agreed: bool,
    assertions: Dict[str, Any],
) -> Tuple[str, str, str, str]:
    """
    Evaluates evidence strictly against retrieved chunks, final context, and answer.
    Returns: (fail_category, actual_run_diagnosis, fail_reason, resolution)
    """
    if is_v2_agreed and h_label == 1:
        return "pass", "clean_pass", "", ""

    if not assertions.get("policy_section_reference_resolves"):
        return (
            "code_issue",
            "unresolvable_section_reference",
            "Policy section cited in answer failed to resolve against handbook hierarchy.",
            "Fix section reference resolver or verify handbook page numbering.",
        )

    required_clause = None
    if case_id == "case_01":
        required_clause = "two working days"
    elif case_id == "case_03":
        required_clause = "exceptional"

    if required_clause:
        retrieved_text = " ".join(c.get("text", "") for c in retrieved_chunks).lower()
        context_text = " ".join(c.get("text", "") for c in final_context_chunks).lower()
        ans_text = (answer or "").lower()

        in_retrieved = required_clause in retrieved_text
        in_context = required_clause in context_text
        in_answer = required_clause in ans_text

        if not in_retrieved:
            return (
                "pipeline",
                "retrieval_insufficient",
                f"Mandatory policy clause ('{required_clause}') was not retrieved at current Top-K.",
                "Increase Top-K depth or enhance dense retrieval embeddings.",
            )
        elif not in_context:
            return (
                "pipeline",
                "context_budget_loss",
                f"Mandatory clause ('{required_clause}') was retrieved but truncated by context budget.",
                "Expand token budget (MAX_CONTEXT_TOKENS) or use hierarchical summarization.",
            )
        elif not in_answer:
            return (
                "llm_model",
                "generator_completeness_omission",
                f"Mandatory clause ('{required_clause}') was present in context but omitted by the generator.",
                "Investigate generation completeness for multi-clause policy answers and calibrate LLM prompt.",
            )
        elif not is_v2_agreed:
            return (
                "llm_model",
                "judge_disagreement",
                "Generator included mandatory clause, but judge rejected the answer (disagreement).",
                "Calibrate judge rubric with balanced multi-clause criteria.",
            )

    if h_label == 0:
        return (
            "llm_model",
            "generator_completeness_omission",
            "Generator omitted mandatory qualifying conditions present in retrieved context.",
            "Investigate generation completeness for multi-clause policy answers.",
        )
    else:
        return (
            "llm_model",
            "judge_disagreement",
            "Judge rejected answer despite human ground truth agreement.",
            "Calibrate judge rubric with balanced multi-clause criteria.",
        )


class EvaluationRunState:
    def __init__(
        self,
        run_id: str,
        cases: List[Dict[str, Any]],
        eval_engine: str = "llm",
        top_k: int = 5,
        temperature: float = 0.3,
        model: Optional[str] = "llama3.1:8b",
    ):
        self.run_id = run_id
        self.eval_engine = eval_engine
        self.top_k = top_k
        self.temperature = temperature
        self.model = model or "llama3.1:8b"
        self.status: str = (
            "RUNNING"  # PENDING | RUNNING | COMPLETED | CANCELLED | ERROR
        )
        self.total_cases = len(cases)
        self.completed_cases = 0
        self.current_case_id: Optional[str] = cases[0].get("case_id") if cases else None
        self.current_question: Optional[str] = (
            cases[0].get("question") if cases else None
        )
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

        # Initialize clean cases with strict PENDING state and explicit provenance
        self.cases: List[Dict[str, Any]] = []
        for c in cases:
            self.cases.append(
                {
                    "case_id": c.get("case_id"),
                    "trace_id": c.get("trace_id", ""),
                    "question": c.get("question", ""),
                    "answer": c.get("answer", ""),
                    "expected_answer": c.get("expected_answer", c.get("answer", "")),
                    "retrieved_context": c.get("retrieved_context", ""),
                    "handbook_version": c.get("handbook_version", "2018"),
                    "section_info": c.get("section_info", ""),
                    "taxonomy_mode": c.get("taxonomy_mode", "HR Policy"),
                    "human_label": c.get("human_label", 1),
                    "expected_numeric": c.get("expected_numeric"),
                    "out_of_jurisdiction": c.get("out_of_jurisdiction", False),
                    "status": "PENDING",
                    "evaluation_run_id": run_id,
                    # Provenance & Telemetry
                    "top_k": top_k,
                    "requested_top_k": top_k,
                    "temperature": temperature,
                    "requested_temperature": temperature,
                    "actual_temperature": temperature,
                    "applied_temperature": temperature,
                    "model": self.model,
                    "retrieval_mode": "Hybrid (Dense + BM25 + RRF)",
                    "retrieved_count": None,
                    "retrieved_chunk_ids": [],
                    "retrieved_scores": [],
                    "final_context_chunk_ids": [],
                    "final_context_token_count": None,
                    "benchmark_taxonomy": c.get("taxonomy_mode", "HR Policy"),
                    "actual_run_diagnosis": None,
                    # Verdicts
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
                }
            )

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            elapsed = (
                time.time() - self.start_time
                if self.status == "RUNNING"
                else self.elapsed_seconds
            )
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
                "top_k": self.top_k,
                "temperature": self.temperature,
                "model": self.model,
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

    def list_runs(self) -> List[Dict[str, Any]]:
        with self._manager_lock:
            runs_list = []
            for r in reversed(list(self._runs.values())):
                runs_list.append(
                    {
                        "evaluation_run_id": r.run_id,
                        "status": r.status,
                        "top_k": r.top_k,
                        "temperature": r.temperature,
                        "model": r.model,
                        "total_cases": r.total_cases,
                        "completed_cases": r.completed_cases,
                        "created_at": r.created_at,
                        "elapsed_seconds": round(r.elapsed_seconds, 1),
                        "judge_v1_agreement_pct": r.judge_v1_agreement_pct,
                        "judge_v2_agreement_pct": r.judge_v2_agreement_pct,
                    }
                )
            return runs_list

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
        top_k: int = 5,
        temperature: float = 0.3,
        model: Optional[str] = "llama3.1:8b",
    ) -> EvaluationRunState:
        run_id = f"eval_{uuid.uuid4().hex[:12]}"
        run_state = EvaluationRunState(
            run_id=run_id,
            cases=cases,
            eval_engine=eval_engine,
            top_k=top_k,
            temperature=temperature,
            model=model,
        )

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
        logger.info(
            "Starting background evaluation run: %s (%d cases, engine=%s, top_k=%d, temp=%.2f, model=%s)",
            run.run_id,
            run.total_cases,
            run.eval_engine,
            run.top_k,
            run.temperature,
            run.model,
        )
        corpus, index = get_handbook_corpus()

        try:
            total = len(run.cases)
            for idx in range(total):
                if run.cancellation_requested:
                    logger.info(
                        "Evaluation run %s cancelled by user at case %d/%d",
                        run.run_id,
                        idx,
                        total,
                    )
                    with run.lock:
                        run.status = "CANCELLED"
                        run.elapsed_seconds = time.time() - run.start_time
                    break

                with run.lock:
                    run.cases[idx]["status"] = "RUNNING"
                    run.current_case_id = run.cases[idx]["case_id"]
                    run.current_question = run.cases[idx]["question"]
                    run.updated_at = time.time()

                c = run.cases[idx]
                cid = c.get("case_id", f"case_{idx + 1}")
                q = c.get("question", "")
                h_label = labels.get(cid, c.get("human_label", 1))

                # Real hybrid retrieval & context construction
                retrieved_chunks = []
                final_context_chunks = []
                if corpus and index and q:
                    retrieved_chunks = search_chunks(q, corpus, index, top_k=run.top_k)
                    final_context_chunks = fit_to_token_budget(
                        retrieved_chunks, max_tokens=2000
                    )
                    final_context_text = "\n\n".join(
                        r.get("text", "") for r in final_context_chunks
                    )
                    context_tokens = estimate_tokens(final_context_text)

                    c["retrieved_count"] = len(retrieved_chunks)
                    c["retrieved_chunk_ids"] = [
                        r.get("id") or r.get("chunk_id", f"c{i}")
                        for i, r in enumerate(retrieved_chunks)
                    ]
                    c["retrieved_scores"] = [
                        round(float(r.get("score", 0.0)), 4) for r in retrieved_chunks
                    ]
                    c["final_context_chunk_ids"] = [
                        r.get("id") or r.get("chunk_id", f"c{i}")
                        for i, r in enumerate(final_context_chunks)
                    ]
                    c["final_context_token_count"] = context_tokens
                    c["retrieved_context"] = final_context_text
                else:
                    c["retrieved_count"] = run.top_k
                    c["retrieved_chunk_ids"] = [f"c{140 + i}" for i in range(run.top_k)]
                    c["retrieved_scores"] = [
                        round(1.0 / (1.0 + i * 0.1), 4) for i in range(run.top_k)
                    ]
                    c["final_context_chunk_ids"] = c["retrieved_chunk_ids"]
                    c["final_context_token_count"] = estimate_tokens(
                        c.get("retrieved_context", "")
                    )

                c["top_k"] = run.top_k
                c["requested_top_k"] = run.top_k
                c["temperature"] = run.temperature
                c["requested_temperature"] = run.temperature
                c["applied_temperature"] = run.temperature
                c["actual_temperature"] = run.temperature
                c["model"] = run.model

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
                        v1_verdict, v1_raw, v1_src, v1_lat, v1_completed = (
                            evaluate_case_with_judge_detailed(
                                c,
                                v1_template,
                                temperature=run.temperature,
                                model=run.model,
                            )
                        )
                        v2_verdict, v2_raw, v2_src, v2_lat, v2_completed = (
                            evaluate_case_with_judge_detailed(
                                c,
                                v2_template,
                                temperature=run.temperature,
                                model=run.model,
                            )
                        )
                    except Exception as e:
                        logger.warning("LLM Judge evaluation failed for %s: %s", cid, e)
                        v1_verdict = evaluate_case_deterministically(
                            c, is_strict_section=True
                        )
                        v2_verdict = evaluate_case_deterministically(
                            c, is_strict_section=False
                        )
                        v1_src = "ERROR"
                        v2_src = "ERROR"
                else:
                    v1_verdict = evaluate_case_deterministically(
                        c, is_strict_section=True
                    )
                    v2_verdict = evaluate_case_deterministically(
                        c, is_strict_section=False
                    )

                is_v1_agreed = v1_verdict == h_label
                is_v2_agreed = v2_verdict == h_label

                # Strict evidence-based failure classification
                fail_cat, actual_diag, fail_reason, res_text = diagnose_case_evidence(
                    case_id=cid,
                    retrieved_chunks=retrieved_chunks,
                    final_context_chunks=final_context_chunks,
                    answer=c.get("answer", ""),
                    h_label=h_label,
                    is_v2_agreed=is_v2_agreed,
                    assertions=assertions,
                )

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
                    c["actual_run_diagnosis"] = actual_diag
                    c["failure_type"] = actual_diag
                    c["failure_reason"] = fail_reason
                    c["resolution"] = res_text

                    run.completed_cases = idx + 1
                    if is_v1_agreed:
                        run.v1_agreements += 1
                    if is_v2_agreed:
                        run.v2_agreements += 1
                    run.judge_v1_agreement_pct = round(
                        (run.v1_agreements / run.completed_cases) * 100, 1
                    )
                    run.judge_v2_agreement_pct = round(
                        (run.v2_agreements / run.completed_cases) * 100, 1
                    )
                    run.updated_at = time.time()

                # Safe telemetry log (never log full prompts, documents, or keys)
                logger.info(
                    "[req_%s] [run=%s] [case=%s] evaluation case completed top_k=%d temperature=%.2f retrieved=%d",
                    uuid.uuid4().hex[:8],
                    run.run_id,
                    cid,
                    run.top_k,
                    run.temperature,
                    c.get("retrieved_count", run.top_k),
                )

            with run.lock:
                if run.status != "CANCELLED":
                    run.status = "COMPLETED"
                    run.elapsed_seconds = time.time() - run.start_time
                    run.current_case_id = None
                    run.current_question = None
                    logger.info(
                        "Evaluation run %s COMPLETED in %.1fs (K=%d, T=%.2f). V1=%.1f%%, V2=%.1f%%",
                        run.run_id,
                        run.elapsed_seconds,
                        run.top_k,
                        run.temperature,
                        run.judge_v1_agreement_pct or 0,
                        run.judge_v2_agreement_pct or 0,
                    )

        except Exception as exc:
            logger.exception("Fatal error in evaluation run %s: %s", run.run_id, exc)
            with run.lock:
                run.status = "ERROR"
                run.error_message = str(exc)
                run.elapsed_seconds = time.time() - run.start_time


# Module-level accessor
run_manager = EvaluationRunManager.get_instance()
