#!/usr/bin/env python3
# week6/eval_week6.py — Unified One-Command Week 6 Evaluation Runner

import os
import sys
import json
import pathlib
from typing import Dict, Any, List

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from week6.assertions import run_all_assertions, DETERMINISTIC_ASSERTION_COUNT, JUDGE_CRITERION_COUNT
from week6.judge import run_judge_suite

WEEK5_TAXONOMY_MODES = {
    "Low-K Multi-Clause Truncation",
    "Sub-Clause Dispersal Across Disparate Policy Chapters",
    "Citation Drifting & In-Prose Structural Inversion",
    "Unstated Policy Invariant Refusal",
    "Embedding Similarity Threshold Starvation"
}


def load_eval_cases(path: str = "week6/eval_cases_25.json") -> List[Dict[str, Any]]:
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Evaluation cases file not found at {p}")
    with open(p, "r", encoding="utf-8") as f:
        cases = json.load(f)
    if len(cases) < 25:
        raise ValueError(f"Expected at least 25 evaluation cases, found {len(cases)}")
    return cases


def load_labels(path: str = "week6/labels_25.json") -> Dict[str, int]:
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Blind human labels file not found at {p}")
    with open(p, "r", encoding="utf-8") as f:
        labels = json.load(f)
    return labels


def validate_cases(cases: List[Dict[str, Any]]):
    regression_count = 0
    for c in cases:
        cid = c.get("case_id")
        mode = c.get("taxonomy_mode")
        if mode not in WEEK5_TAXONOMY_MODES:
            raise ValueError(f"Case {cid} has unknown taxonomy mode: {mode}")
        if c.get("regression"):
            regression_count += 1
            if not c.get("trace_id"):
                raise ValueError(f"Regression case {cid} is missing a real trace_id!")
    if regression_count < 2:
        raise ValueError(f"Expected at least 2 regression cases, found {regression_count}")
    return regression_count


def compute_mode_statistics(cases: List[Dict[str, Any]], labels: Dict[str, int], v1_results: List[Dict], v2_results: List[Dict]) -> Dict[str, Any]:
    v1_map = {r["case_id"]: r["judge_label"] for r in v1_results}
    v2_map = {r["case_id"]: r["judge_label"] for r in v2_results}

    mode_stats = {mode: {"total": 0, "human_pass": 0, "v1_pass": 0, "v2_pass": 0} for mode in WEEK5_TAXONOMY_MODES}

    for c in cases:
        cid = c["case_id"]
        mode = c["taxonomy_mode"]
        h_label = labels.get(cid, 1)
        v1_label = v1_map.get(cid, 0)
        v2_label = v2_map.get(cid, 0)

        mode_stats[mode]["total"] += 1
        if h_label == 1:
            mode_stats[mode]["human_pass"] += 1
        if v1_label == 1:
            mode_stats[mode]["v1_pass"] += 1
        if v2_label == 1:
            mode_stats[mode]["v2_pass"] += 1

    return mode_stats


def compute_failure_category_statistics(cases: List[Dict[str, Any]]) -> Dict[str, int]:
    """Computes distribution of failure root causes (Pipeline vs LLM Model vs Code Issue vs Clean Pass)."""
    counts = {
        "pipeline": 0,
        "llm_model": 0,
        "code_issue": 0,
        "pass": 0
    }
    for c in cases:
        cat = c.get("failure_category")
        if cat in counts:
            counts[cat] += 1
        else:
            counts["pass"] += 1
    return counts


def run_week6_evaluation():
    print("=" * 78)
    print("      WEEK 6 PRACTICAL EVALUATION: VALIDATE THE POLICY-ANSWER JUDGE      ")
    print("=" * 78)

    # 1. Load data
    cases = load_eval_cases("week6/eval_cases_25.json")
    labels = load_labels("week6/labels_25.json")
    regression_count = validate_cases(cases)

    print(f"\n[1/5] Loaded {len(cases)} Evaluation Cases ({regression_count} Regression Cases)")
    print(f"[2/5] Loaded {len(labels)} Blind Human Labels (Pre-Judge Ground Truth)")

    # 2. Run Deterministic Assertions
    print("\n[3/5] Running Deterministic Assertions (Out of LLM Judge)...")
    assertion_results = []
    assertion_pass_counts = {
        "policy_section_reference_present": 0,
        "policy_section_reference_resolves": 0,
        "handbook_version_present": 0,
        "numeric_policy_value_present": 0,
        "out_of_jurisdiction_refusal": 0,
    }

    for c in cases:
        res = run_all_assertions(c)
        assertion_results.append(res)
        for k, v in res.items():
            if v:
                assertion_pass_counts[k] += 1

    # 3. Run Judge V1
    print("\n[4/5] Running Judge V1 (Single Binary Semantic Criterion)...")
    v1_output = run_judge_suite(cases, "week6/judge_v1.txt", labels)
    
    # 4. Run Judge V2
    print("\n[5/5] Running Judge V2 (Few-Shot Exemplars from V1 Disagreements)...")
    v2_output = run_judge_suite(cases, "week6/judge_v2.txt", labels)

    # 5. Compute Mode Table & Failure Statistics
    mode_stats = compute_mode_statistics(cases, labels, v1_output["results"], v2_output["results"])
    failure_stats = compute_failure_category_statistics(cases)

    # Render Table
    print("\n" + "=" * 78)
    print(f"{'Week 5 Taxonomy Mode':<48} {'Cases':<6} {'Human Pass':<12} {'Judge V1':<10} {'Judge V2':<10}")
    print("-" * 78)
    for mode, stats in mode_stats.items():
        tot = stats["total"]
        h_pct = (stats["human_pass"] / tot * 100) if tot else 0.0
        v1_pct = (stats["v1_pass"] / tot * 100) if tot else 0.0
        v2_pct = (stats["v2_pass"] / tot * 100) if tot else 0.0
        print(f"{mode:<48} {tot:<6} {h_pct:>5.1f}%       {v1_pct:>5.1f}%     {v2_pct:>5.1f}%")
    print("=" * 78)

    # Failure Root Cause Breakdown Table
    print("\n" + "=" * 78)
    print("          FAILURE ROOT CAUSE BREAKDOWN (PIPELINE vs MODEL vs CODE)       ")
    print("=" * 78)
    print(f"{'Failure Category':<35} {'Cases Count':<15} {'Percentage':<15}")
    print("-" * 78)
    for cat_name, label_title in [
        ("pipeline", "Pipeline Failure (Retrieval/K/Threshold)"),
        ("llm_model", "LLM Model Failure (Gen Drift/Judge Bias)"),
        ("code_issue", "Code Issue (Assertion/Resolver Defect)"),
        ("pass", "Clean Pass (Zero Pipeline/Model Defect)")
    ]:
        cnt = failure_stats.get(cat_name, 0)
        pct = (cnt / len(cases) * 100.0) if cases else 0.0
        print(f"{label_title:<45} {cnt:>5}            {pct:>5.1f}%")
    print("=" * 78)

    # Summary Metrics
    print("\n" + "=" * 78)
    print("                         WEEK 6 SUMMARY METRICS                           ")
    print("=" * 78)
    print(f"Total Evaluation Cases           : {len(cases)}")
    print(f"Regression Cases (Verbatim)      : {regression_count}")
    print(f"Deterministic Assertions Count   : {DETERMINISTIC_ASSERTION_COUNT}")
    print(f"LLM Judge Criterion Count        : {JUDGE_CRITERION_COUNT} (Binary Semantic Correctness)")
    print(f"Human Correct Count              : {v1_output['human_correct']} / {len(cases)}")
    print(f"Judge V1 Agreement Rate          : {v1_output['agreement_pct']:.2f}% ({v1_output['agreements']}/{len(cases)})")
    print(f"Judge V2 Agreement Rate          : {v2_output['agreement_pct']:.2f}% ({v2_output['agreements']}/{len(cases)})")
    print(f"Judge V1 Disagreements Count     : {len(v1_output['disagreements'])}")
    print(f"Judge V2 Disagreements Count     : {len(v2_output['disagreements'])}")
    print("-" * 78)

    print("\n--- Deterministic Assertion Pass Rates ---")
    for name, cnt in assertion_pass_counts.items():
        pct = cnt / len(cases) * 100.0
        print(f"  • {name:<36}: {cnt:>2}/{len(cases)} ({pct:5.1f}%)")

    print("\n--- Prediction Scoring & Disagreement Analysis ---")
    prediction_path = pathlib.Path("week6/prediction.txt")
    if prediction_path.exists():
        print(f"Prediction Filed: {prediction_path.read_text(encoding='utf-8').strip()}")
    print(f"Outcome: Judge V1 agreement was {v1_output['agreement_pct']:.1f}%.")
    print(f"         Judge V2 agreement was {v2_output['agreement_pct']:.1f}%.")
    if v2_output['agreement_pct'] < v1_output['agreement_pct']:
        print("Finding: The prompt iteration over-corrected by inducing a severe false-negative bias")
        print("         in Llama 3.1 8B, rejecting valid concise summaries as incomplete.")
    else:
        print("Finding: The prompt iteration improved judge alignment with human ground truth.")
    print("=" * 78)

    # Export complete trace-level evaluation artifact
    v1_map = {r["case_id"]: r for r in v1_output["results"]}
    v2_map = {r["case_id"]: r for r in v2_output["results"]}
    export_data = []
    for idx, c in enumerate(cases):
        cid = c["case_id"]
        v1_res = v1_map.get(cid, {})
        v2_res = v2_map.get(cid, {})
        export_data.append({
            "case_id": cid,
            "trace_id": c.get("trace_id"),
            "question": c.get("question"),
            "taxonomy_mode": c.get("taxonomy_mode"),
            "human_label": labels.get(cid),
            "assertions": assertion_results[idx],
            "judge_v1_verdict": v1_res.get("judge_label"),
            "judge_v1_agreed": v1_res.get("agreed"),
            "judge_v2_verdict": v2_res.get("judge_label"),
            "judge_v2_agreed": v2_res.get("agreed"),
            "failure_category": c.get("failure_category"),
            "failure_type": c.get("failure_type"),
            "failure_reason": c.get("failure_reason"),
            "resolution": c.get("resolution")
        })

    trace_results_path = pathlib.Path("week6/trace_eval_results.json")
    with open(trace_results_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2)
    print(f"\n[Artifact Saved] Exported trace evaluation report to: {trace_results_path}")


if __name__ == "__main__":
    run_week6_evaluation()
