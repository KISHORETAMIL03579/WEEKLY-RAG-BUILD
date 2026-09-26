from types import SimpleNamespace

from benchmarks.policy_execution.trajectory_eval import (
    evaluate_trajectory,
    summarize,
)


def _result(
    tool_names,
    *,
    termination_reason="SUCCESS",
    passed=True,
    latency_ms=10.0,
    total_tokens=20,
    explanation="Accrues 2 days per month, grounded in the handbook.",
):
    return SimpleNamespace(
        tool_calls=[{"tool_name": name} for name in tool_names],
        termination_reason=termination_reason,
        passed=passed,
        iterations=len(tool_names),
        prompt_tokens=12,
        completion_tokens=8,
        total_tokens=total_tokens,
        token_source="groq_live",
        latency_ms=latency_ms,
        cost_usd=0.00001,
        entitlement_value="24 working days",
        rule_cited="Section 5.2.1",
        explanation=explanation,
    )


def _case(case_id="case_01"):
    return {
        "case_id": case_id,
        "employee_id": "EMP001",
        "expected_value": "24 working days",
        "deterministic_pass_criteria": ["24", "2 days", "month"],
    }


def test_trajectory_evaluation_records_required_sequence_and_success():
    record = evaluate_trajectory(
        _case(),
        _result(["get_employee_record", "search_handbook"]),
    )

    assert record["required_tool_sequence_valid"] is True
    assert record["failure_mode"] is None
    assert record["token_source"] == "groq_live"
    assert all(item["satisfied"] for item in record["answer_criteria"])
    assert record["unmet_answer_criteria"] == []


def test_trajectory_evaluation_flags_ordering_failure_without_changing_answer():
    record = evaluate_trajectory(
        _case(),
        _result(["search_handbook", "get_employee_record"]),
    )

    assert record["required_tool_sequence_valid"] is False
    assert record["failure_mode"] == "required_tool_sequence"
    assert record["expected_value"] == "24 working days"


def test_trajectory_reports_unmet_unchanged_answer_criteria():
    record = evaluate_trajectory(
        _case(),
        _result(
            ["get_employee_record", "search_handbook"],
            passed=False,
            explanation="Correct annual leave is 24 days.",
        ),
    )

    assert record["passed"] is False
    assert record["unmet_answer_criteria"] == ["2 days", "month"]
    assert record["answer_criteria"] == [
        {"criterion": "24", "satisfied": True},
        {"criterion": "2 days", "satisfied": False},
        {"criterion": "month", "satisfied": False},
    ]


def test_trajectory_evaluation_records_redundant_calls_as_a_failure_mode():
    record = evaluate_trajectory(
        _case(),
        _result(
            [
                "get_employee_record",
                "search_handbook",
                "get_jurisdiction_rules",
            ]
        ),
    )

    assert record["required_tool_sequence_valid"] is True
    assert record["extra_tool_calls"] == ["get_jurisdiction_rules"]
    assert record["failure_mode"] == "redundant_tool_calls"


def test_trajectory_summary_reports_baseline_measurables():
    records = [
        evaluate_trajectory(
            _case("case_01"),
            _result(["get_employee_record", "search_handbook"], latency_ms=12),
        ),
        evaluate_trajectory(
            _case("case_02"),
            _result(
                ["get_employee_record"],
                termination_reason="BUDGET_WALL_CLOCK",
                passed=False,
                latency_ms=30,
            ),
        ),
    ]

    summary = summarize(records)

    assert summary["case_count"] == 2
    assert summary["answer_pass_rate_pct"] == 50
    assert summary["required_sequence_valid_rate_pct"] == 50
    assert summary["p50_latency_ms"] == 21
    assert summary["failure_mode_counts"] == {"execution_failure": 1}
    assert summary["unmet_answer_criterion_counts"] == {}
