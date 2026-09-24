#!/usr/bin/env python
# scripts/run_policy_workflow.py — CLI Runner for HR Policy Deterministic Workflow
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.services.policy_workflow import run_workflow_case


def main():
    parser = argparse.ArgumentParser(description="Run the Fixed 3-Step Deterministic HR Policy Workflow")
    parser.add_argument("--employee-id", type=str, default=None, help="Employee ID (e.g. EMP001)")
    parser.add_argument("--question", type=str, default=None, help="Custom policy question")
    parser.add_argument("--cases-file", type=str, default=str(ROOT_DIR / "benchmarks" / "policy_execution" / "cases.json"))
    args = parser.parse_args()

    if args.employee_id and args.question:
        print(f"\n[WORKFLOW] Running single case for {args.employee_id}: '{args.question}'")
        res = run_workflow_case("custom_case", args.employee_id, args.question)
        print(json.dumps(res.model_dump(), indent=2))
        return

    cases_path = Path(args.cases_file)
    if not cases_path.exists():
        print(f"Error: Cases file not found at {cases_path}")
        sys.exit(1)

    with open(cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"\n{'='*75}")
    print(f" HR POLICY DETERMINISTIC WORKFLOW: BENCHMARK EXECUTION ({len(cases)} CASES)")
    print(f" Pipeline: (1) Fetch Employee -> (2) Branch on Attributes -> (3) Fetch Handbook Rule -> (4) Synthesize")
    print(f"{'='*75}\n")

    results = []
    for c in cases:
        cid = c["case_id"]
        empid = c["employee_id"]
        q = c["question"]
        crit = c.get("deterministic_pass_criteria", [])

        res = run_workflow_case(cid, empid, q, deterministic_pass_criteria=crit)
        results.append(res)
        status_icon = "PASS" if res.passed else "FAIL"
        print(f"[{status_icon}] {cid} ({empid}): {res.entitlement_value[:60]}... | Latency: {res.latency_ms:.2f}ms | Tokens: {res.total_tokens} | Cost: ${res.cost_usd:.6f}")

    passed_count = sum(1 for r in results if r.passed)
    pass_rate = (passed_count / len(results)) * 100
    avg_latency = sum(r.latency_ms for r in results) / len(results)
    total_tokens = sum(r.total_tokens for r in results)
    total_cost = sum(r.cost_usd for r in results)

    print(f"\n{'-'*75}")
    print(f" WORKFLOW SUMMARY: {passed_count}/{len(results)} Passed ({pass_rate:.1f}%) | Avg Latency: {avg_latency:.2f}ms | Total Tokens: {total_tokens} | Total Cost: ${total_cost:.6f}")
    print(f"{'-'*75}\n")


if __name__ == "__main__":
    main()
