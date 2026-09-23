"""
audit_live_llm_judge.py — Comprehensive Audit of Live Ollama LLM Judge Evaluation
Runs all 25 Week 6 benchmark cases through genuine live Ollama inference.
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

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

from week6.assertions import run_all_assertions
from week6.judge import parse_judge_output

def query_ollama(prompt: str, timeout: int = 60) -> tuple:
    """
    Sends request to Ollama with stop tokens to avoid conversational filler.
    Returns: (raw_response, source, latency_ms, telemetry_dict)
    """
    t_start = time.perf_counter()
    payload = {
        "model": "llama3.1:8b",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "top_p": 0.1,
            "num_predict": 16,
            "stop": ["\n", "}", "```"]
        }
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
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

def audit_all_25_cases():
    print("=" * 110)
    print("                DEEP AUDIT: LIVE OLLAMA LLM JUDGE EVALUATION (ALL 25 CASES)                ")
    print("=" * 110)

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

    # 1. Warm-up Ollama
    print("\n[Step 1] Warming up Ollama daemon on http://127.0.0.1:11434 with llama3.1:8b...")
    warm_raw, warm_src, warm_ms, _ = query_ollama("Hello, test.", timeout=60)
    if warm_src == "LLM":
        print(f"  [OK] Ollama daemon is warm and ready ({warm_ms:.1f}ms).")
    else:
        print(f"  [FAIL] Failed to warm up Ollama: {warm_raw}")
        return

    # 2. Run all 25 cases through genuine live Ollama inference
    print("\n[Step 2] Executing live inference for 25 cases on Judge V1 and Judge V2...")
    print(f"{'Case':<9} | {'Human':<5} | {'V1 Verd':<7} | {'V1 Src':<6} | {'V1 ms':<8} | {'V2 Verd':<7} | {'V2 Src':<6} | {'V2 ms':<8} | {'V1 Agree':<8} | {'V2 Agree':<8}")
    print("-" * 110)

    results = []
    v1_latencies = []
    v2_latencies = []
    v1_agreed = 0
    v2_agreed = 0
    actual_llm_calls = 0
    cache_hits = 0
    fallback_count = 0
    error_count = 0

    wall_start = time.perf_counter()

    for idx, c in enumerate(cases, 1):
        cid = c.get("case_id", f"case_{idx:02d}")
        h_label = labels.get(cid, c.get("human_label", 1))

        # --- Evaluate Judge V1 ---
        t_prep_0 = time.perf_counter()
        p1 = v1_template.replace("{question}", c.get("question", "").strip()) \
                        .replace("{context}", c.get("retrieved_context", "").strip()) \
                        .replace("{answer}", c.get("answer", "").strip())
        t_prep_v1 = (time.perf_counter() - t_prep_0) * 1000

        v1_raw, v1_src, v1_infer_ms, v1_telemetry = query_ollama(p1, timeout=60)
        if v1_src == "LLM":
            actual_llm_calls += 1
        elif v1_src == "ERROR":
            error_count += 1
        elif v1_src == "FALLBACK":
            fallback_count += 1
        elif v1_src == "CACHE":
            cache_hits += 1

        v1_latencies.append(v1_infer_ms)
        v1_verdict = parse_judge_output(v1_raw)
        v1_is_agree = (v1_verdict == h_label)
        if v1_is_agree:
            v1_agreed += 1

        # --- Evaluate Judge V2 ---
        t_prep_0 = time.perf_counter()
        p2 = v2_template.replace("{question}", c.get("question", "").strip()) \
                        .replace("{context}", c.get("retrieved_context", "").strip()) \
                        .replace("{answer}", c.get("answer", "").strip())
        t_prep_v2 = (time.perf_counter() - t_prep_0) * 1000

        v2_raw, v2_src, v2_infer_ms, v2_telemetry = query_ollama(p2, timeout=60)
        if v2_src == "LLM":
            actual_llm_calls += 1
        elif v2_src == "ERROR":
            error_count += 1
        elif v2_src == "FALLBACK":
            fallback_count += 1
        elif v2_src == "CACHE":
            cache_hits += 1

        v2_latencies.append(v2_infer_ms)
        v2_verdict = parse_judge_output(v2_raw)
        v2_is_agree = (v2_verdict == h_label)
        if v2_is_agree:
            v2_agreed += 1

        res_item = {
            "case_id": cid,
            "human_label": h_label,
            "v1_verdict": v1_verdict,
            "v1_agreed": v1_is_agree,
            "v1_source": v1_src,
            "v1_prep_ms": round(t_prep_v1, 2),
            "v1_latency_ms": round(v1_infer_ms, 2),
            "v1_raw": v1_raw,
            "v1_telemetry": v1_telemetry,
            "v2_verdict": v2_verdict,
            "v2_agreed": v2_is_agree,
            "v2_source": v2_src,
            "v2_prep_ms": round(t_prep_v2, 2),
            "v2_latency_ms": round(v2_infer_ms, 2),
            "v2_raw": v2_raw,
            "v2_telemetry": v2_telemetry,
        }
        results.append(res_item)

        print(f"[{idx:02d}/25] {cid:<6} | {h_label:<5} | {v1_verdict:<7} | {v1_src:<6} | {v1_infer_ms:6.1f}ms | {v2_verdict:<7} | {v2_src:<6} | {v2_infer_ms:6.1f}ms | {'[AGREE]' if v1_is_agree else '[DISAGREE]':<8} | {'[AGREE]' if v2_is_agree else '[DISAGREE]':<8}")

    wall_total = time.perf_counter() - wall_start

    # 3. Statistical Analysis
    all_latencies = v1_latencies + v2_latencies
    min_lat = min(all_latencies)
    max_lat = max(all_latencies)
    avg_lat = statistics.mean(all_latencies)
    med_lat = statistics.median(all_latencies)
    sorted_lats = sorted(all_latencies)
    p95_idx = int(len(sorted_lats) * 0.95)
    p95_lat = sorted_lats[p95_idx]

    print("\n" + "=" * 110)
    print("                                   AUDIT SUMMARY & METRICS                                  ")
    print("=" * 110)
    print(f"Total Evaluation Cases            : {len(cases)}")
    print(f"Total Actual LLM Inferences       : {actual_llm_calls} ({int(actual_llm_calls/2)} V1 + {int(actual_llm_calls/2)} V2)")
    print(f"Number of Cache Hits              : {cache_hits}")
    print(f"Number of Fallback Verdicts       : {fallback_count}")
    print(f"Number of Errors                  : {error_count}")
    print(f"Total Wall-Clock Evaluation Time  : {wall_total:.2f} seconds")
    print(f"Sum of All LLM Inferences Time    : {sum(all_latencies)/1000:.2f} seconds")
    print("-" * 110)
    print(f"Minimum Inference Time            : {min_lat:.2f} ms")
    print(f"Maximum Inference Time            : {max_lat:.2f} ms")
    print(f"Average Inference Time            : {avg_lat:.2f} ms")
    print(f"Median Inference Time             : {med_lat:.2f} ms")
    print(f"P95 Inference Time                : {p95_lat:.2f} ms")
    print("-" * 110)
    print(f"Judge V1 Agreement Rate           : {(v1_agreed / len(cases) * 100):.2f}% ({v1_agreed}/{len(cases)})")
    print(f"Judge V2 Agreement Rate           : {(v2_agreed / len(cases) * 100):.2f}% ({v2_agreed}/{len(cases)})")
    print("=" * 110)

    # Save detailed audit report to JSON
    audit_file = REPO_ROOT / "week6" / "live_llm_audit_results.json"
    audit_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": "llama3.1:8b",
        "temperature": 0.0,
        "total_cases": len(cases),
        "actual_llm_calls": actual_llm_calls,
        "cache_hits": cache_hits,
        "fallbacks": fallback_count,
        "errors": error_count,
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
    print(f"\n[Audit Saved] Detailed audit artifact written to: {audit_file.relative_to(REPO_ROOT)}")

if __name__ == "__main__":
    audit_all_25_cases()
