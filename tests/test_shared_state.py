import uuid

import pytest

from backend.storage import shared_state
from backend.storage.shared_state import (
    create_background_run,
    get_active_session_access,
    get_active_background_run_id,
    get_background_run,
    load_session_metadata,
    remove_session_state,
    request_background_run_cancellation,
    save_background_run,
    save_session_metadata,
)


@pytest.fixture
def isolated_state_db(tmp_path, monkeypatch):
    database_path = tmp_path / "shared-state-test.sqlite3"
    monkeypatch.setattr(shared_state, "APP_STATE_DB", database_path)
    monkeypatch.setenv("APP_STATE_DB", str(database_path))
    monkeypatch.setattr(shared_state, "_schema_ready", False)
    monkeypatch.setattr(shared_state, "_schema_ready_path", None)


def test_background_run_cancellation_is_not_lost_by_stale_progress_writes(
    isolated_state_db,
):
    namespace = f"test_{uuid.uuid4().hex}"
    run_id = f"run_{uuid.uuid4().hex}"
    snapshot = {"evaluation_run_id": run_id, "status": "RUNNING"}
    create_background_run(namespace, run_id, "RUNNING", snapshot)

    cancellation = request_background_run_cancellation(namespace, run_id)
    assert cancellation["cancellation_requested"] is True

    saved_status = save_background_run(namespace, run_id, "RUNNING", snapshot)
    assert saved_status == "CANCELLING"
    persisted = get_background_run(namespace, run_id)
    assert persisted["status"] == "CANCELLING"
    assert persisted["cancellation_requested"] is True

    save_background_run(namespace, run_id, "CANCELLED", persisted)
    assert get_active_background_run_id(namespace) is None


def test_session_metadata_persists_and_clear_advances_revision(isolated_state_db):
    session_id = f"session_{uuid.uuid4().hex}"
    hash_by_doc = {"doc-1": ["content-digest", "structured"]}
    revision = save_session_metadata(session_id, hash_by_doc, {"structured": 3})

    metadata = load_session_metadata(session_id)
    assert metadata["hash_by_doc"] == hash_by_doc
    assert metadata["chunk_counts"] == {"structured": 3}
    assert metadata["revision"] == revision

    remove_session_state(session_id)
    cleared = load_session_metadata(session_id)
    assert cleared["hash_by_doc"] == {}
    assert cleared["chunk_counts"] == {}
    assert cleared["revision"] > revision


def test_active_session_access_excludes_expired_sessions(isolated_state_db):
    import time

    from backend.storage.shared_state import state_connection

    now = time.time()
    with state_connection(immediate=True) as connection:
        connection.executemany(
            "INSERT INTO session_activity (session_id, last_access) VALUES (?, ?)",
            [
                ("active-session", now - 30),
                ("expired-session", now - 600),
            ],
        )

    assert set(get_active_session_access(ttl_seconds=300)) == {"active-session"}
