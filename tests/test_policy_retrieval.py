"""Policy tools read only uploaded chunks: employee rows, policy passages, jurisdictions, citations."""

import pytest

from backend.services import policy_retrieval as retrieval
from backend.services.policy_retrieval import PolicyContext
from tests.policy_test_utils import FakeStore, build_store, install_indexed_session


def test_employee_record_is_parsed_from_the_uploaded_roster_chunks(policy_session):
    record = retrieval.find_employee_record(policy_session, "emp003")
    assert record["found"] is True
    assert record["employee_id"] == "EMP003"
    assert record["fields"]["employment_status"] == "Probation"
    assert record["fields"]["tenure_months"] == 4
    assert record["fields"]["separation_reason"] is None
    assert record["source"]["filename"] == "employee_records.md"


def test_unknown_employee_is_a_recoverable_error_naming_what_was_searched(policy_session):
    with pytest.raises(retrieval.EmployeeNotFoundError) as caught:
        retrieval.find_employee_record(policy_session, "EMP999")
    error = caught.value.to_error()
    assert error["code"] == "EMPLOYEE_NOT_FOUND"
    assert error["retryable"] is False
    assert "employee_records.md" in error["hint"]


def test_roster_lists_every_row_with_typed_fields(policy_session):
    records = retrieval.list_employee_records(policy_session)
    assert [r["employee_id"] for r in records] == ["EMP001", "EMP002", "EMP003"]
    assert records[1]["jurisdiction"] == "Ireland"


def test_policy_search_returns_ranked_passages_with_metadata(policy_session):
    result = retrieval.search_policy(policy_session, "resignation notice probation", top_k=3)
    assert result["no_match"] is False
    assert result["retrieval_mode"] == "lexical"
    top = result["results"][0]
    assert "one week written notice" in top["text"]
    assert top["filename"] == "handbook.md"
    assert {"chunk_id", "page", "section", "score"} <= set(top)


def test_policy_search_never_returns_roster_rows(policy_session):
    result = retrieval.search_policy(policy_session, "employment status probation tenure", top_k=10)
    assert all(item["filename"] != "employee_records.md" for item in result["results"])


def test_policy_search_says_no_match_instead_of_inventing_a_clause(policy_session):
    result = retrieval.search_policy(policy_session, "helicopter parking allowance")
    assert result["results"] == []
    assert result["no_match"] is True


def test_top_k_is_clamped(policy_session):
    assert len(retrieval.search_policy(policy_session, "leave", top_k=999)["results"]) <= retrieval.MAX_TOP_K


def test_jurisdiction_rules_come_from_chunks_mentioning_the_jurisdiction(policy_session):
    result = retrieval.find_jurisdiction_rules(policy_session, "Kenya", "notice_and_separation")
    assert result["no_match"] is False
    assert any("Employment Act" in item["text"] for item in result["results"])


def test_jurisdiction_without_evidence_is_a_recoverable_no_evidence_error(policy_session):
    with pytest.raises(retrieval.NoEvidenceError) as caught:
        retrieval.find_jurisdiction_rules(policy_session, "Rwanda", "leave")
    error = caught.value.to_error()
    assert error["code"] == "NO_EVIDENCE"
    assert "handbook.md" in error["hint"]
    assert "search_handbook" in error["hint"]


def test_jurisdiction_arguments_are_checked_against_the_taxonomy(policy_session):
    with pytest.raises(retrieval.PolicyToolError):
        retrieval.find_jurisdiction_rules(policy_session, "Atlantis", "leave")
    with pytest.raises(retrieval.PolicyToolError):
        retrieval.find_jurisdiction_rules(policy_session, "Kenya", "astrology")


def test_no_documents_means_no_answers(monkeypatch):
    ctx = install_indexed_session(monkeypatch, FakeStore([]))
    for call in (
        lambda: retrieval.search_policy(ctx, "leave"),
        lambda: retrieval.find_employee_record(ctx, "EMP001"),
    ):
        with pytest.raises(retrieval.NoIndexedDocumentsError):
            call()
    with pytest.raises(retrieval.NoIndexedDocumentsError):
        retrieval.search_policy(None, "leave")


def test_a_roster_only_upload_has_no_policy_text_to_search(monkeypatch):
    ctx = install_indexed_session(monkeypatch, build_store({"employee_records.md": "# R\n\nEMP001 | Name: A | Tenure (months): 1"}))
    with pytest.raises(retrieval.NoIndexedDocumentsError):
        retrieval.search_policy(ctx, "leave")


def test_document_scope_restricts_the_search(monkeypatch):
    store = build_store()
    ctx = install_indexed_session(monkeypatch, store)
    roster_doc = next(c["doc_id"] for c in store.chunks if c["filename"] == "employee_records.md")
    scoped = PolicyContext(ctx.session_id, (roster_doc,))
    with pytest.raises(retrieval.NoIndexedDocumentsError):
        retrieval.search_policy(scoped, "resignation notice")


def test_citations_resolve_against_headings_present_in_the_chunks(policy_session):
    known = retrieval.known_sections(policy_session)
    assert {"5.2.1", "5.2.7", "10.1", "10.5.1"} <= known
    good = retrieval.check_citation("Section 10.1 Resignation", known)
    assert good["all_resolve"] is True and good["resolved_sections"] == ["10.1"]
    bad = retrieval.check_citation("Section 10.1 and Section 3.6.4", known)
    assert bad["unresolved_sections"] == ["3.6.4"] and bad["all_resolve"] is False
    assert retrieval.check_citation("no numbers here", known)["has_citation"] is False


def test_context_round_trips_through_request_meta():
    ctx = PolicyContext("abc", ("d1", "d2"))
    assert PolicyContext.from_meta(ctx.to_meta()) == ctx
    assert PolicyContext.from_meta({}) is None
    assert PolicyContext.from_meta({"session_id": ""}) is None


def test_embedding_outage_falls_back_to_lexical_with_a_cooldown(monkeypatch, policy_session):
    store = build_store()
    store.vectors = [[0.1, 0.2] for _ in store.chunks]  # vectors present, so semantic is attempted
    ctx = install_indexed_session(monkeypatch, store)
    monkeypatch.setattr(retrieval, "embeddings_configured", lambda: True)
    monkeypatch.setattr(retrieval, "LEXICAL_ONLY", False)
    monkeypatch.setattr(retrieval, "_embedding_down_until", 0.0)
    calls = []

    def dead(text, timeout=None):
        calls.append(timeout)
        raise ConnectionError("embedding service down")

    monkeypatch.setattr(retrieval, "embed_text", dead)
    first = retrieval.search_policy(ctx, "resignation notice probation")
    assert first["retrieval_mode"] == "lexical" and first["results"]
    assert any("keyword-ranked" in w for w in first["warnings"])
    assert calls == [retrieval.EMBED_QUERY_TIMEOUT_SECONDS]  # short timeout, not the 120s default
    retrieval.search_policy(ctx, "resignation notice probation")
    assert len(calls) == 1  # circuit breaker: no second attempt during the cooldown
    monkeypatch.setattr(retrieval, "_embedding_down_until", 0.0)
