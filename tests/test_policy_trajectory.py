"""Week 8: expected paths, the four trajectory numbers, the gap, the failure-mode zoo, before/after."""

import json

import pytest

from backend.services import policy_trajectory as traj
from backend.services.policy_benchmark_runner import load_suite

E, S, J = "get_employee_record", "search_handbook", "get_jurisdiction_rules"
CASE = {"case_id": "case_01", "employee_id": "EMP001", "question": "q"}
SPEC = {"paths": [[E, S], [S, E]], "steps_needed": 2}


def call(tool, arguments=None, output=None, step=1, error=False, attempts=1, roles=()):
    return {
        "step": step, "tool_name": tool, "server": "s", "roles": list(roles),
        "arguments": arguments or {}, "output": output or {}, "is_error": error,
        "attempts": attempts, "retries": attempts - 1, "selection": {"rationale": "why"},
    }


def record_call(emp="EMP001", jurisdiction="Kenya", step=1):
    return call(E, {"employee_id": emp}, {"found": True, "fields": {"jurisdiction": jurisdiction}}, step=step, roles=["employee_lookup"])


def run(calls, *, passed=True, termination="SUCCESS", rejected=(), citation=None, tokens=100, cost=0.0001, latency=500.0, llm_calls=()):
    return {
        "tool_calls": calls, "rejected_tool_calls": list(rejected), "passed": passed, "strict_passed": passed,
        "termination_reason": termination, "citation": citation, "total_tokens": tokens, "cost_usd": cost,
        "latency_ms": latency, "llm_calls": list(llm_calls),
        "entitlement_value": "x", "rule_cited": "y", "explanation": "z",
    }


def evaluate(calls, **kwargs):
    return traj.evaluate_case(CASE, run(calls, **kwargs), SPEC)


# -- paths -------------------------------------------------------------------


@pytest.mark.parametrize("order", [[E, S], [S, E]])
def test_every_listed_order_is_a_pass_not_a_failure(order):
    calls = [record_call(step=i + 1) if tool == E else call(S, {"query": "q"}, step=i + 1) for i, tool in enumerate(order)]
    record = evaluate(calls)
    assert record["path_exact"] and record["trajectory_passed"] and record["failure_modes"] == []
    assert record["accepts_alternate_paths"] is True and record["step_efficiency"] == 1.0


def test_skipping_a_required_tool_is_its_own_mode_even_with_a_right_answer():
    record = evaluate([record_call()])
    assert record["missing_tools"] == [S] and record["primary_failure_mode"] == "skipped_required_tool"
    assert record["right_answer_wrong_path"] is True and record["trajectory_passed"] is False


def test_an_unneeded_tool_is_wrong_tool_selection():
    record = evaluate([record_call(), call(S, step=2), call(J, {"jurisdiction": "Kenya"}, step=3)])
    assert record["extra_tools"] == [J] and record["primary_failure_mode"] == "wrong_tool_selection"
    assert record["step_efficiency"] == 1.5


def test_repeating_a_tool_is_redundant_calls():
    record = evaluate([record_call(), call(S, step=2), call(S, step=3)])
    assert record["duplicate_tools"] == [S] and "redundant_calls" in record["failure_modes"]


def test_allowed_extra_tools_are_not_penalised_as_wrong_selection():
    spec = {**SPEC, "allowed_extra_tools": [J]}
    record = traj.evaluate_case(CASE, run([record_call(), call(S, step=2), call(J, step=3)]), spec)
    assert "wrong_tool_selection" not in record["failure_modes"]


# -- arguments ---------------------------------------------------------------


def test_argument_validity_checks_ids_and_data_dependent_jurisdictions():
    good = evaluate([record_call(), call(J, {"jurisdiction": "Kenya", "policy_category": "leave"}, step=2), call(S, step=3)])
    checks = {c["check"]: c["ok"] for c in good["argument_checks"]}
    assert checks == {"employee_id_real": True, "jurisdiction_matches_record": True}
    bad = evaluate([record_call(), call(J, {"jurisdiction": "Ireland", "policy_category": "leave"}, step=2), call(S, step=3)])
    assert bad["argument_validity"] == 0.5 and "bad_arguments" in bad["failure_modes"]
    assert any("record says 'Kenya'" in c["detail"] for c in bad["argument_checks"] if not c["ok"])


def test_a_fabricated_employee_id_is_invalid_even_if_the_tool_was_called():
    fake = call(E, {"employee_id": "EMP777"}, {}, error=True, roles=["employee_lookup"])
    record = evaluate([fake, call(S, step=2)])
    assert record["argument_checks"][0]["ok"] is False


def test_unresolved_citations_count_as_invalid_arguments():
    record = evaluate([record_call(), call(S, step=2)], citation={"has_citation": True, "cited_sections": ["3.6.4"], "unresolved_sections": ["3.6.4"]})
    assert [c["check"] for c in record["argument_checks"] if not c["ok"]] == ["citation_resolves"]


def test_rejected_model_calls_count_as_failed_schema_checks():
    rejected = [{"step": 1, "tool_name": "nope", "arguments": {}, "reason": "Unknown tool"}]
    record = evaluate([record_call(), call(S, step=2)], rejected=rejected)
    assert record["primary_failure_mode"] == "invalid_tool_call" and record["trajectory_passed"] is False
    assert record["steps_taken"] == 3


# -- modes from termination --------------------------------------------------


@pytest.mark.parametrize(
    "termination,mode",
    [("PROVIDER_TRANSIENT", "provider_error"), ("GROQ_TIMEOUT", "provider_error"), ("BUDGET_TOKENS", "budget_exhausted"), ("BUDGET_ITERATIONS", "budget_exhausted"), ("TOOL_ERROR", "tool_error")],
)
def test_terminations_map_to_zoo_modes(termination, mode):
    record = evaluate([record_call()], termination=termination, passed=False)
    assert record["primary_failure_mode"] == mode and record["trajectory_passed"] is False


def test_a_clean_path_with_a_wrong_answer_is_answer_wrong():
    calls = [record_call(), call(S, step=2)]
    record = evaluate(calls, passed=False)
    assert record["trajectory_passed"] is True and record["primary_failure_mode"] == "answer_wrong"
    assert record["right_answer_wrong_path"] is False


# -- summary, gap, compare ---------------------------------------------------


def records():
    good = [record_call(), call(S, step=2)]
    return [
        evaluate(good, cost=0.0001, latency=400, tokens=1000),
        evaluate(good, cost=0.0002, latency=600, tokens=2000),
        evaluate([record_call()], cost=0.0009, latency=9000, tokens=9000),  # right answer, wrong path
        evaluate(good, passed=False, cost=0.0003, latency=500, tokens=1500),  # right path, wrong answer
    ]


def test_summary_reports_the_four_numbers_with_p50_and_max():
    summary = traj.summarize(records())
    assert summary["outcome_pass_rate_pct"] == 75.0 and summary["trajectory_pass_rate_pct"] == 75.0
    assert summary["outcome_vs_trajectory_gap_pct"] == 0.0
    assert summary["tool_choice_accuracy"] == pytest.approx((1 + 1 + 0.5 + 1) / 4)
    assert summary["step_efficiency_mean"] == pytest.approx((1 + 1 + 0.5 + 1) / 4)
    assert summary["argument_validity_rate"] == 1.0 and summary["argument_checks_total"] == 4
    assert summary["cost_usd"] == {"p50": 0.00025, "max": 0.0009}
    assert summary["latency_ms"]["max"] == 9000 and summary["total_tokens"]["p50"] == 1750
    assert summary["failure_mode_counts"]["skipped_required_tool"] == 1 and summary["failure_mode_counts"]["answer_wrong"] == 1
    wrong_path = summary["right_answer_wrong_path"]
    assert [w["observed_sequence"] for w in wrong_path] == [[E]] and "never called" in wrong_path[0]["why"]


def test_gap_is_outcome_minus_trajectory_and_positive_when_paths_are_wrong():
    lucky = [evaluate([record_call()]) for _ in range(3)] + [evaluate([record_call(), call(S, step=2)])]
    summary = traj.summarize(lucky)
    assert summary["outcome_pass_rate_pct"] == 100.0 and summary["trajectory_pass_rate_pct"] == 25.0
    assert summary["outcome_vs_trajectory_gap_pct"] == 75.0


def test_retries_are_aggregated_per_tool_and_for_model_calls():
    flaky = evaluate([record_call(), call(S, step=2, attempts=3)], llm_calls=[{"provider_retries": 2}, {"provider_retries": 1}])
    summary = traj.summarize([flaky])
    assert summary["retries"] == {"tool_attempts": {E: 1, S: 3}, "tool_retries": {E: 0, S: 2}, "model_call_retries": 3}


def test_compare_reports_modes_price_and_regressions():
    before = traj.summarize([evaluate([record_call()], termination="PROVIDER_TRANSIENT", passed=False, cost=0.0001, latency=500, tokens=500)])
    after = traj.summarize([evaluate([record_call(), call(S, step=2), call(J, step=3)], cost=0.0004, latency=2500, tokens=2000)])
    result = traj.compare(before, after)
    by_mode = {row["mode"]: row for row in result["per_mode"]}
    assert by_mode["provider_error"] == {"mode": "provider_error", "before": 1, "after": 0, "delta": -1}
    assert by_mode["wrong_tool_selection"]["delta"] == 1
    assert result["regressions"] == ["wrong_tool_selection: 0 -> 1"]
    assert set(result["modes_checked"]) == set(traj.FAILURE_MODES)
    assert result["price"]["latency_ms_p50_delta"] == 2000 and result["price"]["tokens_p50_delta"] == 1500


# -- ad-hoc audit ------------------------------------------------------------


def test_audit_is_not_evaluated_for_runs_that_ended_early():
    audit = traj.audit_tool_selection("notice for EMP999?", [call(E, roles=["employee_lookup"], error=True)], termination_reason="INVALID_EMPLOYEE")
    assert audit["selection_ok"] is None and audit["missing_tools"] == [] and "not judged" in audit["reasons"][0]


def test_audit_counts_retries_per_tool():
    audit = traj.audit_tool_selection("notice?", [call(E, attempts=2, roles=["employee_lookup"]), call(S, attempts=3, step=2)], llm_calls=[{"provider_retries": 1}])
    assert audit["retries"]["tool_retries"] == {E: 1, S: 2} and audit["retries"]["model_call_retries"] == 1


def test_audit_ignores_tools_no_server_provides():
    audit = traj.audit_tool_selection("grade band?", [call(E, roles=["employee_lookup"])], available_tools=[E, S])
    assert audit["missing_tools"] == [] and audit["required"] == []


# -- the expected-path data itself -------------------------------------------


def test_every_benchmark_case_has_an_expected_trajectory_with_consistent_steps():
    expected = traj.load_expected_trajectories()
    for case in load_suite("all"):
        spec = expected[case["case_id"]]
        assert spec["paths"] and all(spec["paths"]), case["case_id"]
        assert spec["steps_needed"] == min(len(p) for p in spec["paths"]), case["case_id"]
        for tool in case.get("requires_tools", []):
            assert any(tool in path for path in spec["paths"]), (case["case_id"], tool)


def test_alternate_path_cases_are_documented():
    spec = traj.load_expected_trajectory("case_03")
    assert len(spec["paths"]) == 2 and "either order" in spec["notes"]
    assert len(traj.load_expected_trajectory("branch_01")["paths"]) == 3
    with pytest.raises(KeyError):
        traj.load_expected_trajectory("missing")


def test_suites_load_and_reject_unknown_names():
    assert len(load_suite("canonical")) == 10 and len(load_suite("branching")) == 6
    assert len(load_suite("all")) == 16
    with pytest.raises(ValueError):
        load_suite("nope")


def test_no_case_criteria_are_lost_when_aliases_are_added():
    original = {c["case_id"]: c["deterministic_pass_criteria"] for c in load_suite("canonical")}
    assert original["case_08"] == ["not entitled to severance", "0 severance"]
    assert original["case_03"] == ["1 week", "7 days", "probation"]
    assert json.dumps(load_suite("canonical")[6]["criteria_aliases"]) == '{"60 days": ["10000"]}'
