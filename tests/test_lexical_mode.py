"""EMBED_BACKEND=none: chunks live in Qdrant, retrieval is BM25, Groq still answers.

Groq has no embeddings API, so a Groq-only deployment needs this mode. Nothing below may
call an embedding provider.
"""

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.routes import chat as chat_route
from backend.services import embeddings
from tests.policy_test_utils import build_store
from tests.test_eval_metrics import make_client, set_session


def test_placeholder_vectors_are_constant_one_dimensional_and_the_right_length():
    assert embeddings.lexical_placeholder_vectors(3) == [[1.0], [1.0], [1.0]]
    assert embeddings.lexical_placeholder_vectors(0) == []


def test_embedding_calls_refuse_cleanly_in_lexical_mode(monkeypatch):
    monkeypatch.setattr(embeddings, "LEXICAL_ONLY", True)
    with pytest.raises(RuntimeError, match="EMBED_BACKEND=none"):
        embeddings.embed_texts(["hello"])
    assert embeddings.embed_texts([]) == []


def test_embeddings_are_reported_unconfigured_when_backend_is_none(monkeypatch):
    monkeypatch.setattr(embeddings, "EMBED_BACKEND", "none")
    assert embeddings.embeddings_configured() is False
    monkeypatch.setattr(embeddings, "EMBED_BACKEND", "gemini")
    monkeypatch.setattr(embeddings, "GEMINI_API_KEY", "")
    assert embeddings.embeddings_configured() is False
    monkeypatch.setattr(embeddings, "GEMINI_API_KEY", "k")
    assert embeddings.embeddings_configured() is True


def test_upload_to_qdrant_stores_placeholder_vectors_without_calling_an_embedder():
    from app import app

    client = make_client(app)
    set_session(client, "lexical_upload")
    embed = MagicMock(side_effect=AssertionError("no embedding provider may be called"))
    with patch("app.VECTOR_BACKEND", "qdrant"), patch("backend.routes.ingestion.LEXICAL_ONLY", True), patch(
        "app._embeddings_configured", return_value=False
    ), patch("app.embed_texts", embed), patch("app._get_store") as get_store:
        store = MagicMock()
        store.chunks = []
        get_store.return_value = store
        response = client.post(
            "/upload",
            files={"files": ("notes.txt", io.BytesIO(b"Staff on probation give one week written notice."), "text/plain")},
        )
    assert response.status_code == 200
    document = response.json()["documents"][0]
    assert "error" not in document and document["chunks"] >= 1
    chunks, vectors = store.add.call_args.args
    assert len(vectors) == len(chunks) and all(v == [1.0] for v in vectors)
    embed.assert_not_called()


def ask_overrides(store, answers):
    def generate(query, results, temperature=0.3):
        answers.append([r["filename"] for r in results])
        return "One week written notice [1]."

    trace_store = SimpleNamespace(log=lambda record: None)
    overrides = {
        "_get_store": lambda sid: store,
        "_embeddings_configured": lambda: False,
        "_chat_configured": lambda: True,
        "generate_answer": generate,
        "TRACES": trace_store,
        "RERANK_ENABLED": False,
        "QUERY_REWRITE_ENABLED": False,
        "SESSION_FILES": {"test-session": {}},
    }
    return lambda name, default=None: overrides.get(name, default)


def test_chat_uses_bm25_retrieval_and_groq_generation_in_lexical_mode():
    store = build_store()
    answers = []
    with patch.object(chat_route, "LEXICAL_ONLY", True), patch.object(
        chat_route, "get_app_symbol", side_effect=ask_overrides(store, answers)
    ), patch.object(chat_route, "embed_text", side_effect=AssertionError("no query embedding")):
        result = chat_route.ask("test-session", chat_route.AskPayload(query="written notice resignation probation"))
    assert result["found"] is True and "One week" in result["answer"]
    assert answers == [["handbook.md"]] or all(f == "handbook.md" for f in answers[0])
    assert result["sources"] and result["sources"][0]["filename"] == "handbook.md"


def test_chat_in_lexical_mode_still_refuses_when_nothing_matches():
    store = build_store()
    answers = []
    with patch.object(chat_route, "LEXICAL_ONLY", True), patch.object(
        chat_route, "get_app_symbol", side_effect=ask_overrides(store, answers)
    ):
        result = chat_route.ask("test-session", chat_route.AskPayload(query="helicopter parking allowance"))
    assert result["found"] is False and answers == []  # the LLM is not asked to invent an answer


def test_status_and_health_report_lexical_mode(monkeypatch):
    from app import app

    monkeypatch.setattr("backend.routes.chat.LEXICAL_ONLY", True)
    monkeypatch.setattr("backend.routes.chat.EMBED_BACKEND", "none")
    monkeypatch.setattr(embeddings, "EMBED_BACKEND", "none")
    client = TestClient(app)
    health = client.get("/healthz").json()
    assert health["retrieval_mode"] == "lexical" and health["embeddings_backend"] == "none"
    assert health["embeddings_configured"] is False
