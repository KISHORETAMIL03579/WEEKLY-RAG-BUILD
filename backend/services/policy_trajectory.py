"""Tool-selection audit (per run) and trajectory evaluation (Week 8).

Two layers, both pure functions over the recorded ``tool_calls`` of a run:

* :func:`audit_tool_selection` - attached to every agent response. Which tools
  did the model pick, did the question need others, were calls rejected, how
  many attempts/retries did each tool need.
* :func:`evaluate_case` / :func:`summarize` / :func:`compare` - score a run
  against the expected path(s) of a benchmark case and aggregate the four
  trajectory numbers, the outcome-vs-trajectory gap and the failure-mode zoo.

Expected paths are data (``benchmarks/policy_execution/expected_trajectories.json``);
cases that legitimately allow several orders list every allowed path and a run
passes if it matches any one of them exactly.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from backend.config import BASE_DIR
from backend.services import policy_retrieval

EXPECTATIONS_PATH = BASE_DIR / "backend" / "data" / "tool_expectations.json"
TRAJECTORIES_PATH = BASE_DIR / "benchmarks" / "policy_execution" / "expected_trajectories.json"

PROVIDER_TERMINATIONS = {
    "PROVIDER_TRANSIENT",
    "PROVIDER_ERROR",
    "PROVIDER_UNAVAILABLE",
    "GROQ_UNAVAILABLE",
    "GROQ_TIMEOUT",
}

# Order matters: the first mode that applies becomes the case's primary mode.
FAILURE_MODES = (
    "provider_error",
    "budget_exhausted",
    "tool_error",
    "invalid_tool_call",
    "skipped_required_tool",
    "wrong_tool_selection",
    "bad_arguments",
    "redundant_calls",
    "answer_wrong",
)


def _dump(result: Any) -> Dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return dict(vars(result))


# ---------------------------------------------------------------------------
# Per-run audit of the model's tool selection
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_expectations() -> Dict[str, Any]:
    return json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))


def matching_rules(question: str) -> List[Dict[str, Any]]:
    """Rules that apply to ``question``; naming a jurisdiction also triggers ``local_rules``.

    Shared by the audit, the router and the fixed workflow so they agree on what a
    question needs. Jurisdiction names and demonyms come from the taxonomy data.
    """
    text = question or ""
    rules = list(load_expectations()["rules"])
    terms = [
        term
        for names in policy_retrieval.load_taxonomy().get("jurisdiction_terms", {}).values()
        for term in names
    ]
    names_a_jurisdiction = any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE) for term in terms
    )
    return [
        rule
        for rule in rules
        if re.search(rule["pattern"], text, re.IGNORECASE)
        or (rule["id"] == "local_rules" and names_a_jurisdiction)
    ]


def observed_sequence(tool_calls: Iterable[Mapping[str, Any]]) -> List[str]:
    return [str(call["tool_name"]) for call in tool_calls]


def _retry_stats(tool_calls: Sequence[Mapping[str, Any]], llm_calls: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    attempts: Dict[str, int] = {}
    retries: Dict[str, int] = {}
    for call in tool_calls:
        name = str(call["tool_name"])
        attempts[name] = attempts.get(name, 0) + int(call.get("attempts", 1))
        retries[name] = retries.get(name, 0) + int(call.get("retries", 0))
    model_retries = sum(int(item.get("provider_retries", 0)) for item in llm_calls)
    return {
        "tool_attempts": attempts,
        "tool_retries": retries,
        "total_tool_retries": sum(retries.values()),
        "model_call_retries": model_retries,
        "model_calls": len(llm_calls),
    }


def audit_tool_selection(
    question: str,
    tool_calls: Sequence[Mapping[str, Any]],
    rejected_tool_calls: Sequence[Mapping[str, Any]] = (),
    llm_calls: Sequence[Mapping[str, Any]] = (),
    available_tools: Optional[Iterable[str]] = None,
    termination_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Judge tool selection for an ad-hoc question using the declarative rules.

    ``selection_ok`` is only decided for completed runs (``SUCCESS``): a run that stopped
    early (unknown employee, budget, provider outage) never got the chance to call every
    tool, so its selection is reported as not evaluated (``None``).
    """
    available = set(available_tools) if available_tools is not None else None
    selected = observed_sequence(tool_calls)
    reasons: List[str] = []
    required_groups: List[Dict[str, Any]] = []
    for rule in matching_rules(question):
        options = [t for t in rule["requires_any"] if available is None or t in available]
        if not options:
            continue  # the tool is not installed on any connected server
        satisfied = any(tool in selected for tool in options)
        required_groups.append(
            {
                "rule": rule["id"],
                "requires_any": options,
                "satisfied": satisfied,
                "reason": rule["reason"],
            }
        )
        if not satisfied and termination_reason in (None, "SUCCESS"):
            reasons.append(f"{rule['reason']} Expected one of: {', '.join(options)}.")
    required_tools = {tool for group in required_groups for tool in group["requires_any"]}
    counts = Counter(selected)
    # "Extra" only makes sense once the question's needs are known; extra evidence is
    # informational, never a failure.
    extra = (
        sorted(
            tool
            for tool in counts
            if tool not in required_tools and tool not in _lookup_tools(tool_calls)
        )
        if required_groups
        else []
    )
    duplicates = sorted(tool for tool, count in counts.items() if count > 1)
    if duplicates:
        reasons.append(f"Tool(s) called more than once: {', '.join(duplicates)}.")
    if rejected_tool_calls:
        reasons.append(f"{len(rejected_tool_calls)} tool call(s) were rejected before execution.")
    missing = sorted(
        tool
        for group in required_groups
        if not group["satisfied"]
        for tool in group["requires_any"]
    )
    completed = termination_reason in (None, "SUCCESS")
    if not completed:
        reasons.insert(0, f"Run ended early ({termination_reason}); tool selection was not judged.")
    return {
        "tools_selected": selected,
        "call_counts": dict(counts),
        "required": required_groups,
        "missing_tools": missing if completed else [],
        "extra_tools": extra,
        "duplicate_tools": duplicates,
        "rejected_calls": len(rejected_tool_calls),
        "selection_ok": (not missing and not rejected_tool_calls) if completed else None,
        "termination_reason": termination_reason,
        "reasons": reasons,
        "retries": _retry_stats(tool_calls, llm_calls),
    }


def _lookup_tools(tool_calls: Sequence[Mapping[str, Any]]) -> set:
    """Tools that play the employee-lookup role are always acceptable first steps."""
    role = load_expectations()["employee_lookup_role"]
    return {str(call["tool_name"]) for call in tool_calls if role in call.get("roles", [])}


# ---------------------------------------------------------------------------
# Benchmark trajectory evaluation
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_expected_trajectories() -> Dict[str, Dict[str, Any]]:
    payload = json.loads(TRAJECTORIES_PATH.read_text(encoding="utf-8"))
    return payload["cases"]


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    left, right = set(a), set(b)
    return len(left & right) / len(left | right) if left | right else 1.0


def best_path(observed: Sequence[str], paths: Sequence[Sequence[str]]) -> Dict[str, Any]:
    """Closest allowed path to ``observed`` (exact match wins, else tool-set overlap)."""
    for path in paths:
        if list(path) == list(observed):
            return {"path": list(path), "exact": True}
    ranked = sorted(
        paths,
        key=lambda path: (-_jaccard(observed, path), abs(len(observed) - len(path))),
    )
    return {"path": list(ranked[0]), "exact": False}


def _argument_checks(
    calls: Sequence[Mapping[str, Any]],
    rejected: Sequence[Mapping[str, Any]],
    employee_id: str,
    citation: Optional[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Were ids, jurisdictions and cited sections real, or fluent fiction?"""
    checks: List[Dict[str, Any]] = []
    record_jurisdiction: Optional[str] = None
    for call in calls:
        output = call.get("output") or {}
        if "jurisdiction" in (output.get("fields") or {}):
            record_jurisdiction = output["fields"]["jurisdiction"]
    for call in calls:
        args = call.get("arguments") or {}
        name = call["tool_name"]
        if "employee_id" in args:
            found = not call.get("is_error") and (call.get("output") or {}).get("found", True)
            same = str(args["employee_id"]).strip().upper() == employee_id.strip().upper()
            checks.append(
                {
                    "check": "employee_id_real",
                    "tool": name,
                    "step": call.get("step"),
                    "ok": bool(found and same),
                    "detail": f"argument {args['employee_id']!r}, "
                    f"{'resolved' if found else 'not found in the documents'}",
                }
            )
        if "jurisdiction" in args and record_jurisdiction is not None:
            checks.append(
                {
                    "check": "jurisdiction_matches_record",
                    "tool": name,
                    "step": call.get("step"),
                    "ok": args["jurisdiction"] == record_jurisdiction,
                    "detail": f"argument {args['jurisdiction']!r}, record says {record_jurisdiction!r}",
                }
            )
    for item in rejected:
        checks.append(
            {
                "check": "schema_valid",
                "tool": item.get("tool_name"),
                "step": item.get("step"),
                "ok": False,
                "detail": item.get("reason"),
            }
        )
    if citation and citation.get("has_citation"):
        unresolved = citation.get("unresolved_sections", [])
        checks.append(
            {
                "check": "citation_resolves",
                "tool": None,
                "step": None,
                "ok": not unresolved,
                "detail": f"cited {citation.get('cited_sections')}, unresolved {unresolved}",
            }
        )
    return checks


def evaluate_case(
    case: Mapping[str, Any],
    result: Any,
    expected: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Score one recorded run against the expected trajectory of ``case``."""
    run = _dump(result)
    spec = expected or load_expected_trajectory(case["case_id"])
    calls = run.get("tool_calls") or []
    rejected = run.get("rejected_tool_calls") or []
    observed = observed_sequence(calls)
    matched = best_path(observed, spec["paths"])
    expected_set, observed_set = set(matched["path"]), set(observed)
    missing = sorted(expected_set - observed_set)
    extra = sorted(observed_set - expected_set)
    duplicates = sorted(name for name, count in Counter(observed).items() if count > 1)
    checks = _argument_checks(
        calls, rejected, case["employee_id"], run.get("citation")
    )
    invalid_checks = [item for item in checks if not item["ok"]]
    termination = run.get("termination_reason", "")
    completed = termination == "SUCCESS"
    steps_needed = int(spec.get("steps_needed") or len(matched["path"]) or 1)
    steps_taken = len(calls) + len(rejected)
    trajectory_passed = bool(matched["exact"] and not invalid_checks and not rejected and completed)
    outcome_passed = bool(run.get("passed"))

    modes: List[str] = []
    if termination in PROVIDER_TERMINATIONS:
        modes.append("provider_error")
    if termination.startswith("BUDGET_"):
        modes.append("budget_exhausted")
    if termination == "TOOL_ERROR":
        modes.append("tool_error")
    if rejected:
        modes.append("invalid_tool_call")
    if completed and missing:
        modes.append("skipped_required_tool")
    if extra and set(extra) - set(spec.get("allowed_extra_tools", [])):
        modes.append("wrong_tool_selection")
    if [item for item in invalid_checks if item["check"] != "schema_valid"]:
        modes.append("bad_arguments")
    if duplicates or (extra and "wrong_tool_selection" not in modes):
        modes.append("redundant_calls")
    if completed and matched["exact"] and not modes and not outcome_passed:
        modes.append("answer_wrong")
    primary = next((mode for mode in FAILURE_MODES if mode in modes), None)

    return {
        "case_id": case["case_id"],
        "employee_id": case["employee_id"],
        "question": case.get("question"),
        "expected_paths": spec["paths"],
        "accepts_alternate_paths": len(spec["paths"]) > 1,
        "path_notes": spec.get("notes"),
        "observed_sequence": observed,
        "matched_path": matched["path"],
        "path_exact": matched["exact"],
        "missing_tools": missing,
        "extra_tools": extra,
        "duplicate_tools": duplicates,
        "tool_choice_score": round(_jaccard(observed, matched["path"]), 4),
        "argument_checks": checks,
        "argument_validity": (
            round(1 - len(invalid_checks) / len(checks), 4) if checks else None
        ),
        "steps_taken": steps_taken,
        "steps_needed": steps_needed,
        "step_efficiency": round(steps_taken / steps_needed, 4),
        "outcome_passed": outcome_passed,
        "strict_passed": bool(run.get("strict_passed")),
        "trajectory_passed": trajectory_passed,
        "right_answer_wrong_path": outcome_passed and not trajectory_passed,
        "failure_modes": modes,
        "primary_failure_mode": primary,
        "termination_reason": termination,
        "tool_trace": [
            {
                "step": call.get("step"),
                "tool": call["tool_name"],
                "server": call.get("server"),
                "arguments": call.get("arguments"),
                "is_error": call.get("is_error", False),
                "attempts": call.get("attempts", 1),
                "retries": call.get("retries", 0),
                "rationale": (call.get("selection") or {}).get("rationale"),
            }
            for call in calls
        ],
        "rejected_tool_calls": list(rejected),
        "retries": (run.get("tool_audit") or {}).get("retries") or _retry_stats(calls, run.get("llm_calls") or []),
        "latency_ms": run.get("latency_ms", 0.0),
        "total_tokens": run.get("total_tokens", 0),
        "cost_usd": run.get("cost_usd", 0.0),
        "answer": {
            "entitlement_value": run.get("entitlement_value"),
            "rule_cited": run.get("rule_cited"),
            "explanation": run.get("explanation"),
        },
    }


def load_expected_trajectory(case_id: str) -> Dict[str, Any]:
    try:
        return load_expected_trajectories()[case_id]
    except KeyError:
        raise KeyError(
            f"No expected trajectory for {case_id!r} in {TRAJECTORIES_PATH.name}"
        ) from None


def _pct(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 2) if denominator else 0.0


def _p50_max(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"p50": 0.0, "max": 0.0}
    return {"p50": round(statistics.median(values), 6), "max": round(max(values), 6)}


def summarize(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregate the four trajectory numbers, the gap and the failure-mode zoo."""
    count = len(records)
    outcome = sum(1 for r in records if r["outcome_passed"])
    strict = sum(1 for r in records if r.get("strict_passed"))
    trajectory = sum(1 for r in records if r["trajectory_passed"])
    checks = [c for r in records for c in r["argument_checks"]]
    invalid = sum(1 for c in checks if not c["ok"])
    primary = Counter(r["primary_failure_mode"] for r in records if r["primary_failure_mode"])
    anywhere = Counter(mode for r in records for mode in r["failure_modes"])
    wrong_path = [
        {
            "case_id": r["case_id"],
            "question": r["question"],
            "observed_sequence": r["observed_sequence"],
            "expected_paths": r["expected_paths"],
            "why": _why_wrong_path(r),
        }
        for r in records
        if r["right_answer_wrong_path"]
    ]
    tool_retries: Counter = Counter()
    tool_attempts: Counter = Counter()
    model_retries = 0
    for r in records:
        tool_retries.update(r["retries"].get("tool_retries", {}))
        tool_attempts.update(r["retries"].get("tool_attempts", {}))
        model_retries += r["retries"].get("model_call_retries", 0)
    return {
        "case_count": count,
        "outcome_pass_rate_pct": _pct(outcome, count),
        "outcome_strict_pass_rate_pct": _pct(strict, count),
        "trajectory_pass_rate_pct": _pct(trajectory, count),
        "outcome_vs_trajectory_gap_pct": round(_pct(outcome, count) - _pct(trajectory, count), 2),
        "tool_choice_accuracy": round(statistics.mean(r["tool_choice_score"] for r in records), 4) if count else 0.0,
        "exact_tool_set_rate_pct": _pct(sum(1 for r in records if not r["missing_tools"] and not r["extra_tools"]), count),
        "argument_validity_rate": round(1 - invalid / len(checks), 4) if checks else None,
        "argument_checks_total": len(checks),
        "argument_checks_failed": invalid,
        "step_efficiency_mean": round(statistics.mean(r["step_efficiency"] for r in records), 4) if count else 0.0,
        "step_efficiency_worst": max((r["step_efficiency"] for r in records), default=0.0),
        "cost_usd": _p50_max([r["cost_usd"] for r in records]),
        "latency_ms": _p50_max([r["latency_ms"] for r in records]),
        "total_tokens": _p50_max([r["total_tokens"] for r in records]),
        "failure_mode_counts": {mode: primary.get(mode, 0) for mode in FAILURE_MODES},
        "failure_mode_any_counts": {mode: anywhere.get(mode, 0) for mode in FAILURE_MODES},
        "right_answer_wrong_path": wrong_path,
        "retries": {
            "tool_attempts": dict(tool_attempts),
            "tool_retries": dict(tool_retries),
            "model_call_retries": model_retries,
        },
    }


def _why_wrong_path(record: Mapping[str, Any]) -> str:
    parts: List[str] = []
    if record["missing_tools"]:
        parts.append(f"never called {', '.join(record['missing_tools'])}")
    if record["extra_tools"]:
        parts.append(f"also called unexpected {', '.join(record['extra_tools'])}")
    bad = [c for c in record["argument_checks"] if not c["ok"]]
    if bad:
        parts.append("; ".join(f"{c['check']}: {c['detail']}" for c in bad))
    if not parts:
        parts.append("path did not match any allowed order")
    return "; ".join(parts)


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> Dict[str, Any]:
    """Before/after view of one mitigation: per-mode counts, price paid, regressions."""
    modes = sorted(set(before["failure_mode_counts"]) | set(after["failure_mode_counts"]))
    table = []
    regressions: List[str] = []
    for mode in modes:
        b = before["failure_mode_counts"].get(mode, 0)
        a = after["failure_mode_counts"].get(mode, 0)
        table.append({"mode": mode, "before": b, "after": a, "delta": a - b})
        if a > b:
            regressions.append(f"{mode}: {b} -> {a}")

    def delta(path: Sequence[str]) -> float:
        def dig(source: Mapping[str, Any]) -> float:
            value: Any = source
            for key in path:
                value = value[key]
            return value

        return round(dig(after) - dig(before), 6)

    return {
        "per_mode": table,
        "regressions": regressions,
        "modes_checked": modes,
        "price": {
            "latency_ms_p50_delta": delta(("latency_ms", "p50")),
            "latency_ms_max_delta": delta(("latency_ms", "max")),
            "tokens_p50_delta": delta(("total_tokens", "p50")),
            "tokens_max_delta": delta(("total_tokens", "max")),
            "cost_usd_p50_delta": delta(("cost_usd", "p50")),
            "cost_usd_max_delta": delta(("cost_usd", "max")),
        },
        "outcome_pass_rate_delta_pct": round(
            after["outcome_pass_rate_pct"] - before["outcome_pass_rate_pct"], 2
        ),
        "trajectory_pass_rate_delta_pct": round(
            after["trajectory_pass_rate_pct"] - before["trajectory_pass_rate_pct"], 2
        ),
    }
