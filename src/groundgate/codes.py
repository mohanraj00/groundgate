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
    "NO_EVIDENCE": "The candidate gives no value item and no outside evidence.",
    "SPAN_INVALID": "The evidence span is outside its text or splits a character.",
    "QUOTE_NOT_FOUND": "The quoted value text does not occur in the document or reference.",
    "VALUE_NOT_IN_EVIDENCE": "The value cannot be read from the cited text.",
    "UNIT_NOT_IN_EVIDENCE": "The value is in the cited text, but not with the field's unit.",
    "SOURCE_REJECTED": "Only outside evidence supports the value, and the policy rejects it.",
}

FLAG = {
    "NON_VERBATIM_EVIDENCE": "The quoted text differs from the text at the cited location.",
    "QUALIFIED_VALUE": (
        'Text such as "more than" or "up to" qualifies the value, and the field does not say so.'
    ),
    "SCALE_WORD": (
        'A scale word such as "million" follows the value, and the value was given unscaled.'
    ),
    "PART_MISSING": "The value needs a sign, a scale or a unit that no evidence item supports.",
    "SIGN_CITATION_INVALID": "The sign item does not make the value negative.",
    "SCALE_CITATION_INVALID": "The scale item does not scale the value.",
    "UNIT_CITATION_INVALID": "The unit item does not supply the field's unit at the value.",
    "FIELD_CITATION_INVALID": "The field item does not name the field at the value.",
    "KEY_NOT_AT_VALUE": (
        "The key the document mentions at the value is not the candidate's key, or none is."
    ),
    "KEY_CITATION_INVALID": "The key item does not hold a mention of the candidate's key.",
    "EVIDENCE_QUOTED": "Only an external quote supports the value; the policy sends it to review.",
    "EVIDENCE_STATED": "Only the extractor's knowledge supports the value; the policy says review.",
    "LOW_CONFIDENCE": "The extractor's confidence is below the policy minimum.",
    "CONFLICTING_CANDIDATES": "Another candidate for this field and key has a different value.",
    "MODEL_DOUBT": "A recorded judgment of the policy's judge doubts this value.",
}

INFO = {
    "EVIDENCE_REANCHORED": "The cited span did not hold the value; its one other occurrence did.",
    "VALUE_DERIVED": "The value is the cited number with a sign or scale that the evidence gives.",
    "KEY_CITED": "A key item put the key at the value by the column rule.",
    "ADMITTED_BY_POLICY": "The policy admits the outside evidence that supports the value.",
    "MODEL_CLEARED": "A recorded judgment of the policy's judge cleared KEY_NOT_AT_VALUE.",
}

COVERAGE = {
    "REQUIRED_FIELD_MISSING": "No candidate for this required field was admitted or flagged.",
}

DESCRIPTIONS = {**REJECT, **FLAG, **INFO, **COVERAGE}
