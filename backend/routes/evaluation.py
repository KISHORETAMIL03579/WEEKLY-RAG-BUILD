# backend/routes/evaluation.py — Retrieval Benchmarks & LLM Judge Endpoints
from __future__ import annotations

import json
import re
import tempfile
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Body, File, UploadFile
from fastapi.responses import JSONResponse

from backend.config import BASE_DIR, get_app_symbol, logger
from backend.evaluation.assertions import run_all_assertions
from backend.evaluation.judge import (
    evaluate_case_deterministically,
    evaluate_case_with_judge,
    evaluate_case_with_judge_detailed,
)
from backend.evaluation.retrieval_runner import (
    EVAL_PRESETS,
    run_eval_preset,
)
from backend.services.evaluation_runner import run_manager
from backend.schemas.evaluation import (
    EvalRunPayload,
    JudgeCasePayload,
    JudgeEvalPayload,
    Week6CasePayload,
    Week6EvalPayload,
)
from backend.services.llm import chat_configured
from backend.services.text_extractor import extract_pdf_pages
from backend.storage.session_manager import (
    RequiredSessionId,
    get_store,
    save_upload_to,
)

# Backward-compatibility aliases
EvalRunRequest = EvalRunPayload

router = APIRouter(tags=["evaluation"])


def parse_qa_pairs(text: str) -> list[dict]:
    """Parses Question / Expected Answer pairs out of raw text, filtering comments, metadata keys, and headers."""
    pairs = []
    current_q, current_a = None, None
    mode = None

    # Metadata keys to ignore when parsing question/answer blocks
    ignored_prefix_pattern = re.compile(
        r"^(?:case\s*id|employee\s*(?:id|details)?|source\s*(?:policy\s*)?section|tenure\s*(?:\/|\s*)status|deterministic\s*pass\s*criteria)\s*[:\-.]",
        re.IGNORECASE
    )

    def flush():
        nonlocal current_q, current_a, mode
        if current_q and current_a:
            pairs.append({"question": current_q.strip(), "expected": current_a.strip()})
        current_q, current_a = None, None
        mode = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Ignore comment lines and section dividers
        if line.startswith(("#", "//", "/*", "*/", "---", "===")) or re.match(r"^[=\-_*]{3,}$", line):
            continue

        q_match = re.match(r"^(?:q(?:uestion)?|query)\s*[:\-.]\s*(.*)", line, re.IGNORECASE)
        a_match = re.match(
            r"^(?:a(?:nswer)?|expected(?:\s*(?:entitlement\s*\/\s*answer|entitlement|value|answer))?)\s*[:\-.]\s*(.*)",
            line,
            re.IGNORECASE
        )

        if q_match:
            flush()
            current_q = q_match.group(1).strip()
            mode = "q"
        elif a_match:
            current_a = a_match.group(1).strip()
            mode = "a"
        elif ignored_prefix_pattern.match(line):
            # Known metadata field — don't append to question or answer
            continue
        elif mode == "q" and current_q is not None:
            current_q += " " + line
        elif mode == "a" and current_a is not None:
            current_a += " " + line
    flush()
    return pairs


@router.post("/eval/parse-qa-pdf")
def eval_parse_qa_pdf(file: Optional[UploadFile] = File(default=None)):
    """Accepts an uploaded PDF, TXT, MD, or JSON file containing Q:/A: formatted pairs."""
    if not file or not file.filename:
        return JSONResponse({"error": "No file uploaded"}, status_code=400)

    filename_lower = file.filename.lower()
    if filename_lower.endswith(".pdf"):
        tmp_path = Path(tempfile.gettempdir()) / f"qa_upload_{uuid.uuid4().hex}.pdf"
        try:
            save_upload_to(file, tmp_path)
            pages = extract_pdf_pages(str(tmp_path))
            if not pages:
                return JSONResponse({
                    "error": "Could not extract any text from that PDF — it may be corrupt, encrypted, or a scanned image without a text layer"
                }, status_code=400)
            full_text = "\n".join(p["text"] for p in pages)
        finally:
            tmp_path.unlink(missing_ok=True)
    elif filename_lower.endswith((".txt", ".md")):
        try:
            full_text = file.file.read().decode("utf-8", errors="replace")
        except Exception:
            return JSONResponse({"error": "Could not read that file as text"}, status_code=400)
    elif filename_lower.endswith(".json"):
        try:
            raw_bytes = file.file.read()
            data = json.loads(raw_bytes.decode("utf-8", errors="replace"))
            pairs = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        q = item.get("question") or item.get("q") or ""
                        a = item.get("expected") or item.get("answer") or item.get("section_info") or item.get("a") or ""
                        if q:
                            pairs.append({"question": str(q).strip(), "expected": str(a).strip() or "HR Policy"})
            elif isinstance(data, dict):
                items = data.get("pairs") or data.get("questions") or data.get("cases") or []
                for item in items:
                    if isinstance(item, dict):
                        q = item.get("question") or item.get("q") or ""
                        a = item.get("expected") or item.get("answer") or item.get("section_info") or item.get("a") or ""
                        if q:
                            pairs.append({"question": str(q).strip(), "expected": str(a).strip() or "HR Policy"})
            if pairs:
                return {"ok": True, "pairs": pairs}
            return JSONResponse({"error": "No valid question/expected pairs found in JSON"}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Invalid JSON format: {exc}"}, status_code=400)
    else:
        return JSONResponse({"error": "Only PDF, TXT, MD, or JSON files are supported here"}, status_code=400)

    pairs = parse_qa_pairs(full_text)
    if not pairs:
        return JSONResponse({
            "error": 'No "Q:"/"A:" pairs found. Expected format: "Q: your question" on one line, "A: expected answer" on the next, blank line between pairs.'
        }, status_code=400)
    return {"ok": True, "pairs": pairs}


@router.post("/eval/run")
def eval_run(sid: RequiredSessionId, payload: Optional[EvalRunPayload] = Body(default=None)):
    """Runs a hit-rate@k and MRR benchmark over question sets across retrieval strategies."""
    payload = payload or EvalRunPayload()
    k = max(1, min(payload.top_k or payload.k, 20))
    chunk_mode_filter = (payload.strategy_filter or payload.chunk_mode or "").strip() or None
    preset_names = payload.presets or list(EVAL_PRESETS.keys())
    legacy_modes = payload.modes

    questions = []
    for idx, q in enumerate(payload.questions):
        q_text = (q.question or "").strip()
        expected = (q.expected or "").strip()
        expected_doc = (q.expected_doc or "").strip()
        expected_section = (q.expected_section or "").strip()
        q_id = str(q.id or f"q_{idx + 1}")

        if q_text and (expected or expected_doc or expected_section):
            questions.append({
                "id": q_id,
                "question": q_text,
                "expected": expected or expected_section or expected_doc,
                "expected_doc": expected_doc,
                "expected_section": expected_section,
            })

    if not questions:
        return JSONResponse(
            {"error": "No valid questions provided (both question and expected ground truth are required)"},
            status_code=400,
        )

    fn_get_store = get_app_symbol("_get_store", get_store)
    fn_run_preset = get_app_symbol("_run_eval_preset", run_eval_preset)
    eval_presets_map = get_app_symbol("EVAL_PRESETS", EVAL_PRESETS)

    store = fn_get_store(sid)
    if not store.chunks:
        return JSONResponse({"error": "No documents indexed in this session yet — upload one first"},
                            status_code=400)

    active_store = store.filtered_by_method(chunk_mode_filter) if chunk_mode_filter else store
    if chunk_mode_filter and not active_store.chunks:
        return JSONResponse({"error": f"No documents indexed under the '{chunk_mode_filter}' strategy"},
                            status_code=400)

    by_preset = {}
    names = legacy_modes if legacy_modes else preset_names
    for name in names:
        preset = eval_presets_map.get(name) or {
            "force_tfidf": False, "mode": name, "rerank": False, "rewrite": False,
        }
        per_question = []
        hits = 0
        for q in questions:
            result = fn_run_preset(
                active_store,
                q["id"],
                q["question"],
                q["expected"],
                k,
                preset,
                expected_doc=q["expected_doc"],
                expected_section=q["expected_section"]
            )
            hits += int(result["hit"])
            per_question.append(result)

        rr_sum = sum(r.get("reciprocal_rank", 0.0) for r in per_question)
        total = len(questions) or 1
        by_preset[name] = {
            "hit_rate": hits / total,
            "mrr": round(rr_sum / total, 4),
            "hits": hits,
            "total": total,
            "results": per_question,
        }

    return {"ok": True, "k": k, "total_questions": len(questions), "modes": by_preset}


def find_matching_benchmark(cid: str, question: str, answer: str, raw_cases: list[dict]) -> dict:
    """Robustly matches an incoming case against the benchmark catalog by ID, index, or QA similarity."""
    if not raw_cases:
        return {}

    cid_clean = str(cid or "").strip().lower()
    # 1. Exact case_id match
    for c in raw_cases:
        if c.get("case_id", "").lower() == cid_clean:
            return c

    # 2. Extract numeric index from ID (e.g. 'txt_case_2', 'custom_05', 'case_2')
    num_match = re.search(r"(\d+)", cid_clean)
    if num_match:
        target_cid = f"case_{int(num_match.group(1)):02d}"
        for c in raw_cases:
            if c.get("case_id", "").lower() == target_cid:
                return c

    # 3. Match by question and disambiguate with answer tokens
    q_norm = re.sub(r"[^\w\s]", "", question or "").strip().lower()
    matching_q = [
        c for c in raw_cases
        if re.sub(r"[^\w\s]", "", c.get("question", "")).strip().lower() == q_norm
    ]
    if len(matching_q) == 1:
        return matching_q[0]
    elif len(matching_q) > 1:
        ans_tokens = set(re.findall(r"\w+", (answer or "").lower()))
        return max(
            matching_q,
            key=lambda c: len(ans_tokens & set(re.findall(r"\w+", (c.get("answer", "")).lower())))
        )

    return {}


@router.get("/api/evaluation/benchmark")
@router.get("/api/week6/benchmark")
def get_week6_benchmark():
    """Returns the pure 25 benchmark case definitions without any precomputed evaluation results."""
    cases_file = BASE_DIR / "week6" / "eval_cases_25.json"
    labels_file = BASE_DIR / "week6" / "labels_25.json"

    raw_cases = []
    if cases_file.exists():
        try:
            with open(cases_file, "r", encoding="utf-8") as f:
                raw_cases = json.load(f)
        except Exception:
            raw_cases = []

    labels = {}
    if labels_file.exists():
        try:
            with open(labels_file, "r", encoding="utf-8") as f:
                labels = json.load(f)
        except Exception:
            labels = {}

    clean_cases = []
    for c in raw_cases:
        cid = c.get("case_id")
        clean_cases.append({
            "case_id": cid,
            "trace_id": c.get("trace_id", ""),
            "question": c.get("question", ""),
            "answer": c.get("answer", ""),
            "retrieved_context": c.get("retrieved_context", ""),
            "handbook_version": c.get("handbook_version", "2018"),
            "section_info": c.get("section_info", ""),
            "taxonomy_mode": c.get("taxonomy_mode", ""),
            "human_label": labels.get(cid, c.get("human_label", 1)),
            "expected_numeric": c.get("expected_numeric"),
            "out_of_jurisdiction": c.get("out_of_jurisdiction", False),
            "status": "PENDING",
            "evaluation_run_id": None,
            "judge_v1_verdict": None,
            "judge_v1_agreed": None,
            "judge_v1_raw": None,
            "judge_v2_verdict": None,
            "judge_v2_agreed": None,
            "judge_v2_raw": None,
            "assertions": None,
            "failure_category": None,
            "failure_type": None,
            "failure_reason": None,
            "resolution": None,
            "source": None,
            "llm_completed": None,
            "latency_ms": None,
        })

    return {
        "total_cases": len(clean_cases),
        "cases": clean_cases,
        "results": clean_cases,
    }


@router.get("/api/evaluation/judges")
@router.get("/api/week6/results")
def get_week6_results(include_history: bool = False):
    """Returns benchmark cases or historical evaluation results."""
    if not include_history:
        return get_week6_benchmark()

    cases_file = BASE_DIR / "week6" / "eval_cases_25.json"
    results_file = BASE_DIR / "week6" / "trace_eval_results.json"
    labels_file = BASE_DIR / "week6" / "labels_25.json"

    raw_cases = []
    if cases_file.exists():
        try:
            with open(cases_file, "r", encoding="utf-8") as f:
                raw_cases = json.load(f)
        except Exception:
            raw_cases = []

    labels = {}
    if labels_file.exists():
        try:
            with open(labels_file, "r", encoding="utf-8") as f:
                labels = json.load(f)
        except Exception:
            labels = {}

    eval_results = []
    if results_file.exists():
        try:
            with open(results_file, "r", encoding="utf-8") as f:
                eval_results = json.load(f)
        except Exception:
            eval_results = []

    merged = []
    v1_agreed = 0
    v2_agreed = 0
    case_map = {c.get("case_id"): c for c in raw_cases}

    for res in eval_results:
        cid = res.get("case_id")
        base = case_map.get(cid, {})
        item = {
            **base,
            **res,
            "human_label": labels.get(cid, res.get("human_label", 1)),
            "status": "COMPLETED",
        }
        if item.get("judge_v1_agreed"):
            v1_agreed += 1
        if item.get("judge_v2_agreed"):
            v2_agreed += 1
        merged.append(item)

    total = len(merged)
    v1_pct = (v1_agreed / total * 100) if total else 0.0
    v2_pct = (v2_agreed / total * 100) if total else 0.0

    return {
        "total_cases": total,
        "judge_v1_agreement_pct": round(v1_pct, 2),
        "judge_v2_agreement_pct": round(v2_pct, 2),
        "v1_agreements": v1_agreed,
        "v2_agreements": v2_agreed,
        "results": merged,
    }


def _prepare_cases_for_evaluation(cases_payload: Optional[list]) -> tuple[list[dict], dict[str, int], str, str]:
    """Prepares and resolves test cases against benchmark metadata with zero data leakage."""
    v1_prompt_path = BASE_DIR / "week6" / "judge_v1.txt"
    v2_prompt_path = BASE_DIR / "week6" / "judge_v2.txt"
    cases_file = BASE_DIR / "week6" / "eval_cases_25.json"
    labels_file = BASE_DIR / "week6" / "labels_25.json"

    v1_template = v1_prompt_path.read_text(encoding="utf-8") if v1_prompt_path.exists() else ""
    v2_template = v2_prompt_path.read_text(encoding="utf-8") if v2_prompt_path.exists() else ""

    raw_benchmark_cases = []
    if cases_file.exists():
        try:
            with open(cases_file, "r", encoding="utf-8") as f:
                raw_benchmark_cases = json.load(f)
        except Exception:
            raw_benchmark_cases = []

    labels = {}
    if labels_file.exists():
        try:
            with open(labels_file, "r", encoding="utf-8") as f:
                labels = json.load(f)
        except Exception:
            labels = {}

    cases_to_eval = []
    if cases_payload:
        for idx, c in enumerate(cases_payload):
            if hasattr(c, "model_dump"):
                c_dict = c.model_dump()
            elif isinstance(c, dict):
                c_dict = c
            else:
                c_dict = getattr(c, "__dict__", {})

            cid = c_dict.get("case_id") or f"custom_{idx + 1}"
            bm = find_matching_benchmark(cid, c_dict.get("question", ""), c_dict.get("answer", ""), raw_benchmark_cases)
            resolved_cid = bm.get("case_id", cid)

            ctx = c_dict.get("retrieved_context") or bm.get("retrieved_context", "")
            exp_num = c_dict.get("expected_numeric") if c_dict.get("expected_numeric") is not None else bm.get("expected_numeric")
            is_ooj = c_dict.get("out_of_jurisdiction") if c_dict.get("out_of_jurisdiction") is not None else bm.get("out_of_jurisdiction", False)

            if c_dict.get("human_label") is not None:
                h_lbl = c_dict["human_label"]
            elif resolved_cid in labels:
                h_lbl = labels[resolved_cid]
            elif "human_label" in bm:
                h_lbl = bm["human_label"]
            elif bm.get("regression", False) or resolved_cid in ("case_01", "case_03"):
                h_lbl = 0
            else:
                h_lbl = 1

            mode_val = c_dict.get("taxonomy_mode")
            if not mode_val or mode_val in ("Custom Query", "Uploaded TXT QA", "Imported Case"):
                mode_val = bm.get("taxonomy_mode", "HR Policy")

            cases_to_eval.append({
                "case_id": resolved_cid,
                "trace_id": c_dict.get("trace_id") or bm.get("trace_id", f"trace_{resolved_cid}"),
                "question": c_dict.get("question", ""),
                "answer": c_dict.get("answer", ""),
                "retrieved_context": ctx,
                "handbook_version": c_dict.get("handbook_version") or bm.get("handbook_version", "2018"),
                "section_info": c_dict.get("section_info") or bm.get("section_info", ""),
                "taxonomy_mode": mode_val,
                "human_label": h_lbl,
                "expected_numeric": exp_num,
                "out_of_jurisdiction": is_ooj,
            })
    else:
        for c in raw_benchmark_cases:
            cid = c.get("case_id")
            cases_to_eval.append({
                "case_id": cid,
                "trace_id": c.get("trace_id", f"trace_{cid}"),
                "question": c.get("question", ""),
                "answer": c.get("answer", ""),
                "retrieved_context": c.get("retrieved_context", ""),
                "handbook_version": c.get("handbook_version", "2018"),
                "section_info": c.get("section_info", ""),
                "taxonomy_mode": c.get("taxonomy_mode", "HR Policy"),
                "human_label": labels.get(cid, c.get("human_label", 1)),
                "expected_numeric": c.get("expected_numeric"),
                "out_of_jurisdiction": c.get("out_of_jurisdiction", False),
            })

    return cases_to_eval, labels, v1_template, v2_template


@router.post("/api/evaluation/runs")
@router.post("/api/week6/runs")
def create_evaluation_run(payload: Optional[Week6EvalPayload] = Body(default=None)):
    """Starts a background evaluation run independent of the frontend component lifecycle."""
    cases_payload = payload.cases if payload else None
    eval_engine = "llm" if (payload and payload.run_llm) else "deterministic"

    cases_to_eval, labels, v1_template, v2_template = _prepare_cases_for_evaluation(cases_payload)
    if not cases_to_eval:
        return JSONResponse({"error": "No cases available to evaluate"}, status_code=400)

    run_state = run_manager.start_run(
        cases=cases_to_eval,
        eval_engine=eval_engine,
        v1_template=v1_template,
        v2_template=v2_template,
        labels=labels,
    )

    return run_state.to_dict()


@router.get("/api/evaluation/runs/active")
@router.get("/api/week6/runs/active")
def get_active_evaluation_run():
    """Returns the currently active running evaluation or the latest run state."""
    active_id = run_manager.get_active_run_id()
    if not active_id:
        return {"active_run_id": None, "run": None}
    run = run_manager.get_run(active_id)
    return {
        "active_run_id": active_id,
        "run": run.to_dict() if run else None,
    }


@router.get("/api/evaluation/runs/{run_id}")
@router.get("/api/week6/runs/{run_id}")
def get_evaluation_run(run_id: str):
    """Returns the current state and results for a specific evaluation run."""
    run = run_manager.get_run(run_id)
    if not run:
        return JSONResponse({"error": f"Evaluation run '{run_id}' not found"}, status_code=404)
    return run.to_dict()


@router.post("/api/evaluation/runs/{run_id}/cancel")
@router.post("/api/week6/runs/{run_id}/cancel")
def cancel_evaluation_run(run_id: str):
    """Explicitly cancels an active background evaluation run upon user request."""
    success = run_manager.cancel_run(run_id)
    if not success:
        return JSONResponse({"error": f"Evaluation run '{run_id}' not found"}, status_code=404)
    return {"ok": True, "evaluation_run_id": run_id, "status": "CANCELLED"}


@router.post("/api/evaluation/judges")
@router.post("/api/week6/evaluate")
def evaluate_week6(payload: Optional[Week6EvalPayload] = Body(default=None)):
    """Synchronous judge evaluation endpoint returning clean and dynamic failure metadata."""
    cases_payload = payload.cases if payload else None
    run_llm_active = bool(payload and payload.run_llm)

    cases_to_eval, labels, v1_template, v2_template = _prepare_cases_for_evaluation(cases_payload)
    eval_run_id = f"eval_{uuid.uuid4().hex[:12]}"
    results = []
    v1_agreed = 0
    v2_agreed = 0

    for c in cases_to_eval:
        cid = c.get("case_id", "case_x")
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

        if run_llm_active and v1_template and v2_template:
            try:
                v1_verdict, v1_raw, v1_src, v1_lat, v1_completed = evaluate_case_with_judge_detailed(c, v1_template)
                v2_verdict, v2_raw, v2_src, v2_lat, v2_completed = evaluate_case_with_judge_detailed(c, v2_template)
            except Exception as e:
                logger.warning("LLM Judge call failed for case %s: %s", cid, e)
                v1_verdict = evaluate_case_deterministically(c, is_strict_section=True)
                v2_verdict = evaluate_case_deterministically(c, is_strict_section=False)
                v1_src = "ERROR"
                v2_src = "ERROR"
        else:
            judge_v1_verdict = evaluate_case_deterministically(c, is_strict_section=True)
            judge_v2_verdict = evaluate_case_deterministically(c, is_strict_section=False)

        is_v1_agreed = (v1_verdict == h_label)
        is_v2_agreed = (v2_verdict == h_label)

        if is_v1_agreed:
            v1_agreed += 1
        if is_v2_agreed:
            v2_agreed += 1

        # Dynamic, non-contradictory failure metadata calculation
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
            fail_cat = "llm_model"
            fail_type = "generator_completeness_omission"
            if is_v2_agreed:
                fail_reason = "Generator omitted mandatory qualifying conditions present in retrieved context; Judge V2 correctly detected omission."
            else:
                fail_reason = "Generator omitted mandatory qualifying conditions present in retrieved context; Judge V2 failed to detect omission (judge disagreement)."
            res_text = "Investigate generation completeness for multi-clause policy answers."
        else:
            fail_cat = "llm_model"
            fail_type = "judge_disagreement"
            fail_reason = "Judge rejected answer despite human ground truth agreement."
            res_text = "Calibrate judge rubric with balanced multi-clause criteria."

        results.append({
            **c,
            "status": "COMPLETED",
            "evaluation_run_id": eval_run_id,
            "human_label": h_label,
            "assertions": assertions,
            "judge_v1_verdict": v1_verdict,
            "judge_v1_agreed": is_v1_agreed,
            "judge_v1_raw": v1_raw,
            "judge_v1_source": v1_src,
            "judge_v1_latency_ms": round(v1_lat, 2),
            "judge_v1_llm_completed": v1_completed,
            "judge_v2_verdict": v2_verdict,
            "judge_v2_agreed": is_v2_agreed,
            "judge_v2_raw": v2_raw,
            "judge_v2_source": v2_src,
            "judge_v2_latency_ms": round(v2_lat, 2),
            "judge_v2_llm_completed": v2_completed,
            "source": v2_src,
            "latency_ms": round(v2_lat, 2),
            "llm_completed": v2_completed,
            "failure_category": fail_cat,
            "failure_type": fail_type,
            "failure_reason": fail_reason,
            "resolution": res_text,
        })

    total = len(results)
    v1_pct = (v1_agreed / total * 100) if total else 0.0
    v2_pct = (v2_agreed / total * 100) if total else 0.0

    return {
        "evaluation_run_id": eval_run_id,
        "total_cases": total,
        "judge_v1_agreement_pct": round(v1_pct, 2),
        "judge_v2_agreement_pct": round(v2_pct, 2),
        "v1_agreements": v1_agreed,
        "v2_agreements": v2_agreed,
        "results": results,
    }
