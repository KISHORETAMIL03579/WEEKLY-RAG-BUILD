from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.storage import qdrant_store
from backend.storage.qdrant_store import QdrantVectorStore
from backend.storage import session_manager


def test_clear_inactive_collections_only_deletes_expired_sessions(monkeypatch):
    client = MagicMock()
    client.get_collections.return_value.collections = [
        SimpleNamespace(name="chunks_active"),
        SimpleNamespace(name="chunks_expired"),
        SimpleNamespace(name="evaluation_results"),
    ]
    monkeypatch.setattr(qdrant_store, "_client", lambda: client)

    deleted, failed = QdrantVectorStore.clear_inactive_collections({"active"})

    assert (deleted, failed) == (1, 0)
    client.delete_collection.assert_called_once_with("chunks_expired")


def test_failed_inactive_collection_delete_is_reported_and_retryable(monkeypatch):
    client = MagicMock()
    client.get_collections.return_value.collections = [
        SimpleNamespace(name="chunks_expired"),
    ]
    client.delete_collection.side_effect = RuntimeError("Qdrant unavailable")
    monkeypatch.setattr(qdrant_store, "_client", lambda: client)

    deleted, failed = QdrantVectorStore.clear_inactive_collections(set())

    assert (deleted, failed) == (0, 1)
    client.delete_collection.assert_called_once_with("chunks_expired")


def test_session_sweep_retries_failed_qdrant_cleanup(monkeypatch, tmp_path):
    attempts = iter([(0, 1), (1, 0)])
    monkeypatch.setattr(session_manager, "VECTOR_BACKEND", "qdrant")
    monkeypatch.setattr(session_manager, "UPLOAD_FOLDER", tmp_path)
    monkeypatch.setattr(
        session_manager, "get_active_session_access", lambda ttl: {"active": 1}
    )
    monkeypatch.setattr(
        QdrantVectorStore,
        "clear_inactive_collections",
        lambda active: next(attempts),
    )

    assert session_manager.sweep_inactive_qdrant_collections(force=True) == (0, 1)
    assert session_manager.sweep_inactive_qdrant_collections(force=True) == (1, 0)
