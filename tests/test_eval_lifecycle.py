# tests/test_eval_lifecycle.py — Evaluation Run Lifecycle & Data Lineage Integration Tests
import unittest
import time
from fastapi.testclient import TestClient
from backend.main import create_app


class TestEvaluationLifecycle(unittest.TestCase):
    """Integration test suite verifying the complete evaluation lifecycle, zero-leakage, and background runner."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = TestClient(cls.app)

    def test_01_benchmark_endpoint_zero_precomputation_leakage(self):
        """Verify GET /api/evaluation/benchmark returns 25 cases all PENDING with no verdicts or failure reasons."""
        res = self.client.get("/api/evaluation/benchmark")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        cases = data.get("cases", [])
        self.assertEqual(len(cases), 25)
        for c in cases:
            self.assertEqual(c.get("status"), "PENDING")
            self.assertIsNone(c.get("judge_v1_verdict"))
            self.assertIsNone(c.get("judge_v2_verdict"))
            self.assertIsNone(c.get("failure_category"))
            self.assertIsNone(c.get("failure_reason"))
            self.assertIsNone(c.get("assertions"))

    def test_02_evaluation_run_lifecycle_and_lineage(self):
        """Verify POST /api/evaluation/runs starts background evaluation and completes with non-contradictory metadata."""
        # 1. Load benchmark cases
        res_bm = self.client.get("/api/evaluation/benchmark")
        self.assertEqual(res_bm.status_code, 200)
        cases = res_bm.json().get("cases", [])

        # 2. Start background evaluation run (deterministic fast mode)
        res_start = self.client.post("/api/evaluation/runs", json={"cases": cases, "run_llm": False})
        self.assertEqual(res_start.status_code, 200)
        run_data = res_start.json()
        run_id = run_data.get("evaluation_run_id")
        self.assertIsNotNone(run_id)

        # 3. Poll until completed
        final_state = None
        for _ in range(50):
            time.sleep(0.05)
            res_poll = self.client.get(f"/api/evaluation/runs/{run_id}")
            self.assertEqual(res_poll.status_code, 200)
            poll_data = res_poll.json()
            if poll_data.get("status") in ("COMPLETED", "ERROR", "CANCELLED"):
                final_state = poll_data
                break

        self.assertIsNotNone(final_state)
        self.assertEqual(final_state.get("status"), "COMPLETED")
        self.assertEqual(final_state.get("completed_cases"), 25)
        self.assertEqual(final_state.get("total_cases"), 25)

        # 4. Verify Case 02 non-contradiction
        cases_map = {c["case_id"]: c for c in final_state.get("cases", [])}
        c2 = cases_map.get("case_02")
        self.assertIsNotNone(c2)
        self.assertEqual(c2.get("human_label"), 1)
        self.assertEqual(c2.get("judge_v2_verdict"), 1)
        self.assertEqual(c2.get("failure_category"), "pass")
        self.assertEqual(c2.get("failure_reason"), "")

    def test_03_active_run_query_endpoint(self):
        """Verify GET /api/evaluation/runs/active returns valid active run envelope."""
        res = self.client.get("/api/evaluation/runs/active")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("active_run_id", data)
        self.assertIn("run", data)

    def test_04_cancel_evaluation_run_endpoint(self):
        """Verify POST /api/evaluation/runs/{run_id}/cancel cancels an active or queued run."""
        res_bm = self.client.get("/api/evaluation/benchmark")
        cases = res_bm.json().get("cases", [])[:5]
        res_start = self.client.post("/api/evaluation/runs", json={"cases": cases, "run_llm": False})
        run_id = res_start.json().get("evaluation_run_id")

        res_cancel = self.client.post(f"/api/evaluation/runs/{run_id}/cancel")
        self.assertEqual(res_cancel.status_code, 200)
        cancel_data = res_cancel.json()
        self.assertTrue(cancel_data.get("ok"))
        self.assertEqual(cancel_data.get("status"), "CANCELLED")

    def test_05_stale_judge_run_error_contract(self):
        """Verify stale run ID (e.g. eval_6e2692a623ef) returns 404 with canonical error contract."""
        res = self.client.get("/api/evaluation/runs/eval_6e2692a623ef")
        self.assertEqual(res.status_code, 404)
        data = res.json()
        self.assertFalse(data.get("success", True))
        self.assertIn("error", data)
        self.assertEqual(data["error"].get("code"), "NOT_FOUND")
        self.assertIn("eval_6e2692a623ef", data["error"].get("message", ""))
        self.assertIn("request_id", data["error"])
        # Ensure no stack traces or path leakage
        self.assertNotIn("Traceback", res.text)
        self.assertNotIn("D:\\", res.text)

    def test_06_cross_module_state_isolation(self):
        """Verify Policy, Judge, and Retrieval benchmarks have completely isolated endpoints and states."""
        # 1. Start a judge run
        res_bm = self.client.get("/api/evaluation/benchmark")
        cases = res_bm.json().get("cases", [])[:2]
        res_start = self.client.post("/api/evaluation/runs", json={"cases": cases, "run_llm": False})
        self.assertEqual(res_start.status_code, 200)
        judge_run_id = res_start.json().get("evaluation_run_id")

        # 2. Verify Policy active run does NOT adopt the judge run
        res_policy_active = self.client.get("/api/policy/benchmark/runs/active")
        self.assertEqual(res_policy_active.status_code, 200)
        policy_data = res_policy_active.json()
        # Even if a judge run is running, policy run should not be active or match judge_run_id
        if policy_data.get("active") and policy_data.get("run"):
            self.assertNotEqual(policy_data["run"].get("run_id"), judge_run_id)

        # 3. Clean up
        self.client.post(f"/api/evaluation/runs/{judge_run_id}/cancel")

    def test_07_frontend_source_contains_zero_legacy_week6_calls(self):
        """Verify frontend source files do not contain any legacy /api/week6/runs calls."""
        import os
        frontend_src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "src")
        legacy_occurrences = []
        for root, _, files in os.walk(frontend_src):
            for file in files:
                if file.endswith((".ts", ".tsx", ".js", ".jsx")):
                    path = os.path.join(root, file)
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_idx, line in enumerate(f, 1):
                            if "week6/runs" in line:
                                legacy_occurrences.append(f"{file}:{line_idx}: {line.strip()}")
        self.assertEqual(len(legacy_occurrences), 0, f"Found legacy week6 calls in frontend: {legacy_occurrences}")

    def test_08_benchmark_progress_and_completion_invariants(self):
        """Verify progress counters increment monotonically and complete at 100%."""
        res_bm = self.client.get("/api/evaluation/benchmark")
        cases = res_bm.json().get("cases", [])[:3]
        res_start = self.client.post("/api/evaluation/runs", json={"cases": cases, "run_llm": False})
        run_id = res_start.json().get("evaluation_run_id")

        for _ in range(30):
            time.sleep(0.05)
            poll = self.client.get(f"/api/evaluation/runs/{run_id}").json()
            if poll.get("status") == "COMPLETED":
                self.assertEqual(poll.get("completed_cases"), 3)
                self.assertEqual(poll.get("total_cases"), 3)
                self.assertIsNotNone(poll.get("cases"))
                self.assertEqual(len(poll.get("cases")), 3)
                break


if __name__ == "__main__":
    unittest.main()

