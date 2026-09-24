#!/usr/bin/env python
# scripts/benchmark_policy_execution.py — Benchmark comparison script for Agent vs Workflow
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.services.policy_agent import run_agent_case
from backend.services.policy_workflow import run_workflow_case


def main():
    cases_file = ROOT_DIR / "benchmarks" / "policy_execution" / "cases.json"
    results_csv = ROOT_DIR / "benchmarks" / "policy_execution" / "results.csv"

    if not cases_file.exists():
        print(f"Error: Cases file not found at {cases_file}")
        sys.exit(1)

    with open(cases_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"\n{'='*80}")
    print(f" RUNNING HR POLICY BENCHMARK (AGENT vs DETERMINISTIC WORKFLOW) — {len(cases)} CASES")
    print(f"{'='*80}\n")

    csv_rows = []

    agent_passed = 0
    wf_passed = 0
    agent_lats = []
    wf_lats = []
    agent_tokens = 0
    wf_tokens = 0
    agent_cost = 0.0
    wf_cost = 0.0

    for c in cases:
        cid = c["case_id"]
        empid = c["employee_id"]
        q = c["question"]
        crit = c.get("deterministic_pass_criteria", [])

        # Run ReAct Agent
        a_res = run_agent_case(cid, empid, q, deterministic_pass_criteria=crit)
        # Run Deterministic Workflow
        w_res = run_workflow_case(cid, empid, q, deterministic_pass_criteria=crit)

        if a_res.passed:
            agent_passed += 1
        if w_res.passed:
            wf_passed += 1

        agent_lats.append(a_res.latency_ms)
        wf_lats.append(w_res.latency_ms)
        agent_tokens += a_res.total_tokens
        wf_tokens += w_res.total_tokens
        agent_cost += a_res.cost_usd
        wf_cost += w_res.cost_usd

        # CSV row
        csv_rows.append({
            "case_id": cid,
            "employee_id": empid,
            "question": q,
            "agent_passed": a_res.passed,
            "agent_latency_ms": a_res.latency_ms,
            "agent_tokens": a_res.total_tokens,
            "agent_cost_usd": a_res.cost_usd,
            "agent_iterations": a_res.iterations,
            "agent_termination": a_res.termination_reason,
            "workflow_passed": w_res.passed,
            "workflow_latency_ms": w_res.latency_ms,
            "workflow_tokens": w_res.total_tokens,
            "workflow_cost_usd": w_res.cost_usd,
            "workflow_iterations": w_res.iterations,
        })

        print(f"Case {cid} ({empid}):")
        print(f"  ├─ Agent   : {'PASS' if a_res.passed else 'FAIL'} | Latency={a_res.latency_ms:6.2f}ms | Tokens={a_res.total_tokens:5d} | Cost=${a_res.cost_usd:.6f}")
        print(f"  └─ Workflow: {'PASS' if w_res.passed else 'FAIL'} | Latency={w_res.latency_ms:6.2f}ms | Tokens={w_res.total_tokens:5d} | Cost=${w_res.cost_usd:.6f}")

    # Write CSV
    fieldnames = [
        "case_id", "employee_id", "question",
        "agent_passed", "agent_latency_ms", "agent_tokens", "agent_cost_usd", "agent_iterations", "agent_termination",
        "workflow_passed", "workflow_latency_ms", "workflow_tokens", "workflow_cost_usd", "workflow_iterations"
    ]
    results_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(results_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    n = len(cases)
    agent_p50 = sorted(agent_lats)[n // 2]
    wf_p50 = sorted(wf_lats)[n // 2]

    print(f"\n{'='*80}")
    print(" BENCHMARK SCORECARD SUMMARY")
    print(f"{'='*80}")
    print(f"{'Metric':<30} | {'ReAct Agent':<20} | {'Deterministic Workflow':<25}")
    print(f"{'-'*30}-+-{'-'*20}-+-{'-'*25}")
    print(f"{'Pass Rate':<30} | {agent_passed}/{n} ({(agent_passed/n)*100:.1f}%)        | {wf_passed}/{n} ({(wf_passed/n)*100:.1f}%)")
    print(f"{'p50 Latency (ms)':<30} | {agent_p50:<20.2f} | {wf_p50:<25.2f}")
    print(f"{'Total Tokens':<30} | {agent_tokens:<20d} | {wf_tokens:<25d}")
    print(f"{'Cost per Question ($)':<30} | ${agent_cost/n:<19.6f} | ${wf_cost/n:<24.6f}")
    print(f"{'Total Cost ($)':<30} | ${agent_cost:<19.6f} | ${wf_cost:<24.6f}")
    print(f"{'='*80}\n")
    print(f"Results saved to: {results_csv}")


if __name__ == "__main__":
    main()
