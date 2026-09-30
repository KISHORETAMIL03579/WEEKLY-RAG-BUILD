"""ReAct agent: tool selection, recoverable rejections, guards, budgets, retry accounting."""

import json

import pytest

from backend.mcp.registry import McpToolRegistry
from backend.schemas.policy import MAX_COST, MAX_INVALID_TOOL_CALLS, MAX_ITERATIONS, MAX_TOKENS, MAX_WALL_CLOCK_SECONDS
from backend.services import policy_agent
from backend.services.policy_agent import PolicyAgentError, parse_policy_answer, run_agent_case
from tests import flaky_server
from tests.policy_test_utils import final_reply, model_reply, script_model, tool_names

Q = "How much written notice must EMP003 provide if they resign while on probation?"
NOTICE = ("10.1 Resignation", "One week written notice on probation")


def run(ctx, **kwargs):
    kwargs.setdefault("deterministic_pass_criteria", None)
    return run_agent_case("case", kwargs.pop("employee_id", "EMP003"), kwargs.pop("question", Q), context=ctx, use_live_llm=True, **kwargs)


def happy_path(monkeypatch, *, reasoning="Need the record, then the policy."):
    return script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"})], reasoning=reasoning),
        model_reply(tool_calls=[("search_handbook", {"query": "resignation notice probation", "top_k": 3})], reasoning="Now the policy wording."),
        final_reply("One week written notice", "10.1 Resignation", "Probation staff give one week."),
    )


# -- selection + trace -------------------------------------------------------


def test_model_selects_tools_and_every_call_is_traced(monkeypatch, policy_session):
    model = happy_path(monkeypatch)
    result = run(policy_session, deterministic_pass_criteria=["1 week", "probation"])
    assert result.termination_reason == "SUCCESS" and result.passed
    assert tool_names(result) == ["get_employee_record", "search_handbook"]
    first, second = result.tool_calls
    assert first["server"] == "policy-search" and first["roles"] == ["employee_lookup"]
    assert first["arguments"] == {"employee_id": "EMP003"}
    assert first["output"]["fields"]["employment_status"] == "Probation"
    assert (first["attempts"], first["retries"], first["is_error"]) == (1, 0, False)
    assert first["selection"]["rationale"] == "Need the record, then the policy."
    assert second["arguments"]["top_k"] == 3 and second["output"]["results"][0]["filename"] == "handbook.md"
    assert len(second["output"]["results"][0]["text"]) <= 240  # traces carry clipped passages
    assert result.iterations == 3 and len(model.calls) == 3
    assert result.total_tokens == 45 and result.token_source.endswith("_live")
    assert result.citation["all_resolve"] and result.citation["resolved_sections"] == ["10.1"]
    audit = result.tool_audit
    assert audit["tools_selected"] == ["get_employee_record", "search_handbook"] and audit["selection_ok"] is True
    assert audit["retries"]["total_tool_retries"] == 0 and audit["retries"]["model_calls"] == 3


def test_the_model_is_sent_discovered_schemas_not_tool_names_baked_into_the_prompt(monkeypatch, policy_session):
    model = happy_path(monkeypatch)
    run(policy_session)
    sent = {t["name"] for t in model.calls[0]["tools"]}
    assert sent == {"get_employee_record", "search_handbook", "get_jurisdiction_rules", "get_grade_band", "get_leave_balance"}
    system = model.calls[0]["messages"][0]["content"]
    assert not any(name in system for name in sent)  # descriptions carry the guidance, not the prompt


def test_parallel_independent_calls_in_one_step_are_all_executed(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "resignation notice"})]),
        final_reply("One week", "10.1"),
    )
    result = run(policy_session)
    assert tool_names(result) == ["get_employee_record", "search_handbook"]
    assert {c["step"] for c in result.tool_calls} == {1}


def test_numeric_strings_from_the_model_are_normalised_before_validation(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"})]),
        model_reply(tool_calls=[("search_handbook", {"query": "notice", "top_k": "4"})]),
        final_reply(),
    )
    result = run(policy_session, top_k=6)
    assert result.tool_calls[1]["arguments"]["top_k"] == 4


def test_hris_tools_are_used_when_the_model_picks_them_with_no_code_change(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_grade_band", {"employee_id": "EMP001"}), ("get_leave_balance", {"employee_id": "EMP001"})]),
        final_reply("G7, 12 days", "HRIS"),
    )
    result = run(policy_session, employee_id="EMP001", question="What is EMP001's grade band and accrued leave balance?")
    assert result.termination_reason == "SUCCESS"
    assert [(c["tool_name"], c["server"]) for c in result.tool_calls] == [("get_grade_band", "hris"), ("get_leave_balance", "hris")]
    assert result.tool_calls[0]["output"]["grade_band"] == "G7"
    assert result.tool_audit["selection_ok"] is True and result.tool_audit["missing_tools"] == []


def test_selection_audit_flags_a_needed_tool_the_model_never_called(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP002"}), ("search_handbook", {"query": "leave"})]),
        final_reply(),
    )
    result = run(policy_session, employee_id="EMP002", question="Which Irish statutory annual leave rules apply to EMP002?")
    assert result.termination_reason == "SUCCESS"
    assert result.tool_audit["selection_ok"] is False
    assert result.tool_audit["missing_tools"] == ["get_jurisdiction_rules"]
    assert any("jurisdiction-specific" in reason for reason in result.tool_audit["reasons"])


def test_a_tool_error_the_model_can_act_on_is_fed_back_not_fatal(monkeypatch, policy_session):
    model = script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP002"})]),
        model_reply(tool_calls=[("get_jurisdiction_rules", {"jurisdiction": "Ireland", "policy_category": "leave"})]),
        model_reply(tool_calls=[("search_handbook", {"query": "annual leave entitlement"})]),
        final_reply("24 days", "5.2.1", "No Irish rule is provided; the handbook grants 24 days."),
    )
    result = run(policy_session, employee_id="EMP002", question="Irish statutory leave for EMP002?")
    assert result.termination_reason == "SUCCESS"
    failed = result.tool_calls[1]
    assert failed["is_error"] and failed["error"]["code"] == "NO_EVIDENCE" and failed["attempts"] == 1
    fed_back = json.loads(model.calls[2]["messages"][-1]["content"])
    assert fed_back["error"]["code"] == "NO_EVIDENCE" and "search_handbook" in fed_back["error"]["hint"]


# -- rejected calls are recoverable, bounded, logged --------------------------


def test_invalid_arguments_are_returned_to_the_model_and_it_corrects_itself(monkeypatch, policy_session):
    model = script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"})]),
        model_reply(tool_calls=[("get_jurisdiction_rules", {"jurisdiction": "Mars", "policy_category": "leave"})]),
        model_reply(tool_calls=[("search_handbook", {"query": "notice"})]),
        final_reply(),
    )
    result = run(policy_session)
    assert result.termination_reason == "SUCCESS"
    assert tool_names(result) == ["get_employee_record", "search_handbook"]
    assert len(result.rejected_tool_calls) == 1
    rejected = result.rejected_tool_calls[0]
    assert rejected["tool_name"] == "get_jurisdiction_rules" and "one of" in rejected["reason"] and rejected["step"] == 2
    assert result.tool_audit["rejected_calls"] == 1 and result.tool_audit["selection_ok"] is False
    tool_msg = json.loads(model.calls[2]["messages"][-1]["content"])
    assert tool_msg["error"]["code"] == "INVALID_TOOL_CALL" and tool_msg["error"]["retryable"] is True


def test_unknown_tool_rejection_lists_the_available_tools(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("delete_everything", {})]),
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "notice"})]),
        final_reply(),
    )
    result = run(policy_session)
    assert result.termination_reason == "SUCCESS"
    assert "Available tools:" in result.rejected_tool_calls[0]["reason"] and "search_handbook" in result.rejected_tool_calls[0]["reason"]


def test_a_batch_with_one_bad_call_executes_nothing_and_asks_again(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {})]),
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "notice"})]),
        final_reply(),
    )
    result = run(policy_session)
    assert tool_names(result) == ["get_employee_record", "search_handbook"]
    assert result.rejected_tool_calls[0]["tool_name"] == "search_handbook"
    assert {c["step"] for c in result.tool_calls} == {2}


def test_duplicate_tool_in_one_step_is_rejected(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("search_handbook", {"query": "a notice"}), ("search_handbook", {"query": "b notice"})]),
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "notice"})]),
        final_reply(),
    )
    result = run(policy_session)
    assert "twice in one step" in result.rejected_tool_calls[0]["reason"]


def test_looking_up_a_different_employee_is_rejected(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP001"})]),
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "notice"})]),
        final_reply(),
    )
    result = run(policy_session)
    assert "only look up the requested employee" in result.rejected_tool_calls[0]["reason"]
    assert result.tool_calls[0]["arguments"]["employee_id"] == "EMP003"


def test_repeated_invalid_calls_end_the_run_cleanly_with_the_reason(monkeypatch, policy_session):
    bad = model_reply(tool_calls=[("nonexistent", {})])
    script_model(monkeypatch, *[bad] * (MAX_INVALID_TOOL_CALLS + 1))
    result = run(policy_session)
    assert result.termination_reason == "MODEL_ERROR" and "invalid tool calls" in result.explanation
    assert len(result.rejected_tool_calls) == MAX_INVALID_TOOL_CALLS + 1 and result.passed is False
    assert result.tool_calls == []


def test_a_final_answer_before_any_tool_is_bounced_back_then_accepted(monkeypatch, policy_session):
    model = script_model(
        monkeypatch,
        final_reply("guess", "5.2.1"),
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "notice"})]),
        final_reply("One week", "10.1"),
    )
    result = run(policy_session)
    assert result.termination_reason == "SUCCESS" and result.entitlement_value == "One week"
    assert "before confirming the employee record" in result.rejected_tool_calls[0]["reason"]
    assert model.calls[1]["messages"][-1]["role"] == "user"


def test_answering_without_policy_evidence_is_bounced_back(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"})]),
        final_reply(),
        final_reply(),
        final_reply(),
    )
    result = run(policy_session)
    assert result.termination_reason == "MODEL_ERROR"
    assert "policy evidence" in result.explanation.lower() and result.passed is False


def test_malformed_final_json_gets_one_repair_chance(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "notice"})]),
        model_reply(content="The answer is one week."),
        final_reply("One week", "10.1"),
    )
    result = run(policy_session)
    assert result.termination_reason == "SUCCESS" and "JSON object" in result.rejected_tool_calls[0]["reason"]


def test_fenced_json_answers_are_accepted():
    answer = parse_policy_answer('```json\n{"entitlement_value":"a","rule_cited":"b","explanation":"c"}\n```')
    assert answer == {"entitlement_value": "a", "rule_cited": "b", "explanation": "c"}
    for bad in ("", None, "not json", '{"entitlement_value":"a"}', '{"entitlement_value":"a","rule_cited":"b","explanation":"c","extra":"d"}'):
        with pytest.raises(PolicyAgentError):
            parse_policy_answer(bad)


# -- stop conditions ---------------------------------------------------------


def test_unknown_employee_never_gets_a_plausible_answer(monkeypatch, policy_session):
    script_model(monkeypatch, model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP999"})]))
    result = run(policy_session, employee_id="EMP999", question="How much leave does EMP999 get?")
    assert result.termination_reason == "INVALID_EMPLOYEE" and result.passed is False
    assert result.entitlement_value == "" and result.rule_cited == ""
    assert "EMP999" in result.explanation and len(result.tool_calls) == 1
    assert result.tool_audit["selection_ok"] is None  # run ended early: selection not judged


def test_no_indexed_documents_ends_the_run_with_a_clear_reason(monkeypatch):
    from tests.policy_test_utils import FakeStore, install_indexed_session

    ctx = install_indexed_session(monkeypatch, FakeStore([]))
    script_model(monkeypatch, model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"})]))
    result = run(ctx)
    assert result.termination_reason == "NO_INDEXED_DOCUMENTS" and "Upload" in result.explanation


def test_iteration_budget_terminates_cleanly_after_the_last_allowed_lap(monkeypatch, policy_session):
    model = script_model(monkeypatch, model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"})], prompt_tokens=10, completion_tokens=5))
    result = run(policy_session, max_iterations=1)
    assert result.termination_reason == "BUDGET_ITERATIONS" and result.iterations == 1
    assert len(result.tool_calls) == 1 and result.total_tokens == 15 and result.passed is False
    assert len(model.calls) == 1


def test_token_budget_stops_before_another_model_call(monkeypatch, policy_session):
    model = script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"})], prompt_tokens=90, completion_tokens=20),
    )
    result = run(policy_session, max_tokens=100)
    assert result.termination_reason == "BUDGET_TOKENS" and len(model.calls) == 1


def test_cost_budget_stops_the_loop(monkeypatch, policy_session):
    script_model(monkeypatch, model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"})], prompt_tokens=6_000, completion_tokens=5_000))
    result = run(policy_session, max_cost=0.005)  # 11,000 tokens x proxy rate = $0.0055
    assert result.termination_reason == "BUDGET_COST"


def test_wall_clock_budget_is_checked_before_calling_the_model(monkeypatch, policy_session):
    model = script_model(monkeypatch)
    result = run(policy_session, max_wall_clock=1e-9)
    assert result.termination_reason == "BUDGET_WALL_CLOCK" and model.calls == []


@pytest.mark.parametrize(
    "override",
    [
        {"max_iterations": MAX_ITERATIONS + 1},
        {"max_tokens": MAX_TOKENS + 1},
        {"max_cost": MAX_COST * 2},
        {"max_wall_clock": MAX_WALL_CLOCK_SECONDS + 1},
        {"max_iterations": 0},
        {"top_k": 0},
        {"top_k": 21},
        {"temperature": 1.5},
        {"model": " "},
    ],
)
def test_budgets_and_settings_above_the_hard_limits_are_refused(monkeypatch, policy_session, override):
    model = script_model(monkeypatch)
    result = run(policy_session, **override)
    assert result.termination_reason == "INVALID_ARGUMENTS" and model.calls == []


def test_the_agent_refuses_to_run_without_groq(monkeypatch, policy_session):
    monkeypatch.setattr(policy_agent, "CHAT_BACKEND", "ollama")
    result = run_agent_case("c", "EMP003", Q, context=policy_session)
    assert result.termination_reason == "PROVIDER_UNAVAILABLE" and "groq" in result.explanation.lower()
    monkeypatch.setattr(policy_agent, "CHAT_BACKEND", "groq")
    monkeypatch.setattr(policy_agent, "GROQ_API_KEY", "")
    assert run_agent_case("c", "EMP003", Q, context=policy_session).termination_reason == "PROVIDER_UNAVAILABLE"


# -- retry accounting --------------------------------------------------------


def test_provider_failure_is_recorded_with_its_attempts_and_never_becomes_a_success(monkeypatch, policy_session):
    error = PolicyAgentError("PROVIDER_TRANSIENT", "HTTP 429", [{"attempt": 1, "outcome": "retry", "status_code": 429}, {"attempt": 2, "outcome": "retry", "status_code": 429}, {"attempt": 3, "outcome": "failed", "status_code": 429}])
    script_model(monkeypatch)
    monkeypatch.setattr(policy_agent, "_call_groq_step", lambda *a, **k: (_ for _ in ()).throw(error))
    result = run(policy_session)
    assert result.termination_reason == "PROVIDER_TRANSIENT" and result.passed is False
    assert result.total_tokens == 0 and result.token_source == "unavailable"
    call = result.llm_calls[0]
    assert (call["status"], call["provider_attempts"], call["provider_retries"]) == ("FAILED", 3, 2)
    assert [a["status_code"] for a in call["provider_attempt_log"]] == [429, 429, 429]
    assert call["retryable"] is True


def test_model_retries_are_counted_in_the_trace_and_the_audit(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "notice"})], provider_attempts=3),
        final_reply(provider_attempts=2),
    )
    result = run(policy_session)
    assert [c["provider_retries"] for c in result.llm_calls] == [2, 1]
    assert result.tool_audit["retries"]["model_call_retries"] == 3


def flaky(tmp_path, fail_times, mode="tool"):
    flaky_server.reset(fail_times, mode)
    config = tmp_path / "servers.json"
    config.write_text(json.dumps({"servers": [{"name": "flaky", "transport": "inprocess", "module": "tests.flaky_server"}]}))
    return McpToolRegistry(config, force_transport="inprocess")


def test_tool_retries_show_up_per_tool_in_the_response(monkeypatch, policy_session, tmp_path):
    script_model(monkeypatch, model_reply(tool_calls=[("flaky_lookup", {})]), final_reply("42", "n/a"))
    result = run(policy_session, registry=flaky(tmp_path, fail_times=2))
    assert result.termination_reason == "SUCCESS"
    call = result.tool_calls[0]
    assert (call["attempts"], call["retries"]) == (3, 2)
    assert [a["status"] for a in call["attempt_log"]] == ["error", "error", "ok"]
    retries = result.tool_audit["retries"]
    assert retries["tool_retries"] == {"flaky_lookup": 2} and retries["total_tool_retries"] == 2
    assert retries["tool_attempts"] == {"flaky_lookup": 3}


def test_a_tool_that_keeps_failing_ends_the_run_as_tool_error_after_bounded_retries(monkeypatch, policy_session, tmp_path):
    model = script_model(monkeypatch, model_reply(tool_calls=[("flaky_lookup", {})]))
    result = run(policy_session, registry=flaky(tmp_path, fail_times=99))
    assert result.termination_reason == "TOOL_ERROR" and "3 attempt(s)" in result.explanation
    assert result.tool_calls[0]["attempts"] == 3 and flaky_server.STATE["calls"] == 3
    assert len(model.calls) == 1  # the model was not asked to reason about an outage


def test_a_permanent_tool_refusal_is_shown_to_the_model_without_retrying(monkeypatch, policy_session, tmp_path):
    script_model(monkeypatch, model_reply(tool_calls=[("flaky_lookup", {})]), final_reply("refused", "n/a"))
    result = run(policy_session, registry=flaky(tmp_path, fail_times=99, mode="permanent"))
    assert result.tool_calls[0]["attempts"] == 1 and result.tool_calls[0]["error"]["code"] == "NOT_ALLOWED"
    assert result.termination_reason == "MODEL_ERROR"  # answered without any successful evidence


def test_no_tools_discovered_is_a_clean_tool_error(monkeypatch, policy_session, tmp_path):
    config = tmp_path / "servers.json"
    config.write_text(json.dumps({"servers": [{"name": "broken", "transport": "inprocess", "module": "no.such.module"}]}))
    script_model(monkeypatch)
    result = run(policy_session, registry=McpToolRegistry(config, force_transport="inprocess"))
    assert result.termination_reason == "TOOL_ERROR" and "No tools" in result.explanation


# -- Groq rejects the model's own malformed tool call (HTTP 400 tool_use_failed) ---------


def _generation_failure(attempts=1):
    return PolicyAgentError(
        "TOOL_CALL_GENERATION_FAILED",
        "Failed to call a function",
        [{"attempt": n, "outcome": "failed", "status_code": 400, "code": "tool_use_failed"} for n in range(1, attempts + 1)],
    )


def script_with_failures(monkeypatch, steps):
    """Like script_model, but a step may be an exception to raise instead of a reply."""
    script_model(monkeypatch)
    queue = list(steps)
    sent = []

    def step(messages, **kwargs):
        sent.append(list(messages))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(policy_agent, "_call_groq_step", step)
    return sent


def test_a_malformed_tool_call_groq_rejected_is_recoverable_not_a_provider_failure(monkeypatch, policy_session):
    sent = script_with_failures(
        monkeypatch,
        [
            _generation_failure(),
            model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "notice"})]),
            final_reply("One week", "10.1"),
        ],
    )
    result = run(policy_session)
    assert result.termination_reason == "SUCCESS" and tool_names(result) == ["get_employee_record", "search_handbook"]
    assert "malformed tool call" in result.rejected_tool_calls[0]["reason"]
    assert result.llm_calls[0]["status"] == "FAILED" and result.llm_calls[0]["provider_attempt_log"][0]["code"] == "tool_use_failed"
    assert sent[1][-1]["role"] == "user" and "valid JSON arguments" in sent[1][-1]["content"]
    assert result.tool_audit["selection_ok"] is False  # a rejected action is visible in the audit


def test_repeated_malformed_tool_calls_end_the_run_as_a_model_error(monkeypatch, policy_session):
    script_with_failures(monkeypatch, [_generation_failure() for _ in range(MAX_INVALID_TOOL_CALLS + 1)])
    result = run(policy_session)
    assert result.termination_reason == "MODEL_ERROR" and "malformed tool call" in result.explanation
    assert len(result.rejected_tool_calls) == MAX_INVALID_TOOL_CALLS + 1


def test_an_empty_rule_cited_is_accepted_when_the_documents_state_no_rule():
    answer = parse_policy_answer('{"entitlement_value":"Not covered","rule_cited":"","explanation":"The documents are silent."}')
    assert answer["rule_cited"] == policy_agent.NO_RULE_CITED
    for empty in ('{"entitlement_value":"","rule_cited":"x","explanation":"y"}', '{"entitlement_value":"a","rule_cited":"x","explanation":" "}'):
        with pytest.raises(PolicyAgentError):
            parse_policy_answer(empty)


def test_a_silent_handbook_answer_with_no_citation_completes(monkeypatch, policy_session):
    script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP002"}), ("search_handbook", {"query": "irish leave"})]),
        model_reply(content='{"entitlement_value":"Not covered","rule_cited":"","explanation":"No Irish rule in the documents."}'),
    )
    result = run(policy_session, employee_id="EMP002", question="Irish leave rules?")
    assert result.termination_reason == "SUCCESS" and result.rule_cited == policy_agent.NO_RULE_CITED
    assert result.citation["has_citation"] is False and result.rejected_tool_calls == []
