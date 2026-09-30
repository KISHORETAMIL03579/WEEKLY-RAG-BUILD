"""Index documents into a session's Qdrant collection so CLI evaluations have a corpus.

The web app indexes whatever a browser session uploads. The command-line evaluations
(``benchmarks.policy_execution.trajectory_eval``) need the same thing without a browser:

    python scripts/index_documents.py --session-id policy-eval ^
        WEEKLY_RAG_TASK/HRPolicy.pdf backend/data/samples/employee_records.md

It uses the app's own pipeline (extract -> structured chunks -> vectors -> Qdrant) and
registers the source files so citation checks can read them. Vectors are real embeddings
when EMBED_BACKEND is ollama/gemini, or placeholders in lexical mode (EMBED_BACKEND=none).

Sessions expire after an hour of inactivity (the app sweeps idle collections), so index
shortly before evaluating.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import EMBED_BACKEND, UPLOAD_FOLDER  # noqa: E402
from backend.services.chunker import chunk_text  # noqa: E402
from backend.services.embeddings import LEXICAL_ONLY, embed_texts, lexical_placeholder_vectors  # noqa: E402
from backend.services.text_extractor import extract_pdf_pages, extract_txt_pages  # noqa: E402
from backend.storage import session_manager  # noqa: E402


def index_file(session_id: str, path: Path, chunk_mode: str = "structured") -> dict:
    store = session_manager.get_store(session_id)
    if any(chunk["filename"] == path.name for chunk in store.chunks):
        return {"filename": path.name, "skipped": "already indexed in this session"}
    ext = path.suffix.lower().lstrip(".")
    pages = extract_pdf_pages(str(path)) if ext == "pdf" else extract_txt_pages(str(path))
    if not pages:
        raise ValueError(f"No extractable text in {path}")
    doc_id = uuid.uuid4().hex[:8]
    chunks = chunk_text({"doc_id": doc_id, "filename": path.name}, pages, chunk_mode)
    vectors = lexical_placeholder_vectors(len(chunks)) if LEXICAL_ONLY else embed_texts([c["text"] for c in chunks])
    store.add(chunks, vectors)
    stored = Path(UPLOAD_FOLDER) / f"{session_id}__{doc_id}.{ext}"
    shutil.copyfile(path, stored)
    session_manager.SESSION_FILES.setdefault(session_id, {})[doc_id] = {"path": stored, "name": path.name}
    session_manager.save_session_manifest(session_id)
    return {"filename": path.name, "doc_id": doc_id, "chunks": len(chunks), "pages": len(pages)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--chunk-mode", default="structured")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    print(f"EMBED_BACKEND={EMBED_BACKEND}")
    for path in args.files:
        print(index_file(args.session_id, path, args.chunk_mode))
    print(f"Session '{args.session_id}' now holds {len(session_manager.get_store(args.session_id).chunks)} chunks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
