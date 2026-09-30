# backend/services/policy_router.py — workflow-or-agent routing
#
# Decision rule (Week 7): use the fixed workflow when the tool path is the same for
# every input; use the agent when the path can vary. The router uses no model and no
# hard-coded question templates: it asks the same declarative rules the tool audit uses
# (backend/data/tool_expectations.json) which tools a question needs, and compares that
# with what the fixed workflow can do.
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from backend.services.policy_trajectory import matching_rules
from backend.services.policy_workflow import EMPLOYEE_TOOL, JURISDICTION_TOOL, SEARCH_TOOL

COMPLEXITY_SIMPLE = "SIMPLE"
COMPLEXITY_MODERATE = "MODERATE"
COMPLEXITY_COMPLEX = "COMPLEX"

MODE_WORKFLOW = "workflow"
MODE_AGENT = "agent"

# The only tools the fixed workflow is wired to call.
WORKFLOW_TOOLS = {EMPLOYEE_TOOL, SEARCH_TOOL, JURISDICTION_TOOL}

_EMPLOYEE_ID = re.compile(r"\bemp[-_]?\w*\d+\b", re.IGNORECASE)
_COMPARISON = re.compile(r"\bcompare\b|\bversus\b|\bvs\.?\b|\bdifference between\b|\bdiffer\b", re.IGNORECASE)


@dataclass
class RoutingDecision:
    """Routing decision returned to the caller and the UI."""

    mode: str  # "workflow" | "agent"
    complexity: str  # "SIMPLE" | "MODERATE" | "COMPLEX"
    reason: str
    requires_agent: bool
    routing_ms: float = 0.0
    routing_id: str = field(default_factory=lambda: f"route_{uuid.uuid4().hex[:8]}")
    matched_signals: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "complexity": self.complexity,
            "reason": self.reason,
            "requires_agent": self.requires_agent,
            "routing_ms": round(self.routing_ms, 3),
            "routing_id": self.routing_id,
            "matched_signals": self.matched_signals,
        }


def route_policy_question(question: str, employee_id: Optional[str] = None) -> RoutingDecision:
    """Pick the fixed workflow or the agent for ``question``.

    Agent when the path can vary: several employees are named, the question compares
    things, or it needs a tool the fixed workflow is not wired to call (for example the
    HRIS). Otherwise the sequence employee -> policy search (-> jurisdiction rules) is the
    same for every input and the cheaper fixed workflow is used.
    """
    started = time.perf_counter()
    text = question or ""
    signals: List[str] = []
    rules = matching_rules(text)

    employees = {match.group(0).upper() for match in _EMPLOYEE_ID.finditer(text)}
    if employee_id:
        employees.add(employee_id.upper())
    if len(employees) > 1:
        signals.append("AGENT_SIGNAL: several employees named")
        reason = "Several employees are named, so the number of lookups depends on the question."
    elif _COMPARISON.search(text):
        signals.append("AGENT_SIGNAL: comparison")
        reason = "A comparison needs evidence for each side, so the path depends on what is found."
    else:
        outside = sorted(
            {tool for rule in rules for tool in rule["requires_any"]} - WORKFLOW_TOOLS
        )
        if outside:
            signals.append(f"AGENT_SIGNAL: needs {', '.join(outside)}")
            reason = (
                f"The question needs {', '.join(outside)}, which the fixed workflow is not wired to call."
            )
        else:
            reason = ""
    if signals:
        return RoutingDecision(
            MODE_AGENT, COMPLEXITY_COMPLEX, reason, True,
            (time.perf_counter() - started) * 1000, matched_signals=signals,
        )

    local_rules = any(rule["id"] == "local_rules" for rule in rules)
    return RoutingDecision(
        MODE_WORKFLOW,
        COMPLEXITY_MODERATE if local_rules else COMPLEXITY_SIMPLE,
        (
            "Local-rule question: the fixed sequence adds one data-dependent step (jurisdiction "
            "read from the employee record) but the tool set is fixed."
            if local_rules
            else "One employee, one policy topic: employee lookup then policy search, the same for every input."
        ),
        False,
        (time.perf_counter() - started) * 1000,
        matched_signals=[f"WORKFLOW_SIGNAL: {rule['id']}" for rule in rules] or ["DEFAULT_SINGLE_EMPLOYEE"],
    )
