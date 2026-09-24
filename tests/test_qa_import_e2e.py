# tests/test_qa_import_e2e.py — End-to-End Tests for Importing Questions & Expected Answers
import json
import io
import unittest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.routes.evaluation import parse_qa_pairs


class TestQaImportE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = TestClient(cls.app)

    def test_parse_qa_pairs_from_text(self):
        """Test parse_qa_pairs extracts question and expected answer pairs from raw text."""
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
        self.assertEqual(pairs[1]["question"], "How much notice is required for resignation during probation?")
        self.assertEqual(pairs[1]["expected"], "1 week written notice.")

    def test_parse_qa_txt_endpoint(self):
        """Test POST /eval/parse-qa-pdf with an uploaded TXT file."""
        txt_content = b"""
Q: Under what circumstances is an employee entitled to paid sick leave?
A: Completed at least two consecutive months of service.

Q: What is the probation period length for new recruits?
A: Six months for all contracts exceeding 12 months.
"""
        response = self.client.post(
            "/eval/parse-qa-pdf",
            files={"file": ("questions.txt", io.BytesIO(txt_content), "text/plain")}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(data.get("pairs")), 2)
        self.assertEqual(data["pairs"][0]["question"], "Under what circumstances is an employee entitled to paid sick leave?")
        self.assertIn("two consecutive months", data["pairs"][0]["expected"])

    def test_parse_qa_json_endpoint(self):
        """Test POST /eval/parse-qa-pdf with an uploaded JSON file."""
        json_data = [
            {"question": "What is annual leave?", "expected": "24 days"},
            {"question": "What is probation period?", "expected": "6 months"},
            {"q": "What is sick leave threshold?", "a": "2 consecutive months"},
        ]
        json_bytes = json.dumps(json_data).encode("utf-8")

        response = self.client.post(
            "/eval/parse-qa-pdf",
            files={"file": ("questions.json", io.BytesIO(json_bytes), "application/json")}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(data.get("pairs")), 3)
        self.assertEqual(data["pairs"][2]["question"], "What is sick leave threshold?")
        self.assertEqual(data["pairs"][2]["expected"], "2 consecutive months")

    def test_import_week7_questions_txt_file(self):
        """Verify the generated tests/test_hr_policy_week7_questions.txt parses all 10 questions."""
        with open("tests/test_hr_policy_week7_questions.txt", "r", encoding="utf-8") as f:
            content = f.read()

        # Test with endpoint
        response = self.client.post(
            "/eval/parse-qa-pdf",
            files={"file": ("test_hr_policy_week7_questions.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(data.get("pairs")), 10)


if __name__ == "__main__":
    unittest.main()
