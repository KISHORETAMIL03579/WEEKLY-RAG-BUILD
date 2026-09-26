# backend/evaluation/assertions.py — 5 Deterministic Rule Assertions
from __future__ import annotations

from week6.assertions import (
    DETERMINISTIC_ASSERTION_COUNT,
    JUDGE_CRITERION_COUNT,
    VALID_HANDBOOK_SECTIONS,
    handbook_version_present,
    numeric_policy_value_present,
    out_of_jurisdiction_refusal,
    policy_section_reference_present,
    policy_section_reference_resolves,
    run_all_assertions,
)

CANONICAL_SECTIONS = VALID_HANDBOOK_SECTIONS
assert_policy_section_reference_present = policy_section_reference_present
assert_policy_section_reference_resolves = policy_section_reference_resolves
assert_handbook_version_present = handbook_version_present
assert_numeric_policy_value_present = numeric_policy_value_present
assert_out_of_jurisdiction_refusal = out_of_jurisdiction_refusal
