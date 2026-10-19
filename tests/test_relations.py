"""Relations across fields (SPEC §2.3, §3.4, §5; #321, #284). The conformance vectors 80 to 84
pin the outcomes. These tests pin the digest, the receipt member, verify and exact arithmetic."""

from __future__ import annotations

from typing import Any

import groundgate as gg

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
