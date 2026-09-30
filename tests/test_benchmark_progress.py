"""Benchmark runner: progress, session scope, skipped cases, trajectory, evidence files."""

import csv
import time
from unittest.mock import patch

import pytest

from backend.mcp.registry import McpToolRegistry
from backend.schemas.policy import PolicyOutputContract
from backend.services import policy_trajectory
from backend.services.policy_benchmark_runner import (
    PolicyBenchmarkRunManager,
    PolicyBenchmarkRunState,
    load_suite,
)
from backend.services.policy_retrieval import PolicyContext
from backend.config import BASE_DIR

RUNNER = "backend.services.policy_benchmark_runner"
E = "get_employee_record"


def fake_case_runner(kind, seen=None, passed=True):
    """Stands in for run_agent_case/run_workflow_case: follows each case's first expected path."""
    expected = policy_trajectory.load_expected_trajectories()

    def run(case_id, employee_id, question, deterministic_pass_criteria=None, **kwargs):
        if seen is not None:
            seen.append({"kind": kind, "case_id": case_id, "deterministic_pass_criteria": deterministic_pass_criteria, **kwargs})
        calls = [
            {
                "step": i + 1, "tool_name": tool, "server": "s", "roles": [],
                "arguments": {"employee_id": employee_id} if tool == E else {},
                "output": {"found": True, "fields": {}}, "is_error": False,
                "attempts": 1, "retries": 0, "latency_ms": 1.0, "selection": {"rationale": None},
            }
            for i, tool in enumerate(expected[case_id]["paths"][0])
        ]
        return PolicyOutputContract(
            case_id=case_id, employee_id=employee_id, question=question,
            entitlement_value="answer", rule_cited="5.2.1", explanation="",
            passed=passed, strict_passed=passed, implementation=kind, execution_mode=kind,
            tool_calls=calls, prompt_tokens=20, completion_tokens=10, total_tokens=30,
            token_source="groq_live", cost_usd=1.5e-5, latency_ms=10.0 + len(case_id),
            top_k=kwargs.get("top_k"), temperature=kwargs.get("temperature"), model=kwargs.get("model"),
        )

    return run


@pytest.fixture
def runners():
    seen = []
    with patch(f"{RUNNER}.run_agent_case", side_effect=fake_case_runner("agent", seen)), patch(
        f"{RUNNER}.run_workflow_case", side_effect=fake_case_runner("workflow", seen)
    ):
        yield seen


def run_sync(cases, context=None, run_id="test_sync_run"):
    state = PolicyBenchmarkRunState(run_id, cases, top_k=5, temperature=0.3, model="m", context=context)
    PolicyBenchmarkRunManager.get_instance()._execute_benchmark_worker(state, cases)
    return state


def test_state_initialises_every_case_as_waiting_and_never_serialises_the_session():
    state = PolicyBenchmarkRunState("r1", load_suite("canonical"), context=PolicyContext("secret-session"))
    data = state.to_dict()
    assert (data["status"], data["total_cases"], data["completed_cases"], data["progress_pct"]) == ("RUNNING", 10, 0, 0.0)
    assert {c["status"] for c in data["cases_status"]} == {"WAITING"}
    assert "secret-session" not in str(data)


def test_persisted_progress_snapshot_wins_for_finished_runs_but_live_object_for_active_ones():
    manager = PolicyBenchmarkRunManager()
    run = PolicyBenchmarkRunState("bench_progress", load_suite("canonical")[:2], context=PolicyContext("s"))
    manager._runs[run.run_id] = run
    snapshot = run.to_dict()
    snapshot["completed_cases"] = 1
    with patch(f"{RUNNER}.get_background_run", return_value=snapshot):
        assert manager.get_run(run.run_id) is run  # still RUNNING: keep the object that owns the context
        snapshot["status"] = "COMPLETED"
        restored = manager.get_run(run.run_id)
    assert restored is not run and restored.completed_cases == 1 and restored.context is None


def test_summary_reports_true_median_and_the_maxima():
    def result(latency, cost, tokens):
        return PolicyOutputContract(
            case_id="c", employee_id="E", question="q", entitlement_value="a", rule_cited="r",
            explanation="", latency_ms=latency, cost_usd=cost, total_tokens=tokens,
        )

    results = [result(10, 0.1, 100), result(40, 0.3, 400), result(90, 0.2, 300)]
    summary = PolicyBenchmarkRunManager._compute_summary(results[:2], results)
    assert summary["agent"]["p50_latency_ms"] == 25 and summary["workflow"]["p50_latency_ms"] == 40
    assert summary["workflow"]["max_latency_ms"] == 90 and summary["workflow"]["max_cost_usd"] == 0.3
    assert summary["workflow"]["p50_tokens"] == 300 and summary["workflow"]["max_tokens"] == 400
    assert summary["agent"]["terminations"] == {"SUCCESS": 2}


def test_sync_run_scores_trajectories_and_reuses_the_session_context(runners):
    context = PolicyContext("test-session")
    state = run_sync(load_suite("canonical"), context)
    data = state.to_dict()
    assert (data["status"], data["completed_cases"], data["progress_pct"]) == ("COMPLETED", 10, 100.0)
    assert data["summary"]["agent"]["pass_rate_pct"] == 100.0 and data["summary"]["workflow"]["pass_rate_pct"] == 100.0
    assert all(item["context"] == context for item in runners) and len(runners) == 20
    trajectory = data["trajectory"]["summary"]
    assert trajectory["trajectory_pass_rate_pct"] == 100.0 and trajectory["outcome_vs_trajectory_gap_pct"] == 0.0
    row = data["cases_status"][2]
    assert row["agent_tool_sequence"] == [E, "search_handbook"] and row["agent_tool_retries"] == 0 and row["agent_rejected_calls"] == 0


def test_case_aliases_and_forbidden_phrases_reach_the_runner(runners):
    run_sync(load_suite("branching")[1:2], PolicyContext("s"))
    agent_call = next(c for c in runners if c["kind"] == "agent")
    assert "20 working days" in agent_call["forbidden_phrases"] and agent_call["deterministic_pass_criteria"] == ["24", "ireland"]


def test_cases_needing_tools_no_server_provides_are_skipped_not_failed(runners):
    one = McpToolRegistry(BASE_DIR / "config" / "mcp_servers.server1.json", force_transport="inprocess")
    with patch(f"{RUNNER}.get_tool_registry", return_value=one):
        data = run_sync(load_suite("branching"), PolicyContext("s")).to_dict()
    statuses = {c["case_id"]: c["status"] for c in data["cases_status"]}
    assert statuses["branch_05"] == statuses["branch_06"] == "SKIPPED"
    assert statuses["branch_01"] != "SKIPPED" and data["status"] == "COMPLETED"
    skipped = next(c for c in data["cases_status"] if c["case_id"] == "branch_05")
    assert "get_grade_band" in skipped["skip_reason"]
    assert data["completed_cases"] == 6 and len(data["agent_results"]) == 4


def test_an_unexpected_runner_exception_becomes_an_error_case_not_a_dead_run():
    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    with patch(f"{RUNNER}.run_agent_case", side_effect=boom), patch(
        f"{RUNNER}.run_workflow_case", side_effect=fake_case_runner("workflow")
    ):
        data = run_sync(load_suite("canonical")[:1], PolicyContext("s")).to_dict()
    assert data["status"] == "COMPLETED" and data["cases_status"][0]["status"] == "ERROR"
    assert data["agent_results"][0]["termination_reason"] == "ERROR"


def test_each_run_writes_its_own_headed_csv_and_results_csv_is_only_the_latest(runners):
    run_sync(load_suite("canonical")[:2], PolicyContext("s"), run_id="bench_first")
    run_sync(load_suite("canonical")[:3], PolicyContext("s"), run_id="bench_second")
    out = PolicyBenchmarkRunManager._results_dir()
    latest = list(csv.DictReader((out / "results.csv").open(encoding="utf-8")))
    assert {row["run_id"] for row in latest} == {"bench_second"} and len(latest) == 6
    assert list(latest[0]) == PolicyBenchmarkRunManager.RESULT_FIELDNAMES and "tool_retries" in latest[0]
    assert (out / "runs" / "bench_first.csv").exists() and (out / "runs" / "bench_second.csv").exists()
    assert str(out) != str(BASE_DIR / "benchmarks" / "policy_execution")  # tests never touch tracked evidence


def test_cancellation_stops_a_background_run(runners):
    manager = PolicyBenchmarkRunManager.get_instance()
    state = manager.start_benchmark(cases=load_suite("canonical"), context=PolicyContext("s"))
    assert manager.cancel_run(state.run_id) is True
    deadline = time.time() + 5
    while manager.get_run(state.run_id).status in ("RUNNING", "CANCELLING"):
        assert time.time() < deadline, "cancelled run did not finish"
        time.sleep(0.01)
    assert manager.get_run(state.run_id).status == "CANCELLED"
    assert manager.cancel_run("does_not_exist") is False


def test_a_second_benchmark_cannot_start_while_one_is_active(runners):
    from backend.errors import ConflictError

    gate = {"open": False}
    original = fake_case_runner("agent")

    def slow(*args, **kwargs):
        while not gate["open"]:
            time.sleep(0.01)
        return original(*args, **kwargs)

    manager = PolicyBenchmarkRunManager.get_instance()
    with patch(f"{RUNNER}.run_agent_case", side_effect=slow):
        first = manager.start_benchmark(cases=load_suite("canonical")[:1], context=PolicyContext("s"))
        with pytest.raises(ConflictError) as caught:
            manager.start_benchmark(cases=load_suite("canonical")[:1], context=PolicyContext("s"))
        assert caught.value.code == "BENCHMARK_ACTIVE" and caught.value.details["active_run_id"] == first.run_id
        gate["open"] = True
        deadline = time.time() + 5
        while manager.get_run(first.run_id).status == "RUNNING":
            assert time.time() < deadline
            time.sleep(0.01)
