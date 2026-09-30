"""Shared, deterministic scoring of structured policy answers.

Agent, workflow and the Week 8 trajectory evaluator all decide "did the answer
satisfy the case?" here, so the three can never disagree.

Why this exists: the original check was a literal substring match of each
``deterministic_pass_criteria`` string against the lower-cased answer. That
marks a correct answer wrong when the model writes "One (1) week (7 calendar
days)" (criteria "1 week", "7 days"), "not eligible" (criterion "ineligible")
or "two (2) working days" (criterion "2 working days"). Re-scoring the recorded
Week 8 mitigation run showed 7 of its 8 ``answer_quality`` failures were of
this kind. The strict literal result is still computed and reported as
``strict_passed`` so historical numbers stay comparable; ``passed`` uses the
normalised comparison plus explicit per-case aliases.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Optional

_NUMBER_WORDS = {
    "zero": "0", "no": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15",
    "twenty": "20", "thirty": "30", "sixty": "60",
}
_NUMBER_WORD_PATTERN = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_QUOTES = dict.fromkeys(map(ord, "‘’‚′"), "'")
_UNIT_FILLER = re.compile(r"\b(\d+)\s+(?:working|calendar|business|full|paid)\s+(day|week|month|year)")
_SPOKEN_NUMBER_PAREN = re.compile(rf"\b(?:{_NUMBER_WORD_PATTERN})\s*\((\d+)\)")
_HYPHEN_UNIT = re.compile(r"\b(\d+)-(day|week|month|year)s?\b")
_PLURAL_UNIT = re.compile(r"\b(day|week|month|year)s\b")
_BARE_NUMBER_WORD = re.compile(
    rf"\b({_NUMBER_WORD_PATTERN})\b(?=[\s-]+(?:days?|weeks?|months?|years?)\b)"
)
_NEGATED_ELIGIBLE = re.compile(r"\b(?:is|are|was|were|would be|will be|be)?\s*not\s+eligible\b")
_MONEY_COMMAS = re.compile(r"(?<=\d),(?=\d{3}\b)")


def normalize_text(text: str) -> str:
    """Canonical form used on both the criterion and the answer text."""
    value = unicodedata.normalize("NFKD", str(text or "")).lower()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))  # fold accents
    value = unicodedata.normalize("NFKC", value)
    value = value.translate(_DASHES).translate(_QUOTES)
    value = _MONEY_COMMAS.sub("", value)
    value = _SPOKEN_NUMBER_PAREN.sub(r"\1", value)  # "one (1)" -> "1"
    value = _BARE_NUMBER_WORD.sub(lambda m: _NUMBER_WORDS[m.group(1)], value)
    value = _HYPHEN_UNIT.sub(r"\1 \2", value)  # "four-week" -> "4 week"
    value = _UNIT_FILLER.sub(r"\1 \2", value)  # "2 working days" -> "2 days"
    value = _PLURAL_UNIT.sub(r"\1", value)  # "weeks" -> "week"
    value = _NEGATED_ELIGIBLE.sub(" ineligible", value)
    value = re.sub(r"[^\w%$'./ -]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def answer_text(answer: Mapping[str, Any]) -> str:
    return " ".join(
        str(answer.get(key, "")) for key in ("entitlement_value", "rule_cited", "explanation")
    )


def _contains(haystack: str, needle: str) -> bool:
    """Boundary-aware containment so "2 day" never matches inside "12 days"."""
    if not needle:
        return False
    lead = r"(?<![\w.])" if needle[0].isalnum() else ""
    trail = r"(?!\w)" if needle[-1].isalnum() else ""
    return re.search(f"{lead}{re.escape(needle)}{trail}", haystack) is not None


def score_criteria(
    criteria: Optional[Iterable[str]],
    answer: Mapping[str, Any],
    aliases: Optional[Mapping[str, List[str]]] = None,
    forbidden: Optional[Iterable[str]] = None,
    headline: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Score ``answer`` against ``criteria`` (all must be satisfied).

    ``headline`` criteria must appear in ``entitlement_value`` itself, not merely anywhere
    in the answer: an explanation that quotes the rule ("five (5) days") must not mask a
    wrong conclusion (an entitlement of "0").

    ``forbidden`` lists phrases that must NOT appear (for example a statutory figure
    the uploaded documents never state); any hit fails ``passed`` because the answer
    used knowledge from outside the documents.

    Returns ``passed`` (normalised + aliases), ``strict_passed`` (the legacy
    literal check) and one record per criterion saying how it was matched.
    With no criteria both flags are True, matching the previous behaviour.
    """
    raw_text = answer_text(answer).lower()
    norm_text = normalize_text(answer_text(answer))
    aliases = aliases or {}
    records: List[Dict[str, Any]] = []
    for criterion in criteria or []:
        strict = criterion.lower() in raw_text  # legacy check, kept for comparability
        matched_by: Optional[str] = (
            "literal" if _contains(raw_text, criterion.lower()) else None
        )
        if matched_by is None and _contains(norm_text, normalize_text(criterion)):
            matched_by = "normalized"
        if matched_by is None:
            for alias in aliases.get(criterion, []):
                if _contains(norm_text, normalize_text(alias)):
                    matched_by = f"alias:{alias}"
                    break
        records.append(
            {
                "criterion": criterion,
                "strict_satisfied": strict,
                "satisfied": matched_by is not None,
                "matched_by": matched_by,
            }
        )
    head_text = normalize_text(str(answer.get("entitlement_value", "")))
    headline_records = []
    for criterion in headline or []:
        candidates = [criterion, *aliases.get(criterion, [])]
        headline_records.append(
            {
                "criterion": criterion,
                "satisfied": any(_contains(head_text, normalize_text(c)) for c in candidates),
            }
        )
    forbidden_hits = [
        phrase for phrase in (forbidden or []) if _contains(norm_text, normalize_text(phrase))
    ]
    return {
        "passed": all(item["satisfied"] for item in records)
        and all(item["satisfied"] for item in headline_records)
        and not forbidden_hits,
        "strict_passed": all(item["strict_satisfied"] for item in records),
        "criteria": records,
        "unmet": [item["criterion"] for item in records if not item["satisfied"]]
        + [f"headline:{item['criterion']}" for item in headline_records if not item["satisfied"]],
        "headline": headline_records,
        "forbidden_hits": forbidden_hits,
    }
