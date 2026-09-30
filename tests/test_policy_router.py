"""Workflow-or-agent routing: the path varies -> agent; otherwise the fixed workflow."""

from backend.services.policy_router import (
    COMPLEXITY_COMPLEX,
    COMPLEXITY_MODERATE,
    COMPLEXITY_SIMPLE,
    MODE_AGENT,
    MODE_WORKFLOW,
    route_policy_question,
)


def test_one_employee_one_topic_uses_the_fixed_workflow():
    decision = route_policy_question("How much notice must EMP003 give if resigning on probation?", "EMP003")
    assert (decision.mode, decision.requires_agent, decision.complexity) == (MODE_WORKFLOW, False, COMPLEXITY_SIMPLE)
    assert decision.matched_signals == ["WORKFLOW_SIGNAL: policy_wording"]


def test_local_rules_are_a_data_dependent_step_but_still_the_fixed_tool_set():
    for question in (
        "What statutory rules apply to EMP001?",
        "What does the handbook say about Kenyan employment law for EMP001?",
        "What are the public holidays for EMP001?",
    ):
        decision = route_policy_question(question, "EMP001")
        assert (decision.mode, decision.complexity) == (MODE_WORKFLOW, COMPLEXITY_MODERATE), question


def test_tools_outside_the_workflow_force_the_agent():
    decision = route_policy_question("What is EMP001's grade band and accrued leave balance?", "EMP001")
    assert decision.mode == MODE_AGENT and decision.complexity == COMPLEXITY_COMPLEX
    assert "get_grade_band" in decision.reason and "get_leave_balance" in decision.reason


def test_several_employees_or_comparisons_force_the_agent():
    assert route_policy_question("Compare EMP001 and EMP002 notice periods", "EMP001").mode == MODE_AGENT
    assert route_policy_question("Is EMP003 notice different from EMP004?", "EMP003").mode == MODE_AGENT
    assert route_policy_question("How does Irish leave compare with the handbook?", "EMP002").mode == MODE_AGENT


def test_decision_serialises_for_the_ui_and_ids_are_unique():
    a = route_policy_question("notice for EMP003?", "EMP003")
    b = route_policy_question("notice for EMP003?", "EMP003")
    payload = a.to_dict()
    assert set(payload) == {"mode", "complexity", "reason", "requires_agent", "routing_ms", "routing_id", "matched_signals"}
    assert a.routing_id != b.routing_id and a.routing_ms >= 0


def test_a_question_matching_no_rule_defaults_to_the_workflow_not_the_agent():
    decision = route_policy_question("Tell me about the office dress code", "EMP001")
    assert decision.mode == MODE_WORKFLOW and decision.matched_signals == ["DEFAULT_SINGLE_EMPLOYEE"]
