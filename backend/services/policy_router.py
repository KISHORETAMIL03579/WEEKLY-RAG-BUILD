# backend/services/policy_router.py — Production HR Policy Router
# Automatically decides between NORMAL WORKFLOW and AGENT execution
# for a given user HR policy question.
#
# Routing Principle:
#   WORKFLOW: execution path is fully deterministic once we know the question intent.
#   AGENT:    execution path depends on information discovered during execution
#             (i.e., the next tool depends on what a prior tool returned).
#
# This router does NOT use an LLM to classify. It uses rule-based heuristics
# over the question text and optional employee context hints.
#
# Complexity levels: SIMPLE | MODERATE | COMPLEX
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional


# ── Complexity levels ──────────────────────────────────────────────────────────
COMPLEXITY_SIMPLE = "SIMPLE"
COMPLEXITY_MODERATE = "MODERATE"
COMPLEXITY_COMPLEX = "COMPLEX"

# ── Mode labels ───────────────────────────────────────────────────────────────
MODE_WORKFLOW = "workflow"
MODE_AGENT = "agent"


@dataclass
class RoutingDecision:
    """Structured routing decision returned to the caller and the UI."""
    mode: str                       # "workflow" | "agent"
    complexity: str                 # "SIMPLE" | "MODERATE" | "COMPLEX"
    reason: str                     # Human-readable explanation
    requires_agent: bool            # Convenience boolean
    routing_ms: float = 0.0         # Time taken to make the routing decision
    routing_id: str = field(default_factory=lambda: f"route_{uuid.uuid4().hex[:8]}")
    matched_signals: List[str] = field(default_factory=list)  # Which rules triggered

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


# ── AGENT-triggering signals ───────────────────────────────────────────────────
# These patterns indicate the next tool CANNOT be determined without running
# a prior tool first — the execution path genuinely branches at runtime.

_AGENT_PATTERNS: List[tuple[str, str]] = [
    # Statutory vs organisational comparison: requires both handbook + jurisdiction tool
    (r"\bcompare\b.*\bstatutory\b|\bstatutory\b.*\bcompare\b", "Cross-comparison of statutory and organisational rules requires dynamic multi-tool execution"),
    (r"\boverride\b.*\bpolicy\b|\bpolicy\b.*\boverride\b", "Determining whether local law overrides policy requires dynamic tool discovery"),
    (r"\bstatutory\b.*\bminimum\b|\bminimum\b.*\bstatutory\b", "Statutory minimum comparison requires jurisdiction lookup after employee discovery"),
    # Cross-category questions: e.g., "leave AND pension AND notice"
    (r"\band\b.*\band\b", "Question crosses multiple policy domains requiring dynamic exploration"),
    # Conditional: "if she resigns AND is on probation AND has worked less than..."
    (r"\bif\b.*\band\b.*\bor\b|\bif\b.*\bor\b.*\band\b", "Complex conditional branching cannot be predetermined"),
    # Discovery-dependent: next step depends on whether employee qualifies
    (r"\beligible\b.*\band\b.*\bif\b|\bif\b.*\beligible\b", "Eligibility combined with conditional follow-up requires agent discovery"),
    # Comparison between two employees
    (r"\bemp\d+\b.*\bemp\d+\b", "Comparison between two employees requires independent lookup paths"),
    # Open-ended investigation
    (r"\bwhat all\b|\bwhat are all\b|\blist all\b|\blist every\b", "Open-ended enumeration requires agent to discover scope dynamically"),
    # Scenario with unknown employee attribute
    (r"\bdepending on\b|\bsubject to\b.*\bdiscovery\b", "Path depends on runtime discovery"),
    # Jurisdiction-specific question that must first find the employee's duty station
    (r"\bjurisdiction\b.*\bapply\b|\bapply\b.*\bjurisdiction\b|\bwhich jurisdiction\b", "Applicable jurisdiction cannot be determined without employee lookup first"),
    # Questions that combine notice period with severance and jurisdiction
    (r"\bnotice\b.*\bseverance\b.*\bjurisdiction\b|\bseverance\b.*\bnotice\b.*\bjurisdiction\b", "Notice + severance + jurisdiction requires dynamic 3-tool chain"),
]

# ── WORKFLOW-matching signals (definitive single-path questions) ────────────────
_WORKFLOW_PATTERNS: List[tuple[str, str]] = [
    (r"\bannual leave entitlement\b|\bleave entitlement\b|\bmonthly accrual\b", "Annual leave entitlement follows known employee→handbook sequence"),
    (r"\bcarry.?forward\b|\bcarryover\b", "Carry-forward cap is a single policy lookup"),
    (r"\bresignation notice\b|\bnotice.*resign\b|\bresign.*notice\b", "Resignation notice requires employee status then handbook lookup — deterministic"),
    (r"\bsick leave\b.*\baccrual\b|\baccrual\b.*\bsick leave\b", "Sick leave accrual rate is a single policy lookup"),
    (r"\bsick leave\b.*\beligib\b|\beligib\b.*\bsick leave\b", "Sick leave eligibility is determined by tenure threshold — deterministic"),
    (r"\bpension\b.*\bcontribution\b|\bcontribution\b.*\bpension\b", "Pension contribution lookup is a single employee-status check"),
    (r"\bseverance\b.*\bredundan\b|\bredundan\b.*\bseverance\b", "Redundancy severance follows fixed formula — deterministic"),
    (r"\bunsatisfactory performance\b|\bperformance.*terminat\b", "Unsatisfactory performance severance is a fixed policy rule"),
    (r"\bcommut\b.*\bann.*leave\b|\bann.*leave\b.*\bcommut\b", "Leave commutation cap is a single policy lookup"),
    (r"\bpension.*allowance\b|\ballowance.*pension\b", "Pension allowance eligibility is a single status check"),
    (r"\bnotice period\b", "Notice period is deterministic based on employment status"),
    (r"\bleave balance\b|\bannual leave balance\b", "Leave balance is a direct employee record lookup"),
]

# ── COMPLEXITY classification ──────────────────────────────────────────────────

_COMPLEX_SIGNALS: List[str] = [
    r"\band\b.*\band\b",           # Multiple AND conditions
    r"\bif\b.*\bthen\b",           # Conditional logic
    r"\bcompare\b",                # Comparison
    r"\bversus\b|\bvs\.?\b",      # Versus comparison
    r"\bstatutory\b",              # Statutory law reference
    r"\bjurisdiction\b",           # Jurisdiction-specific
    r"\bmultiple\b",               # Multiple items
]

_MODERATE_SIGNALS: List[str] = [
    r"\bseverance\b",              # Involves calculation
    r"\bnotice.*resign\b",         # Two-step lookup
    r"\beligib\b",                 # Eligibility check
    r"\bpension\b",                # Pension involves status branch
    r"\bcommut\b",                 # Commutation involves separation check
]


def _classify_complexity(question: str) -> str:
    """Classify question complexity based on linguistic signals."""
    q = question.lower()
    # Complex: multiple AND/conditionals, statutory, jurisdiction
    if any(re.search(sig, q) for sig in _COMPLEX_SIGNALS):
        return COMPLEXITY_COMPLEX
    # Moderate: calculations, eligibility branches, two-step lookups
    if any(re.search(sig, q) for sig in _MODERATE_SIGNALS):
        return COMPLEXITY_MODERATE
    return COMPLEXITY_SIMPLE


def route_policy_question(
    question: str,
    employee_id: Optional[str] = None,
) -> RoutingDecision:
    """
    Determine whether a policy question should be handled by WORKFLOW or AGENT.

    Decision rationale:
      - WORKFLOW when: the execution path is fully deterministic from question intent alone.
        E.g., "What is EMP003's annual leave entitlement?" always follows:
        employee_lookup → search_handbook → calculate → return.
      - AGENT when: the execution path cannot be safely predetermined.
        E.g., a question spanning multiple policy domains, or one that requires
        discovering an employee attribute (like duty station jurisdiction) before
        deciding which tool to call next.

    Key distinction: this is about EXECUTION PATH variation, not ANSWER variation.
    Different employees get different answers even via workflow (different tenure = different result),
    but the SEQUENCE of tools is the same. Only when the SEQUENCE itself must change
    based on runtime discovery does agent mode become justified.
    """
    t0 = time.perf_counter()
    q = question.lower().strip()
    matched_signals: List[str] = []

    # ── 1. Check for AGENT-triggering patterns ────────────────────────────────
    for pattern, reason in _AGENT_PATTERNS:
        if re.search(pattern, q):
            matched_signals.append(f"AGENT_SIGNAL: {pattern}")
            complexity = COMPLEXITY_COMPLEX
            routing_ms = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                mode=MODE_AGENT,
                complexity=complexity,
                reason=reason,
                requires_agent=True,
                routing_ms=routing_ms,
                matched_signals=matched_signals,
            )

    # ── 2. Check for definitive WORKFLOW patterns ─────────────────────────────
    for pattern, reason in _WORKFLOW_PATTERNS:
        if re.search(pattern, q):
            matched_signals.append(f"WORKFLOW_SIGNAL: {pattern}")
            complexity = _classify_complexity(q)
            routing_ms = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                mode=MODE_WORKFLOW,
                complexity=complexity,
                reason=reason,
                requires_agent=False,
                routing_ms=routing_ms,
                matched_signals=matched_signals,
            )

    # ── 3. Default: workflow for single-employee factual queries ──────────────
    # If the question mentions a single EMP ID and asks a simple factual question,
    # the execution path is always: lookup employee → lookup policy → synthesize.
    emp_id_mentioned = bool(re.search(r"\bemp\d+\b", q))
    if emp_id_mentioned or employee_id:
        complexity = _classify_complexity(q)
        routing_ms = (time.perf_counter() - t0) * 1000
        return RoutingDecision(
            mode=MODE_WORKFLOW,
            complexity=complexity,
            reason=(
                "The question can be answered using the standard employee lookup -> "
                "policy lookup -> calculation sequence. No runtime discovery of the "
                "execution path is required."
            ),
            requires_agent=False,
            routing_ms=routing_ms,
            matched_signals=["DEFAULT_SINGLE_EMPLOYEE"],
        )

    # ── 4. Fallback: use agent for unrecognised open-ended questions ──────────
    routing_ms = (time.perf_counter() - t0) * 1000
    return RoutingDecision(
        mode=MODE_AGENT,
        complexity=COMPLEXITY_MODERATE,
        reason=(
            "The question does not match a known deterministic policy sequence. "
            "An agent is selected to dynamically discover the required tools."
        ),
        requires_agent=True,
        routing_ms=routing_ms,
        matched_signals=["FALLBACK_AGENT"],
    )
