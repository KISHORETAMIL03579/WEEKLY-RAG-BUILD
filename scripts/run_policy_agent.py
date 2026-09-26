#!/usr/bin/env python3
# scripts/run_policy_agent.py — CLI runner for the HR Policy ReAct Agent benchmark
"""
Usage:
    python scripts/run_policy_agent.py [--top-k 5] [--temperature 0.3] [--model llama3.1:8b]

Runs all 10 frozen benchmark cases through the Dynamic ReAct Policy Agent and
prints per-case results plus a summary scorecard using real time.perf_counter()
latency. Token counts come from actual Ollama metadata where available, or are
explicitly annotated as proxy estimates where Ollama is unavailable.

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

from backend.services.policy_agent import run_agent_case, check_ollama_available


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HR Policy ReAct Agent Benchmark Runner"
    )
    parser.add_argument(
        "--top-k", type=int, default=5, help="Top-K handbook retrieval (default: 5)"
    )
    parser.add_argument(
        "--temperature", type=float, default=0.3, help="LLM temperature (default: 0.3)"
    )
    parser.add_argument(
        "--model", type=str, default="llama3.1:8b", help="Ollama model name"
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

    ollama_live = check_ollama_available()
    token_note = (
        "(live Ollama tokens)"
        if ollama_live
        else "(proxy token estimates — Ollama unavailable)"
    )

    print("=" * 80)
    print("HR POLICY AGENT BENCHMARK: Dynamic ReAct Agent")
    print("=" * 80)
    print(
        f"  Configuration: top_k={args.top_k}  temperature={args.temperature}  model={args.model}"
    )
    print(f"  Ollama available: {ollama_live}")
    print(f"  Token accounting: {token_note}")
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

        result = run_agent_case(
            case_id=cid,
            employee_id=empid,
            question=q,
            deterministic_pass_criteria=crit,
            top_k=args.top_k,
            temperature=args.temperature,
            model=args.model,
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
    print(f"  Total Tokens   : {total_tokens:,} {token_note}")
    print(
        f"  Cost / Question: ${cost_per_q:.6f}  (token-cost proxy rate: $0.50/1M tokens)"
    )
    print(f"  Total Wall Time: {overall_elapsed_ms:.1f} ms")
    print("=" * 80)
    print(f"\nAgent run complete. Token accounting: {token_note}")


if __name__ == "__main__":
    main()
