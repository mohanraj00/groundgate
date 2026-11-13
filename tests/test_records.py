"""Records and document sets (SPEC §4.12, §4.13, #613). The conformance vectors 165 to 169 hold
the decisions, the record lines and the check results."""

from __future__ import annotations

from typing import Any

import groundgate as gg

TEXT = "Price list 2026\nA-100 Hinge $4.20\nB-200 Bracket $12.50\n"
ITEMS = {
    "type": "record",
    "members": {
        "code": {"type": "string", "required": True},
        "unit_price": {"type": "number", "unit": "USD", "required": True},
    },
}


def _row(record: str, code: str, price: str, field: str = "items") -> list[dict[str, Any]]:
    return [
        {"id": f"{record}a", "field": f"{field}.code", "value": code, "record": record,
         "evidence": [{"text": code}]},
        {"id": f"{record}b", "field": f"{field}.unit_price", "value": price, "unit": "USD",
         "record": record, "evidence": [{"text": f"${price}"}]},
    ]  # fmt: skip


def test_schema_digest_holds_the_members() -> None:
    schema = gg.Schema.from_dict({"fields": {"items": ITEMS}})
    raw = schema.to_dict()["fields"]["items"]
    assert raw["type"] == "record" and raw["required"] is False
    assert set(raw["members"]) == {"code", "unit_price"}
    assert raw["members"]["code"]["multiple"] is False  # the defaults of a field
    assert "checks" not in schema.to_dict()
    assert set(schema.fields) == {"items.code", "items.unit_price"}


def test_decision_has_record_only_on_a_member_field() -> None:
    schema = {"fields": {"items": ITEMS, "title": {"type": "string"}}}
    cands = [
        *_row("r1", "A-100", "4.20"),
        {"id": "t", "field": "title", "value": "Price list", "record": "r1",
         "evidence": [{"text": "Price list"}]},
    ]  # fmt: skip
    receipt = gg.admit(TEXT, schema, cands).to_dict()
    by_id = {d["candidate_id"]: d for d in receipt["decisions"]}
    assert by_id["r1a"]["record"] == "r1"
    assert "record" not in by_id["t"]
    assert [r["record"] for r in receipt["records"]] == ["r1"]
    assert "checks" not in receipt


def test_record_ids_are_scoped_to_their_field() -> None:
    schema = {"fields": {"items": ITEMS, "spares": ITEMS}}
    cands = [*_row("r1", "A-100", "4.20"), *_row("r1", "B-200", "12.50", "spares")]
    lines = gg.admit(TEXT, schema, cands).records
    assert lines is not None
    assert [(r.field, r.record, r.outcome) for r in lines] == [
        ("items", "r1", "admitted"),
        ("spares", "r1", "admitted"),
    ]


def test_set_position_is_in_the_receipt() -> None:
    refs = [{"id": "corr-1", "text": "B-200 Bracket: read $14.00.", "set": 1},
            {"id": "notes", "text": "Notes."}]  # fmt: skip
    body = gg.admit(TEXT, {"fields": {"items": ITEMS}}, [], references=refs).to_dict()
    assert body["references"][0]["set"] == 1
    assert "set" not in body["references"][1]


def test_verify_finds_a_changed_record_line() -> None:
    schema = {"fields": {"items": ITEMS}}
    cands = _row("r1", "A-100", "4.20")
    receipt = gg.admit(TEXT, schema, cands).to_dict()
    assert gg.verify(receipt, TEXT, schema, cands).ok
    receipt["records"][0]["outcome"] = "rejected"
    problems = gg.verify(receipt, TEXT, schema, cands).problems
    assert "records differs from the re-derived receipt" in problems
