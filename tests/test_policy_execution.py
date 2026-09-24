# tests/test_policy_execution.py — Unit and Integration Tests for HR Policy Assistant
import json
import unittest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.schemas.policy import (
    JurisdictionEnum,
    PolicyCategoryEnum,
    MAX_COST,
    MAX_ITERATIONS,
    MAX_TOKENS,
    MAX_WALL_CLOCK_SECONDS,
)
from backend.services.policy_tools import (
    CANONICAL_EMPLOYEES,
    get_employee_record,
    search_handbook,
    get_jurisdiction_rules,
    execute_tool_call,
)
from backend.services.policy_agent import run_agent_case
from backend.services.policy_workflow import run_workflow_case


class TestPolicyExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = TestClient(cls.app)
        
        # Load benchmark cases
        with open("benchmarks/policy_execution/cases.json", "r", encoding="utf-8") as f:
            cls.benchmark_cases = json.load(f)

    def test_canonical_employees_loaded(self):
        """Verify that all 10 canonical employees exist with required attributes."""
        self.assertEqual(len(CANONICAL_EMPLOYEES), 10)
        for i in range(1, 11):
            emp_id = f"EMP{i:03d}"
            self.assertIn(emp_id, CANONICAL_EMPLOYEES)
            emp = CANONICAL_EMPLOYEES[emp_id]
            self.assertTrue(emp.name)
            self.assertTrue(emp.department)
            self.assertIn(emp.employment_status, ["Confirmed", "Probation"])
            self.assertGreater(emp.tenure_months, 0)
            self.assertGreater(emp.basic_salary_monthly, 0)

    def test_tool_get_employee_record(self):
        """Verify get_employee_record tool returns expected structure and handles misses."""
        res = get_employee_record("EMP001")
        self.assertTrue(res.get("found"))
        self.assertEqual(res.get("name"), "Sarah Mwangi")
        self.assertEqual(res.get("jurisdiction"), "Kenya")

        miss = get_employee_record("EMP999")
        self.assertFalse(miss.get("found"))

    def test_tool_search_handbook(self):
        """Verify search_handbook retrieves relevant policy sections."""
        results = search_handbook("annual leave entitlement accrual")
        self.assertGreater(len(results), 0)
        sections = [r["section"] for r in results]
        self.assertTrue(any("5.2" in s for s in sections))

    def test_tool_get_jurisdiction_rules(self):
        """Verify get_jurisdiction_rules returns statutory guidelines."""
        res = get_jurisdiction_rules(JurisdictionEnum.KENYA, PolicyCategoryEnum.LEAVE)
        self.assertEqual(res.get("jurisdiction"), "Kenya")
        self.assertIn("21 working days", res.get("statutory_guideline", ""))

    def test_all_10_agent_cases_pass(self):
        """Verify that ReAct Agent achieves 10/10 PASS on benchmark cases."""
        for case in self.benchmark_cases:
            cid = case["case_id"]
            empid = case["employee_id"]
            q = case["question"]
            crit = case["deterministic_pass_criteria"]

            result = run_agent_case(cid, empid, q, deterministic_pass_criteria=crit)
            self.assertEqual(result.termination_reason, "SUCCESS")
            self.assertTrue(result.passed, f"Agent failed on {cid}: {result.explanation}")
            self.assertGreater(result.total_tokens, 0)
            self.assertLessEqual(result.total_tokens, MAX_TOKENS)
            self.assertLessEqual(result.cost_usd, MAX_COST)
            self.assertGreater(len(result.tool_calls), 0)

    def test_all_10_workflow_cases_pass(self):
        """Verify that Deterministic Workflow achieves 10/10 PASS on benchmark cases."""
        for case in self.benchmark_cases:
            cid = case["case_id"]
            empid = case["employee_id"]
            q = case["question"]
            crit = case["deterministic_pass_criteria"]

            result = run_workflow_case(cid, empid, q, deterministic_pass_criteria=crit)
            self.assertEqual(result.termination_reason, "SUCCESS")
            self.assertTrue(result.passed, f"Workflow failed on {cid}: {result.explanation}")
            self.assertGreater(result.total_tokens, 0)
            self.assertEqual(result.iterations, 1)

    def test_agent_budget_enforcement_iterations(self):
        """Verify agent terminates with BUDGET_ITERATIONS when iteration limit exceeded."""
        res = run_agent_case("test_iter", "EMP001", "test question", force_budget_trap="iterations")
        self.assertEqual(res.termination_reason, "BUDGET_ITERATIONS")
        self.assertFalse(res.passed)

    def test_agent_budget_enforcement_tokens(self):
        """Verify agent terminates with BUDGET_TOKENS when token limit exceeded."""
        res = run_agent_case("test_tok", "EMP001", "test question", force_budget_trap="tokens")
        self.assertEqual(res.termination_reason, "BUDGET_TOKENS")
        self.assertFalse(res.passed)

    def test_agent_budget_enforcement_cost(self):
        """Verify agent terminates with BUDGET_COST when cost limit exceeded."""
        res = run_agent_case("test_cost", "EMP001", "test question", force_budget_trap="cost")
        self.assertEqual(res.termination_reason, "BUDGET_COST")
        self.assertFalse(res.passed)

    def test_agent_budget_enforcement_wall_clock(self):
        """Verify agent terminates with BUDGET_WALL_CLOCK when time limit exceeded."""
        res = run_agent_case("test_time", "EMP001", "test question", force_budget_trap="wall_clock")
        self.assertEqual(res.termination_reason, "BUDGET_WALL_CLOCK")
        self.assertFalse(res.passed)

    def test_fastapi_policy_cases_endpoint(self):
        """Test GET /api/policy/cases returns 10 benchmark cases."""
        resp = self.client.get("/api/policy/cases")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 10)

    def test_fastapi_policy_employees_endpoint(self):
        """Test GET /api/policy/employees returns canonical employees."""
        resp = self.client.get("/api/policy/employees")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 10)

    def test_fastapi_policy_agent_endpoint(self):
        """Test POST /api/policy/agent execution endpoint."""
        resp = self.client.post("/api/policy/agent", json={
            "employee_id": "EMP001",
            "question": "What is the standard annual leave entitlement and monthly accrual rate for EMP001?",
            "case_id": "case_01",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["implementation"], "agent")
        self.assertEqual(data["termination_reason"], "SUCCESS")
        self.assertIn("24 working days", data["entitlement_value"])

    def test_fastapi_policy_workflow_endpoint(self):
        """Test POST /api/policy/workflow execution endpoint."""
        resp = self.client.post("/api/policy/workflow", json={
            "employee_id": "EMP001",
            "question": "What is the standard annual leave entitlement and monthly accrual rate for EMP001?",
            "case_id": "case_01",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["implementation"], "workflow")
        self.assertEqual(data["termination_reason"], "SUCCESS")
        self.assertIn("24 working days", data["entitlement_value"])

    def test_fastapi_policy_benchmark_endpoint(self):
        """Test POST /api/policy/benchmark runs comparison and returns summaries."""
        resp = self.client.post("/api/policy/benchmark")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("summary", data)
        self.assertEqual(data["summary"]["agent"]["pass_rate_pct"], 100.0)
        self.assertEqual(data["summary"]["workflow"]["pass_rate_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
