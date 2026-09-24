# tests/test_benchmark_progress.py — Unit Tests for Policy Benchmark Runner & Progress APIs
import json
import time
import unittest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services.policy_benchmark_runner import PolicyBenchmarkRunManager, PolicyBenchmarkRunState


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

    def test_benchmark_runner_sync_execution(self):
        manager = PolicyBenchmarkRunManager.get_instance()
        state = PolicyBenchmarkRunState(
            run_id="test_sync_run",
            cases=self.cases,
            top_k=5,
            temperature=0.3,
        )
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
        state = manager.start_benchmark(
            cases=self.cases,
            top_k=5,
            temperature=0.3,
        )
        self.assertIsNotNone(state.run_id)
        # Cancel immediately
        cancelled = manager.cancel_run(state.run_id)
        self.assertTrue(cancelled)
        data = state.to_dict()
        self.assertIn(data["status"], ["CANCELLED", "COMPLETED"])

    def test_fastapi_benchmark_routes(self):
        # 1. Start background benchmark
        resp = self.client.post("/api/policy/benchmark/start", json={"top_k": 5, "temperature": 0.3})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("run_id", data)
        run_id = data["run_id"]

        # 2. Check active run
        resp = self.client.get("/api/policy/benchmark/runs/active")
        self.assertEqual(resp.status_code, 200)
        active_data = resp.json()
        self.assertTrue(active_data["active"])
        self.assertEqual(active_data["run"]["run_id"], run_id)

        # 3. Poll specific run
        resp = self.client.get(f"/api/policy/benchmark/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        poll_data = resp.json()
        self.assertEqual(poll_data["run_id"], run_id)

        # 4. Cancel run
        resp = self.client.post(f"/api/policy/benchmark/runs/{run_id}/cancel")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["cancelled"])


if __name__ == "__main__":
    unittest.main()
