"""Reason codes (SPEC §3) with one-line explanations for people reading a receipt."""

from __future__ import annotations

REJECT = {
    "CANDIDATE_INVALID": "The candidate is malformed.",
    "FIELD_UNKNOWN": "The field is not in the schema.",
    "NULL_STRING_LITERAL": 'The value is a string like "null" where no value was found.',
    "TYPE_INVALID": "The value does not parse as the field's type.",
    "RANGE_INVALID": "The value is outside the field's allowed range.",
    "UNIT_INVALID": "The unit is not the field's unit.",
    "KEY_INVALID": "The field has keys, and the key is missing or not one of them.",
    "NO_EVIDENCE": "The candidate cites no evidence.",
    "SPAN_INVALID": "The evidence span is outside the document or splits a character.",
    "VALUE_NOT_IN_EVIDENCE": "The value cannot be read from the cited text.",
    "UNIT_NOT_IN_EVIDENCE": "The value is in the cited text, but not with the field's unit.",
}

FLAG = {
    "NON_VERBATIM_EVIDENCE": "The quoted text differs from the text at the cited location.",
    "QUALIFIED_VALUE": (
        'Text such as "more than" or "up to" qualifies the value, and the field does not say so.'
    ),
    "SCALE_WORD": (
        'A scale word such as "million" follows the value, and the value was given unscaled.'
    ),
    "KEY_NOT_AT_VALUE": (
        "The key the document mentions at the value is not the candidate's key, or none is."
    ),
    "LOW_CONFIDENCE": "The extractor's confidence is below the policy minimum.",
    "CONFLICTING_CANDIDATES": "Another candidate for this field and key has a different value.",
}

INFO = {
    "EVIDENCE_REANCHORED": "The cited span did not hold the value; its one other occurrence did.",
}

COVERAGE = {
    "REQUIRED_FIELD_MISSING": "No candidate for this required field was admitted or flagged.",
}

DESCRIPTIONS = {**REJECT, **FLAG, **INFO, **COVERAGE}
