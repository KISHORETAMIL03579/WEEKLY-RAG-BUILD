"""Week 8 trajectory evaluation from the command line (same scoring as the API).

    # 1. put the documents in a session (once)
    python scripts/index_documents.py --session-id policy-eval WEEKLY_RAG_TASK/HRPolicy.pdf backend/data/samples/employee_records.md
    # 2. baseline, then (after applying exactly ONE mitigation) the mitigation run
    python -m benchmarks.policy_execution.trajectory_eval run baseline   --session-id policy-eval --suite all
    python -m benchmarks.policy_execution.trajectory_eval run mitigation --session-id policy-eval --suite all --note "sharper get_jurisdiction_rules description"
    # 3. before -> after per failure mode, price paid, regressions
    python -m benchmarks.policy_execution.trajectory_eval compare benchmarks/policy_execution/trajectory_baseline.json benchmarks/policy_execution/trajectory_mitigation.json
    # Re-grade an OLD evidence file (answers only) with the fixed scorer, no model calls
    python -m benchmarks.policy_execution.trajectory_eval rescore benchmarks/policy_execution/trajectory_mitigation.json

``run`` calls Groq once per case (the agent loop), so it spends API quota. It refuses to
overwrite existing evidence; use ``--output`` for a new path.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.config import CHAT_BACKEND, GROQ_MODEL  # noqa: E402
from backend.services import policy_scoring, policy_trajectory  # noqa: E402
from backend.services.policy_agent import check_model_provider_available, run_agent_case  # noqa: E402
from backend.services.policy_benchmark_runner import _criteria, load_suite  # noqa: E402
from backend.services.policy_retrieval import PolicyContext  # noqa: E402


def run_evaluation(phase: str, output: Path, session_id: str, suite: str, model: str, note: str | None) -> dict[str, Any]:
    if not check_model_provider_available():
        raise RuntimeError(f"Needs CHAT_BACKEND=groq and GROQ_API_KEY (CHAT_BACKEND={CHAT_BACKEND}).")
    if output.exists() or output.with_suffix(output.suffix + ".partial").exists():
        raise FileExistsError(f"Refusing to overwrite existing evidence: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    context = PolicyContext(session_id)
    cases = load_suite(suite)
    expected = policy_trajectory.load_expected_trajectories()
    partial = output.with_suffix(output.suffix + ".partial")
    records: list[dict[str, Any]] = []
    for case in cases:
        result = run_agent_case(
            case_id=case["case_id"],
            employee_id=case["employee_id"],
            question=case["question"],
            deterministic_pass_criteria=_criteria(case),
            criteria_aliases=case.get("criteria_aliases"),
            forbidden_phrases=case.get("forbidden_phrases"),
            headline_criteria=case.get("headline_criteria"),
            model=model,
            context=context,
        )
        records.append(policy_trajectory.evaluate_case(case, result, expected[case["case_id"]]))
        partial.write_text(json.dumps({"phase": phase, "completed": records}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{case['case_id']}: {result.termination_reason} passed={result.passed} path={records[-1]['observed_sequence']}")
    evidence = {
        "phase": phase,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": CHAT_BACKEND,
        "model": model,
        "suite": suite,
        "note": note,
        "summary": policy_trajectory.summarize(records),
        "cases": records,
    }
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    partial.unlink(missing_ok=True)
    return evidence


def rescore(path: Path) -> dict[str, Any]:
    """Re-grade recorded answers with the current scorer: literal vs normalised pass rate."""
    evidence = json.loads(path.read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in load_suite("canonical")}
    rows = []
    for item in evidence.get("results") or evidence.get("cases", []):
        case = cases.get(item["case_id"])
        answer = item.get("answer")
        if not case or not answer or item.get("termination_reason") != "SUCCESS":
            continue
        scored = policy_scoring.score_criteria(_criteria(case), answer, case.get("criteria_aliases"), case.get("forbidden_phrases"), case.get("headline_criteria"))
        rows.append(
            {
                "case_id": item["case_id"],
                "recorded_passed": item.get("passed"),
                "strict_passed": scored["strict_passed"],
                "passed": scored["passed"],
                "unmet": scored["unmet"],
            }
        )
    count = len(rows) or 1
    return {
        "source": str(path),
        "completed_cases": len(rows),
        "strict_pass_rate_pct": round(100 * sum(r["strict_passed"] for r in rows) / count, 1),
        "normalised_pass_rate_pct": round(100 * sum(r["passed"] for r in rows) / count, 1),
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the suite through the agent (calls Groq).")
    run.add_argument("phase", choices=("baseline", "mitigation"))
    run.add_argument("--session-id", required=True, help="Session indexed with scripts/index_documents.py")
    run.add_argument("--suite", default="all", choices=("canonical", "branching", "all"))
    run.add_argument("--model", default=GROQ_MODEL)
    run.add_argument("--note", help="What the mitigation changed (one change only).")
    run.add_argument("--output", type=Path)
    cmp = sub.add_parser("compare", help="Before -> after per failure mode, price and regressions.")
    cmp.add_argument("baseline", type=Path)
    cmp.add_argument("mitigation", type=Path)
    rs = sub.add_parser("rescore", help="Re-grade recorded answers with the fixed scorer (no model calls).")
    rs.add_argument("evidence", type=Path)
    args = parser.parse_args()

    if args.command == "run":
        output = args.output or Path(__file__).with_name(f"trajectory_{args.phase}.json")
        evidence = run_evaluation(args.phase, output, args.session_id, args.suite, args.model, args.note)
        print(json.dumps(evidence["summary"], indent=2))
        print(f"Evidence saved to {output}")
    elif args.command == "compare":
        before = json.loads(args.baseline.read_text(encoding="utf-8"))
        after = json.loads(args.mitigation.read_text(encoding="utf-8"))
        if before.get("phase") != "baseline" or after.get("phase") != "mitigation":
            raise SystemExit("compare needs a baseline file first and a mitigation file second")
        print(json.dumps(policy_trajectory.compare(before["summary"], after["summary"]), indent=2))
    else:
        print(json.dumps(rescore(args.evidence), indent=2))


if __name__ == "__main__":
    main()
