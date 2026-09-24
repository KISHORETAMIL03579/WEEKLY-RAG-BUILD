#!/usr/bin/env python3
# scripts/run_week7_agent.py — Single-Command Runner for Week 7 ReAct Agent
import json
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.services.week7_agent import run_agent_case


def main():
    cases_file = BASE_DIR / "week7" / "race_cases_10.json"
    if not cases_file.exists():
        print(f"Error: {cases_file} not found.", file=sys.stderr)
        sys.exit(1)

    with open(cases_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"============================================================")
    print(f"   RUNNING WEEK 7 HR AGENT (DYNAMIC REACT LOOP - 10 CASES)")
    print(f"============================================================\n")

    results = []
    passed_count = 0
    total_tokens = 0
    total_cost = 0.0
    latencies = []

    for c in cases:
        cid = c["case_id"]
        empid = c["employee_id"]
        q = c["question"]
        crit = c.get("deterministic_pass_criteria", [])

        res = run_agent_case(cid, empid, q, deterministic_pass_criteria=crit)
        results.append(res)

        if res.passed:
            passed_count += 1
        total_tokens += res.total_tokens
        total_cost += res.cost_usd
        latencies.append(res.latency_ms)

        status_str = "PASS" if res.passed else "FAIL"
        print(f"[{cid}] ({empid}) -> {status_str} | Iterations: {res.iterations} | Latency: {res.latency_ms:.1f}ms | Tokens: {res.total_tokens}")
        print(f"    Rule: {res.rule_cited}")
        print(f"    Entitlement: {res.entitlement_value}")
        print(f"    Explanation: {res.explanation[:120]}...")
        print("-" * 60)

    latencies.sort()
    p50_latency = latencies[len(latencies) // 2] if latencies else 0.0
    pass_rate = (passed_count / len(cases)) * 100 if cases else 0.0
    avg_cost = total_cost / len(cases) if cases else 0.0

    print("\n============================================================")
    print(f"AGENT SUMMARY (10 CASES):")
    print(f"  Pass Rate       : {pass_rate:.1f}% ({passed_count}/{len(cases)})")
    print(f"  p50 Latency     : {p50_latency:.1f} ms")
    print(f"  Total Tokens    : {total_tokens}")
    print(f"  Cost / Question : ${avg_cost:.6f} (proxy rate $0.50/1M)")
    print(f"============================================================\n")


if __name__ == "__main__":
    main()
