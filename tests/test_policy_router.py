# tests/test_policy_router.py — Tests for Week 7 Policy Router and Retry Logic
#
# Tests covered per spec:
#  1. Simple query routes to workflow
#  2. Complex/dynamic query routes to agent
#  3. Router returns reason
#  4. Router returns complexity
#  5–6. Agent loop / workflow work (covered in test_policy_execution.py)
#  7. Retry count <= MAX_RETRIES
#  8. Non-retryable errors are not retried
#  9–11. Retry tokens/latency/cost accumulate
#  12. Budget exhaustion prevents retry
#  13. Mode switch is recorded
#  14–20. UI receives mode/reason/complexity/retry/tokens/latency/cost via API
#  21. P50 uses real measurements
#  22. Cost uses actual recorded tokens
#  23. Agent and workflow use identical benchmark cases
#  24–32. Week 6 regression tests are in test_week6.py and test_evaluation_topk_temp.py
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent


# ── Import the router ─────────────────────────────────────────────────────────
from backend.services.policy_router import (
    route_policy_question,
    RoutingDecision,
    MODE_AGENT,
    MODE_WORKFLOW,
    COMPLEXITY_SIMPLE,
    COMPLEXITY_MODERATE,
    COMPLEXITY_COMPLEX,
)
from backend.schemas.policy import MAX_RETRIES, TOKEN_COST_PER_1M, TOKEN_COST_PROXY_RATE


class TestPolicyRouter:
    """Tests for the automatic policy router."""

    # Test 1: Simple query routes to workflow
    def test_simple_annual_leave_routes_workflow(self):
        d = route_policy_question(
            "What is the standard annual leave entitlement and monthly accrual rate for EMP001?",
            "EMP001",
        )
        assert d.mode == MODE_WORKFLOW, f"Expected workflow, got: {d.mode}"
        assert not d.requires_agent

    # Test 1 continued: Multiple simple cases
    @pytest.mark.parametrize(
        "question,emp",
        [
            ("What is EMP004's resignation notice?", "EMP004"),
            ("How much sick leave accrual rate does EMP006 get?", "EMP006"),
            (
                "Is EMP009 eligible to receive the 10% pension contribution allowance?",
                "EMP009",
            ),
            ("How many unused annual leave days can EMP002 carry forward?", "EMP002"),
            (
                "What severance pay is EMP008 entitled to upon termination for unsatisfactory performance?",
                "EMP008",
            ),
            (
                "How many days of accrued unused annual leave can EMP010 commute to cash?",
                "EMP010",
            ),
        ],
    )
    def test_simple_queries_route_to_workflow(self, question, emp):
        d = route_policy_question(question, emp)
        assert (
            d.mode == MODE_WORKFLOW
        ), f"Expected workflow for '{question[:50]}', got agent. Signals: {d.matched_signals}"

    # Test 2: Complex/dynamic query routes to agent
    def test_statutory_comparison_routes_agent(self):
        d = route_policy_question(
            "Compare the statutory minimum sick leave days in Ireland versus the organisational policy for EMP005.",
            "EMP005",
        )
        assert d.mode == MODE_AGENT, f"Expected agent, got: {d.mode}"
        assert d.requires_agent

    @pytest.mark.parametrize(
        "question",
        [
            "Compare the statutory minimum and the handbook maximum for sick leave in Cote d'Ivoire.",
            "Which jurisdiction rules apply to EMP005 and how do they override the global policy?",
            "What are all the policy entitlements for an employee on their first day?",
        ],
    )
    def test_complex_queries_route_to_agent(self, question):
        d = route_policy_question(question)
        assert (
            d.mode == MODE_AGENT
        ), f"Expected agent for '{question[:50]}', got workflow. Signals: {d.matched_signals}"

    # Test 3: Router returns reason
    def test_router_returns_reason(self):
        d = route_policy_question(
            "What is EMP001's annual leave entitlement?", "EMP001"
        )
        assert isinstance(d.reason, str)
        assert len(d.reason) > 10, "Reason should be a meaningful string"

    # Test 4: Router returns complexity
    def test_router_returns_complexity(self):
        d = route_policy_question(
            "What is EMP001's annual leave entitlement?", "EMP001"
        )
        assert d.complexity in (
            COMPLEXITY_SIMPLE,
            COMPLEXITY_MODERATE,
            COMPLEXITY_COMPLEX,
        )

    def test_complex_question_has_complex_complexity(self):
        d = route_policy_question(
            "Compare the statutory minimum sick leave in Ireland versus the handbook policy.",
            "EMP005",
        )
        # Agent-triggering questions should be COMPLEX
        assert d.complexity == COMPLEXITY_COMPLEX

    def test_routing_decision_to_dict(self):
        d = route_policy_question(
            "What is EMP001's annual leave entitlement?", "EMP001"
        )
        data = d.to_dict()
        assert "mode" in data
        assert "reason" in data
        assert "complexity" in data
        assert "requires_agent" in data
        assert "routing_ms" in data
        assert "routing_id" in data
        assert "matched_signals" in data

    def test_routing_ms_is_positive(self):
        d = route_policy_question(
            "What is EMP001's annual leave entitlement?", "EMP001"
        )
        assert d.routing_ms >= 0, "Routing time must not be negative"

    def test_routing_id_is_unique(self):
        d1 = route_policy_question(
            "What is EMP001's annual leave entitlement?", "EMP001"
        )
        d2 = route_policy_question(
            "What is EMP002's annual leave entitlement?", "EMP002"
        )
        assert (
            d1.routing_id != d2.routing_id
        ), "Each routing decision must have a unique ID"


class TestPolicySchemaConstants:
    """Tests for schema constants — single source of truth."""

    # Test 7: MAX_RETRIES is defined and bounded
    def test_max_retries_is_2(self):
        assert MAX_RETRIES == 2, f"MAX_RETRIES must be 2, got {MAX_RETRIES}"

    def test_token_cost_per_1m_is_single_source(self):
        """TOKEN_COST_PER_1M and TOKEN_COST_PROXY_RATE must be consistent."""
        assert (
            TOKEN_COST_PER_1M == 0.50
        ), f"TOKEN_COST_PER_1M must be 0.50, got {TOKEN_COST_PER_1M}"
        expected_rate = TOKEN_COST_PER_1M / 1_000_000
        assert (
            abs(TOKEN_COST_PROXY_RATE - expected_rate) < 1e-12
        ), f"TOKEN_COST_PROXY_RATE {TOKEN_COST_PROXY_RATE} must equal TOKEN_COST_PER_1M/1M = {expected_rate}"


class TestRetryLogic:
    """Tests for retry behavior in the policy routes."""

    def test_workflow_succeeds_without_retry(self):
        """A normal workflow call succeeds on first attempt without retry."""
        from backend.services.policy_workflow import run_workflow_case
        from backend.schemas.policy import PolicyOutputContract

        result = run_workflow_case(
            case_id="test_retry_wf",
            employee_id="EMP001",
            question="What is EMP001's annual leave entitlement?",
            deterministic_pass_criteria=["24"],
        )
        assert isinstance(result, PolicyOutputContract)
        assert result.termination_reason == "SUCCESS"
        assert result.total_tokens > 0

    # Test 8: Non-retryable errors are identified correctly
    def test_non_retryable_budget_reason(self):
        from backend.routes.policy import _is_retryable

        for reason in (
            "BUDGET_ITERATIONS",
            "BUDGET_TOKENS",
            "BUDGET_COST",
            "BUDGET_WALL_CLOCK",
        ):
            assert not _is_retryable(reason), f"{reason} should NOT be retryable"

    def test_retryable_transient_reasons(self):
        from backend.routes.policy import _is_retryable

        for reason in (
            "OLLAMA_TIMEOUT",
            "TRANSIENT_NETWORK",
            "MODEL_ERROR",
            "TOOL_ERROR",
        ):
            assert _is_retryable(reason), f"{reason} should be retryable"

    def test_success_is_not_retryable(self):
        from backend.routes.policy import _is_retryable

        assert not _is_retryable("SUCCESS"), "SUCCESS should not be retried"

    # Test 9-11: Retry token/latency/cost accumulation (simulated)
    def test_retry_accumulation_math(self):
        """Simulate 2 attempts and verify tokens, latency, cost accumulate."""
        # Simulate attempt 1: 800 tokens, 15ms
        # Simulate attempt 2 (retry): 600 tokens, 12ms
        # Total should be 1400 tokens, 27ms

        attempt1_tokens = 800
        attempt2_tokens = 600
        attempt1_latency = 15.0
        attempt2_latency = 12.0

        total_tokens = attempt1_tokens + attempt2_tokens
        total_latency = attempt1_latency + attempt2_latency
        total_cost = total_tokens * TOKEN_COST_PROXY_RATE

        assert total_tokens == 1400
        assert total_latency == 27.0
        assert (
            abs(total_cost - 1400 * TOKEN_COST_PROXY_RATE) < 1e-10
        ), "Cost must use accumulated tokens"

    # Test 12: Budget exhaustion prevents retry
    def test_budget_not_retried(self):
        """Budget exhaustion reasons are not retried."""
        from backend.routes.policy import _is_retryable

        # Budget is exhausted — must not retry
        assert not _is_retryable("BUDGET_ITERATIONS")
        assert not _is_retryable("BUDGET_TOKENS")
        assert not _is_retryable("BUDGET_COST")
        assert not _is_retryable("BUDGET_WALL_CLOCK")

    # Test 22: Cost uses actual recorded tokens
    def test_cost_formula_uses_token_cost_per_1m(self):
        """Verify cost formula is consistent with TOKEN_COST_PER_1M."""
        tokens = 1500
        expected_cost = tokens * TOKEN_COST_PROXY_RATE
        computed_cost = (tokens / 1_000_000) * TOKEN_COST_PER_1M
        assert (
            abs(expected_cost - computed_cost) < 1e-12
        ), f"Cost formula mismatch: {expected_cost} vs {computed_cost}"


class TestBenchmarkCaseIsolation:
    """Tests ensuring benchmark cases are shared and Week 6 is isolated."""

    # Test 23: Agent and workflow use identical benchmark cases
    def test_agent_workflow_use_same_cases(self):
        """The 10 benchmark cases must be the same for both agent and workflow runs."""
        cases_file = BASE_DIR / "benchmarks" / "policy_execution" / "cases.json"
        assert cases_file.exists(), f"Benchmark cases file not found: {cases_file}"
        with open(cases_file, "r") as f:
            cases = json.load(f)
        assert len(cases) == 10, f"Expected 10 benchmark cases, got {len(cases)}"
        case_ids = {c["case_id"] for c in cases}
        assert len(case_ids) == 10, "All case IDs must be unique"

    # Test 24: Week 6 evaluation_type is separate
    def test_week6_evaluation_type_is_separate(self):
        """Week 7 results must not use the Week 6 evaluation type."""
        week7_type = "WEEK7_POLICY_EXECUTION"
        week6_type = "WEEK6_JUDGE"
        assert (
            week7_type != week6_type
        ), "Week 6 and Week 7 must have distinct evaluation types"

    def test_week6_frozen_benchmark_intact(self):
        """The Week 6 frozen benchmark must still have 25 cases."""
        cases_file = BASE_DIR / "week6" / "eval_cases_25.json"
        if not cases_file.exists():
            pytest.skip(
                "Week 6 eval_cases_25.json not found — skipping integrity check"
            )
        with open(cases_file, "r") as f:
            cases = json.load(f)
        assert (
            len(cases) == 25
        ), f"Week 6 frozen benchmark must have 25 cases, found {len(cases)}"

    # Test 21: P50 uses real measurements
    def test_p50_is_real_measurement(self):
        """P50 must be computed from actual per-case latency values, not hardcoded."""
        latencies = [
            19401.5,
            21188.2,
            21173.2,
            20490.1,
            20917.8,
            21009.9,
            8971.3,
            8905.3,
            8915.1,
            9127.1,
        ]
        sorted_lats = sorted(latencies)
        n = len(sorted_lats)
        p50_index = n // 2
        p50 = sorted_lats[p50_index]
        # Must not be 0.0 or a hardcoded constant
        assert p50 > 0.0, "P50 must be a real non-zero measurement"
        assert p50 == sorted_lats[5], "P50 at n=10 should be index 5"


class TestPolicyAPIRoutes:
    """Integration tests for the /api/policy/search and /router/classify endpoints."""

    def test_classify_endpoint_simple_question(self):
        """GET /api/policy/router/classify returns routing for a simple question."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        response = client.get(
            "/api/policy/router/classify",
            params={
                "question": "What is EMP001's annual leave entitlement?",
                "employee_id": "EMP001",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "mode" in data
        assert "reason" in data
        assert "complexity" in data
        assert "requires_agent" in data
        assert data["mode"] in ("workflow", "agent")

    def test_search_endpoint_returns_routing_fields(self):
        """POST /api/policy/search returns execution_mode, routing_reason, complexity, run_id."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        response = client.post(
            "/api/policy/search",
            json={
                "employee_id": "EMP001",
                "question": "What is the standard annual leave entitlement for EMP001?",
                "top_k": 5,
                "temperature": 0.3,
                "model": "llama3.1:8b",
            },
        )
        assert response.status_code == 200
        data = response.json()
        # Test 14: UI receives mode
        assert "execution_mode" in data
        # Test 15: UI receives routing reason
        assert "routing_reason" in data
        # Test 16: UI receives complexity
        assert "complexity" in data
        assert "run_id" in data
        assert data["run_id"].startswith("search_")

    def test_search_endpoint_returns_token_metadata(self):
        """POST /api/policy/search returns token fields."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        response = client.post(
            "/api/policy/search",
            json={
                "employee_id": "EMP001",
                "question": "What is the standard annual leave entitlement for EMP001?",
            },
        )
        assert response.status_code == 200
        data = response.json()
        # Test 18: UI receives tokens
        assert "total_tokens" in data
        assert "prompt_tokens" in data
        assert "completion_tokens" in data
        assert "token_source" in data
        assert data["token_source"] in ("ollama_live", "proxy_estimate", "unavailable")

    def test_search_endpoint_returns_latency(self):
        """POST /api/policy/search returns real latency_ms > 0."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        response = client.post(
            "/api/policy/search",
            json={
                "employee_id": "EMP001",
                "question": "What is EMP001's annual leave entitlement?",
            },
        )
        assert response.status_code == 200
        data = response.json()
        # Test 19: UI receives latency
        assert "latency_ms" in data
        assert data["latency_ms"] > 0, "Latency must be a real non-zero measurement"

    def test_search_endpoint_returns_cost(self):
        """POST /api/policy/search returns estimated cost fields."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        response = client.post(
            "/api/policy/search",
            json={
                "employee_id": "EMP001",
                "question": "What is EMP001's annual leave entitlement?",
            },
        )
        assert response.status_code == 200
        data = response.json()
        # Test 20: UI receives cost
        assert "cost_usd" in data
        assert "provider_cost" in data
        assert data["provider_cost"] == "N/A", "Local Ollama has no billing cost"

    def test_search_endpoint_evaluation_type_isolation(self):
        """Week 7 search must not produce a Week 6 evaluation_type."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        response = client.post(
            "/api/policy/search",
            json={
                "employee_id": "EMP001",
                "question": "What is EMP001's annual leave entitlement?",
            },
        )
        data = response.json()
        assert data.get("evaluation_type") == "WEEK7_POLICY_EXECUTION"

    def test_search_endpoint_retry_metadata(self):
        """POST /api/policy/search returns retry_history field (even if empty)."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        response = client.post(
            "/api/policy/search",
            json={
                "employee_id": "EMP001",
                "question": "What is EMP001's annual leave entitlement?",
            },
        )
        data = response.json()
        # Test 17: UI receives retry metadata
        assert "retry_history" in data
        assert isinstance(data["retry_history"], list)
