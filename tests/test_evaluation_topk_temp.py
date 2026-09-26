# tests/test_evaluation_topk_temp.py — Verification Suite for Top-K / Temperature Propagation & Run Isolation
import json
import unittest
from unittest.mock import MagicMock, patch

from backend.schemas.evaluation import Week6CasePayload, Week6EvalPayload
from backend.services.evaluation_runner import (
    EvaluationRunManager,
    EvaluationRunState,
    diagnose_case_evidence,
    get_handbook_corpus,
)
from backend.services.search import search_chunks, fit_to_token_budget
from week6.judge import call_llm_judge_detailed, evaluate_case_with_judge_detailed


class TestEvaluationTopKTemperature(unittest.TestCase):
    def test_topk_retrieval_difference(self):
        """Proves that top_k=5 and top_k=8 execute real retrieval depth changes."""
        corpus, index = get_handbook_corpus()
        if not corpus or not index:
            self.skipTest("Handbook corpus not available in test environment")

        q = "Under what circumstances is an employee entitled to paid sick leave?"
        res_5 = search_chunks(q, corpus, index, top_k=5)
        res_8 = search_chunks(q, corpus, index, top_k=8)

        self.assertEqual(len(res_5), 5)
        self.assertEqual(len(res_8), 8)

        cids_5 = [r.get("id") or r.get("chunk_id") for r in res_5]
        cids_8 = [r.get("id") or r.get("chunk_id") for r in res_8]

        # Top 5 chunks must be a strict prefix or subset of top 8
        self.assertEqual(cids_5, cids_8[:5])
        # K=8 must have 3 distinct additional chunks
        diff = set(cids_8) - set(cids_5)
        self.assertEqual(len(diff), 3)

    @patch("week6.judge.check_ollama_health", return_value=True)
    @patch("urllib.request.urlopen")
    def test_temperature_sent_to_ollama(self, mock_urlopen, mock_health):
        """Verifies that the exact temperature requested (0.3) is transmitted in the options payload to Ollama."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"response": '{"verdict": 1}'}).encode(
            "utf-8"
        )
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        ans, src, lat = call_llm_judge_detailed(
            prompt="Evaluate this answer: {question}",
            temperature=0.3,
            model="llama3.1:8b",
        )

        self.assertEqual(src, "LLM")
        self.assertTrue(mock_urlopen.called)
        req_arg = mock_urlopen.call_args[0][0]
        payload = json.loads(req_arg.data.decode("utf-8"))

        self.assertEqual(payload["model"], "llama3.1:8b")
        self.assertIn("options", payload)
        self.assertAlmostEqual(payload["options"]["temperature"], 0.3)

    def test_evidence_based_diagnosis(self):
        """Verifies that case classification is based strictly on evidence, decoupling from benchmark taxonomy."""
        assertions = {
            "policy_section_reference_present": True,
            "policy_section_reference_resolves": True,
            "handbook_version_present": True,
            "numeric_policy_value_present": True,
            "out_of_jurisdiction_refusal": False,
        }

        # 1. Retrieval insufficient: required clause missing from retrieved chunks
        cat, diag, reason, res = diagnose_case_evidence(
            case_id="case_01",
            retrieved_chunks=[{"text": "general leave information"}],
            final_context_chunks=[{"text": "general leave information"}],
            answer="Sick leave is granted.",
            h_label=0,
            is_v2_agreed=True,
            assertions=assertions,
        )
        self.assertEqual(cat, "pipeline")
        self.assertEqual(diag, "retrieval_insufficient")

        # 2. Context budget loss: required clause in retrieved chunks, but omitted from final context
        cat, diag, reason, res = diagnose_case_evidence(
            case_id="case_01",
            retrieved_chunks=[
                {"text": "Entitled to two working days per month of completed service"}
            ],
            final_context_chunks=[
                {"text": "Truncated context without mandatory clause"}
            ],
            answer="Sick leave is granted.",
            h_label=0,
            is_v2_agreed=True,
            assertions=assertions,
        )
        self.assertEqual(cat, "pipeline")
        self.assertEqual(diag, "context_budget_loss")

        # 3. Generator completeness omission: clause in final context, but missing from answer
        cat, diag, reason, res = diagnose_case_evidence(
            case_id="case_01",
            retrieved_chunks=[
                {"text": "Entitled to two working days per month of completed service"}
            ],
            final_context_chunks=[
                {"text": "Entitled to two working days per month of completed service"}
            ],
            answer="Staff are entitled to sick leave at one day per month.",
            h_label=0,
            is_v2_agreed=True,
            assertions=assertions,
        )
        self.assertEqual(cat, "llm_model")
        self.assertEqual(diag, "generator_completeness_omission")

        # 4. Clean pass
        cat, diag, reason, res = diagnose_case_evidence(
            case_id="case_02",
            retrieved_chunks=[{"text": "complete clause"}],
            final_context_chunks=[{"text": "complete clause"}],
            answer="Complete accurate answer.",
            h_label=1,
            is_v2_agreed=True,
            assertions=assertions,
        )
        self.assertEqual(cat, "pass")
        self.assertEqual(diag, "clean_pass")

    def test_run_isolation_and_provenance(self):
        """Verifies that consecutive runs with different K/T do not leak state."""
        manager = EvaluationRunManager.get_instance()

        sample_cases = [
            {
                "case_id": "case_01",
                "question": "Under what circumstances is an employee entitled to paid sick leave?",
                "answer": "Answer 1",
                "taxonomy_mode": "Low-K Multi-Clause Truncation",
                "human_label": 0,
            }
        ]

        # Run A: K=5, T=0.3
        run_a = manager.start_run(
            cases=sample_cases,
            eval_engine="deterministic",
            top_k=5,
            temperature=0.3,
            model="llama3.1:8b",
        )
        self.assertEqual(run_a.top_k, 5)
        self.assertAlmostEqual(run_a.temperature, 0.3)
        import time

        for _ in range(200):
            if run_a.status in ("COMPLETED", "CANCELLED", "ERROR"):
                break
            time.sleep(0.01)
        self.assertEqual(run_a.status, "COMPLETED")

        # Run B: K=8, T=0.0
        run_b = manager.start_run(
            cases=sample_cases,
            eval_engine="deterministic",
            top_k=8,
            temperature=0.0,
            model="llama3.1:8b",
        )
        self.assertEqual(run_b.top_k, 8)
        self.assertAlmostEqual(run_b.temperature, 0.0)

        # Ensure Run IDs are unique and cases have distinct provenance
        self.assertNotEqual(run_a.run_id, run_b.run_id)
        self.assertEqual(run_a.cases[0]["evaluation_run_id"], run_a.run_id)
        self.assertEqual(run_b.cases[0]["evaluation_run_id"], run_b.run_id)
        self.assertEqual(run_a.cases[0]["top_k"], 5)
        self.assertEqual(run_b.cases[0]["top_k"], 8)


if __name__ == "__main__":
    unittest.main()
