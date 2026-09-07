# week6/assertions.py — Deterministic Policy Assertions for HR Handbook RAG

"""
Deterministic assertions moved OUT of the LLM Judge:
1. policy_section_reference_present
2. policy_section_reference_resolves
3. handbook_version_present
4. numeric_policy_value_present
5. out_of_jurisdiction_refusal
"""

import re
from typing import Set, Dict, Any, List

# Official GESCI HR Policy & Procedures Manual (HRPPM 2018) section catalog
VALID_HANDBOOK_SECTIONS: Set[str] = {
    # Chapter 1: Scope and Purpose
    "1", "1.1", "1.2", "1.3",
    # Chapter 2: Governance, Ethics and Code of Conduct
    "2", "2.1", "2.2", "2.2.1", "2.2.2", "2.2.3", "2.2.4", "2.2.5", "2.2.6", "2.2.7", "2.2.8", "2.2.9",
    "2", "2.1", "2.2", "2.2.1", "2.2.2", "2.2.3", "2.2.4", "2.2.5", "2.2.6", "2.2.7", "2.2.8", "2.2.9", "2.2.10",
    # Chapter 3: Recruitment and Appointment
    "3", "3.1", "3.2", "3.3", "3.3.1", "3.3.2", "3.3.3", "3.3.4", "3.3.5",
    "3.4", "3.4.1", "3.4.2", "3.4.3", "3.5", "3.6", "3.6.1", "3.6.2",
    "4", "4.1", "4.2", "4.3", "4.4", "4.4.1", "4.4.2", "4.4.3", "4.4.4", "4.4.5", "4.5",
    "5", "5.1", "5.2", "5.2.1", "5.2.2", "5.3", "5.3.1", "5.3.2", "5.3.3", "5.3.4", "5.4",
    "6", "6.1", "6.2", "6.3", "6.4", "6.5",
    "3.4", "3.4.1", "3.4.2", "3.4.3", "3.5", "3.6", "3.6.1", "3.6.2", "3.6.3", "3.7", "3.8",
    # Chapter 4: Remuneration and Benefits
    "4", "4.1", "4.2", "4.2.1", "4.3", "4.3.1", "4.3.2", "4.4", "4.4.1", "4.4.2", "4.4.3", "4.4.4", "4.4.5", "4.4.6", "4.5", "4.5.1", "4.5.2", "4.5.3",
    # Chapter 5: Leave and Absences
    "5", "5.1", "5.2", "5.2.1", "5.2.2", "5.2.3", "5.2.4", "5.2.5", "5.2.6", "5.2.7", "5.2.8",
    "5.3", "5.3.1", "5.3.2", "5.3.3", "5.3.4", "5.3.5", "5.4",
    # Chapter 6: Staff Development and Training
    "6", "6.1", "6.2", "6.2.1", "6.2.2", "6.2.3", "6.2.4", "6.2.5", "6.3", "6.3.1", "6.3.2", "6.3.3", "6.3.4", "6.4", "6.5",
    # Chapter 7: Performance Management
    "7", "7.1", "7.2", "7.3", "7.4",
    "8", "8.1", "8.2", "8.3", "8.4", "8.5", "8.6",
    "9", "9.1", "9.1.1", "9.2", "9.3", "9.3.1", "9.3.2", "9.3.3", "9.4", "9.5", "9.6",
    "10", "10.1", "10.2", "10.3", "10.4", "10.5", "10.6"
    # Chapter 8: Health, Safety and Welfare
    "8", "8.1", "8.1.1", "8.1.2", "8.2", "8.3", "8.4", "8.4.1", "8.4.2", "8.4.3", "8.4.4", "8.5", "8.6", "8.7", "8.7.1", "8.7.2", "8.7.3", "8.7.4", "8.7.5", "8.8",
    # Chapter 9: Disciplinary Policy and Grievance Procedures
    "9", "9.1", "9.1.1", "9.2", "9.2.4", "9.3", "9.3.1", "9.3.2", "9.3.3", "9.3.4", "9.3.5", "9.3.6", "9.4", "9.4.1", "9.5", "9.6", "9.7",
    # Chapter 10: Separation from Service
    "10", "10.1", "10.2", "10.3", "10.4", "10.5", "10.5.1", "10.5.2", "10.5.3", "10.5.4", "10.5.5", "10.6", "10.7",
    # Chapter 11: Travel and Expenses
    "11", "11.1", "11.2", "11.2.1", "11.3", "11.3.1", "11.3.2"
}


def policy_section_reference_present(answer: str) -> bool:
    """Checks if the answer explicitly references a policy section number or section title."""
    if not answer or not answer.strip():
        return False
    sec_pattern = r"(?i)(?:section|sec\.?)\s*:?\s*(\d+(?:\.\d+)*|[A-Z0-9\s\-]+)"
    return bool(re.search(sec_pattern, answer))


def policy_section_reference_resolves(answer: str, valid_sections: Set[str] = None) -> bool:
    """
    Extracts cited section identifiers from answer and verifies they resolve to actual handbook sections.
    Supports exact matches and hierarchical prefix resolution (e.g. 10.5.3 resolves if 10.5 exists).
    If no numeric section is cited, returns True (no unresolvable citation was fabricated).
    """
    if not answer or not answer.strip():
        return True

    if valid_sections is None:
        valid_sections = VALID_HANDBOOK_SECTIONS

    sec_matches = re.findall(r"(?i)(?:section|sec\.?)\s*:?\s*(\d+(?:\.\d+)*)", answer)
    if not sec_matches:
        return True

    for sec in sec_matches:
        normalized_sec = sec.strip().rstrip(".")
        if not normalized_sec:
            continue
        
        # 1. Exact match in catalog
        if normalized_sec in valid_sections:
            continue

        # 2. Hierarchical prefix check (e.g. 5.3.2.1 resolves if 5.3.2 or 5.3 exists)
        parts = normalized_sec.split(".")
        is_valid_hierarchy = False
        for depth in range(len(parts) - 1, 0, -1):
            parent_sec = ".".join(parts[:depth])
            if parent_sec in valid_sections:
                is_valid_hierarchy = True
                break
        
        if is_valid_hierarchy:
            continue

        # If chapter number exceeds valid range (1-11), fail
        return False

    return True


def handbook_version_present(answer: str, expected_version: str = "2018") -> bool:
    """Checks if the cited handbook edition (2018, HRPPM, HRPolicy.pdf, or HR Policy) is referenced."""
    if not answer or not answer.strip():
        return False
    ans_lower = answer.lower()
    return (
        expected_version in ans_lower
        or "hrppm" in ans_lower
        or "hrpolicy" in ans_lower
        or "hr policy" in ans_lower
        or "human resource" in ans_lower
    )


def numeric_policy_value_present(answer: str, expected_numeric: str = None) -> bool:
    """
    Verifies that the required numeric policy entitlement/timeline is present in the answer.
    If expected_numeric is None or empty, returns True (numeric assertion not required).
    """
    if not expected_numeric:
        return True

    if not answer or not answer.strip():
        return False

    ans_lower = answer.lower()
    exp_lower = expected_numeric.lower()

    if exp_lower in ans_lower:
        return True

    exp_digits = re.findall(r"\d+", exp_lower)
    ans_digits = re.findall(r"\d+", ans_lower)

    if exp_digits and all(d in ans_digits for d in exp_digits):
        return True

    word_to_num = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
        "sixteen": "16", "twenty": "20", "twenty-eight": "28", "forty": "40"
    }

    for word, num in word_to_num.items():
        if word in exp_lower and (num in ans_digits or word in ans_lower):
            return True

    return False


def out_of_jurisdiction_refusal(answer: str, is_out_of_jurisdiction: bool = False) -> bool:
    """
    If the question is out-of-jurisdiction or inquires about an unstated policy invariant,
    verifies that the answer executes the proper refusal path.
    """
    if not is_out_of_jurisdiction:
        return True

    if not answer or not answer.strip():
        return True

    ans_lower = answer.lower()
    refusal_indicators = [
        "i don't know",
        "i do not know",
        "not specified",
        "not mentioned",
        "do not mention",
        "does not mention",
        "does not specify",
        "does not contain",
        "no policy",
        "not provide",
        "does not provide"
    ]

    return any(ind in ans_lower for ind in refusal_indicators)


def run_all_assertions(case: Dict[str, Any]) -> Dict[str, bool]:
    """Runs all 5 deterministic assertions on a given eval case dictionary."""
    ans = case.get("answer", "")
    expected_num = case.get("expected_numeric")
    is_ooj = case.get("out_of_jurisdiction", False)

    return {
        "policy_section_reference_present": policy_section_reference_present(ans),
        "policy_section_reference_resolves": policy_section_reference_resolves(ans),
        "handbook_version_present": handbook_version_present(ans),
        "numeric_policy_value_present": numeric_policy_value_present(ans, expected_num),
        "out_of_jurisdiction_refusal": out_of_jurisdiction_refusal(ans, is_ooj),
    }


DETERMINISTIC_ASSERTION_COUNT = 5
JUDGE_CRITERION_COUNT = 1
