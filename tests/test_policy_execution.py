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
)
from backend.services.policy_agent import run_agent_case
from backend.services.policy_workflow import run_workflow_case


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
            result = run_agent_case(cid, empid, q, deterministic_pass_criteria=crit)
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

    def test_fastapi_policy_endpoints(self):
        resp = self.client.get("/api/policy/cases")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 10)

        resp = self.client.get("/api/policy/employees")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 10)

        resp = self.client.post(
            "/api/policy/agent",
            json={"employee_id": "EMP001", "question": "What is annual leave?"},
        )
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(
            "/api/policy/workflow",
            json={"employee_id": "EMP001", "question": "What is annual leave?"},
        )
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post("/api/policy/benchmark")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["summary"]["agent"]["pass_rate_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
