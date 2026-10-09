"""Feedback messages select decisions that a new answer can fix."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

import groundgate as gg
from groundgate.codes import DESCRIPTIONS, INFO
from groundgate.model import Part

RETRY_CODES = (
    "PART_MISSING",
    "QUOTE_NOT_FOUND",
    "NON_VERBATIM_EVIDENCE",
    "SCALE_WORD",
    "NO_EVIDENCE",
    "SIGN_CITATION_INVALID",
    "SCALE_CITATION_INVALID",
    "UNIT_CITATION_INVALID",
    "FIELD_CITATION_INVALID",
    "KEY_CITATION_INVALID",
)
SCHEMA = {"fields": {"cost": {"type": "integer", "aliases": ["Costs"]}}}
CANDIDATE = {"field": "cost", "value": "40", "evidence": [{"text": "40"}]}
ADMITTED = gg.admit("Costs: 40.", SCHEMA, [CANDIDATE]).decisions[0]


@pytest.mark.parametrize("code", RETRY_CODES)
def test_retry_code(code: str) -> None:
    d = replace(ADMITTED, outcome="needs_verification", codes=(code,))
    assert gg.feedback_message(d, CANDIDATE, SCHEMA) == (
        f'Field "cost": you gave the value "40" with value "40".\n- {code}: {DESCRIPTIONS[code]}'
    )


@pytest.mark.parametrize(
    "code", sorted(set(DESCRIPTIONS) - set(RETRY_CODES) - set(INFO) - {"KEY_NOT_AT_VALUE"})
)
def test_other_code_stops_retry_even_with_a_retry_code(code: str) -> None:
    d = replace(ADMITTED, outcome="rejected", codes=("QUOTE_NOT_FOUND", code))
    assert gg.feedback_message(d, CANDIDATE, SCHEMA) is None


@pytest.mark.parametrize("code", INFO)
def test_info_does_not_stop_retry_or_appear_in_message(code: str) -> None:
    d = replace(ADMITTED, outcome="rejected", codes=("QUOTE_NOT_FOUND", code))
    assert gg.feedback_message(d, CANDIDATE, SCHEMA) == (
        'Field "cost": you gave the value "40" with value "40".\n'
        f"- QUOTE_NOT_FOUND: {DESCRIPTIONS['QUOTE_NOT_FOUND']}"
    )


def test_admitted_returns_none() -> None:
    assert gg.feedback_message(ADMITTED, CANDIDATE, SCHEMA) is None


@pytest.mark.parametrize("outcome", ["admitted", "needs_verification", "rejected"])
@pytest.mark.parametrize(
    "change", [{"value": "41"}, {"id": "other"}, {"evidence": [{"text": "41"}]}]
)
def test_digest_check_before_return(outcome: Any, change: dict[str, Any]) -> None:
    d = replace(ADMITTED, outcome=outcome, codes=("VALUE_NOT_IN_EVIDENCE",))
    with pytest.raises(ValueError, match="candidate digest does not match"):
        gg.feedback_message(d, {**CANDIDATE, **change}, SCHEMA)


def test_digest_accepts_reordered_candidate_members() -> None:
    d = replace(ADMITTED, outcome="rejected", codes=("QUOTE_NOT_FOUND",))
    candidate = dict(reversed(list(CANDIDATE.items())))
    assert gg.feedback_message(d, candidate, SCHEMA) is not None


def test_message_lists_quotes_codes_missing_parts_and_failed_parts_in_order() -> None:
    candidate = {
        **CANDIDATE,
        "evidence": [{"text": "40"}, {"role": "field", "text": "Other costs"}],
    }
    d = replace(
        ADMITTED,
        candidate_sha256=gg.digest("candidate", candidate),
        outcome="needs_verification",
        codes=("PART_MISSING", "FIELD_CITATION_INVALID", "VALUE_DERIVED"),
        missing=("sign", "scale", "unit", "key"),
        parts=(Part("sign", (0, 1), True), Part("field", None, False)),
    )
    assert gg.feedback_message(d, candidate, SCHEMA) == (
        'Field "cost": you gave the value "40" with value "40", field "Other costs".\n'
        f"- PART_MISSING: {DESCRIPTIONS['PART_MISSING']}\n"
        f"- FIELD_CITATION_INVALID: {DESCRIPTIONS['FIELD_CITATION_INVALID']}\n"
        '- Cite the sign with a "sign" item.\n'
        '- Cite the scale with a "scale" item.\n'
        '- Cite the unit with a "unit" item.\n'
        '- Also cite the words that name the field with a "field" item.\n'
        '- Cite the key with a "key" item.\n'
        '- Also cite the words that name the field with a "field" item.\n'
        '- The "field" item does not support the field at the value.'
    )


@pytest.mark.parametrize("aliases", [None, ["Costs"]])
@pytest.mark.parametrize("as_object", [False, True])
def test_missing_unit_needs_field_aliases(aliases: Any, as_object: bool) -> None:
    text = "Costs\n(in dollars)\n\n40"
    schema = {"fields": {"cost": {"type": "integer", "unit": "USD", "aliases": aliases}}}
    candidate = {**CANDIDATE, "unit": "USD"}
    d = gg.admit(text, schema, [candidate]).decisions[0]
    assert d.codes == ("PART_MISSING",)
    assert d.missing == ("unit",)
    s = gg.Schema.from_dict(schema) if as_object else schema
    message = gg.feedback_message(d, candidate, s, text)
    if aliases is None:
        assert message is None
    else:
        assert message is not None
        assert message.endswith(
            '- Cite the unit with a "unit" item.\n'
            '- Also cite the words that name the field with a "field" item.'
        )


KEY_SCHEMA = {
    "fields": {
        "cost": {
            "type": "integer",
            "unit": "USD",
            "keys": ["single", "joint"],
            "aliases": ["Costs"],
        }
    }
}
KEY_CANDIDATE = {
    "field": "cost",
    "value": "40",
    "unit": "USD",
    "key": "single",
    "evidence": [{"source": "document", "text": "$40"}],
}
KEY_HEADING = "Café " * 20 + "Single\n\nNotes:\n\n"
KEY_TABLE = KEY_HEADING + "Costs\t$40\t$30"
KEY_PROSE = KEY_HEADING + "Costs: $40.\nOther\t$30"


@pytest.mark.parametrize("text", [KEY_TABLE, KEY_TABLE + "\n", KEY_PROSE])
@pytest.mark.parametrize("aliases", [None, ["Costs"]])
def test_missing_key_needs_table_row_and_aliases(text: str, aliases: Any) -> None:
    schema = {"fields": {"cost": {**KEY_SCHEMA["fields"]["cost"], "aliases": aliases}}}
    d = gg.admit(text, schema, [KEY_CANDIDATE]).decisions[0]
    assert d.codes == ("KEY_NOT_AT_VALUE",)
    assert d.missing == ("key",)
    message = gg.feedback_message(d, KEY_CANDIDATE, schema, text)
    if aliases is None or text == KEY_PROSE:
        assert message is None
    else:
        assert message is not None
        assert message.endswith(
            '- Cite the key with a "key" item.\n'
            '- Also cite the words that name the field with a "field" item.'
        )


def test_missing_key_without_document_text_returns_none() -> None:
    d = gg.admit(KEY_TABLE, KEY_SCHEMA, [KEY_CANDIDATE]).decisions[0]
    assert gg.feedback_message(d, KEY_CANDIDATE, KEY_SCHEMA) is None


def test_key_not_at_value_with_key_item_returns_none() -> None:
    candidate = {
        **KEY_CANDIDATE,
        "evidence": [*KEY_CANDIDATE["evidence"], {"role": "key", "text": "Single"}],
    }
    d = gg.admit(KEY_TABLE, KEY_SCHEMA, [candidate]).decisions[0]
    assert "KEY_NOT_AT_VALUE" in d.codes
    assert "key" not in d.missing
    assert gg.feedback_message(d, candidate, KEY_SCHEMA, KEY_TABLE) is None


@pytest.mark.parametrize("reference_text", [KEY_TABLE, KEY_PROSE])
def test_key_uses_named_reference_instead_of_document(reference_text: str) -> None:
    candidate = {
        **KEY_CANDIDATE,
        "evidence": [{"source": "reference", "ref": "r", "text": "$40"}],
    }
    refs = ({"id": "other", "text": KEY_TABLE}, {"id": "r", "text": reference_text})
    d = gg.admit(KEY_TABLE, KEY_SCHEMA, [candidate], references=refs).decisions[0]
    assert d.codes == ("KEY_NOT_AT_VALUE",)
    assert d.missing == ("key",)
    assert d.ref == "r"
    message = gg.feedback_message(d, candidate, KEY_SCHEMA, references=refs)
    assert (message is not None) == (reference_text == KEY_TABLE)
    assert gg.feedback_message(d, candidate, KEY_SCHEMA, KEY_TABLE) is None
    assert gg.feedback_message(d, candidate, KEY_SCHEMA, KEY_TABLE, refs[:1]) is None


@pytest.mark.parametrize("evidence", [None, [], [{"role": "scale", "text": "in thousands"}]])
def test_no_evidence_message(evidence: Any) -> None:
    candidate = {**CANDIDATE, "evidence": evidence}
    d = gg.admit("Costs: 40.", SCHEMA, [candidate]).decisions[0]
    assert d.codes == ("NO_EVIDENCE",)
    message = gg.feedback_message(d, candidate, SCHEMA)
    quotes = 'scale "in thousands"' if evidence else "no quotes"
    assert message == (
        f'Field "cost": you gave the value "40" with {quotes}.\n'
        f"- NO_EVIDENCE: {DESCRIPTIONS['NO_EVIDENCE']}"
    )


@pytest.mark.parametrize("as_list", [False, True])
def test_span_items_with_quotes(as_list: bool) -> None:
    evidence = {"start": 7, "end": 9, "text": "41"}
    candidate = {**CANDIDATE, "evidence": [evidence] if as_list else evidence}
    d = gg.admit("Costs: 40.", SCHEMA, [candidate]).decisions[0]
    assert d.codes == ("NON_VERBATIM_EVIDENCE",)
    assert 'with value "41".' in gg.feedback_message(d, candidate, SCHEMA)


@pytest.mark.parametrize("as_list", [False, True])
def test_span_items_without_quotes(as_list: bool) -> None:
    text = "(in thousands)\nCosts: 40."
    start = text.encode().index(b"40")
    evidence = {"start": start, "end": start + 2}
    candidate = {**CANDIDATE, "value": "40000", "evidence": [evidence] if as_list else evidence}
    d = gg.admit(text, SCHEMA, [candidate]).decisions[0]
    assert d.codes == ("PART_MISSING",)
    assert gg.feedback_message(d, candidate, SCHEMA) == (
        'Field "cost": you gave the value "40000" with no quotes.\n'
        f"- PART_MISSING: {DESCRIPTIONS['PART_MISSING']}\n"
        '- Cite the scale with a "scale" item.'
    )


def test_a_malformed_evidence_item_is_not_quoted() -> None:
    candidate = {"field": "cost", "value": "40", "evidence": ["40", {"text": None}, {"text": "4"}]}
    d = gg.admit("Costs: 40.", SCHEMA, [candidate]).decisions[0]
    d = replace(d, outcome="rejected", codes=("QUOTE_NOT_FOUND",))
    assert gg.feedback_message(d, candidate, SCHEMA) == (
        'Field "cost": you gave the value "40" with value "4".\n'
        f"- QUOTE_NOT_FOUND: {DESCRIPTIONS['QUOTE_NOT_FOUND']}"
    )
