import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi.responses import JSONResponse

from backend.services import chat_runs
from backend.services.chat_runs import (
    get_current_chat_run,
    managed_chat_run,
)
from backend.storage import shared_state


class _Payload:
    def __init__(self, run_id):
        self.run_id = run_id


@managed_chat_run
def _wait_for_shared_cancellation(sid, payload, started, run_refs):
    started.set()
    run = get_current_chat_run()
    run_refs.append(run)
    with chat_runs._runs_lock:
        chat_runs._runs.pop(run.run_id, None)
    while True:
        run.check()
        time.sleep(0.01)


def test_chat_run_cancellation_reaches_a_different_worker_process(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "chat-test.sqlite3"
    monkeypatch.setattr(shared_state, "APP_STATE_DB", database_path)
    monkeypatch.setenv("APP_STATE_DB", str(database_path))
    monkeypatch.setattr(shared_state, "_schema_ready", False)
    monkeypatch.setattr(shared_state, "_schema_ready_path", None)

    run_id = f"test_{uuid.uuid4().hex}"
    session_id = f"session_{uuid.uuid4().hex}"
    started = threading.Event()
    run_refs = []
    result = []
    worker = threading.Thread(
        target=lambda: result.append(
            _wait_for_shared_cancellation(
                session_id, _Payload(run_id), started, run_refs
            )
        ),
        daemon=True,
    )
    worker.start()
    try:
        assert started.wait(2)
        script = (
            "from backend.services.chat_runs import cancel_chat_run; "
            "import sys; print(cancel_chat_run(sys.argv[1], sys.argv[2]))"
        )
        cancelled = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                run_id,
                session_id,
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert cancelled.stdout.strip() == "True"
    finally:
        if run_refs:
            run_refs[0].cancel()
        worker.join(2)

    assert not worker.is_alive()
    assert isinstance(result[0], JSONResponse)
    assert result[0].status_code == 499
    assert json.loads(result[0].body)["run_id"] == run_id
    assert not chat_runs.cancel_chat_run(run_id, session_id)


def test_background_heartbeat_preserves_long_lived_chat_cancellation(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "chat-heartbeat.sqlite3"
    monkeypatch.setattr(shared_state, "APP_STATE_DB", database_path)
    monkeypatch.setenv("APP_STATE_DB", str(database_path))
    monkeypatch.setattr(shared_state, "_schema_ready", False)
    monkeypatch.setattr(shared_state, "_schema_ready_path", None)

    run_id = f"test_{uuid.uuid4().hex}"
    session_hash = "test-session-hash"
    chat_runs._register_shared_run(run_id, session_hash)
    with shared_state.state_connection(immediate=True) as connection:
        connection.execute(
            "UPDATE chat_runs SET updated_at = ? WHERE run_id = ?",
            (time.time() - chat_runs._RUN_TTL_SECONDS - 1, run_id),
        )

    monkeypatch.setattr(chat_runs, "_SHARED_HEARTBEAT_INTERVAL", 0.01)
    run = chat_runs.ChatRun(run_id, session_hash)
    run.start_heartbeat()
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with shared_state.state_connection() as connection:
                row = connection.execute(
                    "SELECT status, updated_at FROM chat_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            if row["updated_at"] > time.time() - 5:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("Background heartbeat did not refresh the run")

        assert row["status"] == "active"
        assert chat_runs._cancel_shared_run(run_id, session_hash)
        assert run.cancelled.wait(2)
    finally:
        run.finish()
