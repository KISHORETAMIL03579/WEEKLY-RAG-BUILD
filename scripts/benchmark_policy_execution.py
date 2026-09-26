# scripts/benchmark_policy_execution.py — Live HR Policy Execution Benchmark Runner
import csv
import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.services.policy_agent import run_agent_case
from backend.services.policy_workflow import run_workflow_case


def run_benchmark():
    cases_file = BASE_DIR / "benchmarks" / "policy_execution" / "cases.json"
    if not cases_file.exists():
        print(f"Error: Cases file not found at {cases_file}", flush=True)
        sys.exit(1)

    with open(cases_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print("=" * 80, flush=True)
    print(
        "HR POLICY BENCHMARK: DYNAMIC REACT AGENT vs 3-STEP DETERMINISTIC WORKFLOW",
        flush=True,
    )
    print("=" * 80, flush=True)
    print(f"Loaded {len(cases)} benchmark cases from {cases_file}\n", flush=True)

    agent_results = []
    workflow_results = []

    print("-" * 80, flush=True)
    print(
        f"{'Case ID':<10} | {'Emp ID':<8} | {'Agent Pass':<10} | {'Agent Lat(ms)':<14} | {'Agent Tokens (P/C/Tot)':<24} | {'WF Lat(ms)':<10}",
        flush=True,
    )
    print("-" * 80, flush=True)

    for c in cases:
        cid = c["case_id"]
        empid = c["employee_id"]
        q = c["question"]
        crit = c.get("deterministic_pass_criteria", [])

        # 1. Run Dynamic ReAct Agent
        a_res = run_agent_case(
            case_id=cid,
            employee_id=empid,
            question=q,
            deterministic_pass_criteria=crit,
            top_k=5,
            temperature=0.3,
            model="llama3.1:8b",
        )
        agent_results.append(a_res)

        # 2. Run Deterministic Workflow
        w_res = run_workflow_case(
            case_id=cid,
            employee_id=empid,
            question=q,
            deterministic_pass_criteria=crit,
            top_k=5,
        )
        workflow_results.append(w_res)

        tokens_str = (
            f"{a_res.prompt_tokens}/{a_res.completion_tokens}/{a_res.total_tokens}"
        )
        pass_str = "PASS" if a_res.passed else "FAIL"
        print(
            f"{cid:<10} | {empid:<8} | {pass_str:<10} | {a_res.latency_ms:<14.2f} | {tokens_str:<24} | {w_res.latency_ms:<10.2f}",
            flush=True,
        )

    print("-" * 80, flush=True)

    # Calculate Summary Statistics
    def compute_stats(results, name=""):
        n = len(results)
        passed = sum(1 for r in results if r.passed)
        lats = sorted([r.latency_ms for r in results])
        p50 = lats[int(n * 0.5)] if n else 0.0
        p95 = lats[int(n * 0.95)] if n else 0.0
        p99 = lats[-1] if n else 0.0
        total_tokens = sum(r.total_tokens for r in results)
        total_cost = sum(r.cost_usd for r in results)
        cost_per_q = total_cost / n if n else 0.0
        pass_rate = (passed / n) * 100 if n else 0.0

        return {
            "name": name,
            "pass_rate": pass_rate,
            "passed": passed,
            "total": n,
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
            "total_tokens": total_tokens,
            "cost_per_q": cost_per_q,
        }

    a_stats = compute_stats(agent_results, "Dynamic ReAct Agent")
    w_stats = compute_stats(workflow_results, "Deterministic Workflow")

    print("\n" + "=" * 80, flush=True)
    print("BENCHMARK EXECUTION SUMMARY (10 CASES)", flush=True)
    print("=" * 80, flush=True)
    print(
        f"{'Metric':<30} | {'Dynamic ReAct Agent':<22} | {'Deterministic Workflow':<22}",
        flush=True,
    )
    print("-" * 80, flush=True)
    print(
        f"{'Pass Rate':<30} | {a_stats['pass_rate']:>18.1f}% | {w_stats['pass_rate']:>18.1f}%",
        flush=True,
    )
    print(
        f"{'Passed Cases':<30} | {a_stats['passed']:>18}/{a_stats['total']} | {w_stats['passed']:>18}/{w_stats['total']}",
        flush=True,
    )
    print(
        f"{'p50 Latency (ms)':<30} | {a_stats['p50_ms']:>18.3f} | {w_stats['p50_ms']:>18.3f}",
        flush=True,
    )
    print(
        f"{'p95 Latency (ms)':<30} | {a_stats['p95_ms']:>18.3f} | {w_stats['p95_ms']:>18.3f}",
        flush=True,
    )
    print(
        f"{'p99 Latency (ms)':<30} | {a_stats['p99_ms']:>18.3f} | {w_stats['p99_ms']:>18.3f}",
        flush=True,
    )
    print(
        f"{'Total Tokens Consumed':<30} | {a_stats['total_tokens']:>18,d} | {w_stats['total_tokens']:>18,d}",
        flush=True,
    )
    print(
        f"{'Cost per Question ($)':<30} | ${a_stats['cost_per_q']:>17.6f} | ${w_stats['cost_per_q']:>17.6f}",
        flush=True,
    )
    print("=" * 80, flush=True)

    speedup = a_stats["p50_ms"] / max(0.001, w_stats["p50_ms"])
    print(f"Speedup Factor (Workflow vs Agent): {speedup:.1f}x faster\n", flush=True)

    # Persist Results to CSV
    csv_file = BASE_DIR / "benchmarks" / "policy_execution" / "results.csv"
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "case_id",
                "employee_id",
                "question",
                "agent_entitlement",
                "agent_rule",
                "agent_passed",
                "agent_latency_ms",
                "agent_tokens",
                "agent_cost",
                "agent_status",
                "workflow_entitlement",
                "workflow_rule",
                "workflow_passed",
                "workflow_latency_ms",
                "workflow_tokens",
                "workflow_cost",
                "workflow_status",
            ]
        )
        for a, w in zip(agent_results, workflow_results):
            writer.writerow(
                [
                    a.case_id,
                    a.employee_id,
                    a.question,
                    a.entitlement_value,
                    a.rule_cited,
                    a.passed,
                    a.latency_ms,
                    a.total_tokens,
                    a.cost_usd,
                    a.termination_reason,
                    w.entitlement_value,
                    w.rule_cited,
                    w.passed,
                    w.latency_ms,
                    w.total_tokens,
                    w.cost_usd,
                    w.termination_reason,
                ]
            )

    print(f"Saved full benchmark results to: {csv_file}", flush=True)


if __name__ == "__main__":
    run_benchmark()
