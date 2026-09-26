"""Live Week 8 trajectory evaluation for the canonical Week 7 policy cases."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.config import CHAT_BACKEND, GROQ_MODEL  # noqa: E402
from backend.services.llm import chat_configured  # noqa: E402
from backend.services.policy_agent import run_agent_case  # noqa: E402

CASES_PATH = Path(__file__).with_name("cases.json")
REQUIRED_TOOL_SEQUENCE = ("get_employee_record", "search_handbook")


def evaluate_trajectory(case: dict[str, Any], result: Any) -> dict[str, Any]:
    calls = result.tool_calls
    observed = [call["tool_name"] for call in calls]
    answer_text = " ".join(
        (
            result.entitlement_value,
            result.rule_cited,
            result.explanation,
        )
    ).lower()
    answer_criteria = [
        {
            "criterion": criterion,
            "satisfied": criterion.lower() in answer_text,
        }
        for criterion in case.get("deterministic_pass_criteria", [])
    ]
    next_required = 0
    for tool_name in observed:
        if (
            next_required < len(REQUIRED_TOOL_SEQUENCE)
            and tool_name == REQUIRED_TOOL_SEQUENCE[next_required]
        ):
            next_required += 1
    sequence_valid = next_required == len(REQUIRED_TOOL_SEQUENCE)
    extra_calls = [name for name in observed if name not in REQUIRED_TOOL_SEQUENCE]
    duplicates = sorted(name for name, count in Counter(observed).items() if count > 1)

    if result.termination_reason != "SUCCESS":
        failure_mode = "execution_failure"
    elif not sequence_valid:
        failure_mode = "required_tool_sequence"
    elif not result.passed:
        failure_mode = "answer_quality"
    elif extra_calls or duplicates:
        failure_mode = "redundant_tool_calls"
    else:
        failure_mode = None

    return {
        "case_id": case["case_id"],
        "employee_id": case["employee_id"],
        "expected_value": case["expected_value"],
        "required_tool_sequence": list(REQUIRED_TOOL_SEQUENCE),
        "observed_tool_sequence": observed,
        "required_tool_sequence_valid": sequence_valid,
        "extra_tool_calls": extra_calls,
        "duplicate_tool_names": duplicates,
        "termination_reason": result.termination_reason,
        "passed": bool(result.passed),
        "answer_criteria": answer_criteria,
        "unmet_answer_criteria": [
            item["criterion"] for item in answer_criteria if not item["satisfied"]
        ],
        "failure_mode": failure_mode,
        "iterations": result.iterations,
        "tool_call_count": len(calls),
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "token_source": result.token_source,
        "latency_ms": result.latency_ms,
        "token_cost_proxy_usd": result.cost_usd,
        "answer": {
            "entitlement_value": result.entitlement_value,
            "rule_cited": result.rule_cited,
            "explanation": result.explanation,
        },
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    latencies = [item["latency_ms"] for item in results]
    failure_counts = Counter(
        item["failure_mode"] for item in results if item["failure_mode"]
    )
    unmet_criteria = Counter(
        criterion
        for item in results
        for criterion in item.get("unmet_answer_criteria", [])
    )
    termination_counts = Counter(item["termination_reason"] for item in results)
    passed = sum(item["passed"] for item in results)
    valid_sequences = sum(item["required_tool_sequence_valid"] for item in results)
    return {
        "case_count": count,
        "answer_pass_count": passed,
        "answer_pass_rate_pct": round(100 * passed / count, 2) if count else 0.0,
        "required_sequence_valid_count": valid_sequences,
        "required_sequence_valid_rate_pct": (
            round(100 * valid_sequences / count, 2) if count else 0.0
        ),
        "total_tool_calls": sum(item["tool_call_count"] for item in results),
        "extra_tool_calls": sum(len(item["extra_tool_calls"]) for item in results),
        "duplicate_tool_case_count": sum(
            bool(item["duplicate_tool_names"]) for item in results
        ),
        "total_tokens": sum(item["total_tokens"] for item in results),
        "token_cost_proxy_usd": round(
            sum(item["token_cost_proxy_usd"] for item in results), 8
        ),
        "p50_latency_ms": round(statistics.median(latencies), 3) if latencies else 0.0,
        "failure_mode_counts": dict(sorted(failure_counts.items())),
        "unmet_answer_criterion_counts": dict(sorted(unmet_criteria.items())),
        "termination_reason_counts": dict(sorted(termination_counts.items())),
    }


def run_evaluation(phase: str, output_path: Path) -> dict[str, Any]:
    if CHAT_BACKEND != "groq":
        raise RuntimeError(
            "Week 8 live trajectory evaluation requires CHAT_BACKEND=groq."
        )
    if not chat_configured():
        raise RuntimeError(
            "GROQ_API_KEY is not configured. Add a rotated key to your ignored .env."
        )
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing evidence: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    partial_path = output_path.with_suffix(output_path.suffix + ".partial")
    if partial_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite incomplete evidence: {partial_path}"
        )
    try:
        for case in cases:
            result = run_agent_case(
                case_id=case["case_id"],
                employee_id=case["employee_id"],
                question=case["question"],
                deterministic_pass_criteria=case.get("deterministic_pass_criteria"),
                model=GROQ_MODEL,
                use_live_llm=True,
            )
            results.append(evaluate_trajectory(case, result))
            partial_path.write_text(
                json.dumps(
                    {"phase": phase, "completed_results": results},
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        evidence = {
            "phase": phase,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": CHAT_BACKEND,
            "model": GROQ_MODEL,
            "ground_truth_path": str(CASES_PATH.relative_to(ROOT)),
            "required_tool_sequence": list(REQUIRED_TOOL_SEQUENCE),
            "summary": summarize(results),
            "results": results,
        }
        partial_path.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        partial_path.replace(output_path)
        return evidence
    except Exception:
        raise


def compare_evidence(baseline_path: Path, mitigation_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    mitigation = json.loads(mitigation_path.read_text(encoding="utf-8"))
    if baseline.get("phase") != "baseline":
        raise ValueError("First evidence file must be a baseline run.")
    if mitigation.get("phase") != "mitigation":
        raise ValueError("Second evidence file must be a mitigation run.")
    before, after = baseline["summary"], mitigation["summary"]
    return {
        "baseline_run": str(baseline_path),
        "mitigation_run": str(mitigation_path),
        "answer_pass_rate_delta_pct": round(
            after["answer_pass_rate_pct"] - before["answer_pass_rate_pct"], 2
        ),
        "required_sequence_valid_rate_delta_pct": round(
            after["required_sequence_valid_rate_pct"]
            - before["required_sequence_valid_rate_pct"],
            2,
        ),
        "p50_latency_delta_ms": round(
            after["p50_latency_ms"] - before["p50_latency_ms"], 3
        ),
        "token_delta": after["total_tokens"] - before["total_tokens"],
        "token_cost_proxy_delta_usd": round(
            after["token_cost_proxy_usd"] - before["token_cost_proxy_usd"], 8
        ),
        "answer_pass_rate_non_regression": (
            after["answer_pass_rate_pct"] >= before["answer_pass_rate_pct"]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run all ten live Agent cases.")
    run_parser.add_argument("phase", choices=("baseline", "mitigation"))
    run_parser.add_argument("--output", type=Path)
    compare_parser = subparsers.add_parser(
        "compare", help="Compare baseline and post-mitigation evidence."
    )
    compare_parser.add_argument("baseline", type=Path)
    compare_parser.add_argument("mitigation", type=Path)
    args = parser.parse_args()

    if args.command == "run":
        output = args.output or Path(__file__).with_name(
            f"trajectory_{args.phase}.json"
        )
        evidence = run_evaluation(args.phase, output)
        print(json.dumps(evidence["summary"], indent=2))
        print(f"Evidence saved to {output}")
    else:
        print(json.dumps(compare_evidence(args.baseline, args.mitigation), indent=2))


if __name__ == "__main__":
    main()
