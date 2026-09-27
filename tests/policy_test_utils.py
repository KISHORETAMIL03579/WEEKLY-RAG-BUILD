import json
import time
from unittest.mock import patch

from backend.services import policy_agent


def run_scripted_agent_case(
    case_id,
    employee_id,
    question,
    deterministic_pass_criteria=None,
    top_k=5,
    temperature=0.3,
    model="llama3.1:8b",
    **kwargs,
):
    """Exercise the ReAct loop with scripted model decisions and real policy tools."""
    answer = " ".join(deterministic_pass_criteria or ["Policy answer"])
    expected = {
        "entitlement_value": answer,
        "rule_cited": "Section 5.2.1",
        "explanation": "Scripted grounded answer.",
    }
    responses = [
        {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_employee_record",
                            "arguments": {"employee_id": employee_id},
                        }
                    }
                ]
            }
        },
        {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_handbook",
                            "arguments": {"query": question, "top_k": top_k},
                        }
                    }
                ]
            }
        },
        {
            "message": {
                "content": json.dumps(
                    {
                        "entitlement_value": expected["entitlement_value"],
                        "rule_cited": expected["rule_cited"],
                        "explanation": expected["explanation"],
                    }
                )
            }
        },
    ]

    def model_step(*args, **step_kwargs):
        time.sleep(0.01)
        return responses.pop(0), 12, 8, 1.0

    with (
        patch.object(policy_agent, "CHAT_BACKEND", "ollama"),
        patch.object(policy_agent, "check_ollama_available", return_value=True),
        patch.object(policy_agent, "_call_ollama_step", side_effect=model_step),
    ):
        return policy_agent.run_agent_case(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            deterministic_pass_criteria=deterministic_pass_criteria,
            top_k=top_k,
            temperature=temperature,
            model=model,
            **kwargs,
        )
