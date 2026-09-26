from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from backend.schemas.policy import PolicyOutputContract
from backend.services import policy_agent, policy_tools
from backend.services.policy_agent import run_agent_case
from backend.services.policy_router import MODE_AGENT, MODE_WORKFLOW
from backend.services.policy_workflow import run_workflow_case


@pytest.fixture(autouse=True)
def use_local_provider_dispatch(monkeypatch):
    monkeypatch.setattr(policy_agent, "CHAT_BACKEND", "ollama")


def _tool_response(name, arguments, prompt_tokens=10, completion_tokens=5):
    return _tool_calls_response([(name, arguments)], prompt_tokens, completion_tokens)


def _tool_calls_response(calls, prompt_tokens=10, completion_tokens=5):
    return (
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": name, "arguments": arguments}}
                    for name, arguments in calls
                ],
            }
        },
        prompt_tokens,
        completion_tokens,
        2.0,
    )


def _final_response(prompt_tokens=10, completion_tokens=5):
    return (
        {
            "message": {
                "role": "assistant",
                "content": (
                    '{"entitlement_value":"24 working days",'
                    '"rule_cited":"Section 5.2.1",'
                    '"explanation":"The handbook provides 24 working days."}'
                ),
            }
        },
        prompt_tokens,
        completion_tokens,
        2.0,
    )


def test_agent_uses_model_tool_choice_and_validated_tool_schemas():
    decisions = [
        _tool_response("search_handbook", {"query": "annual leave", "top_k": 5}),
        _tool_response("get_employee_record", {"employee_id": "EMP001"}),
        _final_response(),
    ]
    observed_messages = []
    observed_settings = []

    def model_step(messages, **kwargs):
        observed_messages.append(messages)
        observed_settings.append((kwargs["model"], kwargs["temperature"]))
        return decisions.pop(0)

    with patch.object(policy_agent, "_call_ollama_step", side_effect=model_step):
        result = run_agent_case(
            "react-choice",
            "EMP001",
            "What annual leave applies?",
            deterministic_pass_criteria=["24 working days"],
            top_k=7,
            temperature=0.65,
            model="llama3.1:8b",
            use_live_llm=True,
        )

    assert result.termination_reason == "SUCCESS"
    assert result.passed
    assert [call["tool_name"] for call in result.tool_calls] == [
        "search_handbook",
        "get_employee_record",
    ]
    assert result.iterations == 3
    assert result.total_tokens == 45
    assert len(observed_messages) == 3
    assert observed_settings == [("llama3.1:8b", 0.65)] * 3
    assert any(message["role"] == "tool" for message in observed_messages[2])

    policy_tools.validate_tool_call("get_employee_record", {"employee_id": "EMP001"})
    for name, arguments in [
        ("missing_tool", {}),
        ("get_employee_record", {"employee_id": "EMP001", "other": "x"}),
        ("search_handbook", {"query": "leave", "top_k": True}),
        (
            "get_jurisdiction_rules",
            {"jurisdiction": "Mars", "policy_category": "leave"},
        ),
    ]:
        try:
            policy_tools.validate_tool_call(name, arguments)
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError(f"Invalid tool call accepted: {name} {arguments}")


def test_agent_normalizes_numeric_string_from_model_to_integer_tool_argument():
    decisions = [
        _tool_response(
            "search_handbook", {"query": "annual leave entitlement", "top_k": "5"}
        ),
        _tool_response("get_employee_record", {"employee_id": "EMP001"}),
        _final_response(),
    ]
    handbook_call = policy_tools.search_handbook

    with (
        patch.object(policy_agent, "_call_ollama_step", side_effect=decisions),
        patch.object(
            policy_agent, "execute_tool_call", wraps=policy_agent.execute_tool_call
        ) as execute_tool,
        patch.object(policy_tools, "search_handbook", wraps=handbook_call) as search,
    ):
        result = run_agent_case(
            "string-top-k",
            "EMP001",
            "What annual leave applies?",
            use_live_llm=True,
        )

    assert result.termination_reason == "SUCCESS"
    assert result.tool_calls[0]["arguments"]["top_k"] == 5
    assert type(result.tool_calls[0]["arguments"]["top_k"]) is int
    execute_tool.assert_any_call(
        "search_handbook", {"query": "annual leave entitlement", "top_k": 5}
    )
    search.assert_called_once_with("annual leave entitlement", top_k=5)


def test_agent_executes_validated_native_tool_call_batch_and_observes_all_results():
    decisions = [
        _tool_calls_response(
            [
                ("get_employee_record", {"employee_id": "EMP001"}),
                (
                    "search_handbook",
                    {"query": "annual leave entitlement", "top_k": "5"},
                ),
                (
                    "get_jurisdiction_rules",
                    {"jurisdiction": "Kenya", "policy_category": "leave"},
                ),
            ]
        ),
        _final_response(),
    ]
    observed_messages = []

    def model_step(messages, **kwargs):
        observed_messages.append(messages)
        return decisions.pop(0)

    with patch.object(policy_agent, "_call_ollama_step", side_effect=model_step):
        result = run_agent_case(
            "native-tool-batch",
            "EMP001",
            "Compare the handbook leave policy with Kenya's statutory rules.",
            top_k=5,
            use_live_llm=True,
        )

    assert result.termination_reason == "SUCCESS"
    assert result.iterations == 2
    assert [call["tool_name"] for call in result.tool_calls] == [
        "get_employee_record",
        "search_handbook",
        "get_jurisdiction_rules",
    ]
    assert type(result.tool_calls[1]["arguments"]["top_k"]) is int
    assert (
        len([message for message in observed_messages[1] if message["role"] == "tool"])
        == 3
    )
    assistant_message = next(
        message for message in observed_messages[1] if message["role"] == "assistant"
    )
    assert len(assistant_message["tool_calls"]) == 3
    assert assistant_message["tool_calls"][1]["function"]["arguments"]["top_k"] == 5


def test_agent_still_rejects_invalid_integer_string_tool_arguments():
    for top_k in ("0", "21", "5.0", "-1", " 5"):
        try:
            policy_agent._tool_calls_from_message(
                {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_handbook",
                                "arguments": {
                                    "query": "annual leave",
                                    "top_k": top_k,
                                },
                            }
                        }
                    ]
                }
            )
        except policy_agent.PolicyAgentError:
            pass
        else:
            raise AssertionError(f"Invalid top_k accepted: {top_k!r}")


def test_agent_rejects_duplicate_or_oversized_tool_batches():
    duplicate_calls = _tool_calls_response(
        [
            ("get_employee_record", {"employee_id": "EMP001"}),
            ("get_employee_record", {"employee_id": "EMP001"}),
        ]
    )[0]["message"]
    too_many_calls = _tool_calls_response(
        [
            ("get_employee_record", {"employee_id": "EMP001"}),
            ("search_handbook", {"query": "leave"}),
            (
                "get_jurisdiction_rules",
                {"jurisdiction": "Kenya", "policy_category": "leave"},
            ),
            ("get_employee_record", {"employee_id": "EMP001"}),
        ]
    )[0]["message"]

    for message in (duplicate_calls, too_many_calls):
        try:
            policy_agent._tool_calls_from_message(message)
        except policy_agent.PolicyAgentError:
            pass
        else:
            raise AssertionError("Invalid tool-call batch was accepted")


def test_agent_requires_policy_evidence_before_returning_a_final_answer():
    decisions = [
        _tool_response("get_employee_record", {"employee_id": "EMP001"}),
        _final_response(),
    ]
    with patch.object(policy_agent, "_call_ollama_step", side_effect=decisions):
        result = run_agent_case(
            "missing-policy-evidence",
            "EMP001",
            "What annual leave applies?",
            use_live_llm=True,
        )

    assert result.termination_reason == "MODEL_ERROR"
    assert "policy evidence" in result.explanation.lower()
    assert result.passed is False


def test_unknown_employee_never_gets_plausible_agent_or_workflow_answer():
    with patch.object(
        policy_agent,
        "_call_ollama_step",
        return_value=_tool_response("get_employee_record", {"employee_id": "EMP999"}),
    ):
        agent_result = run_agent_case(
            "missing-agent",
            "EMP999",
            "How much annual leave?",
            use_live_llm=True,
        )
    workflow_result = run_workflow_case(
        "missing-workflow", "EMP999", "How much annual leave?"
    )

    for result in (agent_result, workflow_result):
        assert result.termination_reason == "INVALID_EMPLOYEE"
        assert result.passed is False
        assert result.entitlement_value == ""
        assert result.rule_cited == ""
        assert "not found" in result.explanation.lower()
    assert len(agent_result.tool_calls) == 1
    assert len(workflow_result.tool_calls) == 1


def test_bad_model_tool_choice_returns_truthful_error_without_answer():
    with patch.object(
        policy_agent,
        "_call_ollama_step",
        return_value=_tool_response("make_up_entitlement", {}),
    ):
        result = run_agent_case(
            "bad-tool",
            "EMP001",
            "What is my entitlement?",
            use_live_llm=True,
        )

    assert result.termination_reason == "MODEL_ERROR"
    assert result.entitlement_value == ""
    assert result.rule_cited == ""
    assert result.passed is False
    assert result.llm_calls[0]["status"] == "SUCCESS"


def test_provider_error_does_not_fall_back_to_success_or_fake_tokens():
    result = run_agent_case(
        "provider-error", "EMP001", "annual leave", use_live_llm=False
    )

    assert result.termination_reason == "PROVIDER_UNAVAILABLE"
    assert result.passed is False
    assert result.entitlement_value == ""
    assert result.total_tokens == 0
    assert result.token_source == "unavailable"


def test_missing_ollama_model_is_reported_without_retries():
    missing_model_response = HTTPError(
        "http://ollama:11434/api/chat",
        404,
        "Not Found",
        {},
        BytesIO(b'{"error":"model not found"}'),
    )
    with patch.object(
        policy_agent.urllib.request,
        "urlopen",
        side_effect=missing_model_response,
    ):
        try:
            policy_agent._call_ollama_step([], model="llama3.2:3b")
        except policy_agent.PolicyAgentError as error:
            assert error.reason == "MODEL_NOT_FOUND"
            assert "llama3.2:3b" in str(error)
        else:
            raise AssertionError("A missing Ollama model was accepted")

    with patch.object(
        policy_agent,
        "_call_ollama_step",
        side_effect=policy_agent.PolicyAgentError(
            "MODEL_NOT_FOUND",
            "Ollama model 'llama3.2:3b' is not installed.",
        ),
    ):
        result = run_agent_case(
            "missing-model",
            "EMP001",
            "What is the annual leave entitlement?",
            use_live_llm=True,
        )

    assert result.termination_reason == "MODEL_NOT_FOUND"
    assert "not installed" in result.explanation
    assert result.llm_calls[0]["retryable"] is False
    assert result.total_tokens == 0


def test_ollama_health_check_uses_configured_container_host():
    with (
        patch.object(policy_agent, "OLLAMA_URL", "http://ollama:11434"),
        patch.object(policy_agent, "_last_ollama_check_time", 0.0),
        patch.object(policy_agent, "_cached_ollama_status", False),
        patch.object(policy_agent.socket, "create_connection") as connect,
    ):
        assert policy_agent.check_ollama_available()

    connect.assert_called_once_with(("ollama", 11434), timeout=0.05)


def test_provider_exception_details_are_not_returned_to_client():
    with patch.object(
        policy_agent,
        "_call_ollama_step",
        side_effect=policy_agent.PolicyAgentError(
            "PROVIDER_ERROR", "internal endpoint token=do-not-expose"
        ),
    ):
        result = run_agent_case(
            "safe-provider-error",
            "EMP001",
            "What is the annual leave entitlement?",
            use_live_llm=True,
        )

    assert result.termination_reason == "PROVIDER_ERROR"
    assert "do-not-expose" not in result.explanation
    assert result.entitlement_value == ""


def test_agent_rejects_budget_overrides_above_hard_limits():
    with patch.object(policy_agent, "_call_ollama_step") as model_call:
        result = run_agent_case(
            "oversized-budget",
            "EMP001",
            "annual leave",
            use_live_llm=True,
            max_iterations=6,
        )
    model_call.assert_not_called()
    assert result.termination_reason == "INVALID_ARGUMENTS"
    assert result.total_tokens == 0
    assert result.passed is False


def test_wall_clock_timeout_is_hard_budget_and_never_retried():
    timeout_values = []

    def timed_out(messages, **kwargs):
        timeout_values.append(kwargs["timeout"])
        raise policy_agent.PolicyAgentError("OLLAMA_TIMEOUT", "request timed out")

    with patch.object(policy_agent, "_call_ollama_step", side_effect=timed_out):
        result = run_agent_case(
            "timeout",
            "EMP001",
            "annual leave",
            use_live_llm=True,
            max_wall_clock=0.1,
        )

    assert result.termination_reason == "BUDGET_WALL_CLOCK"
    assert result.passed is False
    assert timeout_values and timeout_values[0] <= 0.1

    attempts = []

    def budget_stopped(**kwargs):
        attempts.append(kwargs)
        return PolicyOutputContract(
            case_id="timeout",
            employee_id="EMP001",
            question="annual leave",
            entitlement_value="",
            rule_cited="",
            explanation="wall clock exhausted",
            passed=False,
            termination_reason="BUDGET_WALL_CLOCK",
        )

    with patch("backend.routes.policy.run_agent_case", side_effect=budget_stopped):
        from backend.routes.policy import _run_with_retries

        failed, history = _run_with_retries(
            mode=MODE_AGENT,
            employee_id="EMP001",
            question="annual leave",
            case_id="timeout",
            top_k=5,
            temperature=0.3,
            model="llama3.1:8b",
            max_retries=2,
        )

    assert len(attempts) == 1
    assert failed.termination_reason == "BUDGET_WALL_CLOCK"
    assert [entry["status"] for entry in history] == ["FAILED"]
    assert history[0]["retryable"] is False


def test_groq_agent_sends_openai_tool_call_ids_and_uses_actual_usage():
    messages = [
        {"role": "system", "content": "Use tools."},
        {"role": "user", "content": "Find the leave policy."},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "search_handbook",
                        "arguments": {"query": "leave", "top_k": 5},
                    },
                }
            ],
        },
        {
            "role": "tool",
            "name": "search_handbook",
            "content": '{"matches": []}',
        },
    ]
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"entitlement_value":"24 days",'
                        '"rule_cited":"Section 5.2.1",'
                        '"explanation":"Handbook evidence."}'
                    ),
                }
            }
        ],
        "usage": {"prompt_tokens": 87, "completion_tokens": 23},
    }

    with patch.object(
        policy_agent, "groq_chat_completion", return_value=response
    ) as groq_call:
        result = policy_agent._call_groq_step(
            messages, model="openai/gpt-oss-20b"
        )

    request_messages = groq_call.call_args.args[0]
    assert request_messages[2]["tool_calls"][0]["type"] == "function"
    assert request_messages[2]["tool_calls"][0]["function"]["arguments"] == (
        '{"query":"leave","top_k":5}'
    )
    assert request_messages[3]["tool_call_id"] == "call_1"
    assert result[1:3] == (87, 23)
    assert result[0]["provider_attempts"] == 1


def test_returned_failure_is_not_recorded_as_success():
    calls = []

    def model_failure(**kwargs):
        calls.append(kwargs)
        return PolicyOutputContract(
            case_id="bad-provider",
            employee_id="EMP001",
            question="annual leave",
            entitlement_value="",
            rule_cited="",
            explanation="Provider rejected the model request.",
            passed=False,
            termination_reason="PROVIDER_ERROR",
        )

    with patch("backend.routes.policy.run_agent_case", side_effect=model_failure):
        from backend.routes.policy import _run_with_retries

        result, history = _run_with_retries(
            mode=MODE_AGENT,
            employee_id="EMP001",
            question="annual leave",
            case_id="bad-provider",
            top_k=5,
            temperature=0.3,
            model="bad-model",
            max_retries=0,
        )

    assert len(calls) == 1
    assert result.termination_reason == "PROVIDER_ERROR"
    assert result.passed is False
    assert history[0]["status"] == "FAILED"
    assert history[0]["retryable"] is False
    assert history[0]["retry_reason"] == "PROVIDER_ERROR"


def test_workflow_mode_dispatch_is_not_changed():
    from backend.routes.policy import _run_with_retries

    with patch(
        "backend.routes.policy.run_workflow_case",
        wraps=run_workflow_case,
    ) as workflow:
        result, history = _run_with_retries(
            mode=MODE_WORKFLOW,
            employee_id="EMP001",
            question="What is annual leave?",
            case_id="workflow-semantics",
            top_k=5,
            temperature=0.3,
            model="ignored",
            max_retries=0,
        )
    assert workflow.call_count == 1
    assert result.termination_reason == "SUCCESS"
    assert result.iterations == 1
    assert history[0]["status"] == "SUCCESS"
