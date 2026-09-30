"""Policy HTTP API: session scope, full trace in the response, run-level retries, suites, MCP view."""

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.schemas.policy import MAX_RETRIES
from backend.services import policy_agent
from backend.services.policy_agent import PolicyAgentError
from backend.storage.session_manager import optional_session_id
from tests.policy_test_utils import final_reply, model_reply, script_model

Q = "How much written notice must EMP003 provide if they resign while on probation?"
BODY = {"employee_id": "EMP003", "question": Q, "top_k": 5, "temperature": 0.3}


@pytest.fixture
def client(policy_session):
    app = create_app()
    app.dependency_overrides[optional_session_id] = lambda: policy_session.session_id
    return TestClient(app)


@pytest.fixture
def anonymous_client():
    app = create_app()
    app.dependency_overrides[optional_session_id] = lambda: None
    return TestClient(app)


def agent_script(monkeypatch):
    return script_model(
        monkeypatch,
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"})], reasoning="record first"),
        model_reply(tool_calls=[("search_handbook", {"query": "resignation notice probation"})], provider_attempts=2),
        final_reply("One week written notice", "10.1 Resignation", "Probation."),
    )


# -- session scope -----------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/policy/search", "/api/policy/agent", "/api/policy/workflow", "/api/policy/benchmark/start"])
def test_nothing_uploaded_means_409_with_an_actionable_code(anonymous_client, path):
    body = {"suite": "canonical"} if "benchmark" in path else BODY
    response = anonymous_client.post(path, json=body)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "NO_INDEXED_DOCUMENTS" and "Upload" in error["message"]


def test_an_empty_index_is_also_a_409(monkeypatch):
    from tests.policy_test_utils import FakeStore, install_indexed_session

    install_indexed_session(monkeypatch, FakeStore([]))
    app = create_app()
    app.dependency_overrides[optional_session_id] = lambda: "test-session"
    assert TestClient(app).post("/api/policy/search", json=BODY).status_code == 409


def test_readiness_reports_documents_mode_and_tools(client):
    data = client.get("/api/policy/readiness").json()
    assert data["document_count"] == 2 and data["chunk_count"] > 2 and data["retrieval_mode"] == "lexical"
    assert {d["filename"] for d in data["documents"]} == {"handbook.md", "employee_records.md"}
    assert data["tools"]["tool_count"] == 5 and data["chat_backend"] == "groq"


def test_readiness_without_documents_says_not_ready(anonymous_client):
    data = anonymous_client.get("/api/policy/readiness").json()
    assert data["document_count"] == 0 and data["ready"] is False


def test_employees_come_from_the_uploaded_roster(client, anonymous_client):
    employees = client.get("/api/policy/employees").json()
    assert [e["employee_id"] for e in employees] == ["EMP001", "EMP002", "EMP003"] and employees[2]["employment_status"] == "Probation"
    assert anonymous_client.get("/api/policy/employees").status_code == 409


# -- search: routing, trace, retries ----------------------------------------


def test_search_returns_the_full_trace_for_a_routed_question(client, monkeypatch):
    agent_script(monkeypatch)
    body = client.post("/api/policy/search", json={**BODY, "force_mode": "agent"}).json()
    assert body["termination_reason"] == "SUCCESS" and body["execution_mode"] == "agent"
    assert body["routing"]["mode"] == "agent" and "forced" in body["routing"]["reason"]
    assert [c["tool_name"] for c in body["tool_calls"]] == ["get_employee_record", "search_handbook"]
    first = body["tool_calls"][0]
    assert first["selection"]["rationale"] == "record first" and first["server"] == "policy-search"
    assert {"arguments", "output", "attempts", "retries", "attempt_log", "latency_ms", "roles"} <= set(first)
    assert body["tool_audit"]["selection_ok"] is True and body["citation"]["all_resolve"] is True
    assert body["tool_audit"]["retries"]["model_call_retries"] == 1 and body["tool_audit"]["retries"]["run_attempts"] == 1
    assert body["retry_history"][0]["status"] == "SUCCESS" and body["retry_history"][0]["tool_sequence"] == ["get_employee_record", "search_handbook"]
    assert body["provider_cost"] == "N/A" and body["run_id"].startswith("search_") and body["model"]


def test_auto_routing_uses_the_workflow_for_a_single_path_question(client, monkeypatch):
    script_model(monkeypatch, final_reply("One week", "10.1"))
    body = client.post("/api/policy/search", json=BODY).json()
    assert body["execution_mode"] == "workflow" and body["routing"]["requires_agent"] is False
    assert body["iterations"] == 1 and len(body["llm_calls"]) == 1


def test_a_transient_failure_is_retried_and_every_attempt_is_reported(client, monkeypatch):
    calls = {"n": 0}
    replies = [
        model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP003"}), ("search_handbook", {"query": "notice"})], prompt_tokens=100, completion_tokens=10),
        final_reply(prompt_tokens=200, completion_tokens=20),
    ]

    def step(messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PolicyAgentError("PROVIDER_TRANSIENT", "HTTP 429", [{"attempt": 1, "outcome": "failed", "status_code": 429}])
        return replies.pop(0)

    script_model(monkeypatch)
    monkeypatch.setattr(policy_agent, "_call_groq_step", step)
    body = client.post("/api/policy/search", json={**BODY, "force_mode": "agent"}).json()
    assert body["termination_reason"] == "SUCCESS" and body["total_attempts"] == 2 and body["attempt"] == 2
    history = body["retry_history"]
    assert [h["status"] for h in history] == ["RETRY", "SUCCESS"] and history[0]["retry_reason"] == "PROVIDER_TRANSIENT"
    assert history[0]["retryable"] is True and history[1]["is_retry"] is True
    assert body["total_tokens"] == 330  # attempts accumulate
    assert body["tool_audit"]["retries"]["run_attempts"] == 2 and body["tool_audit"]["retries"]["run_retries"] == 1
    assert [c["attempt"] for c in body["llm_calls"]] == [1, 2, 2]


def test_retries_are_bounded_by_max_retries(client, monkeypatch):
    script_model(monkeypatch)
    error = PolicyAgentError("PROVIDER_TRANSIENT", "HTTP 503")
    monkeypatch.setattr(policy_agent, "_call_groq_step", lambda *a, **k: (_ for _ in ()).throw(error))
    body = client.post("/api/policy/search", json={**BODY, "force_mode": "agent", "max_retries": 1}).json()
    assert body["termination_reason"] == "PROVIDER_TRANSIENT" and body["total_attempts"] == 2
    assert [h["status"] for h in body["retry_history"]] == ["RETRY", "FAILED"]
    none = client.post("/api/policy/search", json={**BODY, "force_mode": "agent", "max_retries": 0}).json()
    assert none["total_attempts"] == 1 and none["retry_history"][0]["status"] == "FAILED"


def test_full_default_retry_budget_is_one_initial_plus_max_retries(client, monkeypatch):
    script_model(monkeypatch)
    error = PolicyAgentError("PROVIDER_TRANSIENT", "HTTP 503")
    monkeypatch.setattr(policy_agent, "_call_groq_step", lambda *a, **k: (_ for _ in ()).throw(error))
    body = client.post("/api/policy/search", json={**BODY, "force_mode": "agent"}).json()
    assert body["total_attempts"] == 1 + MAX_RETRIES


@pytest.mark.parametrize("value", [3, -1])
def test_max_retries_above_the_cap_is_rejected(client, value):
    assert client.post("/api/policy/search", json={**BODY, "max_retries": value}).status_code == 422


def test_unknown_employee_is_not_retried(client, monkeypatch):
    script_model(monkeypatch, model_reply(tool_calls=[("get_employee_record", {"employee_id": "EMP999"})]))
    body = client.post("/api/policy/search", json={"employee_id": "EMP999", "question": "leave?", "force_mode": "agent"}).json()
    assert body["termination_reason"] == "INVALID_EMPLOYEE" and body["total_attempts"] == 1
    assert body["retry_history"][0]["retryable"] is False


def test_direct_agent_and_workflow_endpoints_share_the_contract(client, monkeypatch):
    agent_script(monkeypatch)
    agent = client.post("/api/policy/agent", json=BODY).json()
    assert agent["run_id"].startswith("agent_") and agent["tool_audit"]["tools_selected"] == ["get_employee_record", "search_handbook"]
    script_model(monkeypatch, final_reply())
    workflow = client.post("/api/policy/workflow", json=BODY).json()
    assert workflow["run_id"].startswith("wf_") and set(workflow) == set(agent)


def test_router_classify_previews_without_running_anything(client):
    data = client.get("/api/policy/router/classify", params={"question": "grade band of EMP001?", "employee_id": "EMP001"}).json()
    assert data["mode"] == "agent" and "get_grade_band" in data["reason"]


# -- suites, trajectory, models, MCP -----------------------------------------


def test_case_suites(client):
    assert len(client.get("/api/policy/cases").json()) == 10
    assert len(client.get("/api/policy/cases", params={"suite": "all"}).json()) == 16
    assert client.get("/api/policy/cases", params={"suite": "nope"}).status_code == 422


def test_expected_trajectories_expose_alternate_paths(client):
    expected = {item["case_id"]: item for item in client.get("/api/policy/trajectory/expected").json()}
    assert len(expected) == 16 and len(expected["case_03"]["paths"]) == 2 and expected["branch_05"]["allowed_extra_tools"]


def test_models_endpoint_is_groq_only(client, monkeypatch):
    import httpx

    from backend.routes import policy as routes

    monkeypatch.setattr(routes, "CHAT_BACKEND", "groq")
    monkeypatch.setattr(routes, "GROQ_API_KEY", "k")
    monkeypatch.setattr(routes, "GROQ_AGENT_MODELS", {"agent-model"})
    monkeypatch.setattr(
        httpx, "get",
        lambda *a, **k: httpx.Response(200, json={"data": [{"id": "agent-model"}, {"id": "other"}]}, request=httpx.Request("GET", "http://x")),
    )
    data = client.get("/api/policy/models").json()
    assert data["provider"] == "groq" and data["agent_models"] == ["agent-model"] and data["models"] == ["agent-model", "other"]
    monkeypatch.setattr(routes, "CHAT_BACKEND", "ollama")
    assert client.get("/api/policy/models").status_code == 503


def test_mcp_status_wire_and_reload(client):
    status = client.get("/api/mcp/status").json()
    assert status["server_count"] == 2 and status["tool_count"] == 5
    assert {s["name"] for s in status["servers"]} == {"policy-search", "hris"}
    assert all(t["roles"] for s in status["servers"] for t in s["tool_details"])
    frames = client.get("/api/mcp/wire", params={"server": "hris"}).json()["frames"]
    assert [f["message"].get("method") for f in frames if f["direction"] == "client->server"][:3] == ["initialize", "notifications/initialized", "tools/list"]
    assert client.post("/api/mcp/reload").json()["tool_count"] == 5


def test_benchmark_run_is_trajectory_scored_through_the_api(client, monkeypatch):
    import time
    from unittest.mock import patch

    from tests.test_benchmark_progress import fake_case_runner

    with patch("backend.services.policy_benchmark_runner.run_agent_case", side_effect=fake_case_runner("agent")), patch(
        "backend.services.policy_benchmark_runner.run_workflow_case", side_effect=fake_case_runner("workflow")
    ):
        run_id = client.post("/api/policy/benchmark/start", json={"suite": "canonical"}).json()["run_id"]
        deadline = time.time() + 10
        while client.get(f"/api/policy/benchmark/runs/{run_id}").json()["status"] == "RUNNING":
            assert time.time() < deadline
            time.sleep(0.02)
    run = client.get(f"/api/policy/benchmark/runs/{run_id}").json()
    assert run["status"] == "COMPLETED" and run["trajectory"]["summary"]["case_count"] == 10
    report = client.post("/api/policy/trajectory/evaluate", json={"run_id": run_id}).json()
    assert report["summary"]["trajectory_pass_rate_pct"] == 100.0 and len(report["cases"]) == 10
    compared = client.post("/api/policy/trajectory/evaluate", json={"run_id": run_id, "baseline_run_id": run_id}).json()
    assert compared["comparison"]["regressions"] == [] and len(compared["comparison"]["per_mode"]) == 9
    assert client.post("/api/policy/trajectory/evaluate", json={"run_id": "nope"}).status_code == 404
    assert client.get("/api/policy/benchmark/latest").json()["rows"][0]["run_id"] == run_id
