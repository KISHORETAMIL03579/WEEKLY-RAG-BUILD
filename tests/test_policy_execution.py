# tests/test_policy_execution.py — Unit and Integration Tests for HR Policy Assistant
import json
import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.schemas.policy import (
    JurisdictionEnum,
    PolicyOutputContract,
    PolicyCategoryEnum,
    MAX_COST,
    MAX_ITERATIONS,
    MAX_RETRIES,
    MAX_TOKENS,
    MAX_WALL_CLOCK_SECONDS,
)
from backend.routes.policy import _run_with_retries
from backend.services.policy_router import MODE_AGENT
from backend.services.policy_tools import (
    CANONICAL_EMPLOYEES,
    get_employee_record,
    search_handbook,
    get_jurisdiction_rules,
)
from backend.services.policy_workflow import run_workflow_case
from backend.services.policy_agent import run_agent_case
from tests.policy_test_utils import run_scripted_agent_case


class TestPolicyExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = TestClient(cls.app)
        with open("benchmarks/policy_execution/cases.json", "r", encoding="utf-8") as f:
            cls.benchmark_cases = json.load(f)

    def test_canonical_employees_loaded(self):
        self.assertEqual(len(CANONICAL_EMPLOYEES), 10)
        for i in range(1, 11):
            emp_id = f"EMP{i:03d}"
            self.assertIn(emp_id, CANONICAL_EMPLOYEES)
            emp = CANONICAL_EMPLOYEES[emp_id]
            self.assertTrue(emp.name)
            self.assertTrue(emp.department)
            self.assertIn(emp.employment_status, ["Confirmed", "Probation"])

    def test_tool_get_employee_record(self):
        res = get_employee_record("EMP001")
        self.assertTrue(res.get("found"))
        self.assertEqual(res.get("name"), "Sarah Mwangi")
        miss = get_employee_record("EMP999")
        self.assertFalse(miss.get("found"))

    def test_tool_search_handbook(self):
        results = search_handbook("annual leave entitlement accrual")
        self.assertGreater(len(results), 0)
        sections = [r["section"] for r in results]
        self.assertTrue(any("5.2" in s for s in sections))

    def test_tool_get_jurisdiction_rules(self):
        res = get_jurisdiction_rules(JurisdictionEnum.KENYA, PolicyCategoryEnum.LEAVE)
        self.assertEqual(res.get("jurisdiction"), "Kenya")
        self.assertIn("21 working days", res.get("statutory_guideline", ""))

    def test_all_10_agent_cases_pass(self):
        for case in self.benchmark_cases:
            cid = case["case_id"]
            empid = case["employee_id"]
            q = case["question"]
            crit = case["deterministic_pass_criteria"]
            result = run_scripted_agent_case(
                cid, empid, q, deterministic_pass_criteria=crit
            )
            self.assertEqual(result.termination_reason, "SUCCESS")
            self.assertTrue(
                result.passed, f"Agent failed on {cid}: {result.explanation}"
            )
            self.assertLessEqual(result.total_tokens, MAX_TOKENS)

    def test_all_10_workflow_cases_pass(self):
        for case in self.benchmark_cases:
            cid = case["case_id"]
            empid = case["employee_id"]
            q = case["question"]
            crit = case["deterministic_pass_criteria"]
            result = run_workflow_case(cid, empid, q, deterministic_pass_criteria=crit)
            self.assertEqual(result.termination_reason, "SUCCESS")
            self.assertTrue(
                result.passed, f"Workflow failed on {cid}: {result.explanation}"
            )
            self.assertEqual(result.iterations, 1)

    def test_agent_budget_enforcement(self):
        res = run_agent_case("t1", "EMP001", "q", force_budget_trap="iterations")
        self.assertEqual(res.termination_reason, "BUDGET_ITERATIONS")
        res = run_agent_case("t2", "EMP001", "q", force_budget_trap="tokens")
        self.assertEqual(res.termination_reason, "BUDGET_TOKENS")

    def test_policy_retries_accumulate_usage_and_attempt_provenance(self):
        failed_attempt = PolicyOutputContract(
            case_id="retry-case",
            employee_id="EMP001",
            question="What is the leave policy?",
            entitlement_value="",
            rule_cited="",
            explanation="Provider temporarily unavailable.",
            implementation="agent",
            execution_mode="agent",
            termination_reason="OLLAMA_UNAVAILABLE",
            prompt_tokens=3,
            completion_tokens=2,
            total_tokens=5,
            token_source="ollama_live",
            cost_usd=0.0000025,
            llm_calls=[
                {
                    "call_index": 1,
                    "attempt": 1,
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                    "token_source": "ollama_live",
                }
            ],
        )
        successful_attempt = PolicyOutputContract(
            case_id="retry-case",
            employee_id="EMP001",
            question="What is the leave policy?",
            entitlement_value="24 working days",
            rule_cited="Section 5.2",
            explanation="The handbook provides 24 days.",
            passed=True,
            implementation="agent",
            execution_mode="agent",
            termination_reason="SUCCESS",
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            token_source="ollama_live",
            cost_usd=0.000009,
            llm_calls=[
                {
                    "call_index": 1,
                    "attempt": 1,
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "total_tokens": 18,
                    "token_source": "ollama_live",
                }
            ],
        )
        with patch(
            "backend.routes.policy.run_agent_case",
            side_effect=[failed_attempt, successful_attempt],
        ) as run_agent:
            result, retry_history = _run_with_retries(
                mode=MODE_AGENT,
                employee_id="EMP001",
                question="What is the leave policy?",
                case_id="retry-case",
                top_k=5,
                temperature=0.3,
                model="llama3.1:8b",
                max_retries=1,
            )

        self.assertEqual(result.prompt_tokens, 14)
        self.assertEqual(result.completion_tokens, 9)
        self.assertEqual(result.total_tokens, 23)
        self.assertAlmostEqual(result.cost_usd, 0.0000115)
        self.assertEqual(result.attempt, 2)
        self.assertEqual(result.total_attempts, 2)
        self.assertEqual([entry["attempt"] for entry in retry_history], [1, 2])
        self.assertEqual([call["call_index"] for call in result.llm_calls], [1, 2])
        self.assertEqual([call["is_retry"] for call in result.llm_calls], [False, True])
        retry_kwargs = run_agent.call_args_list[1].kwargs
        self.assertEqual(retry_kwargs["max_tokens"], MAX_TOKENS - 5)
        self.assertAlmostEqual(retry_kwargs["max_cost"], MAX_COST - 0.0000025)

    def test_fastapi_policy_endpoints(self):
        resp = self.client.get("/api/policy/cases")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 10)

        resp = self.client.get("/api/policy/employees")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 10)

        with (
            patch(
                "backend.routes.policy.run_agent_case",
                side_effect=run_scripted_agent_case,
            ),
            patch(
                "backend.services.policy_benchmark_runner.run_agent_case",
                side_effect=run_scripted_agent_case,
            ),
        ):
            agent_resp = self.client.post(
                "/api/policy/agent",
                json={"employee_id": "EMP001", "question": "What is annual leave?"},
            )
            self.assertEqual(agent_resp.status_code, 200)

            workflow_resp = self.client.post(
                "/api/policy/workflow",
                json={"employee_id": "EMP001", "question": "What is annual leave?"},
            )
            self.assertEqual(workflow_resp.status_code, 200)

            resp = self.client.post("/api/policy/benchmark")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["summary"]["agent"]["pass_rate_pct"], 100.0)

    def test_policy_model_list_returns_installed_chat_models_only(self):
        ollama_response = MagicMock()
        ollama_response.__enter__.return_value = ollama_response
        ollama_response.read.return_value = json.dumps(
            {
                "models": [
                    {"name": "llama3.1:8b", "capabilities": ["completion", "tools"]},
                    {"name": "llava:latest", "capabilities": ["completion", "vision"]},
                    {"name": "nomic-embed-text:latest", "capabilities": ["embedding"]},
                ]
            }
        ).encode()
        with patch(
            "backend.routes.policy.urllib.request.urlopen",
            return_value=ollama_response,
        ):
            response = self.client.get("/api/policy/models")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["models"], ["llama3.1:8b", "llava:latest"])
        self.assertEqual(response.json()["agent_models"], ["llama3.1:8b"])
        self.assertEqual(response.json()["default_model"], "llama3.1:8b")

    def test_policy_search_does_not_retry_a_missing_agent_model(self):
        result = PolicyOutputContract(
            case_id="missing-model",
            employee_id="EMP001",
            question="Compare leave rules",
            entitlement_value="",
            rule_cited="",
            explanation="Ollama model is not installed.",
            implementation="agent",
            execution_mode="agent",
            termination_reason="MODEL_NOT_FOUND",
        )
        with patch(
            "backend.routes.policy.run_agent_case",
            return_value=result,
        ) as run_agent:
            response = self.client.post(
                "/api/policy/search",
                json={
                    "employee_id": "EMP001",
                    "question": "Compare leave rules",
                    "force_mode": "agent",
                    "model": "llama3.2:3b",
                    "max_retries": 2,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(run_agent.call_count, 1)
        self.assertEqual(response.json()["termination_reason"], "MODEL_NOT_FOUND")
        self.assertEqual(response.json()["total_attempts"], 1)
        self.assertFalse(response.json()["retry_history"][0]["retryable"])

    def test_policy_search_passes_agent_config_and_marks_workflow_config_unused(self):
        agent_result = PolicyOutputContract(
            case_id="api-config",
            employee_id="EMP001",
            question="Compare leave rules",
            entitlement_value="24 days",
            rule_cited="Section 5.2",
            explanation="Grounded test result.",
            passed=True,
            implementation="agent",
            execution_mode="agent",
            termination_reason="SUCCESS",
        )
        with patch(
            "backend.routes.policy.run_agent_case",
            return_value=agent_result,
        ) as run_agent:
            agent_response = self.client.post(
                "/api/policy/search",
                json={
                    "employee_id": "EMP001",
                    "question": "Compare leave rules",
                    "force_mode": "agent",
                    "top_k": 7,
                    "temperature": 0.65,
                    "model": "llama3.1:8b",
                    "max_retries": 0,
                },
            )

        self.assertEqual(agent_response.status_code, 200)
        self.assertEqual(run_agent.call_args.kwargs["top_k"], 7)
        self.assertEqual(run_agent.call_args.kwargs["temperature"], 0.65)
        self.assertEqual(run_agent.call_args.kwargs["model"], "llama3.1:8b")
        self.assertEqual(agent_response.json()["top_k"], 7)
        self.assertEqual(agent_response.json()["temperature"], 0.65)
        self.assertEqual(agent_response.json()["model"], "llama3.1:8b")

        with patch(
            "backend.routes.policy.run_workflow_case",
            wraps=run_workflow_case,
        ) as run_workflow:
            workflow_response = self.client.post(
                "/api/policy/search",
                json={
                    "employee_id": "EMP001",
                    "question": "What is annual leave?",
                    "force_mode": "workflow",
                    "top_k": 7,
                    "temperature": 0.65,
                    "model": "llama3.1:8b",
                    "max_retries": 0,
                },
            )

        self.assertEqual(workflow_response.status_code, 200)
        self.assertEqual(run_workflow.call_args.kwargs["top_k"], 7)
        self.assertIsNone(workflow_response.json()["temperature"])
        self.assertIsNone(workflow_response.json()["model"])

    def test_policy_search_rejects_retry_limit_above_hard_cap(self):
        response = self.client.post(
            "/api/policy/search",
            json={
                "employee_id": "EMP001",
                "question": "What is the annual leave entitlement?",
                "max_retries": MAX_RETRIES + 1,
            },
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
