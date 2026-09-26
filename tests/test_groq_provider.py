from unittest.mock import MagicMock, patch

import pytest
import httpx
from fastapi import HTTPException

from backend.routes import policy
from backend.services import llm
from week6 import judge


def test_groq_chat_completion_uses_environment_key_and_actual_usage_response():
    response_payload = {
        "choices": [{"message": {"role": "assistant", "content": "OK"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
    }
    response = MagicMock()
    response.json.return_value = response_payload
    client = MagicMock()
    client.__enter__.return_value.post.return_value = response

    with (
        patch.object(llm, "GROQ_API_KEY", "test-groq-key"),
        patch.object(llm.httpx, "Client", return_value=client),
    ):
        result = llm.groq_chat_completion(
            [{"role": "user", "content": "test"}],
            model="openai/gpt-oss-20b",
            max_retries=1,
        )

    request = client.__enter__.return_value.post.call_args
    assert request.kwargs["headers"]["Authorization"] == "Bearer test-groq-key"
    assert request.kwargs["json"]["model"] == "openai/gpt-oss-20b"
    assert request.kwargs["json"]["reasoning_effort"] == "low"
    assert request.kwargs["json"]["include_reasoning"] is False
    assert result["usage"] == {"prompt_tokens": 4, "completion_tokens": 2}


def test_groq_chat_completion_requires_key():
    with patch.object(llm, "GROQ_API_KEY", ""):
        with pytest.raises(llm.ChatProviderError, match="not configured"):
            llm.groq_chat_completion([{"role": "user", "content": "test"}])


def test_groq_retries_rate_limit_and_records_provider_attempts():
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "0"}
    rate_limited.raise_for_status.side_effect = httpx.HTTPStatusError(
        "rate limited",
        request=MagicMock(),
        response=rate_limited,
    )
    success = MagicMock()
    success.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "OK"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
    }
    client = MagicMock()
    client.__enter__.return_value.post.side_effect = [rate_limited, success]

    with (
        patch.object(llm, "GROQ_API_KEY", "test-groq-key"),
        patch.object(llm.httpx, "Client", return_value=client),
        patch.object(llm.time, "sleep") as sleep,
    ):
        result = llm.groq_chat_completion(
            [{"role": "user", "content": "test"}],
            model="openai/gpt-oss-20b",
            max_retries=3,
        )

    assert client.__enter__.return_value.post.call_count == 2
    assert result["_provider_attempts"] == 2
    sleep.assert_not_called()


def test_groq_does_not_retry_before_server_delay_past_request_budget():
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "60"}
    rate_limited.raise_for_status.side_effect = httpx.HTTPStatusError(
        "rate limited",
        request=MagicMock(),
        response=rate_limited,
    )
    client = MagicMock()
    client.__enter__.return_value.post.return_value = rate_limited

    with (
        patch.object(llm, "GROQ_API_KEY", "test-groq-key"),
        patch.object(llm.httpx, "Client", return_value=client),
    ):
        with pytest.raises(llm.ChatProviderError) as error:
            llm.groq_chat_completion(
                [{"role": "user", "content": "test"}],
                timeout=5,
                max_retries=3,
            )

    assert error.value.status_code == 429
    client.__enter__.return_value.post.assert_called_once()


def test_groq_model_endpoint_exposes_only_allowlisted_agent_models():
    response = MagicMock()
    response.json.return_value = {
        "data": [
            {"id": "openai/gpt-oss-20b"},
            {"id": "llama-3.3-70b-versatile"},
        ]
    }
    response.raise_for_status.return_value = None

    with (
        patch.object(policy, "CHAT_BACKEND", "groq"),
        patch.object(policy, "GROQ_API_KEY", "test-groq-key"),
        patch.object(policy, "GROQ_MODEL", "openai/gpt-oss-20b"),
        patch.object(policy, "GROQ_AGENT_MODELS", {"openai/gpt-oss-20b"}),
        patch.object(policy.httpx, "get", return_value=response),
    ):
        result = policy.get_available_models()

    assert result["provider"] == "groq"
    assert result["default_model"] == "openai/gpt-oss-20b"
    assert result["models"] == [
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-20b",
    ]
    assert result["agent_models"] == ["openai/gpt-oss-20b"]


def test_week6_judge_uses_configured_groq_without_falling_back_to_ollama():
    with (
        patch("backend.config.CHAT_BACKEND", "groq"),
        patch("backend.config.LLM_MODEL", "openai/gpt-oss-20b"),
        patch.object(judge, "check_ollama_health") as ollama_health,
        patch(
            "backend.services.llm.chat_configured",
            return_value=True,
        ),
        patch(
            "backend.services.llm.chat_call",
            return_value='{"verdict":1}',
        ) as groq_call,
    ):
        output, source, _ = judge.call_llm_judge_detailed("judge prompt")

    assert (output, source) == ('{"verdict":1}', "LLM")
    ollama_health.assert_not_called()
    assert groq_call.call_args.kwargs["model"] == "openai/gpt-oss-20b"
    assert groq_call.call_args.kwargs["max_tokens"] == 128
