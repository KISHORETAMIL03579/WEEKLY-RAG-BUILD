# tests/test_benchmark_progress.py — Unit Tests for Policy Benchmark Runner & Progress APIs
import json
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.schemas.policy import PolicyOutputContract
from backend.services.policy_benchmark_runner import (
    PolicyBenchmarkRunManager,
    PolicyBenchmarkRunState,
)
from tests.policy_test_utils import run_scripted_agent_case


class TestBenchmarkProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = TestClient(cls.app)
        with open("benchmarks/policy_execution/cases.json", "r", encoding="utf-8") as f:
            cls.cases = json.load(f)

    def test_benchmark_state_initialization(self):
        state = PolicyBenchmarkRunState(
            run_id="test_run_01",
            cases=self.cases,
            top_k=5,
            temperature=0.3,
            model="llama3.1:8b",
        )
        data = state.to_dict()
        self.assertEqual(data["run_id"], "test_run_01")
        self.assertEqual(data["status"], "RUNNING")
        self.assertEqual(data["total_cases"], 10)
        self.assertEqual(data["completed_cases"], 0)
        self.assertEqual(data["progress_pct"], 0.0)
        self.assertEqual(len(data["cases_status"]), 10)
        self.assertEqual(data["cases_status"][0]["status"], "WAITING")

    def test_benchmark_summary_uses_true_median_for_even_case_counts(self):
        results = [
            PolicyOutputContract(
                case_id="median-1",
                employee_id="EMP001",
                question="Question",
                entitlement_value="Answer",
                rule_cited="Section 1",
                explanation="",
                latency_ms=10,
            ),
            PolicyOutputContract(
                case_id="median-2",
                employee_id="EMP002",
                question="Question",
                entitlement_value="Answer",
                rule_cited="Section 1",
                explanation="",
                latency_ms=40,
            ),
        ]

        summary = PolicyBenchmarkRunManager._compute_summary(results, results)

        self.assertEqual(summary["agent"]["p50_latency_ms"], 25)
        self.assertEqual(summary["workflow"]["p50_latency_ms"], 25)

    def test_benchmark_runner_sync_execution(self):
        manager = PolicyBenchmarkRunManager.get_instance()
        state = PolicyBenchmarkRunState(
            run_id="test_sync_run",
            cases=self.cases,
            top_k=5,
            temperature=0.3,
        )
        with patch(
            "backend.services.policy_benchmark_runner.run_agent_case",
            side_effect=run_scripted_agent_case,
        ):
            manager._execute_benchmark_worker(state, self.cases)
        data = state.to_dict()
        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["completed_cases"], 10)
        self.assertEqual(data["progress_pct"], 100.0)
        self.assertIsNotNone(data["summary"])
        self.assertEqual(data["summary"]["agent"]["pass_rate_pct"], 100.0)
        self.assertEqual(data["summary"]["workflow"]["pass_rate_pct"], 100.0)

    def test_benchmark_cancellation(self):
        manager = PolicyBenchmarkRunManager.get_instance()
        with patch(
            "backend.services.policy_benchmark_runner.run_agent_case",
            side_effect=run_scripted_agent_case,
        ):
            state = manager.start_benchmark(
                cases=self.cases,
                top_k=5,
                temperature=0.3,
            )
            self.assertIsNotNone(state.run_id)
            cancelled = manager.cancel_run(state.run_id)
            self.assertTrue(cancelled)
            deadline = time.time() + 3
            while manager.get_run(state.run_id).status in ("RUNNING", "CANCELLING"):
                if time.time() >= deadline:
                    self.fail("Cancelled benchmark run did not finish")
                time.sleep(0.01)
            self.assertEqual(manager.get_run(state.run_id).status, "CANCELLED")

    def test_fastapi_benchmark_routes(self):
        # 1. Start background benchmark
        with patch(
            "backend.services.policy_benchmark_runner.run_agent_case",
            side_effect=run_scripted_agent_case,
        ):
            resp = self.client.post(
                "/api/policy/benchmark/start",
                json={"top_k": 5, "temperature": 0.3},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("run_id", data)
            run_id = data["run_id"]

            active_data = self.client.get("/api/policy/benchmark/runs/active").json()
            self.assertTrue(active_data["active"])
            self.assertEqual(active_data["run"]["run_id"], run_id)

            poll_data = self.client.get(f"/api/policy/benchmark/runs/{run_id}").json()
            self.assertEqual(poll_data["run_id"], run_id)

            resp = self.client.post(f"/api/policy/benchmark/runs/{run_id}/cancel")
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["cancelled"])


if __name__ == "__main__":
    unittest.main()
