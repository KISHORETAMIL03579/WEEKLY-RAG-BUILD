"""MCP host: protocol, discovery, config-only server swap, retries, isolation, audit."""

import hashlib
import json
from pathlib import Path

import pytest

from backend.config import BASE_DIR
from backend.mcp import protocol
from backend.mcp.registry import McpToolRegistry, UnknownToolError
from backend.mcp.schema import normalize_arguments, validate_arguments
from backend.mcp.servers import hris_server, policy_server
from tests import flaky_server

CONFIG_ONE = BASE_DIR / "config" / "mcp_servers.server1.json"
CONFIG_BOTH = BASE_DIR / "config" / "mcp_servers.json"


def write_config(tmp_path, *servers):
    path = tmp_path / "servers.json"
    path.write_text(json.dumps({"servers": list(servers)}), encoding="utf-8")
    return path


def flaky_registry(tmp_path):
    cfg = write_config(tmp_path, {"name": "flaky", "transport": "inprocess", "module": "tests.flaky_server"})
    return McpToolRegistry(cfg, force_transport="inprocess")


# -- protocol ---------------------------------------------------------------


def rpc(server, method, params=None, msg_id=1):
    return server.handle_message(protocol.request(msg_id, method, params))


def test_server_speaks_initialize_list_call():
    server = hris_server.build_server()
    init = rpc(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["serverInfo"]["name"] == "hris"
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert server.handle_message(protocol.notification("notifications/initialized")) is None
    listed = rpc(server, "tools/list", msg_id=2)["result"]["tools"]
    assert {t["name"] for t in listed} == {"get_grade_band", "get_leave_balance"}
    assert all(t["inputSchema"]["additionalProperties"] is False and t["_meta"]["roles"] for t in listed)
    called = rpc(server, "tools/call", {"name": "get_leave_balance", "arguments": {"employee_id": "emp001"}}, msg_id=3)["result"]
    assert called["isError"] is False
    assert called["structuredContent"]["accrued_leave_days"] == 12
    assert json.loads(called["content"][0]["text"]) == called["structuredContent"]


def test_unknown_version_negotiates_down_and_unknown_method_errors():
    server = hris_server.build_server()
    assert rpc(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == protocol.PROTOCOL_VERSION
    assert rpc(server, "nope")["error"]["code"] == protocol.METHOD_NOT_FOUND
    assert rpc(server, "ping")["result"] == {}
    assert server.handle_message("garbage")["error"]["code"] == protocol.INVALID_REQUEST


def test_unknown_tool_is_a_protocol_error_but_bad_arguments_are_a_tool_error_the_model_can_read():
    server = hris_server.build_server()
    assert rpc(server, "tools/call", {"name": "nope", "arguments": {}})["error"]["code"] == protocol.INVALID_PARAMS
    bad = rpc(server, "tools/call", {"name": "get_grade_band", "arguments": {"employee_id": "bad id!"}})["result"]
    assert bad["isError"] is True and bad["structuredContent"]["error"]["code"] == "INVALID_ARGUMENTS"
    missing = rpc(server, "tools/call", {"name": "get_grade_band", "arguments": {}})["result"]
    assert "employee_id" in missing["structuredContent"]["error"]["message"]


def test_hris_distinguishes_unknown_employee_from_hris_down(monkeypatch):
    server = hris_server.build_server()
    err = rpc(server, "tools/call", {"name": "get_grade_band", "arguments": {"employee_id": "EMP999"}})["result"]["structuredContent"]["error"]
    assert err["code"] == "EMPLOYEE_NOT_FOUND" and err["retryable"] is False
    monkeypatch.setenv("HRIS_DATA_PATH", "does/not/exist.json")
    down = rpc(server, "tools/call", {"name": "get_grade_band", "arguments": {"employee_id": "EMP001"}})["result"]["structuredContent"]["error"]
    assert down["code"] == "HRIS_UNAVAILABLE" and down["retryable"] is True


def test_policy_server_error_style_switch_reproduces_the_opaque_before_behaviour(monkeypatch, policy_session):
    def call(name, arguments):
        server = policy_server.build_server()
        return rpc(server, "tools/call", {"name": name, "arguments": arguments, "_meta": policy_session.to_meta()})["result"]

    recoverable = call("get_employee_record", {"employee_id": "EMP999"})["structuredContent"]["error"]
    assert recoverable["code"] == "EMPLOYEE_NOT_FOUND" and "hint" in recoverable
    monkeypatch.setenv(policy_server.ERROR_STYLE_ENV, "opaque")
    opaque = call("get_employee_record", {"employee_id": "EMP999"})["structuredContent"]["error"]
    assert opaque == {"code": "ERROR", "message": "Error: not found", "retryable": False}


def test_policy_tools_use_enums_from_the_taxonomy_and_no_overlapping_jobs():
    tools = {t["name"]: t for t in rpc(policy_server.build_server(), "tools/list")["result"]["tools"]}
    jurisdiction = tools["get_jurisdiction_rules"]["inputSchema"]["properties"]
    assert "Kenya" in jurisdiction["jurisdiction"]["enum"] and "leave" in jurisdiction["policy_category"]["enum"]
    for name, tool in tools.items():
        assert "Do NOT use" in tool["description"], f"{name} description must say what it is not for"


# -- schema -----------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "q": {"type": "string", "minLength": 2, "maxLength": 5, "pattern": "^[a-z]+$"},
        "k": {"type": "integer", "minimum": 1, "maximum": 3},
        "j": {"type": "string", "enum": ["a", "b"]},
    },
    "required": ["q"],
    "additionalProperties": False,
}


@pytest.mark.parametrize(
    "arguments",
    [{}, {"q": "ab", "x": 1}, {"q": 5}, {"q": " "}, {"q": "abcdefg"}, {"q": "AB"}, {"q": "ab", "k": True}, {"q": "ab", "k": 0}, {"q": "ab", "k": 4}, {"q": "ab", "j": "c"}, "not a dict"],
)
def test_schema_rejects_invalid_arguments(arguments):
    with pytest.raises((TypeError, ValueError)):
        validate_arguments(SCHEMA, arguments)


def test_schema_accepts_valid_and_normalises_numeric_strings():
    validate_arguments(SCHEMA, {"q": "abc", "k": 2, "j": "a"})
    assert normalize_arguments(SCHEMA, {"q": "abc", "k": "3"}) == {"q": "abc", "k": 3}
    assert normalize_arguments(SCHEMA, {"q": "abc", "k": "3.5"})["k"] == "3.5"


# -- discovery & config-only swap -------------------------------------------


def test_discovery_reports_servers_tools_and_roles_from_tools_list():
    registry = McpToolRegistry(CONFIG_BOTH, force_transport="inprocess")
    report = registry.discovery_report()
    assert report["server_count"] == 2 and report["tool_count"] == 5
    assert report["tool_names"] == ["get_employee_record", "search_handbook", "get_jurisdiction_rules", "get_grade_band", "get_leave_balance"]
    assert [s["status"] for s in report["servers"]] == ["connected", "connected"]
    assert registry.roles_for("get_grade_band") == ["employee_lookup", "evidence"]
    assert registry.roles_for("search_handbook") == ["evidence"]
    assert registry.tool_definitions()[0]["parameters"]["required"] == ["employee_id"]


def test_adding_the_second_server_needs_no_code_change():
    """Server one -> server one + two: same agent/host code, only the config differs."""
    host_files = [
        BASE_DIR / "backend" / "services" / "policy_agent.py",
        BASE_DIR / "backend" / "mcp" / "client.py",
        BASE_DIR / "backend" / "mcp" / "registry.py",
        BASE_DIR / "backend" / "mcp" / "schema.py",
    ]
    digest = lambda: [hashlib.sha256(f.read_bytes()).hexdigest() for f in host_files]  # noqa: E731
    before_hash = digest()
    one = McpToolRegistry(CONFIG_ONE, force_transport="inprocess").discovery_report()
    both = McpToolRegistry(CONFIG_BOTH, force_transport="inprocess").discovery_report()
    assert digest() == before_hash
    assert one["tool_count"] == 3 and both["tool_count"] == 5
    assert set(both["tool_names"]) - set(one["tool_names"]) == {"get_grade_band", "get_leave_balance"}
    servers = lambda p: [s["name"] for s in json.loads(Path(p).read_text())["servers"]]  # noqa: E731
    assert servers(CONFIG_BOTH) == servers(CONFIG_ONE) + ["hris"]


def test_wire_log_is_the_raw_initialize_list_call_exchange():
    registry = McpToolRegistry(CONFIG_BOTH, force_transport="inprocess")
    registry.call_tool("get_grade_band", {"employee_id": "EMP001"})
    frames = registry.wire_log("hris")
    methods = [f["message"].get("method") for f in frames if f["direction"] == "client->server"]
    assert methods == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    responses = [f["message"] for f in frames if f["direction"] == "server->client"]
    assert [m["id"] for m in responses] == [1, 2, 3]
    assert responses[2]["result"]["structuredContent"]["grade_band"] == "G7"


def test_unknown_tool_and_invalid_calls_fail_before_anything_is_sent():
    registry = McpToolRegistry(CONFIG_BOTH, force_transport="inprocess")
    with pytest.raises(UnknownToolError):
        registry.validate_call("does_not_exist", {})
    with pytest.raises(ValueError):
        registry.validate_call("get_jurisdiction_rules", {"jurisdiction": "Atlantis", "policy_category": "leave"})
    assert not [f for f in registry.wire_log() if f["message"].get("method") == "tools/call"]


def test_duplicate_tool_names_keep_the_first_and_bad_servers_do_not_break_the_rest(tmp_path):
    cfg = write_config(
        tmp_path,
        {"name": "a", "transport": "inprocess", "module": "backend.mcp.servers.hris_server"},
        {"name": "b", "transport": "inprocess", "module": "backend.mcp.servers.hris_server"},
        {"name": "broken", "transport": "inprocess", "module": "no.such.module"},
    )
    report = McpToolRegistry(cfg, force_transport="inprocess").discovery_report()
    assert report["tool_count"] == 2
    statuses = {s["name"]: s["status"] for s in report["servers"]}
    assert statuses == {"a": "connected", "b": "connected", "broken": "error"}
    assert "ModuleNotFoundError" in next(s for s in report["servers"] if s["name"] == "broken")["error"]


def test_config_must_name_unique_servers(tmp_path):
    with pytest.raises(ValueError):
        McpToolRegistry(write_config(tmp_path), force_transport="inprocess").connect()
    dup = write_config(tmp_path, {"name": "x", "module": "m"}, {"name": "x", "module": "m"})
    with pytest.raises(ValueError):
        McpToolRegistry(dup, force_transport="inprocess").connect()


# -- retries ----------------------------------------------------------------


def test_transient_tool_failures_are_retried_and_every_attempt_is_recorded(tmp_path):
    flaky_server.reset(fail_times=2)
    outcome = flaky_registry(tmp_path).call_tool("flaky_lookup", {}, backoff=0)
    assert outcome.is_error is False and outcome.observation["value"] == 42
    assert outcome.attempts == 3 and outcome.retries == 2
    assert [a["status"] for a in outcome.attempt_log] == ["error", "error", "ok"]
    assert [a["retryable"] for a in outcome.attempt_log] == [True, True, False]
    assert flaky_server.STATE["calls"] == 3


def test_retries_are_bounded_and_exhaustion_is_reported_as_a_retryable_error(tmp_path):
    flaky_server.reset(fail_times=99)
    outcome = flaky_registry(tmp_path).call_tool("flaky_lookup", {}, max_retries=2, backoff=0)
    assert outcome.is_error and outcome.error["code"] == "UPSTREAM_DOWN" and outcome.error["retryable"] is True
    assert outcome.attempts == 3 and flaky_server.STATE["calls"] == 3


def test_max_retries_zero_means_a_single_attempt(tmp_path):
    flaky_server.reset(fail_times=99)
    outcome = flaky_registry(tmp_path).call_tool("flaky_lookup", {}, max_retries=0, backoff=0)
    assert outcome.attempts == 1 and flaky_server.STATE["calls"] == 1


def test_permanent_errors_are_never_retried(tmp_path):
    flaky_server.reset(fail_times=99, mode="permanent")
    outcome = flaky_registry(tmp_path).call_tool("flaky_lookup", {}, backoff=0)
    assert outcome.attempts == 1 and outcome.error["code"] == "NOT_ALLOWED"
    assert flaky_server.STATE["calls"] == 1


def test_internal_server_errors_are_retried(tmp_path):
    flaky_server.reset(fail_times=1, mode="rpc")
    outcome = flaky_registry(tmp_path).call_tool("flaky_lookup", {}, backoff=0)
    assert outcome.is_error is False and outcome.attempts == 2
    assert outcome.attempt_log[0]["status"] == "rpc_error"


def test_backoff_doubles_between_attempts(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr("backend.mcp.registry.time.sleep", sleeps.append)
    flaky_server.reset(fail_times=2)
    flaky_registry(tmp_path).call_tool("flaky_lookup", {}, backoff=0.5)
    assert sleeps == [0.5, 1.0]


# -- real stdio process ------------------------------------------------------


def stdio_registry(tmp_path, module, name="probe"):
    cfg = write_config(tmp_path, {"name": name, "transport": "stdio", "module": module})
    return McpToolRegistry(cfg, force_transport="")


def test_stdio_server_runs_as_a_subprocess_and_is_discovered(tmp_path):
    registry = stdio_registry(tmp_path, "backend.mcp.servers.hris_server", "hris")
    try:
        assert registry.discovery_report()["servers"][0]["transport"] == "stdio"
        outcome = registry.call_tool("get_grade_band", {"employee_id": "EMP004"})
        assert outcome.observation["grade_band"] == "G9"
        pid = registry._clients["hris"]._transport._process.pid
        assert pid != __import__("os").getpid()
    finally:
        registry.close()


def test_third_party_server_does_not_inherit_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "super-secret")
    monkeypatch.setenv("QDRANT_API_KEY", "super-secret")
    registry = stdio_registry(tmp_path, "tests.env_probe_server")
    try:
        names = registry.call_tool("env_names", {}).observation["env_names"]
    finally:
        registry.close()
    assert "PATH" in names or "SYSTEMROOT" in names
    assert "GROQ_API_KEY" not in names and "QDRANT_API_KEY" not in names


def test_a_dead_stdio_process_is_reconnected_on_retry(tmp_path):
    registry = stdio_registry(tmp_path, "tests.env_probe_server")
    try:
        first = registry.call_tool("env_names", {}).observation["pid"]
        registry._clients["probe"]._transport._process.kill()
        registry._clients["probe"]._transport._process.wait()
        outcome = registry.call_tool("env_names", {}, backoff=0)
        assert outcome.is_error is False
        assert outcome.observation["pid"] != first  # a fresh process answered
    finally:
        registry.close()


# -- audit ------------------------------------------------------------------


def test_every_call_writes_one_audit_line_without_the_raw_session_id(tmp_path, monkeypatch, policy_session):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr("backend.mcp.registry.MCP_AUDIT_LOG_PATH", audit)
    registry = McpToolRegistry(CONFIG_BOTH, force_transport="inprocess")
    registry.call_tool("get_employee_record", {"employee_id": "EMP001"}, context=policy_session, caller="unit")
    registry.call_tool("get_leave_balance", {"employee_id": "EMP999"}, caller="unit")
    lines = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [(l["tool"], l["employee_id"], l["is_error"], l["error_code"]) for l in lines] == [
        ("get_employee_record", "EMP001", False, None),
        ("get_leave_balance", "EMP999", True, "EMPLOYEE_NOT_FOUND"),
    ]
    assert lines[0]["caller"] == "unit" and lines[0]["attempts"] == 1
    assert "test-session" not in audit.read_text() and lines[0]["session_hash"]
