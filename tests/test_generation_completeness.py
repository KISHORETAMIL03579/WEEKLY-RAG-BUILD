# tests/test_generation_completeness.py — Generic Multi-Clause Policy Generation Tests
import unittest
from backend.services.search import (
    QA_SYSTEM_PROMPT,
    QA_PROMPT_VERSION,
    build_qa_user_prompt,
    fit_to_token_budget,
    estimate_tokens,
)
from backend.storage.trace_store import get_prompt


class TestGenerationCompleteness(unittest.TestCase):
    """Verifies that QA prompt contract mandates exhaustive clause coverage for multi-clause questions."""

    def test_qa_prompt_version_and_contract_markers(self):
        """Verify prompt version is qa-answer-v2 and contains explicit completeness contract."""
        self.assertEqual(QA_PROMPT_VERSION, "qa-answer-v2")
        prompt_text = get_prompt(QA_PROMPT_VERSION)
        self.assertIsNotNone(prompt_text)
        self.assertIn("COMPLETENESS & CLAUSE COVERAGE CONTRACT", prompt_text)
        self.assertIn("include all relevant clauses needed to provide a complete answer", prompt_text)
        self.assertIn("NEVER omit a relevant condition", prompt_text)
        self.assertIn("NEVER stop after listing only the first one or two", prompt_text)
        self.assertIn("I don't know.", prompt_text)

    def test_synthetic_multi_clause_prompt_construction(self):
        """Verify build_qa_user_prompt builds valid multi-source synthetic context without truncation."""
        synthetic_chunks = [
            {
                "id": "c1",
                "filename": "SyntheticPolicy.pdf",
                "page": 1,
                "section": "1.1 Benefit Eligibility",
                "text": "Condition A: Employee must have completed 3 months of service. Benefit rate is 5 days per quarter.",
            },
            {
                "id": "c2",
                "filename": "SyntheticPolicy.pdf",
                "page": 1,
                "section": "1.1 Benefit Eligibility",
                "text": "Condition B: Benefit applies in cases of personal emergency or documented illness.",
            },
            {
                "id": "c3",
                "filename": "SyntheticPolicy.pdf",
                "page": 2,
                "section": "1.2 Authorization",
                "text": "Condition C: In exceptional circumstances, Director written approval is required.",
            },
        ]
        query = "Under what conditions can this benefit be requested?"
        user_prompt = build_qa_user_prompt(query, synthetic_chunks)

        self.assertIn("QUESTION: " + query, user_prompt)
        self.assertIn("[1] SyntheticPolicy.pdf (page 1), section: 1.1 Benefit Eligibility", user_prompt)
        self.assertIn("Condition A", user_prompt)
        self.assertIn("Condition B", user_prompt)
        self.assertIn("Condition C", user_prompt)
        self.assertIn("Director written approval", user_prompt)
        self.assertGreater(estimate_tokens(user_prompt), 10)


if __name__ == "__main__":
    unittest.main()

