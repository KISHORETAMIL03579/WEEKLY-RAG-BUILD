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

    def setUp(self):
        self.workflow_patcher = patch(
            "backend.services.policy_benchmark_runner.run_workflow_case",
            side_effect=self.run_scripted_workflow_case,
        )
        self.workflow_patcher.start()
        self.addCleanup(self.workflow_patcher.stop)
        self.csv_patcher = patch(
            "backend.services.policy_benchmark_runner.PolicyBenchmarkRunManager._save_results_csv"
        )
        self.csv_patcher.start()
        self.addCleanup(self.csv_patcher.stop)

    @staticmethod
    def run_scripted_workflow_case(
        case_id,
        employee_id,
        question,
        deterministic_pass_criteria=None,
        top_k=5,
        temperature=0.3,
        model="test-model",
        **kwargs,
    ):
        answer = " ".join(deterministic_pass_criteria or ["Policy answer"])
        return PolicyOutputContract(
            case_id=case_id,
            employee_id=employee_id,
            question=question,
            entitlement_value=answer,
            rule_cited="Section 5.2.1",
            explanation="Scripted workflow benchmark answer.",
            passed=True,
            implementation="workflow",
            execution_mode="workflow",
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
            token_source="test_live",
            cost_usd=0.000015,
            latency_ms=1.0,
            top_k=top_k,
            temperature=temperature,
            model=model,
        )

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

    def test_get_run_returns_latest_persisted_progress_snapshot(self):
        manager = PolicyBenchmarkRunManager()
        run = PolicyBenchmarkRunState(
            run_id="bench_fresh_progress",
            cases=self.cases[:2],
        )
        manager._runs[run.run_id] = run
        latest_snapshot = run.to_dict()
        latest_snapshot["completed_cases"] = 1
        latest_snapshot["cases_status"][0]["status"] = "PASS"

        with patch(
            "backend.services.policy_benchmark_runner.get_background_run",
            return_value=latest_snapshot,
        ):
            current_run = manager.get_run(run.run_id)

        self.assertIsNotNone(current_run)
        self.assertIsNot(current_run, run)
        self.assertEqual(current_run.completed_cases, 1)
        self.assertEqual(current_run.cases_status[0]["status"], "PASS")

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
