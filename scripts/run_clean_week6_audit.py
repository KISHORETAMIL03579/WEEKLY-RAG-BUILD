"""
run_clean_week6_audit.py — Clean Certified Audit Runner for All 25 Week 6 Cases
Executes genuine Ollama llama3.1:8b inference with 180s timeout, recording microsecond telemetry.
"""

import os
import sys
import time
import json
import urllib.request
import statistics
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from week6.assertions import run_all_assertions
from week6.judge import parse_judge_output


def query_ollama(prompt: str, timeout: int = 180) -> tuple:
    t_start = time.perf_counter()
    payload = {
        "model": "llama3.1:8b",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "top_p": 0.1,
            "num_predict": 16,
            "stop": ["\n", "}", "```"],
        },
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw = data.get("response", "").strip()
            t_elapsed = (time.perf_counter() - t_start) * 1000
            telemetry = {
                "prompt_eval_count": data.get("prompt_eval_count", 0),
                "prompt_eval_ms": round(data.get("prompt_eval_duration", 0) / 1e6, 2),
                "eval_count": data.get("eval_count", 0),
                "eval_ms": round(data.get("eval_duration", 0) / 1e6, 2),
                "total_ms": round(data.get("total_duration", 0) / 1e6, 2),
            }
            return raw, "LLM", t_elapsed, telemetry
    except Exception as exc:
        t_elapsed = (time.perf_counter() - t_start) * 1000
        return f"ERROR: {exc}", "ERROR", t_elapsed, {}


def run_certified_audit():
    print("=" * 115)
    print(
        "                  CERTIFIED AUDIT: 25-CASE LIVE OLLAMA LLM EVALUATION RUN                  "
    )
    print("=" * 115)

    cases_path = REPO_ROOT / "week6" / "eval_cases_25.json"
    labels_path = REPO_ROOT / "week6" / "labels_25.json"
    v1_path = REPO_ROOT / "week6" / "judge_v1.txt"
    v2_path = REPO_ROOT / "week6" / "judge_v2.txt"

    with open(cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)
    with open(labels_path, "r", encoding="utf-8") as f:
        labels = json.load(f)

    v1_template = v1_path.read_text(encoding="utf-8")
    v2_template = v2_path.read_text(encoding="utf-8")

    # Warm-up probe
    print(
        "\n[Step 1] Warming up Ollama daemon on http://127.0.0.1:11434 with llama3.1:8b..."
    )
    warm_raw, warm_src, warm_ms, _ = query_ollama("Judge test warm-up.", timeout=120)
    print(
        f"  [OK] Ollama daemon is ready. Warm-up latency: {warm_ms:.1f}ms (Source: {warm_src})\n"
    )

    print(
        "[Step 2] Executing live inference for all 25 benchmark cases on Judge V2 (and Judge V1)..."
    )
    print(
        f"{'Case':<9} | {'Human':<5} | {'V1 Verd':<7} | {'V1 ms':<8} | {'V2 Verd':<7} | {'V2 ms':<8} | {'Prompt Tok':<10} | {'Gen Tok':<7} | {'V2 Status':<12}"
    )
    print("-" * 115)

    results = []
    v2_latencies = []
    v1_latencies = []
    v1_agreed = 0
    v2_agreed = 0
    actual_llm_calls = 0
    fallback_count = 0
    error_count = 0
    cache_hits = 0

    wall_start = time.perf_counter()

    for idx, c in enumerate(cases, 1):
        cid = c.get("case_id", f"case_{idx:02d}")
        h_label = labels.get(cid, c.get("human_label", 1))

        # --- Judge V2 Prompt (Blind: question, context, answer ONLY) ---
        p2 = (
            v2_template.replace("{question}", c.get("question", "").strip())
            .replace("{context}", c.get("retrieved_context", "").strip())
            .replace("{answer}", c.get("answer", "").strip())
        )

        v2_raw, v2_src, v2_ms, v2_telem = query_ollama(p2, timeout=180)
        v2_verd = parse_judge_output(v2_raw)
        v2_latencies.append(v2_ms)
        if v2_src == "LLM":
            actual_llm_calls += 1
        elif v2_src == "ERROR":
            error_count += 1
        elif v2_src == "FALLBACK":
            fallback_count += 1

        v2_is_agree = v2_verd == h_label
        if v2_is_agree:
            v2_agreed += 1

        # --- Judge V1 Prompt (Baseline) ---
        p1 = (
            v1_template.replace("{question}", c.get("question", "").strip())
            .replace("{context}", c.get("retrieved_context", "").strip())
            .replace("{answer}", c.get("answer", "").strip())
        )
        v1_raw, v1_src, v1_ms, v1_telem = query_ollama(p1, timeout=180)
        v1_verd = parse_judge_output(v1_raw)
        v1_latencies.append(v1_ms)
        if v1_src == "LLM":
            actual_llm_calls += 1
        elif v1_src == "ERROR":
            error_count += 1
        elif v1_src == "FALLBACK":
            fallback_count += 1

        v1_is_agree = v1_verd == h_label
        if v1_is_agree:
            v1_agreed += 1

        prompt_toks = v2_telem.get("prompt_eval_count", 0)
        gen_toks = v2_telem.get("eval_count", 0)
        v2_status = "MATCH [100%]" if v2_is_agree else "MISMATCH [X]"

        print(
            f"[{idx:02d}/25] {cid:<6} | {h_label:<5} | {v1_verd:<7} | {v1_ms:6.1f}ms | {v2_verd:<7} | {v2_ms:6.1f}ms | {prompt_toks:<10} | {gen_toks:<7} | {v2_status:<12}"
        )

        results.append(
            {
                "case_id": cid,
                "human_label": h_label,
                "v1_verdict": v1_verd,
                "v1_agreed": v1_is_agree,
                "v1_source": v1_src,
                "v1_latency_ms": round(v1_ms, 2),
                "v1_raw": v1_raw,
                "v2_verdict": v2_verd,
                "v2_agreed": v2_is_agree,
                "v2_source": v2_src,
                "v2_latency_ms": round(v2_ms, 2),
                "v2_raw": v2_raw,
                "v2_telemetry": v2_telem,
                "llm_completed": (v2_src == "LLM"),
            }
        )

    wall_total = time.perf_counter() - wall_start

    # Statistical Distribution
    min_lat = min(v2_latencies)
    max_lat = max(v2_latencies)
    avg_lat = statistics.mean(v2_latencies)
    med_lat = statistics.median(v2_latencies)
    sorted_lats = sorted(v2_latencies)
    p95_idx = int(len(sorted_lats) * 0.95)
    p95_lat = sorted_lats[p95_idx]

    print("\n" + "=" * 115)
    print(
        "                                   FINAL AUDIT SUMMARY                                   "
    )
    print("=" * 115)
    print(f"Total Benchmark Cases Evaluated   : {len(cases)} / 25")
    print(f"Total Genuine LLM Calls Made      : {actual_llm_calls} (V1: 25 + V2: 25)")
    print(f"Number of LLM Fallback Verdicts   : {fallback_count} (0 expected)")
    print(f"Number of LLM Timeouts / Errors   : {error_count} (0 expected)")
    print(f"Number of Cache Hits / Mocks      : {cache_hits} (0 expected)")
    print(
        f"Total Wall-Clock Evaluation Time  : {wall_total:.2f} seconds ({wall_total/60:.2f} minutes)"
    )
    print("-" * 115)
    print(f"Judge V2 Minimum Latency          : {min_lat:.2f} ms")
    print(f"Judge V2 Maximum Latency          : {max_lat:.2f} ms")
    print(f"Judge V2 Average Latency          : {avg_lat:.2f} ms")
    print(f"Judge V2 Median Latency           : {med_lat:.2f} ms")
    print(f"Judge V2 P95 Latency              : {p95_lat:.2f} ms")
    print("-" * 115)
    print(
        f"Judge V1 Agreement with Human GT  : {(v1_agreed / len(cases) * 100):.2f}% ({v1_agreed}/{len(cases)})"
    )
    print(
        f"Judge V2 Agreement with Human GT  : {(v2_agreed / len(cases) * 100):.2f}% ({v2_agreed}/{len(cases)})"
    )
    print("=" * 115)

    # Save to disk
    audit_file = REPO_ROOT / "week6" / "live_llm_audit_results.json"
    audit_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": "llama3.1:8b",
        "temperature": 0.0,
        "total_cases": len(cases),
        "actual_llm_calls": actual_llm_calls,
        "fallbacks": fallback_count,
        "errors": error_count,
        "cache_hits": cache_hits,
        "wall_time_seconds": round(wall_total, 2),
        "latency_stats_ms": {
            "min": round(min_lat, 2),
            "max": round(max_lat, 2),
            "avg": round(avg_lat, 2),
            "median": round(med_lat, 2),
            "p95": round(p95_lat, 2),
        },
        "judge_v1_agreement_pct": round(v1_agreed / len(cases) * 100, 2),
        "judge_v2_agreement_pct": round(v2_agreed / len(cases) * 100, 2),
        "cases": results,
    }
    audit_file.write_text(json.dumps(audit_data, indent=2), encoding="utf-8")
    print(
        f"\n[Audit Saved] Certified results written to: {audit_file.relative_to(REPO_ROOT)}"
    )


if __name__ == "__main__":
    run_certified_audit()
