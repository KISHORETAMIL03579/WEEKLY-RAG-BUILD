# tests/test_evaluation_classification.py — Truthful Forensic Failure Classification Unit Tests
import unittest
from backend.services.evaluation_runner import EvaluationRunManager, EvaluationRunState
from backend.evaluation.assertions import run_all_assertions


class TestEvaluationClassification(unittest.TestCase):
    """Verifies that evaluation failures are classified truthfully according to forensic evidence."""

    def test_pass_case_categorization(self):
        """When human_label=1 and Judge V2 agrees, failure_category must be 'pass'."""
        case = {
            "case_id": "case_02",
            "question": "Under what circumstances is an employee entitled to paid sick leave?",
            "answer": "According to Section 5.3.2, staff with at least two consecutive months of service are entitled to two working days per month...",
            "retrieved_context": "Section 5.3.2 Minimum and Maximum entitlement...",
            "expected_numeric": "two working days",
            "out_of_jurisdiction": False,
            "human_label": 1,
        }
        manager = EvaluationRunManager.get_instance()
        state = manager.start_run(cases=[case], eval_engine="deterministic")
        # Wait briefly for deterministic run worker
        import time

        for _ in range(20):
            time.sleep(0.05)
            if state.status == "COMPLETED":
                break
        self.assertEqual(state.status, "COMPLETED")
        res_case = state.cases[0]
        self.assertEqual(res_case["failure_category"], "pass")
        self.assertEqual(res_case["failure_reason"], "")

    def test_generator_omission_case_categorization(self):
        """When human_label=0 (generator omission), failure_category must be 'llm_model' with generator_completeness_omission."""
        case = {
            "case_id": "case_01",
            "question": "Under what circumstances is an employee entitled to paid sick leave?",
            "answer": "A staff member is entitled to paid sick leave at the rate of one day at full pay per month of completed service...",
            "retrieved_context": "5.3.2 Sick Leave. Minimum and Maximum entitlement... provided the staff member has completed at least two consecutive months of service...",
            "expected_numeric": "two working days",
            "out_of_jurisdiction": False,
            "human_label": 0,
        }
        manager = EvaluationRunManager.get_instance()
        state = manager.start_run(
            cases=[case], eval_engine="deterministic", labels={"case_01": 0}
        )
        import time

        for _ in range(20):
            time.sleep(0.05)
            if state.status == "COMPLETED":
                break
        self.assertEqual(state.status, "COMPLETED")
        res_case = state.cases[0]
        self.assertEqual(res_case["failure_category"], "llm_model")
        self.assertEqual(res_case["failure_type"], "generator_completeness_omission")
        self.assertIn("Investigate generation completeness", res_case["resolution"])

    def test_unresolvable_section_categorization(self):
        """When policy section reference fails to resolve, failure_category must be 'code_issue'."""
        case = {
            "case_id": "case_fake_sec",
            "question": "What is the policy on leave?",
            "answer": "According to Section 99.999.1, leave is granted freely.",
            "retrieved_context": "Chapter 5 Leave...",
            "expected_numeric": None,
            "out_of_jurisdiction": False,
            "human_label": 1,
        }
        manager = EvaluationRunManager.get_instance()
        state = manager.start_run(cases=[case], eval_engine="deterministic")
        import time

        for _ in range(20):
            time.sleep(0.05)
            if state.status == "COMPLETED":
                break
        self.assertEqual(state.status, "COMPLETED")
        res_case = state.cases[0]
        self.assertEqual(res_case["failure_category"], "code_issue")
        self.assertEqual(res_case["failure_type"], "unresolvable_section_reference")


if __name__ == "__main__":
    unittest.main()
