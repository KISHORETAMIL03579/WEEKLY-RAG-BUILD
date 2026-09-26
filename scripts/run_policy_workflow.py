#!/usr/bin/env python3
# scripts/run_policy_workflow.py — CLI runner for the HR Policy Fixed Deterministic Workflow benchmark
"""
Usage:
    python scripts/run_policy_workflow.py [--top-k 5]

Runs all 10 frozen benchmark cases through the Fixed 3-Step Deterministic Workflow and
prints per-case results plus a summary scorecard using real time.perf_counter()
latency. The workflow has no LLM call; tokens are accounted as fixed-cost proxy estimates
and are explicitly marked as such (not real Ollama token counts).

DO NOT fabricate latency, token counts, or pass results.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.services.policy_workflow import run_workflow_case


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HR Policy Fixed Workflow Benchmark Runner"
    )
    parser.add_argument(
        "--top-k", type=int, default=5, help="Top-K handbook retrieval (default: 5)"
    )
    parser.add_argument(
        "--cases",
        type=str,
        default=str(BASE_DIR / "benchmarks" / "policy_execution" / "cases.json"),
        help="Path to benchmark cases JSON file",
    )
    args = parser.parse_args()

    cases_file = Path(args.cases)
    if not cases_file.exists():
        print(f"ERROR: cases file not found: {cases_file}", file=sys.stderr)
        sys.exit(1)

    with open(cases_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print("=" * 80)
    print("HR POLICY WORKFLOW BENCHMARK: Fixed 3-Step Deterministic Workflow")
    print("=" * 80)
    print(
        f"  Configuration: top_k={args.top_k}  temperature=N/A (no LLM)  model=N/A (deterministic)"
    )
    print(
        f"  Token accounting: proxy estimates (no Ollama call — fixed-path synthesis)"
    )
    print(f"  Cases loaded: {len(cases)} from {cases_file}")
    print("=" * 80)

    results = []
    header = f"{'Case':<10}{'Emp':<8}{'Pass':<6}{'Iter':<6}{'Lat(ms)':<10}{'P-Tok':<8}{'C-Tok':<8}{'Tot-Tok':<10}{'Cost($)':<12}{'Status'}"
    print(header)
    print("-" * 80)

    overall_start = time.perf_counter()

    for c in cases:
        cid = c["case_id"]
        empid = c["employee_id"]
        q = c["question"]
        crit = c.get("deterministic_pass_criteria", [])

        result = run_workflow_case(
            case_id=cid,
            employee_id=empid,
            question=q,
            deterministic_pass_criteria=crit,
            top_k=args.top_k,
        )
        results.append(result)

        pass_str = "PASS" if result.passed else "FAIL"
        print(
            f"{cid:<10}{empid:<8}{pass_str:<6}{result.iterations:<6}"
            f"{result.latency_ms:<10.3f}{result.prompt_tokens:<8}{result.completion_tokens:<8}"
            f"{result.total_tokens:<10}{result.cost_usd:<12.6f}{result.termination_reason}"
        )

    overall_elapsed_ms = (time.perf_counter() - overall_start) * 1000
    print("-" * 80)

    # Summary statistics
    n = len(results)
    passed = sum(1 for r in results if r.passed)
    lats = sorted(r.latency_ms for r in results)
    p50 = lats[n // 2] if n else 0.0
    p95 = lats[int(n * 0.95)] if n else 0.0
    total_tokens = sum(r.total_tokens for r in results)
    total_cost = sum(r.cost_usd for r in results)
    cost_per_q = total_cost / n if n else 0.0

    print(f"\n{'SUMMARY':=<80}")
    print(f"  Pass Rate      : {passed}/{n} = {(passed/n*100):.1f}%")
    print(f"  p50 Latency    : {p50:.3f} ms  (real time.perf_counter())")
    print(f"  p95 Latency    : {p95:.3f} ms")
    print(
        f"  Total Tokens   : {total_tokens:,} (proxy estimates — no LLM call in workflow)"
    )
    print(
        f"  Cost / Question: ${cost_per_q:.6f}  (token-cost proxy rate: $0.50/1M tokens)"
    )
    print(f"  Total Wall Time: {overall_elapsed_ms:.1f} ms")
    print("=" * 80)
    print(
        "\nWorkflow run complete. Note: token counts are fixed-path proxy estimates, not Ollama metadata."
    )


if __name__ == "__main__":
    main()
