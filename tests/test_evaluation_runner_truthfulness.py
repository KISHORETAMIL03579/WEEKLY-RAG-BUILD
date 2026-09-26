import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.errors import ConflictError
from backend.routes.evaluation import cancel_evaluation_run
from backend.services.search import build_index
from backend.services.evaluation_runner import EvaluationRunManager
from backend.storage import shared_state


class TestEvaluationRunnerTruthfulness(unittest.TestCase):
    def setUp(self):
        self._state_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._state_directory.cleanup)
        self._database_path_patch = patch.object(
            shared_state,
            "APP_STATE_DB",
            Path(self._state_directory.name) / "evaluation-test.sqlite3",
        )
        self._database_path_patch.start()
        self.addCleanup(self._database_path_patch.stop)
        self._schema_ready_patch = patch.object(shared_state, "_schema_ready", False)
        self._schema_ready_patch.start()
        self.addCleanup(self._schema_ready_patch.stop)
        self._schema_path_patch = patch.object(shared_state, "_schema_ready_path", None)
        self._schema_path_patch.start()
        self.addCleanup(self._schema_path_patch.stop)

    @staticmethod
    def wait_for_status(run, statuses, timeout=2):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if run.status in statuses:
                return
            time.sleep(0.01)
        raise AssertionError(f"Run did not reach one of {statuses}: {run.status}")

    def test_unavailable_corpus_reports_no_retrieved_provenance(self):
        manager = EvaluationRunManager()
        case = {
            "case_id": "case_unavailable",
            "question": "What is the leave policy?",
            "answer": "The policy answer.",
            "retrieved_context": "Benchmark-supplied context is not this run's retrieval.",
            "human_label": 1,
        }
        with (
            patch(
                "backend.services.evaluation_runner.get_handbook_corpus",
                return_value=(None, None),
            ),
            patch(
                "backend.services.evaluation_runner.run_all_assertions",
                return_value={"policy_section_reference_resolves": True},
            ),
            patch(
                "backend.services.evaluation_runner.evaluate_case_deterministically",
                return_value=1,
            ),
        ):
            run = manager.start_run([case], eval_engine="deterministic", top_k=5)
            self.wait_for_status(run, {"COMPLETED", "ERROR"})

        self.assertEqual(run.status, "COMPLETED")
        result = run.cases[0]
        self.assertEqual(result["retrieval_status"], "UNAVAILABLE")
        self.assertEqual(
            result["retrieval_error"], "Handbook corpus or index unavailable"
        )
        self.assertEqual(result["retrieved_count"], 0)
        self.assertEqual(result["retrieved_chunk_ids"], [])
        self.assertEqual(result["retrieved_scores"], [])
        self.assertEqual(result["final_context_chunk_ids"], [])
        self.assertEqual(result["retrieved_context"], "")

    def test_cancellation_keeps_run_active_until_blocked_case_finishes(self):
        manager = EvaluationRunManager()
        search_entered = threading.Event()
        allow_search_to_finish = threading.Event()
        search_returned = threading.Event()

        def blocked_search(*args, **kwargs):
            search_entered.set()
            if not allow_search_to_finish.wait(timeout=2):
                raise AssertionError("Test did not release blocked retrieval")
            search_returned.set()
            return []

        case = {
            "case_id": "case_blocked",
            "question": "What is the leave policy?",
            "answer": "The policy answer.",
            "human_label": 1,
        }
        corpus = [{"id": "test-chunk", "text": "Policy leave information"}]
        with (
            patch(
                "backend.services.evaluation_runner.get_handbook_corpus",
                return_value=(corpus, build_index(corpus)),
            ),
            patch(
                "backend.services.evaluation_runner.search_chunks",
                side_effect=blocked_search,
            ),
            patch(
                "backend.services.evaluation_runner.run_all_assertions",
                return_value={"policy_section_reference_resolves": True},
            ),
            patch(
                "backend.services.evaluation_runner.evaluate_case_deterministically",
                return_value=1,
            ),
        ):
            run = manager.start_run([case], eval_engine="deterministic")
            self.assertTrue(search_entered.wait(timeout=2))

            with patch("backend.routes.evaluation.run_manager", manager):
                cancellation_response = cancel_evaluation_run(run.run_id)
            self.assertEqual(cancellation_response["status"], "CANCELLING")
            self.assertTrue(cancellation_response["cancellation_requested"])
            self.assertEqual(run.to_dict()["status"], "CANCELLING")
            self.assertTrue(run.to_dict()["cancellation_requested"])
            self.assertEqual(manager.get_active_run_id(), run.run_id)
            with self.assertRaises(ConflictError):
                manager.start_run([case], eval_engine="deterministic")

            allow_search_to_finish.set()
            self.wait_for_status(run, {"CANCELLED", "ERROR"})
            self.assertTrue(search_returned.is_set())
            self.assertEqual(run.status, "CANCELLED")
            self.assertIsNone(manager.get_active_run_id())


if __name__ == "__main__":
    unittest.main()
