"""Fixed-sequence HR policy workflow using the shared policy tools and model."""

from __future__ import annotations

import json
import math
import time
from typing import Any, Callable, Dict, List, Optional

from backend.config import CHAT_BACKEND, LLM_MODEL
from backend.schemas.policy import (
    MAX_COST,
    MAX_TOKENS,
    MAX_WALL_CLOCK_SECONDS,
    JurisdictionEnum,
    PolicyCategoryEnum,
    PolicyOutputContract,
    TOKEN_COST_PROXY_RATE,
)
from backend.services.policy_agent import (
    PolicyAgentError,
    call_policy_model_once,
    parse_policy_answer,
)
from backend.services.policy_tools import execute_tool_call


def _policy_category(question: str) -> PolicyCategoryEnum:
    normalized = question.lower()
    if any(word in normalized for word in ("working hour", "public holiday", "workweek")):
        return PolicyCategoryEnum.HOLIDAYS_AND_WORKING_HOURS
    if any(word in normalized for word in ("leave", "sick", "maternity")):
        return PolicyCategoryEnum.LEAVE
    if any(word in normalized for word in ("notice", "resign", "severance", "redundan")):
        return PolicyCategoryEnum.NOTICE_AND_SEPARATION
    if any(word in normalized for word in ("pension", "benefit", "salary", "pay")):
        return PolicyCategoryEnum.BENEFITS_AND_PENSION
    return PolicyCategoryEnum.CONDUCT_AND_DISCIPLINE


def _requires_jurisdiction_rules(question: str) -> bool:
    normalized = question.lower()
    return any(
        phrase in normalized
        for phrase in (
            "jurisdiction",
            "statutory",
            "statute",
            "local law",
            "public holiday",
            "duty station law",
            "country law",
        )
    )


def _record_tool_call(
    calls: List[Dict[str, Any]],
    step: int,
    name: str,
    arguments: Dict[str, Any],
) -> Any:
    started = time.perf_counter()
    output = execute_tool_call(name, arguments)
    calls.append(
        {
            "step": step,
            "tool_name": name,
            "arguments": arguments,
            "output": output,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    )
    return output


def _failed_result(
    *,
    case_id: str,
    employee_id: str,
    question: str,
    reason: str,
    explanation: str,
    calls: List[Dict[str, Any]],
    started: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    model_call_attempted: bool = False,
    top_k: int,
    temperature: float,
    model: str,
) -> PolicyOutputContract:
    total_tokens = prompt_tokens + completion_tokens
    return PolicyOutputContract(
        case_id=case_id,
        employee_id=employee_id,
        question=question,
        entitlement_value="",
        rule_cited="",
        explanation=explanation,
        passed=False,
        implementation="workflow",
        execution_mode="workflow",
        tool_calls=calls,
        iterations=1 if model_call_attempted else 0,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        token_source=f"{CHAT_BACKEND}_live" if total_tokens else "unavailable",
        cost_usd=round(total_tokens * TOKEN_COST_PROXY_RATE, 8),
        provider_cost="N/A",
        latency_ms=round(max(0.01, (time.perf_counter() - started) * 1000), 3),
        termination_reason=reason,
        top_k=top_k,
        temperature=temperature,
        model=model,
    )


def run_workflow_case(
    case_id: str,
    employee_id: str,
    question: str,
    deterministic_pass_criteria: Optional[List[str]] = None,
    top_k: int = 5,
    temperature: float = 0.3,
    model: str = LLM_MODEL,
    max_tokens: int = MAX_TOKENS,
    max_cost: float = MAX_COST,
    max_wall_clock: float = MAX_WALL_CLOCK_SECONDS,
    on_stage: Optional[Callable[[str], None]] = None,
) -> PolicyOutputContract:
    """Run one hard-coded tool sequence and exactly one final model call."""
    started = time.perf_counter()
    calls: List[Dict[str, Any]] = []
    valid = (
        type(top_k) is int and 1 <= top_k <= 20,
        isinstance(temperature, (int, float))
        and math.isfinite(temperature)
        and 0 <= temperature <= 1,
        isinstance(model, str) and bool(model.strip()),
        type(max_tokens) is int and 1 <= max_tokens <= MAX_TOKENS,
        isinstance(max_cost, (int, float))
        and math.isfinite(max_cost)
        and 0 < max_cost <= MAX_COST,
        isinstance(max_wall_clock, (int, float))
        and math.isfinite(max_wall_clock)
        and 0 < max_wall_clock <= MAX_WALL_CLOCK_SECONDS,
    )
    if not all(valid):
        return _failed_result(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            reason="INVALID_ARGUMENTS",
            explanation="Workflow configuration exceeds supported limits.",
            calls=calls,
            started=started,
            top_k=top_k,
            temperature=temperature,
            model=model,
        )

    if on_stage:
        on_stage("Step 1: Employee lookup")
    employee = _record_tool_call(
        calls, 1, "get_employee_record", {"employee_id": employee_id}
    )
    if not employee.get("found"):
        return _failed_result(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            reason="INVALID_EMPLOYEE",
            explanation=employee.get(
                "error", f"Employee record '{employee_id}' was not found."
            ),
            calls=calls,
            started=started,
            top_k=top_k,
            temperature=temperature,
            model=model,
        )

    if on_stage:
        on_stage("Step 2: Handbook search")
    handbook = _record_tool_call(
        calls,
        2,
        "search_handbook",
        {"query": question, "top_k": top_k},
    )
    evidence: Dict[str, Any] = {
        "employee_record": employee,
        "handbook_results": handbook,
    }

    if _requires_jurisdiction_rules(question):
        if on_stage:
            on_stage("Step 3: Jurisdiction rule lookup")
        jurisdiction = JurisdictionEnum(employee["jurisdiction"])
        category = _policy_category(question)
        evidence["jurisdiction_rules"] = _record_tool_call(
            calls,
            3,
            "get_jurisdiction_rules",
            {
                "jurisdiction": jurisdiction.value,
                "policy_category": category.value,
            },
        )

    if on_stage:
        on_stage("Final answer synthesis")
    remaining = max_wall_clock - (time.perf_counter() - started)
    if remaining <= 0:
        return _failed_result(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            reason="BUDGET_WALL_CLOCK",
            explanation="Workflow stopped before synthesis because its time budget expired.",
            calls=calls,
            started=started,
            top_k=top_k,
            temperature=temperature,
            model=model,
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You answer HR policy questions using only the supplied employee "
                "record and policy evidence. Account for the employee's tenure, "
                "employment status, jurisdiction, and separation reason when they "
                "affect the answer. If evidence is insufficient, say so. Return "
                'only one JSON object with string fields "entitlement_value", '
                '"rule_cited", and "explanation".'
            ),
        },
        {
            "role": "user",
            "content": (
                f"Employee ID: {employee_id}\n"
                f"Question: {question}\n"
                f"Requested handbook result limit: {top_k}\n"
                f"Evidence:\n{json.dumps(evidence, ensure_ascii=False)}"
            ),
        },
    ]
    cost_token_limit = int(max_cost / TOKEN_COST_PROXY_RATE)
    allowed_tokens = min(max_tokens, cost_token_limit)
    if allowed_tokens < 1:
        return _failed_result(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            reason="BUDGET_COST",
            explanation="Workflow stopped before synthesis because its cost budget was exhausted.",
            calls=calls,
            started=started,
            top_k=top_k,
            temperature=temperature,
            model=model,
        )
    try:
        response, prompt_tokens, completion_tokens, _ = call_policy_model_once(
            messages,
            model=model,
            temperature=temperature,
            timeout=remaining,
            max_tokens=allowed_tokens,
        )
    except PolicyAgentError as exc:
        return _failed_result(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            reason=exc.reason,
            explanation="The configured model failed during workflow synthesis.",
            calls=calls,
            started=started,
            model_call_attempted=True,
            top_k=top_k,
            temperature=temperature,
            model=model,
        )

    total_tokens = prompt_tokens + completion_tokens
    cost = total_tokens * TOKEN_COST_PROXY_RATE
    elapsed = time.perf_counter() - started
    if elapsed > max_wall_clock:
        reason = "BUDGET_WALL_CLOCK"
    elif total_tokens > max_tokens:
        reason = "BUDGET_TOKENS"
    elif cost > max_cost:
        reason = "BUDGET_COST"
    else:
        reason = ""
    if reason:
        return _failed_result(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            reason=reason,
            explanation=f"Workflow synthesis exceeded the {reason.lower()} limit.",
            calls=calls,
            started=started,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model_call_attempted=True,
            top_k=top_k,
            temperature=temperature,
            model=model,
        )

    try:
        answer = parse_policy_answer(response.get("message", {}).get("content"))
    except PolicyAgentError as exc:
        return _failed_result(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            reason=exc.reason,
            explanation="The configured model returned an invalid workflow answer.",
            calls=calls,
            started=started,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model_call_attempted=True,
            top_k=top_k,
            temperature=temperature,
            model=model,
        )

    answer_text = " ".join(answer.values()).lower()
    passed = (
        all(
            criterion.lower() in answer_text
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
        implementation="workflow",
        execution_mode="workflow",
        tool_calls=calls,
        iterations=1,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        token_source=f"{CHAT_BACKEND}_live",
        cost_usd=round(cost, 8),
        provider_cost="N/A",
        latency_ms=round(max(0.01, (time.perf_counter() - started) * 1000), 3),
        termination_reason="SUCCESS",
        top_k=top_k,
        temperature=temperature,
        model=model,
    )
