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
    assert r["groundgate"] == "0.5"
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


def test_verify_names_a_receipt_from_another_spec_version() -> None:
    r = gg.admit(DOC, SCHEMA, CANDS).to_dict()
    r["groundgate"] = "0.1"
    result = gg.verify(r, DOC, SCHEMA, CANDS)
    assert result.problems == (
        "receipt was decided under spec 0.1; this groundgate implements 0.5",
    )


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
        {"fields": {"f": {"keys": "adults"}}},
        {"fields": {"f": {"keys": []}}},
        {"fields": {"f": {"keys": ["adults", 1]}}},
        {"fields": {"f": {"keys": ["adults", " "]}}},
        {"fields": {"f": {"keys": ["Heart failure", "heart\nfailure"]}}},
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


def test_flag_order_and_code_descriptions_are_pinned() -> None:
    from groundgate import codes
    from groundgate.admit import FLAG_ORDER, INFO_ORDER

    assert FLAG_ORDER == (
        "NON_VERBATIM_EVIDENCE", "QUALIFIED_VALUE", "SCALE_WORD", "PART_MISSING",
        "SIGN_CITATION_INVALID", "SCALE_CITATION_INVALID", "UNIT_CITATION_INVALID",
        "FIELD_CITATION_INVALID", "KEY_NOT_AT_VALUE", "KEY_CITATION_INVALID", "EVIDENCE_QUOTED",
        "EVIDENCE_STATED", "LOW_CONFIDENCE", "CONFLICTING_CANDIDATES", "MODEL_DOUBT",
    )  # fmt: skip
    assert tuple(codes.FLAG) == FLAG_ORDER
    assert tuple(codes.INFO) == INFO_ORDER
    assert len(codes.REJECT) == 13
    assert set(codes.COVERAGE) == {"REQUIRED_FIELD_MISSING"}


def test_verify_rejects_a_receipt_that_is_not_an_object() -> None:
    with pytest.raises(gg.PacketError):
        gg.verify([], DOC, SCHEMA, CANDS)  # type: ignore[arg-type]


def test_decisions_echo_the_key_of_a_keyed_field() -> None:
    doc = "Adults: take 10 mg. Children: take 5 mg."
    schema = {
        "fields": {
            "dose": {"unit": "mg", "keys": ["adults", "children"]},
            "strength": {"unit": "mg"},
        }
    }
    span = {"start": 13, "end": 18, "text": "10 mg"}
    cands = [
        {"id": 1, "field": "dose", "value": "10", "unit": "mg", "key": "adults", "evidence": span},
        {"id": 2, "field": "dose", "value": "10", "unit": "mg", "key": "teens", "evidence": span},
        {
            "id": 3,
            "field": "strength",
            "value": "10",
            "unit": "mg",
            "key": "adults",
            "evidence": span,
        },
        {"id": 4, "field": "nope", "value": "10", "key": "adults"},
    ]
    got = {d.candidate_id: (d.outcome, d.key) for d in gg.admit(doc, schema, cands).decisions}
    assert got == {
        1: ("admitted", "adults"),
        2: ("rejected", "teens"),
        3: ("admitted", None),
        4: ("rejected", None),
    }
    assert gg.Schema.from_dict(schema).to_dict()["fields"]["strength"]["keys"] is None


JUDGE = {"id": "jev", "digest": "jev-1.13.0"}
DOUBT = {"judge": {**JUDGE, "doubt": {"field_match": 0.2}}}


def test_a_recorded_judgment_is_in_the_receipt_and_verify_needs_it() -> None:
    js = [
        {"candidate_id": "b", "question": "field_match", "judge": JUDGE, "p": 0.1},
        {"candidate_id": "a", "question": "field_match", "judge": JUDGE, "p": 0.9},
    ]
    r = gg.admit(DOC, SCHEMA, CANDS, DOUBT, judgments=js).to_dict()
    by_id = {d["candidate_id"]: d for d in r["decisions"]}
    assert by_id["a"]["outcome"] == "admitted"
    assert (by_id["b"]["outcome"], by_id["b"]["codes"]) == ("needs_verification", ["MODEL_DOUBT"])
    sha = {d["candidate_id"]: d["candidate_sha256"] for d in r["decisions"]}
    assert r["judgments"] == sorted(
        [
            {"candidate_sha256": sha["a"], "question": "field_match", "p": 0.9},
            {"candidate_sha256": sha["b"], "question": "field_match", "p": 0.1},
        ],
        key=lambda j: j["candidate_sha256"],
    )
    assert gg.verify(r, DOC, SCHEMA, CANDS, DOUBT, js).ok
    assert not gg.verify(r, DOC, SCHEMA, CANDS, DOUBT).ok
    # with no judge in the policy, nothing applies and the receipt lists no judgment
    plain = gg.admit(DOC, SCHEMA, CANDS, judgments=js).to_dict()
    assert (
        plain["judgments"] == []
        and plain["decisions"] == gg.admit(DOC, SCHEMA, CANDS).to_dict()["decisions"]
    )


def test_cli_takes_recorded_judgments(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = _write(tmp_path, "doc.txt", DOC)
    schema = _write(tmp_path, "schema.json", SCHEMA)
    cands = _write(tmp_path, "cands.json", CANDS)
    policy = _write(tmp_path, "policy.json", DOUBT)
    js = _write(
        tmp_path,
        "judgments.json",
        [{"candidate_id": "b", "question": "field_match", "judge": JUDGE, "p": 0.1}],
    )
    out = str(tmp_path / "receipt.json")
    run = [doc, schema, cands, "--policy", policy, "--judgments", js]
    assert main(["admit", *run, "-o", out]) == 0
    assert main(["verify", out, *run]) == 0
    assert main(["verify", out, doc, schema, cands, "--policy", policy]) == 1
    page = str(tmp_path / "report.html")
    assert main(["report", out, *run, "-o", page]) == 0
    assert "receipt verified" in Path(page).read_text()
    capsys.readouterr()


@pytest.mark.parametrize(
    "judgments",
    [
        "not a list",
        ["not an object"],
        [{"candidate_id": "a", "question": "field_match", "judge": JUDGE, "p": 0.1, "x": 1}],
        [{"candidate_id": "a", "question": "field_match", "judge": {"id": "jev"}, "p": 0.1}],
        [{"candidate_id": "a", "question": "field_match", "judge": JUDGE, "p": True}],
        [{"candidate_id": "a", "question": "key", "judge": JUDGE, "p": 0.1}],
        [{"candidate_id": "a", "question": "key", "judge": JUDGE, "answer": 3, "p": 0.1}],
        [{"candidate_id": "a", "question": "field_match", "judge": JUDGE, "answer": None, "p": 0}],
        [{"candidate_id": True, "question": "field_match", "judge": JUDGE, "p": 0.1}],
        [{"candidate_id": 1, "question": "field_match", "judge": JUDGE, "p": 0.1}],
    ],
)
def test_malformed_judgments_are_invalid_packets(judgments: Any) -> None:
    with pytest.raises(gg.PacketError):
        gg.admit(DOC, SCHEMA, CANDS, DOUBT, judgments=judgments)


@pytest.mark.parametrize(
    "judge",
    [
        "jev",
        {**JUDGE, "model": "x"},
        {"id": "jev"},
        {**JUDGE, "clear": []},
        {**JUDGE, "doubt": {"field_match": 1.5}},
        {**JUDGE, "doubt": {"field_match": True}},
        {**JUDGE, "doubt": {"field_match": None}},
        {**JUDGE, "clear": {"KEY_NOT_AT_VALUE": None}},
    ],
)
def test_a_malformed_policy_judge_is_invalid(judge: Any) -> None:
    with pytest.raises(gg.PacketError):
        gg.admit(DOC, SCHEMA, CANDS, {"judge": judge})


def test_a_key_judgment_without_the_key_flag_is_recorded_and_changes_nothing() -> None:
    doc = "Adults: take 10 mg. Children: take 5 mg."
    schema = {"fields": {"dose": {"type": "number", "unit": "mg", "keys": ["Adults", "Children"]}}}
    start = doc.encode().index(b"10 mg")
    cand = {"id": "a", "field": "dose", "value": "10", "unit": "mg", "key": "Adults",
            "evidence": {"start": start, "end": start + 5}}  # fmt: skip
    policy = {"judge": {**JUDGE, "clear": {"KEY_NOT_AT_VALUE": 0.9}}}
    js = [{"candidate_id": "a", "question": "key", "judge": JUDGE, "answer": None, "p": 0.99}]
    r = gg.admit(doc, schema, [cand], policy, judgments=js).to_dict()
    assert (r["decisions"][0]["outcome"], r["decisions"][0]["codes"]) == ("admitted", [])
    assert [j["question"] for j in r["judgments"]] == ["key"]


def test_applied_judgments_in_a_receipt_are_immutable() -> None:
    js = [{"candidate_id": "a", "question": "field_match", "judge": JUDGE, "p": 0.9}]
    (j,) = gg.admit(DOC, SCHEMA, CANDS, DOUBT, judgments=js).judgments
    with pytest.raises(AttributeError):
        j.p = 0.1  # type: ignore[misc]


KEYED_DOC = "Café Single\n\nNotes:\n\nThe deduction is $15,000."
KEYED_SCHEMA: dict[str, Any] = {
    "fields": {"d": {"type": "integer", "unit": "USD", "keys": ["single", "joint"]}}
}


def _keyed(*roles: Any) -> dict[str, Any]:
    start = KEYED_DOC.encode().index(b"$15,000")
    return {
        "id": "k",
        "field": "d",
        "value": "15000",
        "unit": "USD",
        "key": "single",
        "evidence": [{"start": start, "end": start + 7}, *roles],
    }


def test_parts_report_byte_spans_and_verify() -> None:
    start = KEYED_DOC.encode().index(b"Single")
    cand = _keyed({"role": "key", "text": "Single"})
    r = gg.admit(KEYED_DOC, KEYED_SCHEMA, [cand])
    d = r.to_dict()["decisions"][0]
    # the label line stops the key, and without a field item the column rule does not apply
    assert (d["outcome"], d["codes"], d["missing"]) == (
        "needs_verification",
        ["KEY_NOT_AT_VALUE"],
        [],
    )
    assert d["parts"] == [{"role": "key", "start": start, "end": start + 6, "passed": True}]
    assert (d["source"], d["ref"], d["url"]) == ("document", None, None)
    assert gg.verify(r.to_dict(), KEYED_DOC, KEYED_SCHEMA, [cand]).ok
    d0 = gg.admit(KEYED_DOC, KEYED_SCHEMA, [_keyed()]).to_dict()["decisions"][0]
    assert (d0["codes"], d0["parts"], d0["missing"]) == (["KEY_NOT_AT_VALUE"], [], ["key"])


def test_failed_key_item_is_not_cleared_by_a_judgment() -> None:
    start = KEYED_DOC.encode().index(b"Notes")
    cand = _keyed({"role": "key", "start": start, "end": start + 5})
    judge = {"id": "j", "digest": "j-1"}
    policy = {"judge": {**judge, "clear": {"KEY_NOT_AT_VALUE": 0.5}}}
    js = [
        {
            "candidate_id": "k",
            "question": "key",
            "judge": judge,
            "answer": "single",
            "p": 0.99,
        }
    ]
    d = gg.admit(KEYED_DOC, KEYED_SCHEMA, [cand], policy, None, js).to_dict()["decisions"][0]
    assert (d["outcome"], d["codes"]) == (
        "needs_verification",
        ["KEY_CITATION_INVALID", "MODEL_CLEARED"],
    )


def test_a_role_item_that_is_not_an_object_makes_the_candidate_invalid() -> None:
    d = gg.admit(KEYED_DOC, KEYED_SCHEMA, [_keyed("Single")]).to_dict()["decisions"][0]
    assert (d["outcome"], d["codes"]) == ("rejected", ["CANDIDATE_INVALID"])


FEE_SCHEMA = {"fields": {"fee": {"type": "integer", "unit": "USD"}}}


def test_receipt_lists_references_and_the_document_source() -> None:
    refs = [
        {"id": "b", "text": "The fee is $40.", "source": "https://example.org/b"},
        {"id": "a", "text": "Fees: $40."},
    ]
    cand = {"field": "fee", "value": 40, "unit": "USD",
            "evidence": [{"source": "reference", "ref": "b", "text": "$40"}]}  # fmt: skip
    r = gg.admit(
        DOC, FEE_SCHEMA, [cand], references=refs, document_source="https://example.org/doc"
    )
    body = r.to_dict()
    assert body["document"]["source"] == "https://example.org/doc"
    assert body["references"] == [
        {"id": "a", "sha256": gg.digest("reference", {"text": "Fees: $40."}), "source": None},
        {"id": "b", "sha256": gg.digest("reference", {"text": "The fee is $40."}),
         "source": "https://example.org/b"},
    ]  # fmt: skip
    d = body["decisions"][0]
    assert (d["outcome"], d["source"], d["ref"], d["evidence"]) == (
        "admitted", "reference", "b", {"start": 11, "end": 14},
    )  # fmt: skip
    assert gg.verify(body, DOC, FEE_SCHEMA, [cand], references=refs,
                     document_source="https://example.org/doc").ok  # fmt: skip
    # another document source changes the receipt
    assert not gg.verify(body, DOC, FEE_SCHEMA, [cand], references=refs).ok


def test_a_rejected_outside_candidate_reports_its_deciding_item() -> None:
    cand = {"field": "fee", "value": 40, "unit": "USD",
            "evidence": [{"source": "external", "url": "https://example.org/fees",
                          "retrieved": "2026-10-01", "text": "The fee is $40."}]}  # fmt: skip
    policy = {"sources": {"external": {"other": "reject"}}}
    d = gg.admit(DOC, FEE_SCHEMA, [cand], policy).to_dict()["decisions"][0]
    assert (d["codes"], d["source"], d["url"], d["evidence"]) == (
        ["SOURCE_REJECTED"], "external", "https://example.org/fees", None,
    )  # fmt: skip


def test_policy_sources_defaults() -> None:
    assert gg.Policy().to_dict()["sources"] == {
        "external": {"allow": [], "other": "review"},
        "knowledge": "review",
    }
    p = gg.Policy.from_dict({"sources": {"knowledge": "admit"}})
    assert p.to_dict()["sources"]["external"] == {"allow": [], "other": "review"}


def test_host_of_a_url() -> None:
    from groundgate.text import host

    assert host("https://user@WWW.Example.org:8080/a?b#c") == "www.example.org"
    assert host("https://example.org?x=1") == "example.org"
    assert host("mailto:someone") is None


def test_an_early_reject_of_a_reference_item_names_its_text() -> None:
    refs = [{"id": "r", "text": "The fee is $40."}]
    cand = {"field": "nope", "value": 40,
            "evidence": [{"source": "reference", "ref": "r", "start": 11, "end": 14}]}  # fmt: skip
    d = gg.admit(DOC, FEE_SCHEMA, [cand], references=refs).to_dict()["decisions"][0]
    assert (d["codes"], d["source"], d["ref"], d["evidence"]) == (
        ["FIELD_UNKNOWN"], "reference", "r", {"start": 11, "end": 14},
    )  # fmt: skip


def test_host_of_an_ipv6_url() -> None:
    from groundgate.text import host

    assert host("https://[2001:DB8::1]:443/p") == "[2001:db8::1]"
    assert host("https://[2001:db8::1]/") != host("https://[2001:db8::2]/")


def test_a_repeated_unit_prefix_is_one_empty_cell() -> None:
    from groundgate.text import cells

    text = "Costs\n\n$\n\n\n\n$\n\n5,500"
    assert cells(text, 5, text.index("5,500"), ["$", "$"]) == [7]
