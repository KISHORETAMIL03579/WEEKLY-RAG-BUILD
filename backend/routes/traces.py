# backend/routes/traces.py — Privacy-Preserving Trace & Replay Endpoints
from __future__ import annotations

import hashlib
from typing import Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.config import get_app_symbol
from backend.schemas.trace import TracesResponse
from backend.services.llm import chat_call
from backend.services.search import build_qa_user_prompt
from backend.storage.session_manager import OptionalSessionId
from backend.storage.trace_store import TRACES, get_prompt

router = APIRouter(tags=["traces"])


@router.get("/traces", response_model=TracesResponse)
def list_traces(current_sid: OptionalSessionId):
    """List logged trace_ids for the current session."""
    if not current_sid:
        return TracesResponse(count=0, trace_ids=[])
    traces_store = get_app_symbol("TRACES", TRACES)
    expected_hash = hashlib.sha256(current_sid.encode()).hexdigest()[:16]
    session_traces = [
        r["trace_id"]
        for r in traces_store.all()
        if r.get("session_id_hash") == expected_hash and "trace_id" in r
    ]
    return TracesResponse(count=len(session_traces), trace_ids=session_traces)


@router.post("/replay/{trace_id}")
def replay_trace(trace_id: str, current_sid: OptionalSessionId):
    """Privacy-preserving replay reconstructing generation from durable prompt template,

    recorded model/temperature, and persisted redacted context snapshot.
    """
    if not current_sid:
        return JSONResponse({"error": "No active session"}, status_code=401)

    traces_store = get_app_symbol("TRACES", TRACES)
    fn_chat_call = get_app_symbol("_chat_call", chat_call)
    fn_get_prompt = get_app_symbol("get_prompt", get_prompt)
    fn_build_user_prompt = get_app_symbol("build_qa_user_prompt", build_qa_user_prompt)

    record = traces_store.get(trace_id)
    if not record:
        return JSONResponse({"error": f"No trace found for trace_id={trace_id}"}, status_code=404)

    expected_hash = hashlib.sha256(current_sid.encode()).hexdigest()[:16]
    if record.get("session_id_hash") != expected_hash:
        return JSONResponse({"error": "Unauthorized: trace belongs to another session"}, status_code=403)

    missing = []
    for field in ("prompt_version", "model", "retrieved", "raw_output"):
        if record.get(field) in (None, [], ""):
            missing.append(field)

    if record.get("retrieval_mode") == "tfidf" or not record.get("prompt_version"):
        return {
            "trace_id": trace_id,
            "replayable": False,
            "reason": (
                "This trace has no LLM prompt_version (either the TF-IDF "
                "offline path answered it, or the context-validation gate "
                "rejected it before any LLM call was made — both produce "
                "deterministic, template-based output with no LLM call)."
            ),
            "original": {
                "answer": record.get("answer"),
                "retrieved": record.get("retrieved"),
            },
            "fields_missing_from_trace": missing,
        }

    prompt_text = fn_get_prompt(record["prompt_version"])
    if prompt_text is None:
        return JSONResponse({
            "trace_id": trace_id,
            "replayable": False,
            "reason": (
                f"Durable prompt artifact for prompt_version {record['prompt_version']!r} "
                f"is missing from registry. Exact prompt version required to replay."
            ),
            "original": {
                "question": record.get("question"),
                "model": record.get("model"),
                "prompt_version": record.get("prompt_version"),
                "raw_output": record.get("raw_output"),
            },
            "replayed": None,
            "outputs_match_exactly": None,
            "fields_missing_from_trace": missing,
        }, status_code=400)

    results_for_prompt = [
        {
            "filename": r.get("filename"),
            "page": r.get("page"),
            "section": r.get("section"),
            "text": r.get("text") or "",
        }
        for r in record.get("retrieved", [])
    ]
    user_prompt = fn_build_user_prompt(record["question"], results_for_prompt)

    try:
        replayed_raw = fn_chat_call(
            prompt_text,
            user_prompt,
            temperature=record.get("temperature") or 0.0,
            model=record.get("model"),
        )
        replay_error = None
    except Exception as exc:
        replayed_raw = None
        replay_error = str(exc)

    return {
        "trace_id": trace_id,
        "replayable": True,
        "replay_type": "privacy_preserving",
        "original": {
            "question": record.get("question"),
            "model": record.get("model"),
            "prompt_version": record.get("prompt_version"),
            "raw_output": record.get("raw_output"),
        },
        "replayed": {
            "model": record.get("model"),
            "prompt_version": record.get("prompt_version"),
            "raw_output": replayed_raw,
            "error": replay_error,
        },
        "outputs_match_exactly": (replayed_raw == record.get("raw_output")) if replayed_raw is not None else None,
        "fields_missing_from_trace": missing,
    }

