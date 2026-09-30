"""Fixed workflow: same tools, same contract, no loop, exactly one model call."""

import pytest

from backend.schemas.policy import PolicyOutputContract
from backend.services import policy_agent
from backend.services.policy_agent import PolicyAgentError
from backend.services.policy_workflow import run_workflow_case
from tests.policy_test_utils import final_reply, patch_groq_ready, script_model, tool_names

Q = "How much written notice must EMP003 provide if they resign while on probation?"


def run(ctx, employee_id="EMP003", question=Q, **kwargs):
    return run_workflow_case("case", employee_id, question, context=ctx, **kwargs)


def test_fixed_sequence_and_exactly_one_model_call(monkeypatch, policy_session):
    model = script_model(monkeypatch, final_reply("One week", "10.1 Resignation", "On probation."))
    result = run(policy_session, deterministic_pass_criteria=["1 week"])
    assert result.termination_reason == "SUCCESS" and result.passed and result.implementation == "workflow"
    assert tool_names(result) == ["get_employee_record", "search_handbook"]
    assert len(model.calls) == 1 and model.calls[0].get("tools") is None  # no tool schemas, no loop
    assert result.iterations == 1 and len(result.llm_calls) == 1
    assert [c["selection"]["rationale"] for c in result.tool_calls] == ["Fixed workflow step (no model choice)."] * 2
    assert result.tool_audit["selection_ok"] is True and result.citation["all_resolve"]
    evidence = model.calls[0]["messages"][1]["content"]
    assert "Probation" in evidence and "one week written notice" in evidence  # evidence came from the chunks


def test_same_contract_and_trace_shape_as_the_agent(monkeypatch, policy_session):
    script_model(monkeypatch, final_reply())
    workflow = run(policy_session)
    agent_fields = set(PolicyOutputContract.model_fields)
    assert set(workflow.model_dump()) == agent_fields
    call = workflow.tool_calls[0]
    assert {"step", "tool_name", "server", "roles", "arguments", "output", "is_error", "attempts", "retries", "attempt_log", "latency_ms", "selection"} <= set(call)


def test_jurisdiction_step_runs_only_for_local_rule_questions_and_uses_the_records_jurisdiction(monkeypatch, policy_session):
    script_model(monkeypatch, final_reply("Employment Act", "10.1"))
    result = run(policy_session, "EMP001", "What does the handbook say about Kenyan employment law for EMP001's separation from service?")
    assert tool_names(result) == ["get_employee_record", "search_handbook", "get_jurisdiction_rules"]
    assert result.tool_calls[2]["arguments"] == {"jurisdiction": "Kenya", "policy_category": "notice_and_separation"}
    assert result.tool_calls[2]["output"]["match_count"] >= 1


def test_no_evidence_for_a_jurisdiction_reaches_the_model_as_a_fact_not_a_crash(monkeypatch, policy_session):
    model = script_model(monkeypatch, final_reply("24 days", "5.2.1", "No Irish rule provided."))
    result = run(policy_session, "EMP002", "Which Irish statutory leave rules apply to EMP002?")
    assert result.termination_reason == "SUCCESS"
    step3 = result.tool_calls[2]
    assert step3["tool_name"] == "get_jurisdiction_rules" and step3["error"]["code"] == "NO_EVIDENCE"
    assert "NO_EVIDENCE" in model.calls[0]["messages"][1]["content"]


def test_unknown_employee_stops_after_step_one(monkeypatch, policy_session):
    model = script_model(monkeypatch)
    result = run(policy_session, "EMP999", "How much leave?")
    assert result.termination_reason == "INVALID_EMPLOYEE" and result.passed is False
    assert result.entitlement_value == "" and len(result.tool_calls) == 1 and model.calls == []


def test_provider_failure_is_not_reported_as_success(monkeypatch, policy_session):
    patch_groq_ready(monkeypatch)
    error = PolicyAgentError("PROVIDER_TRANSIENT", "HTTP 429", [{"attempt": 1, "outcome": "failed", "status_code": 429}])
    monkeypatch.setattr(policy_agent, "_call_groq_step", lambda *a, **k: (_ for _ in ()).throw(error))
    result = run(policy_session)
    assert result.termination_reason == "PROVIDER_TRANSIENT" and result.passed is False
    assert result.total_tokens == 0 and result.llm_calls[0]["status"] == "FAILED"


def test_token_budget_uses_actual_usage(monkeypatch, policy_session):
    script_model(monkeypatch, final_reply(prompt_tokens=900, completion_tokens=200))
    result = run(policy_session, max_tokens=1000)
    assert result.termination_reason == "BUDGET_TOKENS" and result.total_tokens == 1100


def test_malformed_model_answer_is_a_model_error(monkeypatch, policy_session):
    from tests.policy_test_utils import model_reply

    script_model(monkeypatch, model_reply(content="not json"))
    assert run(policy_session).termination_reason == "MODEL_ERROR"


def test_requires_groq(monkeypatch, policy_session):
    monkeypatch.setattr(policy_agent, "CHAT_BACKEND", "ollama")
    result = run(policy_session)
    assert result.termination_reason == "PROVIDER_UNAVAILABLE" and result.tool_calls == []


@pytest.mark.parametrize("override", [{"top_k": 0}, {"temperature": 2}, {"max_tokens": 10**9}, {"model": ""}, {"max_wall_clock": 0}])
def test_invalid_settings_are_refused(monkeypatch, policy_session, override):
    script_model(monkeypatch)
    assert run(policy_session, **override).termination_reason == "INVALID_ARGUMENTS"
