# backend/services/evaluation_dataset.py — Common Q&A Dataset Importer & Pre-import Validator
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class DatasetParseResult:
    ok: bool = True
    filename: str = ""
    evaluator_type: str = "general"  # "judge" | "retrieval" | "policy" | "general"
    total_found: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    duplicate_count: int = 0
    valid_cases: List[Dict[str, Any]] = field(default_factory=list)
    invalid_cases: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    pairs: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "filename": self.filename,
            "evaluator_type": self.evaluator_type,
            "total_found": self.total_found,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "duplicate_count": self.duplicate_count,
            "valid_cases": self.valid_cases,
            "invalid_cases": self.invalid_cases,
            "errors": self.errors,
            "warnings": self.warnings,
            "pairs": self.pairs,
        }


def parse_and_validate_dataset(
    content: str,
    filename: str,
    evaluator_type: str = "general",
) -> DatasetParseResult:
    """
    Parses Q&A datasets from JSON, TXT, or MD format and performs pre-import validation.
    Detects invalid rows, missing fields, duplicate IDs, and normalizes fields to common contract:
    {
      "case_id": "...",
      "question": "...",
      "expected_answer": "...",
      "expected_section": "...",
      "employee_id": "...",
      "taxonomy": "...",
      "metadata": {}
    }
    """
    result = DatasetParseResult(filename=filename, evaluator_type=evaluator_type)
    content = content.strip()
    if not content:
        result.errors.append("Uploaded file is empty.")
        result.ok = False
        return result

    raw_cases: List[Dict[str, Any]] = []

    # 1. Check if JSON
    is_json = False
    if content.startswith(("[", "{")) or filename.lower().endswith(".json"):
        try:
            parsed = json.loads(content)
            is_json = True
            if isinstance(parsed, list):
                raw_cases = parsed
            elif isinstance(parsed, dict):
                if "cases" in parsed and isinstance(parsed["cases"], list):
                    raw_cases = parsed["cases"]
                elif "results" in parsed and isinstance(parsed["results"], list):
                    raw_cases = parsed["results"]
                elif "questions" in parsed and isinstance(parsed["questions"], list):
                    raw_cases = parsed["questions"]
                else:
                    raw_cases = [parsed]
            else:
                result.errors.append("Invalid JSON format. Expected JSON array of objects or object with 'cases'.")
                result.ok = False
                return result
        except json.JSONDecodeError as exc:
            result.errors.append(f"Invalid JSON format: {exc.msg} at line {exc.lineno} col {exc.colno}")
            result.ok = False
            return result
    else:
        # 2. Parse TXT / Markdown Q&A blocks
        raw_cases = _parse_txt_md_blocks(content)

    result.total_found = len(raw_cases)
    if not raw_cases:
        result.errors.append('No Q&A pairs found. Expected format: "Q: question" followed by "A: expected answer".')
        result.ok = False
        return result

    # 3. Validate, deduplicate, and normalize cases
    seen_ids: set[str] = set()

    for idx, c in enumerate(raw_cases):
        row_num = idx + 1
        raw_cid = str(c.get("case_id") or c.get("id") or "").strip()
        q = str(c.get("question") or c.get("q") or c.get("query") or "").strip()
        exp_a = str(
            c.get("expected_answer")
            or c.get("answer")
            or c.get("expected")
            or c.get("expected_value")
            or c.get("a")
            or ""
        ).strip()
        exp_sec = str(c.get("expected_section") or c.get("section_info") or c.get("section") or "").strip()
        emp_id = str(c.get("employee_id") or c.get("emp_id") or "").strip()

        # Generate case_id if missing
        if not raw_cid:
            cid = f"CASE_{row_num:02d}"
        else:
            cid = raw_cid

        # Check for duplicates
        is_duplicate = False
        if cid in seen_ids:
            is_duplicate = True
            result.duplicate_count += 1
            result.warnings.append(f"Row {row_num}: Duplicate case ID '{cid}'. Assigning unique ID '{cid}_{row_num}'.")
            cid = f"{cid}_{row_num}"
        seen_ids.add(cid)

        # Validation rules
        case_errors: List[str] = []
        if not q:
            case_errors.append("Question is empty or missing")

        # Evaluator-specific expectations:
        if evaluator_type == "retrieval":
            # In retrieval, either expected_section or expected_answer is valid as the ground truth target
            if not exp_a and not exp_sec:
                case_errors.append("Missing expected document substring or section reference")
        else:
            # Judge & Policy require an expected answer
            if not exp_a:
                case_errors.append("Missing expected answer or ground truth entitlement")

        if case_errors:
            result.invalid_count += 1
            result.invalid_cases.append({
                "row": row_num,
                "case_id": cid,
                "reason": "; ".join(case_errors),
                "raw": c,
            })
        else:
            normalized = {
                "case_id": cid,
                "question": q,
                "expected_answer": exp_a,
                "expected_section": exp_sec,
                "employee_id": emp_id or "EMP001",
                "taxonomy": str(c.get("taxonomy") or c.get("taxonomy_mode") or "General"),
                "metadata": c.get("metadata") or {},
            }
            # For backward compatibility with legacy endpoints expecting "expected" key
            result.pairs.append({"question": q, "expected": exp_a or exp_sec})
            result.valid_cases.append(normalized)
            result.valid_count += 1

    result.ok = result.valid_count > 0
    return result


def _parse_txt_md_blocks(text: str) -> List[Dict[str, Any]]:
    """Robust parser for TXT and Markdown formatted questions and answers."""
    cases: List[Dict[str, Any]] = []
    current_case: Dict[str, Any] = {}
    current_q_lines: List[str] = []
    current_a_lines: List[str] = []
    active_field: Optional[str] = None

    def flush_case():
        nonlocal current_case, current_q_lines, current_a_lines, active_field
        q = " ".join([l.strip() for l in current_q_lines if l.strip()]).strip()
        a = " ".join([l.strip() for l in current_a_lines if l.strip()]).strip()
        if q:
            current_case["question"] = q
            if a:
                current_case["expected_answer"] = a
            cases.append(current_case)
        current_case = {}
        current_q_lines = []
        current_a_lines = []
        active_field = None

    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if active_field == "q":
                active_field = None
            continue

        # Header detection: e.g. "### Case 01", "# --- Case 02 ---", "Case 1:"
        header_match = re.match(r"^(?:#{1,6}\s*)?(?:---*\s*)?(?:case\s*(\d+|[a-zA-Z0-9_\-]+))", line, re.IGNORECASE)
        if header_match and not re.match(r"^case\s*id\s*[:\-.]", line, re.IGNORECASE):
            flush_case()
            raw_id = header_match.group(1).strip()
            if raw_id.isdigit():
                current_case["case_id"] = f"CASE_{int(raw_id):02d}"
            else:
                current_case["case_id"] = raw_id
            continue

        # Ignore markdown decorative dividers
        if re.match(r"^[=\-_*]{3,}$", line):
            continue

        # Strip bold/italic markdown prefix markers: e.g. "**Question:**" -> "Question: "
        clean_line = re.sub(r"^\*{1,2}([^:*]+):?\*{1,2}\s*:?\s*", r"\1: ", line)

        q_match = re.match(r"^(?:q(?:uestion)?|query)\s*[:\-.]\s*(.*)", clean_line, re.IGNORECASE)
        a_match = re.match(
            r"^(?:a(?:nswer)?|expected(?:\s*(?:entitlement\s*\/\s*answer|entitlement|value|answer))?)\s*[:\-.]\s*(.*)",
            clean_line,
            re.IGNORECASE
        )
        sec_match = re.match(r"^(?:source\s*(?:policy\s*)?section|section)\s*[:\-.]\s*(.*)", clean_line, re.IGNORECASE)
        emp_match = re.match(r"^(?:employee\s*(?:id)?|emp_id)\s*[:\-.]\s*(.*)", clean_line, re.IGNORECASE)
        cid_match = re.match(r"^case\s*id\s*[:\-.]\s*(.*)", clean_line, re.IGNORECASE)

        if q_match:
            if current_q_lines and current_a_lines:
                flush_case()
            current_q_lines = [q_match.group(1).strip()]
            active_field = "q"
        elif a_match:
            current_a_lines = [a_match.group(1).strip()]
            active_field = "a"
        elif sec_match:
            current_case["expected_section"] = sec_match.group(1).strip()
            active_field = None
        elif emp_match:
            current_case["employee_id"] = emp_match.group(1).strip()
            active_field = None
        elif cid_match:
            current_case["case_id"] = cid_match.group(1).strip()
            active_field = None
        elif active_field == "q":
            current_q_lines.append(line)
        elif active_field == "a":
            current_a_lines.append(line)

    flush_case()
    return cases
