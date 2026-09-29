from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.cli import main

DOC = "The contribution limit remains $7,000 ($8,000 for individuals age 50 or older)."
SCHEMA: dict[str, Any] = {
    "fields": {
        "limit": {"type": "integer", "unit": "USD"},
        "limit_50": {"type": "integer", "unit": "USD"},
    }
}


def ev(quote: str) -> dict[str, Any]:
    start = DOC.encode().index(quote.encode())
    return {"start": start, "end": start + len(quote.encode()), "text": quote}


CANDS = [
    {"id": "a", "field": "limit", "value": "7000", "unit": "USD", "evidence": ev("$7,000")},
    {"id": "b", "field": "limit_50", "value": "8000", "unit": "USD", "evidence": ev("$8,000")},
    {"id": "c", "field": "limit_50", "value": "80000", "unit": "USD", "evidence": ev("$8,000")},
]


def test_receipt_shape_and_summary() -> None:
    r = gg.admit(DOC, SCHEMA, CANDS, document_id="doc-1").to_dict()
    assert r["groundgate"] == "0.1"
    assert r["document"]["id"] == "doc-1"
    assert r["summary"] == {"admitted": 2, "needs_verification": 0, "rejected": 1}
    shas = [d["candidate_sha256"] for d in r["decisions"]]
    assert shas == sorted(shas)


def test_order_of_candidates_does_not_change_the_receipt() -> None:
    base = gg.admit(DOC, SCHEMA, CANDS).to_dict()
    for seed in range(5):
        shuffled = CANDS[:]
        random.Random(seed).shuffle(shuffled)
        assert gg.admit(DOC, SCHEMA, shuffled).to_dict() == base


def test_accepts_schema_and_policy_objects() -> None:
    a = gg.admit(DOC, gg.Schema.from_dict(SCHEMA), CANDS, gg.Policy(unit_window=10))
    b = gg.admit(DOC, SCHEMA, CANDS, {"unit_window": 10})
    assert a == b


def test_verify_detects_tampering() -> None:
    r = gg.admit(DOC, SCHEMA, CANDS).to_dict()
    assert gg.verify(r, DOC, SCHEMA, CANDS).ok

    edited = json.loads(json.dumps(r))
    rejected = next(d for d in edited["decisions"] if d["outcome"] == "rejected")
    rejected["outcome"], rejected["codes"] = "admitted", []
    result = gg.verify(edited, DOC, SCHEMA, CANDS)
    assert not result.ok
    assert any("receipt_sha256" in p for p in result.problems)

    other_doc = DOC.replace("$8,000", "$9,000")
    assert not gg.verify(r, other_doc, SCHEMA, CANDS).ok
    assert not gg.verify(r, DOC, SCHEMA, CANDS[:2]).ok


def test_packet_errors() -> None:
    with pytest.raises(gg.PacketError):
        gg.admit("Café", SCHEMA, [])
    with pytest.raises(gg.PacketError):
        gg.admit(DOC, SCHEMA, "not a list")  # type: ignore[arg-type]
    with pytest.raises(gg.PacketError):
        gg.admit(DOC, {"fields": {}, "extra": 1}, [])
    with pytest.raises(gg.PacketError):
        gg.admit(DOC, {"fields": {}, "units": {"X": {"prefix": [""]}}}, [])
    with pytest.raises(gg.PacketError):
        gg.admit(DOC, SCHEMA, [], {"unit_window": -1})


def test_rejected_decision_reports_what_is_known() -> None:
    d = next(x for x in gg.admit(DOC, SCHEMA, CANDS).decisions if x.candidate_id == "c")
    assert (d.outcome, d.codes, d.value, d.unit) == (
        "rejected",
        ("VALUE_NOT_IN_EVIDENCE",),
        "80000",
        "USD",
    )
    assert d.evidence == (ev("$8,000")["start"], ev("$8,000")["end"])


def _write(tmp: Path, name: str, obj: Any) -> str:
    path = tmp / name
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return str(path)


def test_cli_admit_and_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = _write(tmp_path, "doc.txt", DOC)
    schema = _write(tmp_path, "schema.json", SCHEMA)
    cands = _write(tmp_path, "cands.json", CANDS)
    out = str(tmp_path / "receipt.json")
    assert main(["admit", doc, schema, cands, "-o", out]) == 0
    assert main(["verify", out, doc, schema, cands]) == 0
    assert "verified" in capsys.readouterr().out

    policy = _write(tmp_path, "policy.json", {"unit_window": 1})
    assert main(["verify", out, doc, schema, cands, "--policy", policy]) == 1

    assert main(["admit", doc, schema, cands]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["rejected"] == 1

    bad = _write(tmp_path, "bad.txt", "Café")
    assert main(["admit", bad, schema, cands]) == 2


@pytest.mark.parametrize(
    "schema",
    [
        [],
        {"fields": []},
        {"fields": {"f": []}},
        {"fields": {"f": {"minimum": 1.5}}},
        {"fields": {"f": {"minimum": True}}},
        {"fields": {"f": {"comparator": "near"}}},
        {"fields": {"f": {"unit": 5}}},
        {"fields": {"f": {"required": "yes"}}},
        {"fields": {}, "units": []},
        {"fields": {}, "units": {"X": []}},
        {"fields": {}, "units": {"X": {"prefix": "$"}}},
    ],
)
def test_invalid_schemas(schema: Any) -> None:
    with pytest.raises(gg.PacketError):
        gg.Schema.from_dict(schema)


@pytest.mark.parametrize(
    "policy",
    [
        [],
        {"min_confidence": True},
        {"min_confidence": "0.5"},
        {"unit_window": 2.5},
        {"reanchor": 1},
    ],
)
def test_invalid_policies(policy: Any) -> None:
    with pytest.raises(gg.PacketError):
        gg.Policy.from_dict(policy)


def test_schema_defaults_are_hashed() -> None:
    a = gg.admit(DOC, {"fields": {"limit": {"unit": "USD"}}}, [])
    b = gg.admit(
        DOC, {"fields": {"limit": {"unit": "USD", "type": "number", "required": False}}}, []
    )
    assert a.schema_sha256 == b.schema_sha256
