from __future__ import annotations

import json
import math
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.config import (
    CHAT_BACKEND,
    GROQ_API_KEY,
    LLM_MODEL,
    OLLAMA_URL,
    XAI_API_KEY,
    logger,
)
from backend.schemas.policy import (
    MAX_COST,
    MAX_ITERATIONS,
    MAX_TOKENS,
    MAX_WALL_CLOCK_SECONDS,
    PolicyOutputContract,
    TOKEN_COST_PROXY_RATE,
)
from backend.services.policy_tools import (
    POLICY_TOOL_DEFINITIONS,
    execute_tool_call,
    normalize_model_tool_arguments,
    validate_tool_call,
)
from backend.services.llm import ChatProviderError, groq_chat_completion

DEFAULT_AGENT_MODEL = LLM_MODEL

_last_ollama_check_time: float = 0.0
_cached_ollama_status: bool = False


def check_ollama_available(timeout: float = 0.05) -> bool:
    """Check whether the configured Ollama endpoint accepts TCP connections."""
    global _last_ollama_check_time, _cached_ollama_status
    now = time.time()
    if now - _last_ollama_check_time < 2.0:
        return _cached_ollama_status
    try:
        endpoint = urlsplit(OLLAMA_URL)
        if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
            raise ValueError("OLLAMA_URL must be an absolute HTTP(S) URL")
        port = endpoint.port or (443 if endpoint.scheme == "https" else 80)
        with socket.create_connection((endpoint.hostname, port), timeout=timeout):
            _cached_ollama_status = True
    except (OSError, ValueError) as exc:
        _cached_ollama_status = False
        logger.debug("Configured Ollama endpoint is unavailable: %s", exc)
    _last_ollama_check_time = now
    return _cached_ollama_status


def check_model_provider_available(timeout: float = 0.05) -> bool:
    if CHAT_BACKEND == "groq":
        return bool(GROQ_API_KEY)
    if CHAT_BACKEND == "xai":
        return bool(XAI_API_KEY)
    if CHAT_BACKEND == "ollama":
        return check_ollama_available(timeout)
    return False


class PolicyAgentError(Exception):
    """Provider or model response failure with a stable API termination reason."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _call_ollama_step(
    messages: List[Dict[str, Any]],
    model: str = DEFAULT_AGENT_MODEL,
    temperature: float = 0.3,
    timeout: float = 60.0,
    num_predict: int = 512,
) -> Tuple[Dict[str, Any], int, int, float]:
    """Ask Ollama for one ReAct decision and return its actual usage metadata."""
    started = time.perf_counter()
    endpoint = f"{OLLAMA_URL.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "tools": [
            {"type": "function", "function": definition}
            for definition in POLICY_TOOL_DEFINITIONS
        ],
        "stream": False,
        "options": {
            "temperature": float(temperature),
            "num_predict": max(1, int(num_predict)),
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.001, timeout)) as response:
            if response.status != 200:
                raise PolicyAgentError(
                    "PROVIDER_ERROR", f"Ollama returned HTTP {response.status}"
                )
            data = json.loads(response.read().decode("utf-8"))
    except PolicyAgentError:
        raise
    except (TimeoutError, socket.timeout) as exc:
        raise PolicyAgentError(
            "OLLAMA_TIMEOUT", str(exc) or "Ollama request timed out"
        ) from exc
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise PolicyAgentError(
                "MODEL_NOT_FOUND",
                f"Ollama model '{model}' is not installed. Choose an installed model or pull it first.",
            ) from exc
        if exc.code in {429, 500, 502, 503, 504}:
            raise PolicyAgentError(
                "PROVIDER_TRANSIENT", f"Ollama returned HTTP {exc.code}"
            ) from exc
        raise PolicyAgentError(
            "PROVIDER_ERROR", f"Ollama returned HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise PolicyAgentError(
                "OLLAMA_TIMEOUT", str(exc.reason) or "Ollama request timed out"
            ) from exc
        raise PolicyAgentError(
            "OLLAMA_UNAVAILABLE", str(exc.reason) or "Ollama is unavailable"
        ) from exc
    except Exception as exc:
        raise PolicyAgentError("PROVIDER_ERROR", str(exc)) from exc

    if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
        raise PolicyAgentError(
            "MODEL_ERROR", "Ollama returned a malformed chat response"
        )
    if "prompt_eval_count" not in data or "eval_count" not in data:
        raise PolicyAgentError("MODEL_ERROR", "Ollama response omitted token metadata")
    p_tokens = data["prompt_eval_count"]
    c_tokens = data["eval_count"]
    if (
        type(p_tokens) is not int
        or type(c_tokens) is not int
        or p_tokens < 0
        or c_tokens < 0
    ):
        raise PolicyAgentError("MODEL_ERROR", "Ollama returned invalid token metadata")
    return data, p_tokens, c_tokens, (time.perf_counter() - started) * 1000


def _call_groq_step(
    messages: List[Dict[str, Any]],
    model: str = DEFAULT_AGENT_MODEL,
    temperature: float = 0.3,
    timeout: float = 60.0,
    num_predict: int = 512,
) -> Tuple[Dict[str, Any], int, int, float]:
    """Call Groq with OpenAI-compatible policy tools and require actual usage."""
    started = time.perf_counter()
    groq_messages: List[Dict[str, Any]] = []
    for message in messages:
        normalized = dict(message)
        if normalized.get("role") == "assistant":
            tool_calls = normalized.get("tool_calls")
            if isinstance(tool_calls, list):
                normalized["tool_calls"] = [
                    {
                        **call,
                        "type": "function",
                        "function": {
                            **call["function"],
                            "arguments": json.dumps(
                                call["function"]["arguments"],
                                separators=(",", ":"),
                            )
                            if isinstance(call["function"].get("arguments"), dict)
                            else call["function"].get("arguments"),
                        },
                    }
                    for call in tool_calls
                ]
        elif normalized.get("role") == "tool" and not normalized.get("tool_call_id"):
            tool_name = normalized.get("name")
            tool_call_id = next(
                (
                    call.get("id")
                    for previous in reversed(groq_messages)
                    if previous.get("role") == "assistant"
                    for call in previous.get("tool_calls", [])
                    if isinstance(call, dict)
                    and isinstance(call.get("function"), dict)
                    and call["function"].get("name") == tool_name
                ),
                None,
            )
            if not tool_call_id:
                raise PolicyAgentError(
                    "MODEL_ERROR",
                    "Groq tool result has no matching assistant tool-call ID",
                )
            normalized["tool_call_id"] = tool_call_id
        groq_messages.append(normalized)

    groq_tools = [
        {"type": "function", "function": definition}
        for definition in POLICY_TOOL_DEFINITIONS
    ]
    try:
        data = groq_chat_completion(
            groq_messages,
            model=model,
            temperature=float(temperature),
            max_tokens=max(1, int(num_predict)),
            timeout=max(0.001, timeout),
            tools=groq_tools,
            max_retries=3,
        )
    except ChatProviderError as exc:
        reason = (
            "PROVIDER_TRANSIENT"
            if exc.status_code in {429, 500, 502, 503, 504}
            else "GROQ_UNAVAILABLE"
            if exc.status_code is None and "network" in str(exc).lower()
            else "PROVIDER_ERROR"
        )
        raise PolicyAgentError(reason, str(exc)) from exc
    except TimeoutError as exc:
        raise PolicyAgentError("GROQ_TIMEOUT", "Groq request timed out") from exc

    choices = data.get("choices")
    usage = data.get("usage")
    if (
        not isinstance(choices, list)
        or not choices
        or not isinstance(choices[0], dict)
        or not isinstance(choices[0].get("message"), dict)
    ):
        raise PolicyAgentError("MODEL_ERROR", "Groq returned a malformed chat response")
    if not isinstance(usage, dict):
        raise PolicyAgentError("MODEL_ERROR", "Groq response omitted token usage")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if (
        type(prompt_tokens) is not int
        or type(completion_tokens) is not int
        or prompt_tokens < 0
        or completion_tokens < 0
    ):
        raise PolicyAgentError("MODEL_ERROR", "Groq returned invalid token usage")
    return (
        {
            "message": choices[0]["message"],
            "provider_attempts": data.get("_provider_attempts", 1),
        },
        prompt_tokens,
        completion_tokens,
        (time.perf_counter() - started) * 1000,
    )


def _call_agent_step(
    messages: List[Dict[str, Any]],
    model: str,
    temperature: float,
    timeout: float,
    num_predict: int,
) -> Tuple[Dict[str, Any], int, int, float]:
    if CHAT_BACKEND == "groq":
        return _call_groq_step(
            messages,
            model=model,
            temperature=temperature,
            timeout=timeout,
            num_predict=num_predict,
        )
    if CHAT_BACKEND == "ollama":
        return _call_ollama_step(
            messages,
            model=model,
            temperature=temperature,
            timeout=timeout,
            num_predict=num_predict,
        )
    raise PolicyAgentError(
        "PROVIDER_ERROR", f"Policy Agent does not support CHAT_BACKEND={CHAT_BACKEND!r}"
    )


def _tool_calls_from_message(
    message: Dict[str, Any],
) -> Tuple[List[Tuple[str, Dict[str, Any]]], Dict[str, Any]]:
    calls = message.get("tool_calls", [])
    if calls is None:
        calls = []
    if not isinstance(calls, list) or len(calls) > len(POLICY_TOOL_DEFINITIONS):
        raise PolicyAgentError(
            "MODEL_ERROR", "Model returned too many policy tool calls in one step"
        )
    if not calls:
        return [], dict(message)

    selected_tools: List[Tuple[str, Dict[str, Any]]] = []
    normalized_calls = []
    seen_names = set()
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            raise PolicyAgentError("MODEL_ERROR", "Malformed tool call from model")
        name = function.get("name")
        if not isinstance(name, str):
            raise PolicyAgentError("MODEL_ERROR", "Malformed tool name from model")
        if name in seen_names:
            raise PolicyAgentError(
                "MODEL_ERROR", "Model repeated a policy tool in one step"
            )
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise PolicyAgentError(
                    "MODEL_ERROR", "Tool arguments are not valid JSON"
                ) from exc
        arguments = normalize_model_tool_arguments(name, arguments)
        try:
            validate_tool_call(name, arguments)
        except (TypeError, ValueError) as exc:
            raise PolicyAgentError("MODEL_ERROR", str(exc)) from exc

        seen_names.add(name)
        selected_tools.append((name, arguments))
        normalized_function = dict(function)
        normalized_function["arguments"] = arguments
        normalized_call = dict(call)
        normalized_call["function"] = normalized_function
        normalized_calls.append(normalized_call)

    normalized_message = dict(message)
    normalized_message["tool_calls"] = normalized_calls
    return selected_tools, normalized_message


def _parse_final_answer(content: Any) -> Dict[str, str]:
    if not isinstance(content, str) or not content.strip():
        raise PolicyAgentError(
            "MODEL_ERROR", "Model returned neither a tool call nor a final answer"
        )
    text = content.strip()
    if text.startswith("Final Answer:"):
        text = text[len("Final Answer:") :].strip()
    try:
        answer = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyAgentError(
            "MODEL_ERROR", "Final answer must be a JSON object"
        ) from exc
    required = {"entitlement_value", "rule_cited", "explanation"}
    if (
        not isinstance(answer, dict)
        or set(answer) != required
        or any(
            not isinstance(answer[key], str) or not answer[key].strip()
            for key in required
        )
    ):
        raise PolicyAgentError(
            "MODEL_ERROR",
            "Final answer must contain non-empty entitlement_value, rule_cited, and explanation strings",
        )
    return answer


def _failure_result(
    case_id: str,
    employee_id: str,
    question: str,
    reason: str,
    explanation: str,
    started: float,
    tool_calls: List[Dict[str, Any]],
    llm_calls: List[Dict[str, Any]],
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    iteration: int,
    top_k: int,
    temperature: float,
    model: str,
) -> PolicyOutputContract:
    return PolicyOutputContract(
        case_id=case_id,
        employee_id=employee_id,
        question=question,
        entitlement_value="",
        rule_cited="",
        explanation=explanation,
        passed=False,
        implementation="agent",
        execution_mode="agent",
        tool_calls=tool_calls,
        iterations=iteration,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        token_source=(
            next(
                (
                    call["token_source"]
                    for call in llm_calls
                    if str(call.get("token_source", "")).endswith("_live")
                ),
                "unavailable",
            )
        ),
        llm_calls=llm_calls,
        cost_usd=round(cost_usd, 8),
        provider_cost="N/A",
        latency_ms=round(max(0.01, (time.perf_counter() - started) * 1000), 3),
        termination_reason=reason,
        top_k=top_k,
        temperature=temperature,
        model=model,
    )


def run_agent_case(
    case_id: str,
    employee_id: str,
    question: str,
    deterministic_pass_criteria: Optional[List[str]] = None,
    max_iterations: int = MAX_ITERATIONS,
    max_tokens: int = MAX_TOKENS,
    max_cost: float = MAX_COST,
    max_wall_clock: float = MAX_WALL_CLOCK_SECONDS,
    force_budget_trap: Optional[str] = None,
    top_k: int = 5,
    temperature: float = 0.3,
    model: str = DEFAULT_AGENT_MODEL,
    use_live_llm: Optional[bool] = None,
    on_stage: Optional[Callable[[str], None]] = None,
) -> PolicyOutputContract:
    """Run a model-driven ReAct loop with validated tools and hard execution budgets."""
    started = time.perf_counter()
    calls: List[Dict[str, Any]] = []
    llm_calls: List[Dict[str, Any]] = []
    prompt_tokens = 0
    completion_tokens = 0
    cost_usd = 0.0
    iteration = 0
    reason = "SUCCESS"

    valid_budgets = (
        type(max_iterations) is int and 1 <= max_iterations <= MAX_ITERATIONS,
        type(max_tokens) is int and 1 <= max_tokens <= MAX_TOKENS,
        isinstance(max_cost, (int, float))
        and math.isfinite(max_cost)
        and 0 < max_cost <= MAX_COST,
        isinstance(max_wall_clock, (int, float))
        and math.isfinite(max_wall_clock)
        and 0 < max_wall_clock <= MAX_WALL_CLOCK_SECONDS,
    )
    if (
        not all(valid_budgets)
        or type(top_k) is not int
        or not 1 <= top_k <= 20
        or not isinstance(temperature, (int, float))
        or not math.isfinite(temperature)
        or not 0 <= temperature <= 1
        or not isinstance(model, str)
        or not model.strip()
    ):
        return _failure_result(
            case_id,
            employee_id,
            question,
            "INVALID_ARGUMENTS",
            "Agent configuration exceeds the supported model or execution budgets.",
            started,
            calls,
            llm_calls,
            prompt_tokens,
            completion_tokens,
            cost_usd,
            iteration,
            top_k,
            temperature,
            model,
        )

    if force_budget_trap in {"iterations", "tokens", "cost", "wall_clock"}:
        trap_reasons = {
            "iterations": "BUDGET_ITERATIONS",
            "tokens": "BUDGET_TOKENS",
            "cost": "BUDGET_COST",
            "wall_clock": "BUDGET_WALL_CLOCK",
        }
        trap = force_budget_trap
        return _failure_result(
            case_id,
            employee_id,
            question,
            trap_reasons[trap],
            f"Terminated by forced {trap} budget.",
            started,
            calls,
            llm_calls,
            prompt_tokens,
            completion_tokens,
            cost_usd,
            0,
            top_k,
            temperature,
            model,
        )

    if use_live_llm is False or (
        use_live_llm is None and not check_model_provider_available()
    ):
        return _failure_result(
            case_id,
            employee_id,
            question,
            "PROVIDER_UNAVAILABLE",
            f"The configured {CHAT_BACKEND} model provider is unavailable; no answer was generated.",
            started,
            calls,
            llm_calls,
            prompt_tokens,
            completion_tokens,
            cost_usd,
            iteration,
            top_k,
            temperature,
            model,
        )

    system_prompt = (
        "You are a grounded HR policy ReAct agent. Use native calls to registered "
        "policy tools; you may request multiple independent tools in one step, but "
        "never request the same tool more than once in a step. Look up the requested "
        "employee before giving an employee-specific answer; never infer missing "
        "employee details. Use only observations returned by tools and the policy "
        "handbook for facts. When ready, return exactly one JSON object with string "
        'keys "entitlement_value", "rule_cited", and "explanation". Do not output '
        "any other fields."
    )
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Employee ID: {employee_id}\nQuestion: {question}\nRequested handbook result limit: {top_k}",
        },
    ]
    employee_confirmed = False
    policy_evidence_retrieved = False

    while iteration < max_iterations:
        iteration += 1
        if on_stage:
            on_stage("Selecting tool")
        elapsed = time.perf_counter() - started
        remaining = max_wall_clock - elapsed
        if remaining <= 0:
            reason = "BUDGET_WALL_CLOCK"
            return _failure_result(
                case_id,
                employee_id,
                question,
                reason,
                f"Terminated before model call: wall-clock budget of {max_wall_clock}s was exhausted.",
                started,
                calls,
                llm_calls,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                iteration - 1,
                top_k,
                temperature,
                model,
            )
        total_tokens = prompt_tokens + completion_tokens
        if total_tokens >= max_tokens:
            return _failure_result(
                case_id,
                employee_id,
                question,
                "BUDGET_TOKENS",
                f"Terminated before model call: token budget of {max_tokens} was exhausted.",
                started,
                calls,
                llm_calls,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                iteration - 1,
                top_k,
                temperature,
                model,
            )
        if cost_usd >= max_cost:
            return _failure_result(
                case_id,
                employee_id,
                question,
                "BUDGET_COST",
                f"Terminated before model call: cost budget of ${max_cost:.4f} was exhausted.",
                started,
                calls,
                llm_calls,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                iteration - 1,
                top_k,
                temperature,
                model,
            )

        num_predict = max(1, max_tokens - total_tokens)
        llm_started = time.perf_counter()
        try:
            response, p_tokens, c_tokens, latency_ms = _call_agent_step(
                messages,
                model=model,
                temperature=temperature,
                timeout=remaining,
                num_predict=num_predict,
            )
        except PolicyAgentError as exc:
            # Each provider timeout is set to the entire remaining request budget.
            if exc.reason in {"OLLAMA_TIMEOUT", "GROQ_TIMEOUT"}:
                reason = "BUDGET_WALL_CLOCK"
                message = f"{CHAT_BACKEND} timed out before generating an answer."
            elif exc.reason == "OLLAMA_UNAVAILABLE":
                reason = exc.reason
                message = "Ollama is unavailable; no answer was generated."
            elif exc.reason == "MODEL_NOT_FOUND":
                reason = exc.reason
                message = str(exc)
            elif exc.reason == "PROVIDER_TRANSIENT":
                reason = exc.reason
                message = f"The {CHAT_BACKEND} provider is temporarily unavailable."
            else:
                reason = exc.reason
                message = "The model provider returned an invalid or failed response."
            llm_calls.append(
                {
                    "call_index": iteration,
                    "attempt": 1,
                    "is_retry": False,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "latency_ms": round(
                        max(0.0, (time.perf_counter() - llm_started) * 1000), 3
                    ),
                    "token_source": "unavailable",
                    "status": "FAILED",
                    "retry_reason": reason,
                    "retryable": reason
                    in {
                        "OLLAMA_TIMEOUT",
                        "OLLAMA_UNAVAILABLE",
                        "GROQ_TIMEOUT",
                        "GROQ_UNAVAILABLE",
                        "PROVIDER_UNAVAILABLE",
                        "PROVIDER_TRANSIENT",
                        "MODEL_ERROR",
                        "TOOL_ERROR",
                    },
                }
            )
            logger.warning(
                "Policy agent model call failed (%s): %s",
                reason,
                exc,
                exc_info=True,
            )
            return _failure_result(
                case_id,
                employee_id,
                question,
                reason,
                message,
                started,
                calls,
                llm_calls,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                iteration,
                top_k,
                temperature,
                model,
            )
        except Exception:
            logger.exception("Unexpected policy agent model call error")
            return _failure_result(
                case_id,
                employee_id,
                question,
                "MODEL_ERROR",
                "The model provider failed; no answer was generated.",
                started,
                calls,
                llm_calls,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                iteration,
                top_k,
                temperature,
                model,
            )

        prompt_tokens += p_tokens
        completion_tokens += c_tokens
        cost_usd = (prompt_tokens + completion_tokens) * TOKEN_COST_PROXY_RATE
        provider_attempts = response.get("provider_attempts", 1)
        llm_calls.append(
            {
                "call_index": iteration,
                "attempt": 1,
                "provider_attempts": provider_attempts,
                "provider_retries": max(0, provider_attempts - 1),
                "is_retry": False,
                "input_tokens": p_tokens,
                "output_tokens": c_tokens,
                "total_tokens": p_tokens + c_tokens,
                "latency_ms": round(latency_ms, 3),
                "token_source": f"{CHAT_BACKEND}_live",
                "status": "SUCCESS",
                "retry_reason": None,
                "retryable": False,
            }
        )
        if time.perf_counter() - started >= max_wall_clock:
            return _failure_result(
                case_id,
                employee_id,
                question,
                "BUDGET_WALL_CLOCK",
                f"Terminated by wall-clock budget of {max_wall_clock}s.",
                started,
                calls,
                llm_calls,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                iteration,
                top_k,
                temperature,
                model,
            )
        if prompt_tokens + completion_tokens > max_tokens:
            return _failure_result(
                case_id,
                employee_id,
                question,
                "BUDGET_TOKENS",
                f"Terminated by token budget ({prompt_tokens + completion_tokens} > {max_tokens}).",
                started,
                calls,
                llm_calls,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                iteration,
                top_k,
                temperature,
                model,
            )
        if cost_usd > max_cost:
            return _failure_result(
                case_id,
                employee_id,
                question,
                "BUDGET_COST",
                f"Terminated by cost budget (${cost_usd:.6f} > ${max_cost:.4f}).",
                started,
                calls,
                llm_calls,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                iteration,
                top_k,
                temperature,
                model,
            )

        message = response["message"]
        try:
            selected_tools, message = _tool_calls_from_message(message)
        except PolicyAgentError as exc:
            return _failure_result(
                case_id,
                employee_id,
                question,
                exc.reason,
                str(exc),
                started,
                calls,
                llm_calls,
                prompt_tokens,
                completion_tokens,
                cost_usd,
                iteration,
                top_k,
                temperature,
                model,
            )
        messages.append(message)

        if not selected_tools:
            if not employee_confirmed:
                return _failure_result(
                    case_id,
                    employee_id,
                    question,
                    "MODEL_ERROR",
                    "Model attempted a final answer before confirming the employee record.",
                    started,
                    calls,
                    llm_calls,
                    prompt_tokens,
                    completion_tokens,
                    cost_usd,
                    iteration,
                    top_k,
                    temperature,
                    model,
                )
            if not policy_evidence_retrieved:
                return _failure_result(
                    case_id,
                    employee_id,
                    question,
                    "MODEL_ERROR",
                    "Model attempted a final answer before retrieving policy evidence.",
                    started,
                    calls,
                    llm_calls,
                    prompt_tokens,
                    completion_tokens,
                    cost_usd,
                    iteration,
                    top_k,
                    temperature,
                    model,
                )
            try:
                answer = _parse_final_answer(message.get("content"))
            except PolicyAgentError as exc:
                return _failure_result(
                    case_id,
                    employee_id,
                    question,
                    exc.reason,
                    str(exc),
                    started,
                    calls,
                    llm_calls,
                    prompt_tokens,
                    completion_tokens,
                    cost_usd,
                    iteration,
                    top_k,
                    temperature,
                    model,
                )
            full_text = " ".join(answer.values()).lower()
            passed = (
                all(
                    criterion.lower() in full_text
                    for criterion in deterministic_pass_criteria
                )
                if deterministic_pass_criteria
                else True
            )
            return PolicyOutputContract(
                case_id=case_id,
                employee_id=employee_id,
                question=question,
                entitlement_value=answer["entitlement_value"],
                rule_cited=answer["rule_cited"],
                explanation=answer["explanation"],
                passed=passed,
                implementation="agent",
                execution_mode="agent",
                tool_calls=calls,
                iterations=iteration,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                token_source=f"{CHAT_BACKEND}_live",
                llm_calls=llm_calls,
                cost_usd=round(cost_usd, 8),
                provider_cost="N/A",
                latency_ms=round(max(0.01, (time.perf_counter() - started) * 1000), 3),
                termination_reason="SUCCESS",
                top_k=top_k,
                temperature=temperature,
                model=model,
            )

        for tool_name, arguments in selected_tools:
            if tool_name == "get_employee_record":
                if (
                    arguments["employee_id"].strip().upper()
                    != employee_id.strip().upper()
                ):
                    return _failure_result(
                        case_id,
                        employee_id,
                        question,
                        "MODEL_ERROR",
                        "Model requested an employee record different from the request employee.",
                        started,
                        calls,
                        llm_calls,
                        prompt_tokens,
                        completion_tokens,
                        cost_usd,
                        iteration,
                        top_k,
                        temperature,
                        model,
                    )
            if tool_name == "search_handbook":
                arguments["top_k"] = min(arguments.get("top_k", top_k), top_k)
            if on_stage:
                on_stage(f"Executing tool: {tool_name}")
            tool_started = time.perf_counter()
            try:
                observation = execute_tool_call(tool_name, arguments)
            except Exception:
                logger.exception("Policy agent tool execution failed (%s)", tool_name)
                return _failure_result(
                    case_id,
                    employee_id,
                    question,
                    "TOOL_ERROR",
                    "A policy tool failed; no answer was generated.",
                    started,
                    calls,
                    llm_calls,
                    prompt_tokens,
                    completion_tokens,
                    cost_usd,
                    iteration,
                    top_k,
                    temperature,
                    model,
                )
            tool_latency = (time.perf_counter() - tool_started) * 1000
            calls.append(
                {
                    "step": iteration,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "output": observation,
                    "latency_ms": round(max(0.01, tool_latency), 3),
                }
            )
            if tool_name == "get_employee_record":
                if not observation.get("found"):
                    return _failure_result(
                        case_id,
                        employee_id,
                        question,
                        "INVALID_EMPLOYEE",
                        observation.get(
                            "error",
                            f"Employee record '{employee_id}' was not found.",
                        ),
                        started,
                        calls,
                        llm_calls,
                        prompt_tokens,
                        completion_tokens,
                        cost_usd,
                        iteration,
                        top_k,
                        temperature,
                        model,
                    )
                employee_confirmed = True
            if tool_name in {"search_handbook", "get_jurisdiction_rules"}:
                policy_evidence_retrieved = True
            messages.append(
                {
                    "role": "tool",
                    "name": tool_name,
                    **(
                        {
                            "tool_call_id": next(
                                call.get("id")
                                for call in message.get("tool_calls", [])
                                if call.get("function", {}).get("name") == tool_name
                            )
                        }
                        if any(
                            call.get("id")
                            for call in message.get("tool_calls", [])
                            if call.get("function", {}).get("name") == tool_name
                        )
                        else {}
                    ),
                    "content": json.dumps(observation, ensure_ascii=False),
                }
            )
            if on_stage:
                on_stage("Processing tool result")

    return _failure_result(
        case_id,
        employee_id,
        question,
        "BUDGET_ITERATIONS",
        f"Terminated by iteration budget ({max_iterations}).",
        started,
        calls,
        llm_calls,
        prompt_tokens,
        completion_tokens,
        cost_usd,
        iteration,
        top_k,
        temperature,
        model,
    )
