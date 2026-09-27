import json
from unittest.mock import patch

from backend.schemas.policy import JurisdictionEnum, PolicyCategoryEnum
from backend.services.policy_agent import PolicyAgentError
from backend.services.policy_tools import execute_tool_call
from backend.services.policy_workflow import run_workflow_case


def _model_response(answer, prompt_tokens=120, completion_tokens=40):
    return (
        {"message": {"content": json.dumps(answer)}},
        prompt_tokens,
        completion_tokens,
        2.5,
    )


def test_fixed_workflow_uses_same_model_settings_once_and_records_live_usage():
    answer = {
        "entitlement_value": "24 working days",
        "rule_cited": "Section 5.2.1",
        "explanation": "The employee receives 24 working days.",
    }
    with patch(
        "backend.services.policy_workflow.call_policy_model_once",
        return_value=_model_response(answer),
    ) as model_call:
        result = run_workflow_case(
            "workflow-live-path",
            "EMP001",
            "What is the annual leave entitlement?",
            deterministic_pass_criteria=["24 working days"],
            top_k=7,
            temperature=0.65,
            model="selected-model",
        )

    assert result.termination_reason == "SUCCESS"
    assert result.passed
    assert result.execution_mode == "workflow"
    assert result.iterations == 1
    assert result.total_tokens == 160
    assert result.token_source.endswith("_live")
    assert result.model == "selected-model"
    assert result.temperature == 0.65
    assert [call["tool_name"] for call in result.tool_calls] == [
        "get_employee_record",
        "search_handbook",
    ]
    model_call.assert_called_once()
    assert model_call.call_args.kwargs["model"] == "selected-model"
    assert model_call.call_args.kwargs["temperature"] == 0.65
    assert model_call.call_args.kwargs["timeout"] > 0
    assert model_call.call_args.kwargs["max_tokens"] == 4000
    messages = model_call.call_args.args[0]
    assert "24 working days" not in messages[0]["content"]
    assert "tenure_months" in messages[1]["content"]


def test_fixed_workflow_uses_enum_jurisdiction_tool_when_question_requires_it():
    answer = {
        "entitlement_value": "Kenya statutory leave rules",
        "rule_cited": "Kenya",
        "explanation": "The jurisdiction evidence is included.",
    }
    with (
        patch(
            "backend.services.policy_workflow.call_policy_model_once",
            return_value=_model_response(answer),
        ),
        patch(
            "backend.services.policy_workflow.execute_tool_call",
            wraps=execute_tool_call,
        ) as execute_tool,
    ):
        result = run_workflow_case(
            "workflow-jurisdiction",
            "EMP001",
            "What statutory public holiday rules apply in my jurisdiction?",
            model="selected-model",
        )

    assert result.termination_reason == "SUCCESS"
    assert [call["tool_name"] for call in result.tool_calls] == [
        "get_employee_record",
        "search_handbook",
        "get_jurisdiction_rules",
    ]
    execute_tool.assert_any_call(
        "get_jurisdiction_rules",
        {
            "jurisdiction": JurisdictionEnum.KENYA.value,
            "policy_category": PolicyCategoryEnum.HOLIDAYS_AND_WORKING_HOURS.value,
        },
    )


def test_workflow_provider_failure_is_not_reported_as_a_success():
    with patch(
        "backend.services.policy_workflow.call_policy_model_once",
        side_effect=PolicyAgentError("PROVIDER_TRANSIENT", "temporary outage"),
    ):
        result = run_workflow_case(
            "workflow-provider-error",
            "EMP001",
            "What is the annual leave entitlement?",
            model="selected-model",
        )

    assert result.termination_reason == "PROVIDER_TRANSIENT"
    assert result.iterations == 1
    assert result.passed is False
    assert result.entitlement_value == ""
    assert result.total_tokens == 0
    assert result.token_source == "unavailable"


def test_workflow_stops_when_actual_usage_exceeds_token_budget():
    answer = {
        "entitlement_value": "24 working days",
        "rule_cited": "Section 5.2.1",
        "explanation": "The employee receives 24 working days.",
    }
    with patch(
        "backend.services.policy_workflow.call_policy_model_once",
        return_value=_model_response(answer, prompt_tokens=3500, completion_tokens=100),
    ) as model_call:
        result = run_workflow_case(
            "workflow-token-budget",
            "EMP001",
            "What is the annual leave entitlement?",
            model="selected-model",
            max_tokens=3000,
        )

    assert result.termination_reason == "BUDGET_TOKENS"
    assert result.passed is False
    assert result.total_tokens == 3600
    assert model_call.call_args.kwargs["max_tokens"] == 3000
