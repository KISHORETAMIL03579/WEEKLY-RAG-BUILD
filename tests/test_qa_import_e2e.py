# tests/test_qa_import_e2e.py — End-to-End Tests for Importing Questions & Expected Answers
import json
import io
import unittest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.routes.evaluation import parse_qa_pairs
from backend.services.evaluation_dataset import parse_and_validate_dataset


class TestQaImportE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = TestClient(cls.app)

    def test_01_parse_qa_pairs_from_text(self):
        """1. Test parse_qa_pairs extracts question and expected answer pairs from raw text."""
        raw_text = """
# Header comment
# --- Case 01 ---
Q: What is the annual leave entitlement?
A: 24 working days per annum.

# --- Case 02 ---
Question: How much notice is required for resignation during probation?
Answer: 1 week written notice.
"""
        pairs = parse_qa_pairs(raw_text)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0]["question"], "What is the annual leave entitlement?")
        self.assertEqual(pairs[0]["expected"], "24 working days per annum.")
        self.assertEqual(
            pairs[1]["question"],
            "How much notice is required for resignation during probation?",
        )
        self.assertEqual(pairs[1]["expected"], "1 week written notice.")

    def test_02_parse_qa_txt_endpoint(self):
        """2. Test legacy POST /eval/parse-qa-pdf with an uploaded TXT file."""
        txt_content = b"""
Q: Under what circumstances is an employee entitled to paid sick leave?
A: Completed at least two consecutive months of service.

Q: What is the probation period length for new recruits?
A: Six months for all contracts exceeding 12 months.
"""
        response = self.client.post(
            "/eval/parse-qa-pdf",
            files={"file": ("questions.txt", io.BytesIO(txt_content), "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(data.get("pairs")), 2)
        self.assertEqual(
            data["pairs"][0]["question"],
            "Under what circumstances is an employee entitled to paid sick leave?",
        )
        self.assertIn("two consecutive months", data["pairs"][0]["expected"])

    def test_03_parse_qa_json_endpoint(self):
        """3. Test legacy POST /eval/parse-qa-pdf with an uploaded JSON file."""
        json_data = [
            {"question": "What is annual leave?", "expected": "24 days"},
            {"question": "What is probation period?", "expected": "6 months"},
            {"q": "What is sick leave threshold?", "a": "2 consecutive months"},
        ]
        json_bytes = json.dumps(json_data).encode("utf-8")

        response = self.client.post(
            "/eval/parse-qa-pdf",
            files={
                "file": ("questions.json", io.BytesIO(json_bytes), "application/json")
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(data.get("pairs")), 3)
        self.assertEqual(data["pairs"][2]["question"], "What is sick leave threshold?")
        self.assertEqual(data["pairs"][2]["expected"], "2 consecutive months")

    def test_04_api_evaluation_dataset_parse_endpoint(self):
        """4. Test POST /api/evaluation/dataset/parse endpoint with standardized validation."""
        dataset = [
            {
                "case_id": "TC_01",
                "question": "What is the probation period?",
                "expected_answer": "6 months",
            },
            {
                "case_id": "TC_02",
                "question": "",
                "expected_answer": "Invalid case missing question",
            },
            {
                "case_id": "TC_03",
                "question": "What is standard working hours?",
                "expected_answer": "40 hours per week",
            },
        ]
        json_bytes = json.dumps(dataset).encode("utf-8")
        response = self.client.post(
            "/api/evaluation/dataset/parse?evaluator_type=judge",
            files={
                "file": (
                    "test_dataset.json",
                    io.BytesIO(json_bytes),
                    "application/json",
                )
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["total_found"], 3)
        self.assertEqual(data["valid_count"], 2)
        self.assertEqual(data["invalid_count"], 1)
        self.assertEqual(len(data["valid_cases"]), 2)
        self.assertEqual(data["valid_cases"][0]["case_id"], "TC_01")
        self.assertEqual(
            data["valid_cases"][0]["question"], "What is the probation period?"
        )
        self.assertEqual(data["valid_cases"][0]["expected_answer"], "6 months")

    def test_05_parse_markdown_qa_blocks(self):
        """5. Test Markdown formatted Q&A parsing with headers, bold keys, and multi-line answers."""
        md_content = """
# Test Benchmark Dataset

### Case 01
**Question:** What is the maximum duration for paternity leave?
**Answer:** Two continuous calendar weeks paid by the company.

### Case 02
**Question:** Under what conditions can unused annual leave be carried forward?
**Answer:** A maximum of 5 days can be carried forward into Q1 with written director approval.
"""
        result = parse_and_validate_dataset(
            md_content, "cases.md", evaluator_type="policy"
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.valid_count, 2)
        self.assertEqual(result.valid_cases[0]["case_id"], "CASE_01")
        self.assertEqual(
            result.valid_cases[0]["question"],
            "What is the maximum duration for paternity leave?",
        )
        self.assertIn(
            "Two continuous calendar weeks", result.valid_cases[0]["expected_answer"]
        )
        self.assertEqual(result.valid_cases[1]["case_id"], "CASE_02")

    def test_06_parse_duplicate_case_id_handling(self):
        """6. Test auto-disambiguation of duplicate case IDs with warnings."""
        raw_json = json.dumps(
            [
                {
                    "case_id": "CASE_DUP",
                    "question": "Question 1?",
                    "expected_answer": "Answer 1",
                },
                {
                    "case_id": "CASE_DUP",
                    "question": "Question 2?",
                    "expected_answer": "Answer 2",
                },
                {
                    "case_id": "CASE_DUP",
                    "question": "Question 3?",
                    "expected_answer": "Answer 3",
                },
            ]
        )
        result = parse_and_validate_dataset(
            raw_json, "dup.json", evaluator_type="judge"
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.valid_count, 3)
        self.assertEqual(result.duplicate_count, 2)
        case_ids = [c["case_id"] for c in result.valid_cases]
        self.assertEqual(case_ids, ["CASE_DUP", "CASE_DUP_2", "CASE_DUP_3"])
        self.assertEqual(len(result.warnings), 2)

    def test_07_retrieval_dataset_semantics(self):
        """7. Test that retrieval benchmark permits expected_section without expected_answer."""
        retrieval_json = json.dumps(
            [
                {
                    "case_id": "RET_01",
                    "question": "Where is the grievance procedure described?",
                    "expected_section": "Section 14: Grievance and Dispute Resolution",
                }
            ]
        )
        result = parse_and_validate_dataset(
            retrieval_json, "retrieval.json", evaluator_type="retrieval"
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.valid_count, 1)
        self.assertEqual(
            result.valid_cases[0]["expected_section"],
            "Section 14: Grievance and Dispute Resolution",
        )

    def test_08_zero_expected_answer_leakage(self):
        """8. Verify Zero-Leakage: expected_answer / expected_value is NEVER passed to agent or workflow prompts."""
        import inspect
        from backend.services.policy_benchmark_runner import PolicyBenchmarkRunState
        from backend.services.policy_agent import run_agent_case

        custom_cases = [
            {
                "case_id": "CUSTOM_LEAK_CHECK",
                "employee_id": "EMP001",
                "question": "What is the annual leave allowance?",
                "expected_answer": "SECRET_GROUND_TRUTH_DO_NOT_LEAK",
                "expected_value": "SECRET_GROUND_TRUTH_DO_NOT_LEAK",
            }
        ]
        run_state = PolicyBenchmarkRunState(run_id="run_leak_check", cases=custom_cases)
        self.assertIsNotNone(run_state)
        case_item = run_state.cases_status[0]
        self.assertEqual(case_item["case_id"], "CUSTOM_LEAK_CHECK")
        self.assertEqual(case_item["question"], "What is the annual leave allowance?")
        self.assertEqual(case_item["ground_truth"], "SECRET_GROUND_TRUTH_DO_NOT_LEAK")
        # Ensure that running single policy agent does not accept expected_answer parameter
        sig = inspect.signature(run_agent_case)
        self.assertNotIn("expected_answer", sig.parameters)
        self.assertNotIn("expected_value", sig.parameters)


if __name__ == "__main__":
    unittest.main()
