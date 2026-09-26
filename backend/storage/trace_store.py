# backend/storage/trace_store.py — Durable TraceStore & Prompt Registry
from __future__ import annotations

import json
import random
import re
import threading
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from filelock import FileLock

from backend.config import BASE_DIR, TRACE_LOG_PATH, logger

# ─────────────────────────────────────────────────────────────────────────────
#  PII / identifier redaction
# ─────────────────────────────────────────────────────────────────────────────
_PATTERNS = [
    # Employee ID formats: EMP-1234, E00123, employee id 88231
    (re.compile(r"\b(?:EMP|emp)[-_ ]?\d{3,8}\b"), "[REDACTED_EMP_ID]"),
    (re.compile(r"\b[Ee]\d{5,8}\b"), "[REDACTED_EMP_ID]"),
    (
        re.compile(r"(?i)\bemployee\s*(?:id|number|no\.?)\s*[:#]?\s*\d{3,8}\b"),
        "[REDACTED_EMP_ID]",
    ),
    # SSN-shaped
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    # Emails
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[REDACTED_EMAIL]"),
    # Phone numbers (loose, US-ish + generic)
    (
        re.compile(r"\b(?:\+?\d{1,2}[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
        "[REDACTED_PHONE]",
    ),
    # "Name: John Smith" / "Employee: John Smith" style labeled fields
    (
        re.compile(
            r"(?i)\b(?:name|employee|staff)\s*:\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+"
        ),
        lambda m: m.group(0).split(":")[0] + ": [REDACTED_NAME]",
    ),
]


def redact(text: Optional[str]) -> str:
    """Best-effort redaction of employee identifiers/names."""
    if not text:
        return text or ""
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_deep(value: Any) -> Any:
    """Recursively redact strings inside dicts/lists."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_deep(v) for v in value]
    return value


# ─────────────────────────────────────────────────────────────────────────────
#  Durable Prompt version registry
# ─────────────────────────────────────────────────────────────────────────────
QA_PROMPT_VERSION = "qa-answer-v2"
RERANK_PROMPT_VERSION = "rerank-v1"
REWRITE_PROMPT_VERSION = "rewrite-v1"

PROMPT_REGISTRY: Dict[str, str] = {}
PROMPTS_DIR = BASE_DIR / "prompts"


def register_prompt(version: str, text: str) -> str:
    """Register (or confirm) a prompt version's exact text durably on disk."""
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    prompt_file = PROMPTS_DIR / f"{version}.txt"
    if prompt_file.exists():
        stored_text = prompt_file.read_text(encoding="utf-8")
        if stored_text != text:
            raise ValueError(
                f"Prompt version {version!r} already registered on disk with different "
                f"text. Bump the version string instead of editing it in place."
            )
    else:
        prompt_file.write_text(text, encoding="utf-8")

    PROMPT_REGISTRY[version] = text
    return text


def get_prompt(version: str) -> Optional[str]:
    """Retrieve prompt text by version from in-memory cache or durable disk artifact."""
    if version in PROMPT_REGISTRY:
        return PROMPT_REGISTRY[version]
    prompt_file = PROMPTS_DIR / f"{version}.txt"
    if prompt_file.exists():
        text = prompt_file.read_text(encoding="utf-8")
        PROMPT_REGISTRY[version] = text
        return text
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Trace store
# ─────────────────────────────────────────────────────────────────────────────
class TraceStore:
    """Append-only JSONL trace log with defensive PII redaction, lookup, and seeded sampling."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        self._lock = threading.Lock()

    def log(self, record: dict) -> str:
        """Append one trace record with deep regex redaction."""
        record = redact_deep(dict(record))
        record.setdefault("trace_id", str(uuid.uuid4()))
        record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

        if "prompt_version" in record and "prompt_hash" not in record:
            p_text = get_prompt(record["prompt_version"])
            if p_text:
                record["prompt_hash"] = (
                    "sha256:" + hashlib.sha256(p_text.encode("utf-8")).hexdigest()
                )

        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with FileLock(str(self.path) + ".lock", timeout=10):
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        return record["trace_id"]

    def all(self) -> List[dict]:
        """Read all valid trace records from the JSONL log."""
        if not self.path.exists():
            return []
        out = []
        with self._lock, FileLock(str(self.path) + ".lock", timeout=10):
            with self.path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError as err:
                        logger.warning(
                            "Skipping corrupted trace line %d in %s: %s (Error: %s)",
                            line_no,
                            self.path,
                            line[:60],
                            err,
                        )
        return out

    def all_ids(self) -> List[str]:
        return [r["trace_id"] for r in self.all() if "trace_id" in r]

    def get(self, trace_id: str) -> Optional[dict]:
        """Lookup a trace by trace_id (last-write-wins)."""
        match = None
        for r in self.all():
            if r.get("trace_id") == trace_id:
                match = r
        return match

    def sample(self, n: int, seed: int) -> List[str]:
        """Seeded random sample of n trace_ids."""
        if n <= 0:
            raise ValueError(f"Sample size n must be greater than 0, got {n}.")
        ids = sorted(self.all_ids())
        if len(ids) < n:
            raise ValueError(
                f"Only {len(ids)} traces logged so far — need at least {n} to draw a sample of {n}."
            )
        rng = random.Random(seed)
        chosen = rng.sample(ids, n)
        return sorted(chosen)

    def pick_one(self, seed: int) -> Optional[str]:
        """Seeded single-trace pick."""
        ids = self.all_ids()
        if not ids:
            return None
        rng = random.Random(seed)
        return rng.choice(sorted(ids))


# Singleton default trace store
TRACES = TraceStore(TRACE_LOG_PATH)
