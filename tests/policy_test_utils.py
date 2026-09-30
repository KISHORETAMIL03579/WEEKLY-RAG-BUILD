"""Fixtures for the policy tests: a fake indexed session, scripted Groq steps, tool helpers.

The documents below are *test fixtures*, not application data: the application itself
contains no policy text. They are passed through the real chunker so the tools are
exercised on chunk-shaped text (section prefixes, joined lines) exactly as in Qdrant.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from backend.services import policy_agent
from backend.services.chunker import chunk_text
from backend.services.policy_retrieval import PolicyContext
from backend.services.search import build_index

POLICY_TEXT = """# Annual leave

5.2.1 Annual leave entitlement
The standard entitlement for full-time staff members is 24 days per annum. Leave accrues at the rate of 2 days per month.


5.2.7 Carry forward of leave
Staff members shall not, except with the consent of the CEO, carry forward more than 5 days beyond December 31st.


# Separation from service

10.1 Resignation
A staff member resigning must give four weeks written notice or one week written notice in the case of staff members on probation. Separation is subject to the Employment Act of the Republic of Kenya.


10.5.1 Termination for redundancy
A redundant staff member receives one month's written notice and severance pay at fifteen days' pay for each completed year of service.
"""

ROSTER_TEXT = """# Employee Records

EMP001 | Name: Sarah Mwangi | Jurisdiction: Kenya | Tenure (months): 18 | Employment status: Confirmed | Annual leave balance (days): 12 | Separation reason: None
EMP002 | Name: Brian O'Connor | Jurisdiction: Ireland | Tenure (months): 24 | Employment status: Confirmed | Annual leave balance (days): 18 | Separation reason: None
EMP003 | Name: David Omondi | Jurisdiction: Kenya | Tenure (months): 4 | Employment status: Probation | Annual leave balance (days): 4 | Separation reason: None
"""


class FakeStore:
    """Stands in for the Qdrant-backed session store (chunks only, lexical retrieval)."""

    def __init__(self, chunks: List[dict]):
        self.chunks = chunks
        self.vectors: List[List[float]] = []

    def get_tfidf_index(self) -> dict:
        return build_index(self.chunks)

    def query_scores(self, vector):
        return [0.0] * len(self.chunks)


_HEADING = re.compile(r"^(\d+(?:\.\d+)+)\s+(.+)$")


def section_chunks(filename: str, text: str, doc_id: str) -> List[dict]:
    """One chunk per numbered section, shaped like the chunker's output ("<label>. <body>")."""
    chunks: List[dict] = []
    label, body = None, []

    def flush():
        if label:
            index = len(chunks)
            chunks.append(
                {
                    "id": f"{doc_id}::c{index}",
                    "doc_id": doc_id,
                    "filename": filename,
                    "page": index + 1,
                    "section": label,
                    "text": f"{label}. {' '.join(body)}",
                    "method": "structured",
                }
            )

    for line in text.splitlines():
        heading = _HEADING.match(line.strip())
        if heading:
            flush()
            label, body = f"{heading.group(1)} {heading.group(2)}", []
        elif line.strip() and not line.startswith("#") and label:
            body.append(line.strip())
    flush()
    return chunks


def chunks_for(filename: str, text: str, doc_id: str) -> List[dict]:
    """Real chunker output (used for the roster: joined lines, section-title prefix)."""
    pages = [{"page": 1, "text": text}]
    return chunk_text({"doc_id": doc_id, "filename": filename}, pages, "structured")


def build_store(documents: Optional[Dict[str, str]] = None) -> FakeStore:
    documents = documents if documents is not None else {"handbook.md": POLICY_TEXT, "employee_records.md": ROSTER_TEXT}
    chunks: List[dict] = []
    for index, (name, text) in enumerate(documents.items()):
        make = section_chunks if name.startswith("handbook") else chunks_for
        chunks.extend(make(name, text, f"doc{index}"))
    return FakeStore(chunks)


def install_indexed_session(monkeypatch, store: Optional[FakeStore] = None, sid: str = "test-session") -> PolicyContext:
    """Route every policy store lookup to ``store`` and return the matching context."""
    store = store or build_store()
    fake = lambda session_id: store if session_id == sid else FakeStore([])  # noqa: E731
    monkeypatch.setattr("backend.services.policy_retrieval.get_store", fake)
    monkeypatch.setattr("backend.routes.policy.get_store", fake)
    return PolicyContext(sid)


# -- scripted Groq ----------------------------------------------------------


def model_reply(
    *,
    tool_calls: Optional[Iterable[tuple]] = None,
    content: str = "",
    reasoning: Optional[str] = None,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    provider_attempts: int = 1,
) -> tuple:
    """Shape of ``_call_groq_step``'s return value."""
    message: Dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning"] = reasoning
    if tool_calls:
        message["tool_calls"] = [
            {"id": f"call_{index}", "type": "function", "function": {"name": name, "arguments": arguments}}
            for index, (name, arguments) in enumerate(tool_calls)
        ]
    log = [{"attempt": n, "outcome": "retry"} for n in range(1, provider_attempts)]
    log.append({"attempt": provider_attempts, "outcome": "ok"})
    return (
        {"message": message, "provider_attempts": provider_attempts, "attempt_log": log},
        prompt_tokens,
        completion_tokens,
        2.0,
    )


def final_reply(entitlement="24 days", rule="5.2.1 Annual leave entitlement", why="The handbook grants 24 days.", **kwargs) -> tuple:
    return model_reply(
        content=json.dumps({"entitlement_value": entitlement, "rule_cited": rule, "explanation": why}),
        **kwargs,
    )


class ScriptedModel:
    """Patches the Groq step with a fixed list of replies and records what it was sent."""

    def __init__(self, monkeypatch, replies: List[tuple]):
        self.replies = list(replies)
        self.calls: List[Dict[str, Any]] = []
        monkeypatch.setattr(policy_agent, "CHAT_BACKEND", "groq")
        monkeypatch.setattr(policy_agent, "GROQ_API_KEY", "test-key")
        monkeypatch.setattr(policy_agent, "_call_groq_step", self._step)

    def _step(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), **kwargs})
        if not self.replies:
            raise AssertionError("The agent asked the model for more steps than were scripted")
        return self.replies.pop(0)


def script_model(monkeypatch, *replies: tuple) -> ScriptedModel:
    return ScriptedModel(monkeypatch, list(replies))


def patch_groq_ready(monkeypatch) -> None:
    monkeypatch.setattr(policy_agent, "CHAT_BACKEND", "groq")
    monkeypatch.setattr(policy_agent, "GROQ_API_KEY", "test-key")


def tool_names(result) -> List[str]:
    return [call["tool_name"] for call in result.tool_calls]
