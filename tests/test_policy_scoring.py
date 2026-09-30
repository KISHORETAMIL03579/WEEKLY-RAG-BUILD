"""Deterministic answer scoring: normalisation, aliases, forbidden phrases, legacy strict check."""

from backend.services.policy_scoring import normalize_text, score_criteria


def answer(text):
    return {"entitlement_value": text, "rule_cited": "", "explanation": ""}


def test_spoken_numbers_and_units_match_the_criteria_wording():
    scored = score_criteria(
        ["1 week", "7 days", "probation"], answer("One (1) week (7 calendar days) written notice while on probation")
    )
    assert scored["passed"] is True
    assert scored["strict_passed"] is False  # the legacy literal check misses it


def test_hyphenated_spoken_quantities():
    assert score_criteria(["1 month"], answer("a one‑month written notice"))["passed"]
    assert score_criteria(["4 weeks"], answer("four-week notice"))["passed"]


def test_negated_eligibility_satisfies_ineligible():
    assert score_criteria(["ineligible"], answer("EMP005 is not eligible for paid sick leave"))["passed"]


def test_working_days_filler_and_plurals_are_ignored():
    scored = score_criteria(["2 working days", "7 days"], answer("two (2) working days per month, at least seven (7) days"))
    assert scored["passed"]


def test_a_number_never_matches_inside_a_bigger_number():
    assert not score_criteria(["2 days"], answer("12 days carried over"))["passed"]
    assert not score_criteria(["5"], answer("15 days"))["passed"]


def test_aliases_accept_alternative_phrasings_without_editing_the_criteria():
    scored = score_criteria(["0 severance"], answer("The employee receives no severance"), {"0 severance": ["no severance"]})
    assert scored["passed"]
    assert scored["criteria"][0]["matched_by"] == "alias:no severance"


def test_accents_are_folded():
    assert score_criteria(["ivoire"], answer("Côte d’Ivoire"))["passed"]


def test_forbidden_phrases_fail_an_otherwise_matching_answer():
    scored = score_criteria(["24"], answer("24 days, and Ireland grants 20 working days by statute"), forbidden=["20 working days"])
    assert scored["passed"] is False
    assert scored["forbidden_hits"] == ["20 working days"]
    assert scored["strict_passed"] is True


def test_wrong_answers_still_fail():
    assert not score_criteria(["5 days", "5"], answer("no unused annual leave days can be carried forward"))["passed"]


def test_no_criteria_passes_like_before():
    assert score_criteria([], answer("anything")) ["passed"]
    assert score_criteria(None, answer("anything"))["strict_passed"]


def test_normalize_is_idempotent():
    once = normalize_text("Four (4) weeks’ notice")
    assert normalize_text(once) == once


def test_headline_criteria_must_be_in_the_entitlement_not_just_the_explanation():
    # The real failure: a wrong conclusion whose explanation merely quotes the rule.
    wrong = {"entitlement_value": "0", "rule_cited": "5.2.7", "explanation": "The policy allows five (5) days with CEO consent; without it none."}
    assert score_criteria(["5 days", "5"], wrong)["passed"] is True  # criteria alone are fooled
    scored = score_criteria(["5 days", "5"], wrong, headline=["5"])
    assert scored["passed"] is False and scored["unmet"] == ["headline:5"]
    right = {"entitlement_value": "Up to five (5) days", "rule_cited": "5.2.7", "explanation": "x"}
    assert score_criteria(["5 days"], right, headline=["5"])["passed"] is True


def test_headline_aliases_cover_yes_no_answers():
    answer = {"entitlement_value": "No", "rule_cited": "4.4.1", "explanation": "Staff on probation are not eligible."}
    assert score_criteria(["ineligible"], answer, {"ineligible": ["no"]}, headline=["ineligible"])["passed"]
    assert not score_criteria(["ineligible"], {**answer, "entitlement_value": "Yes"}, {"ineligible": ["no"]}, headline=["ineligible"])["passed"]
