"""Reason codes (SPEC §3) with one-line explanations for people reading a receipt."""

from __future__ import annotations

REJECT = {
    "CANDIDATE_INVALID": "The candidate is malformed.",
    "FIELD_UNKNOWN": "The field is not in the schema.",
    "NULL_STRING_LITERAL": 'The value is a string like "null" where no value was found.',
    "TYPE_INVALID": "The value does not parse as the field's type.",
    "RANGE_INVALID": "The value is outside the field's allowed range.",
    "DATE_OUT_OF_RANGE": "The date is before the field's minimum or after its maximum.",
    "UNIT_INVALID": "The unit is not the field's unit.",
    "KEY_INVALID": "The field has keys, and the key is missing or not one of them.",
    "RECORD_INVALID": "The field is a member of a record field, and the candidate has no record.",
    "NO_EVIDENCE": "The candidate gives no value item and no outside evidence.",
    "SPAN_INVALID": "The evidence span is outside its text or splits a character.",
    "QUOTE_NOT_FOUND": "The quoted value text does not occur in the document or reference.",
    "VALUE_NOT_IN_EVIDENCE": "The value cannot be read from the cited text.",
    "UNIT_NOT_IN_EVIDENCE": "The value is in the cited text, but not with the field's unit.",
    "DATE_FORMAT_UNDECLARED": (
        "The text gives the date only in a format that the field does not accept."
    ),
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
    "DATE_AMBIGUOUS": "Two formats of the field read the cited date as two dates, as 03/04/2025.",
    "PART_MISSING": "The value needs a sign, a scale or a unit that no evidence item supports.",
    "SIGN_DROPPED": "The value is positive, and the document prints it with a minus sign.",
    "SIGN_CITATION_INVALID": "The sign item does not make the value negative.",
    "SCALE_CITATION_INVALID": "The scale item does not scale the value.",
    "UNIT_CITATION_INVALID": "The unit item does not supply the field's unit at the value.",
    "FIELD_CITATION_INVALID": "The field item does not name the field at the value.",
    "KEY_NOT_AT_VALUE": (
        "The key the document mentions at the value is not the candidate's key, or none is."
    ),
    "KEY_CITATION_INVALID": "The key item does not hold a mention of the candidate's key.",
    "COLUMN_NOT_AT_VALUE": "The value is not in a column of the field, such as Typ. or Max.",
    "MARKER_OTHER_FIELD": "A marker word of another field, such as family, is next to the value.",
    "READ_DOUBT": "The cited text is on a word that the reader read with a low confidence.",
    "EVIDENCE_QUOTED": "Only an external quote supports the value; the policy sends it to review.",
    "EVIDENCE_STATED": "Only the extractor's knowledge supports the value; the policy says review.",
    "LOW_CONFIDENCE": "The extractor's confidence is below the policy minimum.",
    "CONFLICTING_CANDIDATES": "Another candidate for this field and key has a different value.",
    "NOT_CORROBORATED": "No candidate of another proposer gives this value at this span.",
    "OTHER_SPAN": "Another proposer gives this value at a span that does not overlap.",
    "RELATION_FAILED": (
        "A relation of the schema, such as a total and its parts, does not hold for these values."
    ),
    "MODEL_DOUBT": "A recorded judgment of the policy's judge doubts this value.",
    "RECORD_NOT_ADMITTED": "The record of this value is not admitted.",
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

RECORD = {
    "RECORD_MEMBER_MISSING": "A required member of the record has no value that passed.",
    "RECORD_MEMBER_CONFLICT": "A member of the record has two different values.",
    "RECORD_SOURCE_MIXED": "The values of the record cite two or more texts.",
    "SET_REPLACES_NOTHING": "A later document of the set changes a record that no earlier one has.",
    "SET_DUPLICATE": "Another record of the document set has the same value of the check member.",
    "SET_CONFLICT": "Two documents of the set give this record with different values.",
}

DESCRIPTIONS = {**REJECT, **FLAG, **INFO, **COVERAGE, **RECORD}
