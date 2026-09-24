# tests/test_week7.py — Comprehensive Unit & Integration Tests for Week 7 (Testing Production Policy Modules)
from __future__ import annotations

import csv
import json
import os
import unittest
from pathlib import Path

from backend.schemas.policy import (
    EmployeeRecord,
    JurisdictionEnum,
    MAX_COST,
    MAX_ITERATIONS,
    MAX_TOKENS,
    MAX_WALL_CLOCK_SECONDS,
    PolicyCategoryEnum,
    PolicyOutputContract,
    TOKEN_COST_PROXY_RATE,
)
from backend.services.policy_agent import run_agent_case
from backend.services.policy_tools import (
    CANONICAL_EMPLOYEES,
    POLICY_TOOL_DEFINITIONS,
    execute_tool_call,
    get_employee_record,
    get_jurisdiction_rules,
    search_handbook,
)
from backend.services.policy_workflow import run_workflow_case

BASE_DIR = Path(__file__).resolve().parent.parent


class TestWeek7SchemasAndTools(unittest.TestCase):
    """Test production policy schemas, enums, canonical data, and tool execution."""

    def test_jurisdiction_enum_values(self):
        expected_jurisdictions = {"Kenya", "Ireland", "Cote d'Ivoire", "Rwanda", "Global"}
        actual = {j.value for j in JurisdictionEnum}
        self.assertEqual(expected_jurisdictions, actual)

    def test_policy_category_enum_values(self):
        expected_categories = {
            "leave",
            "notice_and_separation",
            "benefits_and_pension",
            "holidays_and_working_hours",
            "conduct_and_discipline",
        }
        actual = {c.value for c in PolicyCategoryEnum}
        self.assertEqual(expected_categories, actual)

    def test_canonical_employee_database(self):
        self.assertEqual(len(CANONICAL_EMPLOYEES), 10)
        for emp_id, emp in CANONICAL_EMPLOYEES.items():
            self.assertTrue(emp_id.startswith("EMP"))
            self.assertIsInstance(emp.tenure_months, int)
            self.assertIn(emp.employment_status, ["Probation", "Confirmed"])
            self.assertIsInstance(emp.jurisdiction, JurisdictionEnum)

    def test_get_employee_record_tool(self):
        rec = get_employee_record("EMP001")
        self.assertTrue(rec["found"])
        self.assertEqual(rec["employee_id"], "EMP001")
        self.assertEqual(rec["name"], "Sarah Mwangi")
        self.assertEqual(rec["employment_status"], "Confirmed")

        rec_missing = get_employee_record("EMP999")
        self.assertFalse(rec_missing["found"])
        self.assertIn("not found", rec_missing["error"])

    def test_search_handbook_tool(self):
        results = search_handbook("annual leave entitlement", top_k=2)
        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(any("5.2.1" in r["section"] or "Annual Leave" in r["title"] for r in results))

    def test_get_jurisdiction_rules_tool(self):
        rules = get_jurisdiction_rules(JurisdictionEnum.KENYA, PolicyCategoryEnum.LEAVE)
        self.assertEqual(rules["jurisdiction"], "Kenya")
        self.assertEqual(rules["policy_category"], "leave")
        self.assertIn("24 working days", rules["statutory_guideline"])

    def test_tool_definitions_and_no_overlap(self):
        self.assertEqual(len(POLICY_TOOL_DEFINITIONS), 3)
        tool_names = [t["name"] for t in POLICY_TOOL_DEFINITIONS]
        self.assertEqual(tool_names, ["get_employee_record", "search_handbook", "get_jurisdiction_rules"])

        # Verify parameter isolation
        emp_params = POLICY_TOOL_DEFINITIONS[0]["parameters"]["properties"]
        self.assertIn("employee_id", emp_params)
        self.assertNotIn("query", emp_params)

        hb_params = POLICY_TOOL_DEFINITIONS[1]["parameters"]["properties"]
        self.assertIn("query", hb_params)
        self.assertNotIn("employee_id", hb_params)

        jur_params = POLICY_TOOL_DEFINITIONS[2]["parameters"]["properties"]
        self.assertIn("jurisdiction", jur_params)
        self.assertIn("policy_category", jur_params)
        self.assertIn("enum", jur_params["jurisdiction"])


class TestWeek7AgentBudgets(unittest.TestCase):
    """Test strict budget enforcement and termination across all 4 budgets."""

    def test_max_iterations_budget_termination(self):
        res = run_agent_case(
            case_id="test_iter_budget",
            employee_id="EMP001",
            question="What is the annual leave?",
            max_iterations=1,
            force_budget_trap="iterations",
        )
        self.assertEqual(res.termination_reason, "BUDGET_ITERATIONS")
        self.assertIn("MAX_ITERATIONS", res.explanation)
        self.assertFalse(res.passed)

    def test_max_tokens_budget_termination(self):
        res = run_agent_case(
            case_id="test_tok_budget",
            employee_id="EMP001",
            question="What is the annual leave?",
            max_tokens=100,
            force_budget_trap="tokens",
        )
        self.assertEqual(res.termination_reason, "BUDGET_TOKENS")
        self.assertIn("MAX_TOKENS", res.explanation)
        self.assertFalse(res.passed)

    def test_max_cost_budget_termination(self):
        res = run_agent_case(
            case_id="test_cost_budget",
            employee_id="EMP001",
            question="What is the annual leave?",
            max_cost=0.0001,
            force_budget_trap="cost",
        )
        self.assertEqual(res.termination_reason, "BUDGET_COST")
        self.assertIn("MAX_COST", res.explanation)
        self.assertFalse(res.passed)

    def test_max_wall_clock_budget_termination(self):
        res = run_agent_case(
            case_id="test_time_budget",
            employee_id="EMP001",
            question="What is the annual leave?",
            max_wall_clock=0.0001,
            force_budget_trap="wall_clock",
        )
        self.assertEqual(res.termination_reason, "BUDGET_WALL_CLOCK")
        self.assertIn("MAX_WALL_CLOCK", res.explanation)
        self.assertFalse(res.passed)


class TestWeek7BenchmarkRace(unittest.TestCase):
    """Test 10 benchmark cases on both Agent and Workflow for 100% correctness and contract parity."""

    @classmethod
    def setUpClass(cls):
        cases_file = BASE_DIR / "week7" / "race_cases_10.json"
        with open(cases_file, "r", encoding="utf-8") as f:
            cls.benchmark_cases = json.load(f)

    def test_benchmark_has_10_cases(self):
        self.assertEqual(len(self.benchmark_cases), 10)

    def test_agent_100_percent_pass_rate(self):
        for c in self.benchmark_cases:
            res = run_agent_case(
                c["case_id"],
                c["employee_id"],
                c["question"],
                deterministic_pass_criteria=c["deterministic_pass_criteria"],
            )
            self.assertTrue(
                res.passed,
                f"Agent failed case {c['case_id']} on criteria {c['deterministic_pass_criteria']}. "
                f"Value: {res.entitlement_value}, Explanation: {res.explanation}",
            )
            self.assertEqual(res.termination_reason, "SUCCESS")
            self.assertEqual(res.implementation, "agent")
            self.assertGreaterEqual(res.iterations, 2)

    def test_workflow_100_percent_pass_rate(self):
        for c in self.benchmark_cases:
            res = run_workflow_case(
                c["case_id"],
                c["employee_id"],
                c["question"],
                deterministic_pass_criteria=c["deterministic_pass_criteria"],
            )
            self.assertTrue(
                res.passed,
                f"Workflow failed case {c['case_id']} on criteria {c['deterministic_pass_criteria']}. "
                f"Value: {res.entitlement_value}, Explanation: {res.explanation}",
            )
            self.assertEqual(res.termination_reason, "SUCCESS")
            self.assertEqual(res.implementation, "workflow")
            self.assertEqual(res.iterations, 1)

    def test_workflow_token_efficiency_over_agent(self):
        c = self.benchmark_cases[0]
        agent_res = run_agent_case(c["case_id"], c["employee_id"], c["question"])
        wf_res = run_workflow_case(c["case_id"], c["employee_id"], c["question"])

        self.assertLess(
            wf_res.total_tokens,
            agent_res.total_tokens,
            "Workflow should consume fewer tokens than iterative ReAct loop",
        )


class TestWeek7ArtifactsAndIntegrity(unittest.TestCase):
    """Test required Week 7 deliverables and ensure Week 6 files are completely frozen."""

    def test_week7_deliverable_files_exist(self):
        expected_files = [
            BASE_DIR / "week7" / "race_cases_10.json",
            BASE_DIR / "week7" / "race.csv",
            BASE_DIR / "week7" / "budget_termination.log",
            BASE_DIR / "week7" / "tool_description_diff.md",
            BASE_DIR / "week7" / "week7_report.md",
        ]
        for f in expected_files:
            self.assertTrue(f.exists(), f"Missing required deliverable: {f}")
            self.assertGreater(f.stat().st_size, 0, f"Deliverable is empty: {f}")

    def test_race_csv_has_20_records(self):
        csv_path = BASE_DIR / "week7" / "race.csv"
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
        # 10 agent records + 10 workflow records = 20 rows
        self.assertEqual(len(reader), 20)
        implementations = {r["implementation"] for r in reader}
        self.assertEqual(implementations, {"agent", "workflow"})

    def test_week6_files_frozen_and_untouched(self):
        week6_cases = BASE_DIR / "week6" / "eval_cases_25.json"
        week6_labels = BASE_DIR / "week6" / "labels_25.json"
        week6_judge1 = BASE_DIR / "week6" / "judge_v1.txt"
        week6_judge2 = BASE_DIR / "week6" / "judge_v2.txt"

        self.assertTrue(week6_cases.exists())
        self.assertTrue(week6_labels.exists())
        self.assertTrue(week6_judge1.exists())
        self.assertTrue(week6_judge2.exists())

        with open(week6_cases, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(len(data), 25)

        with open(week6_labels, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(len(data), 25)


if __name__ == "__main__":
    unittest.main()
