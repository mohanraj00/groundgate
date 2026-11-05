"""Relations across fields (SPEC §2.3, §3.4, §5; #321, #284). The conformance vectors 80 to 84
pin the outcomes. These tests pin the digest, the receipt member, verify and exact arithmetic."""

from __future__ import annotations

from typing import Any

import pytest

import groundgate as gg
from groundgate.report import render

USD = {"type": "integer", "unit": "USD"}
DOC = "Revenue was $1.25 billion: $1 billion from sales and $250 million from fees."


def cand(cid: str, field: str, value: str, text: str) -> dict[str, Any]:
    return {"id": cid, "field": field, "value": value, "unit": "USD", "evidence": [{"text": text}]}


SCHEMA: dict[str, Any] = {
    "fields": {"revenue": USD, "sales": USD, "fees": USD},
    "relations": [
        {"id": "revenue", "total": "revenue", "parts": [{"field": "sales"}, {"field": "fees"}]}
    ],
}
CANDS = [
    cand("r", "revenue", "1250000000", "$1.25 billion"),
    cand("s", "sales", "1000000000", "$1 billion"),
    cand("f", "fees", "250000000", "$250 million"),
]


def test_no_relations_keep_the_schema_digest_and_the_receipt() -> None:
    plain = {"fields": SCHEMA["fields"]}
    empty = {**plain, "relations": []}
    a = gg.admit(DOC, plain, CANDS).to_dict()
    b = gg.admit(DOC, empty, CANDS).to_dict()
    assert a == b
    assert "relations" not in a
    assert "relations" not in gg.Schema.from_dict(empty).to_dict()


def test_defaults_are_in_the_digest() -> None:
    filled = gg.Schema.from_dict(SCHEMA).to_dict()["relations"]
    assert filled == [
        {
            "id": "revenue",
            "total": "revenue",
            "parts": [{"field": "sales", "factor": "1"}, {"field": "fees", "factor": "1"}],
            "tolerance": "0",
        }
    ]
    given = {
        **SCHEMA,
        "relations": [
            {
                "id": "revenue",
                "total": "revenue",
                "parts": [{"field": "sales", "factor": "1"}, {"field": "fees", "factor": "1"}],
                "tolerance": "0",
            }
        ],
    }
    assert gg.admit(DOC, given, CANDS).to_dict() == gg.admit(DOC, SCHEMA, CANDS).to_dict()


def test_a_scale_word_scales_the_place() -> None:
    receipt = gg.admit(DOC, SCHEMA, CANDS).to_dict()
    assert [d["outcome"] for d in receipt["decisions"]] == ["admitted"] * 3
    # places: 0.01 * 10^9, 1 * 10^9 and 1 * 10^6, so the allowance is half of their sum
    assert receipt["relations"] == [
        {"id": "revenue", "key": None, "holds": True, "difference": "0", "allowance": "505500000"}
    ]


def test_a_failed_relation_flags_every_value() -> None:
    # the fees take the revenue figure: a right number for the wrong field
    wrong = [*CANDS[:2], cand("f", "fees", "1250000000", "$1.25 billion")]
    receipt = gg.admit(DOC, SCHEMA, wrong).to_dict()
    for d in receipt["decisions"]:
        assert (d["outcome"], d["codes"]) == ("needs_verification", ["RELATION_FAILED"])
    assert receipt["relations"][0]["holds"] is False
    assert receipt["relations"][0]["difference"] == "-1000000000"
    assert receipt["relations"][0]["allowance"] == "510000000"


def test_long_numbers_are_exact() -> None:
    """40 digits: more than the 28 of the default Decimal context, which would round them."""
    big = 10**40
    doc = f"Total {big + 1}. Other total {big + 3}. Part {big}. Rest 1."
    number = {"type": "integer"}
    schema = {
        "fields": {"total": number, "part": number, "rest": number},
        "relations": [
            {"id": "sum", "total": "total", "parts": [{"field": "part"}, {"field": "rest"}]}
        ],
    }
    part = {"field": "part", "value": str(big), "evidence": {"text": f"Part {big}"}}
    rest = {"field": "rest", "value": "1", "evidence": {"text": "Rest 1"}}

    def total(value: int, text: str) -> dict[str, Any]:
        return {"field": "total", "value": str(value), "evidence": {"text": text}}

    holds = gg.admit(doc, schema, [total(big + 1, f"Total {big + 1}"), part, rest]).to_dict()
    assert holds["relations"] == [
        {"id": "sum", "key": None, "holds": True, "difference": "0", "allowance": "1.5"}
    ]
    fails = gg.admit(doc, schema, [total(big + 3, f"total {big + 3}"), part, rest]).to_dict()
    assert fails["relations"][0]["difference"] == "2"
    assert fails["relations"][0]["holds"] is False


def test_a_number_of_5000_digits_does_not_crash() -> None:
    """Python refuses to change an int of more than 4300 digits to a string."""
    one, three = "1" + "0" * 4999, "3" + "0" * 4999
    number = {"type": "integer"}
    schema = {
        "fields": {"total": number, "part": number, "rest": number},
        "relations": [
            {"id": "sum", "total": "total", "parts": [{"field": "part"}, {"field": "rest"}]}
        ],
    }
    doc = f"Total {three}. Part {one}. Rest {one}."
    cands = [
        {"field": f, "value": v, "evidence": {"text": f"{f.title()} {v}"}}
        for f, v in (("total", three), ("part", one), ("rest", one))
    ]
    relation = gg.admit(doc, schema, cands).to_dict()["relations"][0]
    assert (relation["holds"], relation["difference"], relation["allowance"]) == (False, one, "1.5")


def test_verify_compares_the_relations() -> None:
    receipt = gg.admit(DOC, SCHEMA, CANDS).to_dict()
    assert gg.verify(receipt, DOC, SCHEMA, CANDS).ok
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    body["relations"] = [{**body["relations"][0], "holds": False}]
    forged = {**body, "receipt_sha256": gg.digest("receipt", body)}
    result = gg.verify(forged, DOC, SCHEMA, CANDS)
    assert result.problems == ("relations differs from the re-derived receipt",)


def test_the_runner_asks_for_a_subset_of_the_fields_of_a_relation() -> None:
    from groundgate.extract.runner import _output_schema

    schema = gg.Schema.from_dict(SCHEMA)
    shape = _output_schema(schema, ["sales"], [])
    plain = _output_schema(gg.Schema.from_dict({"fields": {"sales": USD}}), ["sales"], [])
    assert shape == plain


NUMBER = {"type": "integer"}
PAIR: dict[str, Any] = {
    "fields": {"total": NUMBER, "part": NUMBER},
    "relations": [{"id": "sum", "total": "total", "parts": [{"field": "part"}]}],
}


def pair(total: str, part: str) -> tuple[str, list[dict[str, Any]]]:
    doc = f"Total {total}. Part {part}."
    cands = [
        {"field": f, "value": v, "evidence": {"text": f"{f.title()} {v}"}}
        for f, v in (("total", total), ("part", part))
    ]
    return doc, cands


def test_a_difference_past_the_digit_limit_fails_the_relation() -> None:
    """A total of 1,000,001 nines and a part of 1: the difference has 1,000,001 digits before the
    decimal point. The relation fails with no difference and no allowance (#582)."""
    doc, cands = pair("9" * 1_000_001, "1")
    receipt = gg.admit(doc, PAIR, cands).to_dict()
    assert receipt["relations"] == [
        {"id": "sum", "key": None, "holds": False, "difference": None, "allowance": None}
    ]
    assert [d["codes"] for d in receipt["decisions"]] == [["RELATION_FAILED"]] * 2
    assert gg.verify(receipt, doc, PAIR, cands).ok
    assert "<html" in render(receipt, doc, cands, schema=PAIR)


def test_a_difference_at_the_digit_limit_is_a_decimal() -> None:
    """1,000,000 nines minus 1 has 1,000,000 digits: under the limit, so it is exact."""
    doc, cands = pair("9" * 1_000_000, "1")
    relation = gg.admit(doc, PAIR, cands).to_dict()["relations"][0]
    assert relation == {
        "id": "sum",
        "key": None,
        "holds": False,
        "difference": "9" * 999_999 + "8",
        "allowance": "1",
    }


def test_an_allowance_past_the_digit_limit_fails_the_relation() -> None:
    """A tolerance of 1,000,000 nines is valid. With the half places of the total and the part,
    the allowance is 10^1000000, which has 1,000,001 digits (#582)."""
    schema = {**PAIR, "relations": [{**PAIR["relations"][0], "tolerance": "9" * 1_000_000}]}
    doc, cands = pair("5", "5")
    receipt = gg.admit(doc, schema, cands).to_dict()
    assert receipt["relations"][0] == {
        "id": "sum",
        "key": None,
        "holds": False,
        "difference": None,
        "allowance": None,
    }
    assert gg.verify(receipt, doc, schema, cands).ok


def test_a_factor_or_tolerance_past_the_digit_limit_is_invalid() -> None:
    """The schema check counts the digits before the decimal point (SPEC §2.3, #582)."""
    doc, cands = pair("5", "5")
    too_long = "1" + "0" * 1_000_000
    for member in ({"parts": [{"field": "part", "factor": too_long}]}, {"tolerance": too_long}):
        schema = {**PAIR, "relations": [{**PAIR["relations"][0], **member}]}
        with pytest.raises(gg.PacketError, match="1,000,000 digits before the decimal point"):
            gg.admit(doc, schema, cands)
    # 1,000,000 digits before the point, and any number after it, are valid.
    tolerance = "9" * 999_999 + "." + "5" * 10
    schema = {**PAIR, "relations": [{**PAIR["relations"][0], "tolerance": tolerance}]}
    assert gg.admit(doc, schema, cands).relations[0].holds
