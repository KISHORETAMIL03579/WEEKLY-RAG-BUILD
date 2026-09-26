# backend/evaluation/metrics.py — Pure Evaluation Metrics (MRR, Hit-Rate, Reciprocal Rank)
from typing import List, Tuple


def hit_check(retrieved: List[dict], expected: str) -> bool:
    """Checks if expected section or filename substring appears in retrieved items."""
    if not expected:
        return False
    expected_lower = expected.lower()
    for r in retrieved:
        section = (r.get("section") or "").lower()
        filename = (r.get("filename") or "").lower()
        if expected_lower in section or expected_lower in filename:
            return True
    return False


def rr_rank(
    retrieved: List[dict],
    expected: str = "",
    expected_doc: str = "",
    expected_section: str = "",
) -> Tuple[bool, float, int]:
    """Calculates Hit (bool), Reciprocal Rank (float), and Rank Index (1-based int)."""
    exp_lower = (expected or "").strip().lower()
    exp_doc_lower = (expected_doc or "").strip().lower()
    exp_sec_lower = (expected_section or "").strip().lower()

    if not (exp_lower or exp_doc_lower or exp_sec_lower):
        return False, 0.0, 0

    for idx, r in enumerate(retrieved, start=1):
        section = (r.get("section") or "").lower()
        filename = (r.get("filename") or "").lower()
        text = (r.get("text") or "").lower()

        hit = False
        if exp_doc_lower and exp_doc_lower in filename:
            hit = True
        elif exp_sec_lower and (exp_sec_lower in section or exp_sec_lower in text):
            hit = True
        elif exp_lower and (
            exp_lower in section or exp_lower in filename or exp_lower in text
        ):
            hit = True

        if hit:
            return True, 1.0 / idx, idx

    return False, 0.0, 0


# Aliases for exact backward compatibility with test_eval_metrics.py
_hit_check = hit_check
_rr_rank = rr_rank
