"""State and result assembly shared by the ReAct agent and the fixed workflow.

Both implementations answer with the same :class:`PolicyOutputContract`, record tool
calls in the same shape (selected tool, arguments, result, attempts/retries, model
rationale) and are audited by the same tool-selection audit, so the Week 7 race and
the Week 8 trajectory evaluation compare like with like.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.config import CHAT_BACKEND, logger
from backend.mcp.registry import McpToolRegistry, ToolOutcome, ToolSpec
from backend.schemas.policy import (
    MAX_COST,
    MAX_ITERATIONS,
    MAX_TOKENS,
    MAX_WALL_CLOCK_SECONDS,
    PolicyOutputContract,
    TOKEN_COST_PROXY_RATE,
)
from backend.services import policy_trajectory

TRACE_TEXT_LIMIT = 240
RETRYABLE_MODEL_REASONS = {"GROQ_TIMEOUT", "GROQ_UNAVAILABLE", "PROVIDER_TRANSIENT", "MODEL_ERROR"}


@dataclass
class RunState:
    case_id: str
    employee_id: str
    question: str
    top_k: int
    temperature: float
    model: str
    implementation: str = "agent"
    started: float = field(default_factory=time.perf_counter)
    calls: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    llm_calls: List[Dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    iteration: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float:
        return self.total_tokens * TOKEN_COST_PROXY_RATE

    def elapsed(self) -> float:
        return time.perf_counter() - self.started


def compact_observation(observation: Dict[str, Any]) -> Dict[str, Any]:
    """Trace copy of a tool result: retrieved passages keep metadata, text is clipped."""
    results = observation.get("results")
    if not isinstance(results, list):
        return observation
    clipped = [
        {**item, "text": str(item.get("text", ""))[:TRACE_TEXT_LIMIT]}
        if isinstance(item, dict)
        else item
        for item in results
    ]
    return {**observation, "results": clipped}


def record_tool_call(
    run: RunState,
    spec: ToolSpec,
    outcome: ToolOutcome,
    *,
    step: int,
    rationale: Optional[str],
    call_id: Optional[str] = None,
) -> None:
    run.calls.append(
        {
            "step": step,
            "tool_name": outcome.name,
            "server": outcome.server,
            "roles": spec.roles,
            "arguments": outcome.arguments,
            "output": compact_observation(outcome.observation),
            "is_error": outcome.is_error,
            "error": outcome.error,
            "attempts": outcome.attempts,
            "retries": outcome.retries,
            "attempt_log": outcome.attempt_log,
            "latency_ms": max(0.01, outcome.latency_ms),
            "selection": {"rationale": rationale, "call_id": call_id},
        }
    )


def record_llm_call(
    run: RunState,
    *,
    response: Optional[Dict[str, Any]] = None,
    error: Optional[Any] = None,
    usage: Tuple[int, int] = (0, 0),
    latency_ms: float = 0.0,
) -> None:
    """Append one model call, including how many provider attempts it took."""
    attempt_log = (response or {}).get("attempt_log") if response else getattr(error, "attempt_log", [])
    attempts = (
        (response or {}).get("provider_attempts", 1) if response else max(1, len(attempt_log or []))
    )
    reason = getattr(error, "reason", None)
    run.llm_calls.append(
        {
            "call_index": len(run.llm_calls) + 1,
            "attempt": 1,
            "is_retry": False,
            "provider_attempts": attempts,
            "provider_retries": max(0, attempts - 1),
            "provider_attempt_log": attempt_log or [],
            "input_tokens": usage[0],
            "output_tokens": usage[1],
            "total_tokens": usage[0] + usage[1],
            "latency_ms": round(latency_ms, 3),
            "token_source": f"{CHAT_BACKEND}_live" if error is None else "unavailable",
            "status": "SUCCESS" if error is None else "FAILED",
            "retry_reason": reason,
            "retryable": reason in RETRYABLE_MODEL_REASONS,
        }
    )


def budgets_valid(max_iterations: Any, max_tokens: Any, max_cost: Any, max_wall_clock: Any) -> bool:
    return all(
        (
            type(max_iterations) is int and 1 <= max_iterations <= MAX_ITERATIONS,
            type(max_tokens) is int and 1 <= max_tokens <= MAX_TOKENS,
            isinstance(max_cost, (int, float)) and math.isfinite(max_cost) and 0 < max_cost <= MAX_COST,
            isinstance(max_wall_clock, (int, float))
            and math.isfinite(max_wall_clock)
            and 0 < max_wall_clock <= MAX_WALL_CLOCK_SECONDS,
        )
    )


def finish(
    run: RunState,
    reason: str,
    explanation: str,
    registry: Optional[McpToolRegistry] = None,
    answer: Optional[Dict[str, str]] = None,
    scored: Optional[Dict[str, Any]] = None,
    citation: Optional[Dict[str, Any]] = None,
) -> PolicyOutputContract:
    live = any(str(call.get("token_source", "")).endswith("_live") for call in run.llm_calls)
    available = [spec.name for spec in registry.list_tools()] if registry else None
    if reason != "SUCCESS":
        logger.warning(
            "policy %s case=%s terminated reason=%s steps=%d tools=%s rejected=%d",
            run.implementation,
            run.case_id,
            reason,
            run.iteration,
            [call["tool_name"] for call in run.calls],
            len(run.rejected),
        )
    return PolicyOutputContract(
        case_id=run.case_id,
        employee_id=run.employee_id,
        question=run.question,
        entitlement_value=answer["entitlement_value"] if answer else "",
        rule_cited=answer["rule_cited"] if answer else "",
        explanation=answer["explanation"] if answer else explanation,
        passed=bool(scored and scored["passed"]),
        strict_passed=bool(scored and scored["strict_passed"]),
        answer_criteria=scored["criteria"] if scored else [],
        citation=citation or {},
        implementation=run.implementation,
        execution_mode=run.implementation,
        tool_calls=run.calls,
        rejected_tool_calls=run.rejected,
        tool_audit=policy_trajectory.audit_tool_selection(
            run.question, run.calls, run.rejected, run.llm_calls, available, reason
        ),
        iterations=run.iteration,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        total_tokens=run.total_tokens,
        token_source=f"{CHAT_BACKEND}_live" if live else "unavailable",
        llm_calls=run.llm_calls,
        cost_usd=round(run.cost_usd, 8),
        provider_cost="N/A",
        latency_ms=round(max(0.01, run.elapsed() * 1000), 3),
        termination_reason=reason,
        top_k=run.top_k,
        temperature=run.temperature,
        model=run.model,
    )
