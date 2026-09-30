"""Test-wide isolation and shared fixtures.

Evidence and audit files must never land in tracked paths, and unit tests patch tool
code inside this process, so MCP servers run in-process (same JSON-RPC frames, no
subprocess). All of this is set before any backend module is imported.
"""

from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="policy_tests_")
os.environ.setdefault("POLICY_BENCHMARK_OUTPUT_DIR", os.path.join(_TMP, "bench"))
os.environ.setdefault("MCP_AUDIT_LOG_PATH", os.path.join(_TMP, "mcp_audit.jsonl"))
os.environ.setdefault("MCP_FORCE_TRANSPORT", "inprocess")
# Tests must not depend on a developer's .env. The older suites assume the semantic (Ollama)
# embedding setup; lexical mode (EMBED_BACKEND=none) is covered by tests/test_lexical_mode.py.
os.environ["EMBED_BACKEND"] = "ollama"
os.environ["CHAT_BACKEND"] = "groq"
os.environ.setdefault("APP_STATE_DB", os.path.join(_TMP, "app_state.sqlite3"))  # never the live app DB
os.environ.setdefault("MCP_TOOL_RETRY_BACKOFF_SECONDS", "0")

import pytest  # noqa: E402

from tests.policy_test_utils import install_indexed_session  # noqa: E402


@pytest.fixture
def policy_session(monkeypatch):
    """A fake indexed browser session (policy text + roster chunks) and its context."""
    return install_indexed_session(monkeypatch)


@pytest.fixture(autouse=True)
def fresh_tool_registry():
    """Each test discovers tools afresh from the active config."""
    from backend.mcp.registry import reset_tool_registry

    reset_tool_registry()
    yield
    reset_tool_registry()
