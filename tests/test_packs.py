"""Vocabulary packs (SPEC §4.8): the loader, the union, and the receipt members (#334)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate import text
from groundgate.cli import main
from groundgate.pack import (
    BASE,
    MAX_CANONICAL,
    MAX_FILE,
    _conflicts,
    combine,
    pack_digest,
    with_defaults,
)

DOC = "The grant is 5 lac. The fee is 9 sites."
SCHEMA = {
    "packs": [{"id": "words-x-test", "version": "1.0.0"}],
    "fields": {"grant": {"type": "integer"}, "fee": {"type": "integer"}},
}


def pack(pid: str = "words-x-test", **lists: Any) -> dict[str, Any]:
    return {"groundgate_pack": 1, "type": "vocabulary", "id": pid, "version": "1.0.0", **lists}


LAC = pack(scale={"words": {"lac": 5}})


def cand(cid: str, field: str, value: str, quote: str) -> dict[str, Any]:
    return {"id": cid, "field": field, "value": value, "evidence": {"text": quote}}


CANDS = [cand("a", "grant", "5", "5 lac"), cand("b", "fee", "9", "9 sites")]


def _outcomes(receipt: dict[str, Any]) -> dict[str, str]:
    return {d["candidate_id"]: d["outcome"] for d in receipt["decisions"]}


def test_the_base_pack_passes_its_own_checks() -> None:
    assert combine(BASE, []) == with_defaults(BASE)
    _conflicts(with_defaults(BASE), combine(BASE, []))


def test_the_digest_reads_the_pack_after_defaults() -> None:
    full = {**pack(), "description": "", "status": [], "per_units": [], "units": {}}
    assert pack_digest(pack()) == pack_digest(full)
    assert pack_digest(pack()) != pack_digest(pack(per_units=["acre"]))


def test_load_pack_reads_a_file(tmp_path: Path) -> None:
    f = tmp_path / "lac.json"
    f.write_text(json.dumps(LAC), encoding="utf-8")
    assert gg.load_pack(f) == LAC


def test_load_pack_refuses_a_big_file_before_it_parses_it(tmp_path: Path) -> None:
    f = tmp_path / "big.json"
    f.write_bytes(b"[" * (MAX_FILE + 1))  # not JSON: only the size check can refuse it first
    with pytest.raises(gg.PacketError, match="more than 1048576 bytes"):
        gg.load_pack(f)


@pytest.mark.parametrize(
    "raw",
    [b'{"id": "a-x-b", "id": "c-x-d"}', b"[" * 5000 + b"]" * 5000, b"\xff", b"{NaN}"],
    ids=["key twice", "deep", "not utf-8", "not json"],
)
def test_load_pack_refuses_a_file_that_is_not_one_json_object(tmp_path: Path, raw: bytes) -> None:
    f = tmp_path / "bad.json"
    f.write_bytes(raw)
    with pytest.raises(gg.PacketError):
        gg.load_pack(f)


def test_a_pack_of_more_than_256_kib_as_canonical_json_is_invalid() -> None:
    words = [f"{'w' * 60}{i:04d}" for i in range(1999)]
    big = pack(per_units=words, null_literals=list(words), changes={"stop_words": list(words)})
    assert len(gg.jcs(big)) > MAX_CANONICAL
    with pytest.raises(gg.PacketError, match="262144"):
        gg.admit(DOC, SCHEMA, [], packs=[big])


def test_a_deep_object_is_refused_without_recursion() -> None:
    deep: Any = "x"
    for _ in range(100_000):
        deep = [deep]
    with pytest.raises(gg.PacketError, match="depth"):
        gg.admit(DOC, SCHEMA, [], packs=[pack(status=deep)])


def test_the_receipt_names_each_pack_and_each_decision_names_the_packs_it_read() -> None:
    receipt = gg.admit(DOC, SCHEMA, CANDS, packs=[LAC]).to_dict()
    assert list(receipt)[:4] == ["groundgate", "document", "references", "packs"]
    assert receipt["packs"] == [
        {"id": "words-x-test", "type": "vocabulary", "version": "1.0.0", "sha256": pack_digest(LAC)}
    ]
    assert [d["packs"] for d in receipt["decisions"]] == [["words-x-test"], ["words-x-test"]]
    assert _outcomes(receipt) == {"a": "needs_verification", "b": "admitted"}


def test_a_pack_whose_words_do_not_occur_is_not_named_in_a_decision() -> None:
    doc = "The fee is 9 sites."
    receipt = gg.admit(doc, SCHEMA, [cand("b", "fee", "9", "9 sites")], packs=[LAC]).to_dict()
    assert receipt["decisions"][0]["packs"] == []
    assert receipt["packs"][0]["id"] == "words-x-test"


def test_a_pack_word_in_the_candidate_marks_the_decision() -> None:
    nulls = pack(null_literals=["0"])
    schema = {**SCHEMA, "fields": {"fee": {"type": "integer"}}}
    d = gg.admit("The fee is 0 sites.", schema, [cand("b", "fee", 0, "0")], packs=[nulls])  # type: ignore[arg-type]
    assert (d.decisions[0].codes, d.decisions[0].packs) == (
        ("NULL_STRING_LITERAL",),
        ("words-x-test",),
    )


def test_a_word_that_the_base_gives_in_the_same_list_is_no_mark() -> None:
    same = pack(scale={"words": {"million": 6}})
    receipt = gg.admit("The fee is 5 million.", SCHEMA, [], packs=[same]).to_dict()
    assert receipt["decisions"] == []
    schema = gg.Schema.from_dict(SCHEMA, [same])
    assert schema.marks == (("words-x-test", frozenset()),)


def test_the_schema_digest_holds_the_pack_digest() -> None:
    a = gg.admit(DOC, SCHEMA, CANDS, packs=[LAC]).to_dict()
    b = gg.admit(DOC, SCHEMA, CANDS, packs=[pack(scale={"words": {"lac": 5}}, description="x")])
    assert a["schema_sha256"] != b.to_dict()["schema_sha256"]
    plain = {"fields": SCHEMA["fields"]}
    assert "packs" not in gg.Schema.from_dict(plain).to_dict()
    assert gg.Schema.from_dict(SCHEMA, [LAC]).to_dict()["packs"] == [
        {"id": "words-x-test", "version": "1.0.0", "sha256": pack_digest(LAC)}
    ]


def test_a_pin_that_matches_is_accepted() -> None:
    pinned = {**SCHEMA, "packs": [{**SCHEMA["packs"][0], "sha256": pack_digest(LAC)}]}
    assert (
        _outcomes(gg.admit(DOC, pinned, CANDS, packs=[LAC]).to_dict())["a"] == "needs_verification"
    )


def test_the_order_of_the_packs_never_changes_the_receipt() -> None:
    a = pack("a-x-test", qualifiers={"before": {"gt": ["upwards of", "north of"]}})
    b = pack("b-x-test", scale={"words": {"lac": 5, "lacs": 5}}, per_units=["acre"])
    schema = {
        "packs": [{"id": "b-x-test", "version": "1.0.0"}, {"id": "a-x-test", "version": "1.0.0"}],
        "fields": {"grant": {"type": "integer"}, "fee": {"type": "integer"}},
    }
    one = gg.admit(DOC, schema, CANDS, packs=[a, b]).to_dict()
    two = gg.admit(DOC, schema, CANDS, packs=[b, a]).to_dict()
    assert one == two
    assert [p["id"] for p in one["packs"]] == ["a-x-test", "b-x-test"]


def test_added_words_follow_the_base_longest_first() -> None:
    merged = combine(BASE, [pack(per_units=["ha", "acre", "hectare"])])
    assert merged["per_units"] == [*BASE["per_units"], "hectare", "acre", "ha"]


def test_an_empty_list_matches_nothing() -> None:
    assert text._words([]) == "(?!)" and text._phrases([]) == "(?!)"
    assert re.search(text._words([]), "") is None
    assert re.search(text._sign_class(""), "$") is None
    only = pack(qualifiers={"after": {"approx": ["or so"]}})
    v = text.Vocabulary(combine(BASE, [only]))
    assert set(v._AFTER_RE) == {"ge", "le", "approx"}
    assert v._AFTER_RE["approx"].search("5 or so") is not None


def test_a_given_pack_cannot_change_after_the_check() -> None:
    p = pack(scale={"words": {"lac": 5}})
    schema = gg.Schema.from_dict(SCHEMA, [p])
    p["scale"]["words"]["lac"] = 4  # the schema holds its own copy
    assert schema.vocabulary._SCALE_EXP["lac"] == 5


def test_a_packet_with_no_pack_reads_the_base_only() -> None:
    plain = {"fields": SCHEMA["fields"]}
    receipt = gg.admit(DOC, plain, CANDS).to_dict()
    assert receipt["packs"] == [] and [d["packs"] for d in receipt["decisions"]] == [[], []]
    assert _outcomes(receipt) == {"a": "admitted", "b": "admitted"}
    assert text.vocabulary() is text.BASE_VOCABULARY


def test_verify_needs_the_same_packs() -> None:
    receipt = gg.admit(DOC, SCHEMA, CANDS, packs=[LAC]).to_dict()
    assert gg.verify(receipt, DOC, SCHEMA, CANDS, packs=[LAC]).ok
    with pytest.raises(gg.PacketError, match="not given"):
        gg.verify(receipt, DOC, SCHEMA, CANDS)
    other = pack(scale={"words": {"lac": 5}}, description="another copy")
    assert not gg.verify(receipt, DOC, SCHEMA, CANDS, packs=[other]).ok


def test_a_schema_object_takes_its_packs_from_from_dict() -> None:
    schema = gg.Schema.from_dict(SCHEMA, [LAC])
    assert _outcomes(gg.admit(DOC, schema, CANDS).to_dict())["a"] == "needs_verification"
    with pytest.raises(gg.PacketError, match="from_dict"):
        gg.admit(DOC, schema, CANDS, packs=[LAC])


@pytest.mark.parametrize(
    "bad",
    [
        pack(sign={"loss": ["income"]}),
        pack(heading_units={"USD": {"names": ["bucks"], "sign": "€"}}),
        pack(heading_units={"JPY": {"names": ["euros"]}}),
        pack(scale={"suffixes": {"k": 6}}),
        pack(scale={"currency": {"k": 6}}),
        pack(heading_units={"usd": {"names": ["bucks"]}}),
        pack(currency_signs=["Y"]),
        pack(null_literals=["Unknown"]),
        pack(sentence={"abbreviations": ["approx"]}),
        pack(units={"USD": {"forms": ["$"]}}),
        pack(scale={"words": {"lac": 2**60}}),
    ],
    ids=[
        "loss and gain",
        "two signs",
        "a name under two codes",
        "suffix with two powers",
        "suffix and currency scale",
        "code case",
        "sign is a letter",
        "null literal case",
        "abbreviation dot",
        "unit member",
        "integer range",
    ],
)
def test_more_loader_checks(bad: dict[str, Any]) -> None:
    with pytest.raises(gg.PacketError):
        gg.admit(DOC, SCHEMA, [], packs=[bad])


def test_the_cli_reads_each_pack_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = {
        "doc.txt": DOC,
        "schema.json": json.dumps(SCHEMA),
        "cands.json": json.dumps(CANDS),
        "lac.json": json.dumps(LAC),
    }
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    doc, schema, cands, lac = (str(tmp_path / n) for n in files)
    out = str(tmp_path / "receipt.json")
    assert main(["admit", doc, schema, cands, "--pack", lac, "-o", out]) == 0
    assert json.loads(Path(out).read_text(encoding="utf-8"))["packs"][0]["id"] == "words-x-test"
    assert main(["verify", out, doc, schema, cands, "--pack", lac]) == 0
    assert main(["verify", out, doc, schema, cands]) == 2
    assert "not given" in capsys.readouterr().err
    assert main(["schema", schema, "--pack", lac]) == 0
    assert main(["schema", "check", schema, "--pack", lac]) == 0


class _Shifty(dict):  # type: ignore[type-arg]
    """A dict that gives another value on the second read."""

    reads = 0

    def __getitem__(self, key: object) -> object:
        _Shifty.reads += 1
        return {"lac": 2**60} if _Shifty.reads > 1 else super().__getitem__(key)


def test_a_subclass_of_a_json_type_is_not_data() -> None:
    shifty = pack(scale={"words": _Shifty(lac=5)})
    with pytest.raises(gg.PacketError, match="L2"):
        gg.admit(DOC, SCHEMA, [], packs=[shifty])
    with pytest.raises(gg.PacketError, match="L2"):
        gg.admit(DOC, SCHEMA, [], packs=[pack(per_units=type("L", (list,), {})(["acre"]))])


def test_load_pack_refuses_a_path_that_is_not_a_file(tmp_path: Path) -> None:
    for path in (tmp_path / "missing.json", tmp_path):
        with pytest.raises(gg.PacketError, match="is not a file"):
            gg.load_pack(path)


def test_a_documents_count_is_not_a_bool() -> None:
    row = {"kind": "scale", "field": "words", "code": "lac", "status": "draft"}
    gg.admit(DOC, SCHEMA, [], packs=[pack(status=[{**row, "documents": 3}])])
    with pytest.raises(gg.PacketError, match="bool is not data"):
        gg.admit(DOC, SCHEMA, [], packs=[pack(status=[{**row, "documents": True}])])


def test_a_shared_list_is_refused_at_once() -> None:
    x: Any = []
    for _ in range(6):
        x = [x] * 2000  # 2000**6 paths through 7 lists, at depth 8
    with pytest.raises(gg.PacketError, match="two places"):
        gg.admit(DOC, SCHEMA, [], packs=[pack(status=x)])
    loop: list[Any] = []
    loop.append(loop)
    with pytest.raises(gg.PacketError, match="two places"):
        gg.admit(DOC, SCHEMA, [], packs=[pack(status=loop)])


# ---------------------------------------------------------------- kind packs (#335)
def kind(pid: str = "grants-x-test", **members: Any) -> dict[str, Any]:
    return {"groundgate_pack": 1, "type": "kind", "id": pid, "version": "1.0.0", **members}


GRANTS = kind(
    needs=[{"id": "words-x-test", "version": "1.0.0"}],
    fields={"grant": {"type": "integer", "aliases": ["grant"], "description": "A grant."}},
)
KIND_SCHEMA = {
    "packs": [{"id": "grants-x-test", "version": "1.0.0"}],
    "fields": {"grant": {"template": "grants-x-test/grant"}, "fee": {"type": "integer"}},
}


def test_a_template_fills_the_field_and_the_resolved_schema_keeps_it() -> None:
    schema = gg.Schema.from_dict(KIND_SCHEMA, [GRANTS, LAC])
    grant = schema.to_dict()["fields"]["grant"]
    assert grant["template"] == "grants-x-test/grant"
    assert (grant["type"], grant["aliases"], grant["description"]) == (
        "integer",
        ["grant"],
        "A grant.",
    )
    assert [p["id"] for p in schema.to_dict()["packs"]] == ["grants-x-test", "words-x-test"]
    again = gg.Schema.from_dict(schema.to_dict(), [GRANTS, LAC])
    assert again.to_dict() == schema.to_dict()


def test_a_changed_template_changes_the_schema_digest() -> None:
    other = kind(needs=GRANTS["needs"], fields={"grant": {"type": "integer", "aliases": ["aid"]}})
    a = gg.admit(DOC, KIND_SCHEMA, CANDS, packs=[GRANTS, LAC]).to_dict()
    b = gg.admit(DOC, KIND_SCHEMA, CANDS, packs=[other, LAC]).to_dict()
    assert a["schema_sha256"] != b["schema_sha256"]


def test_the_receipt_names_the_kind_pack_and_the_decision_that_took_its_template() -> None:
    receipt = gg.admit(DOC, KIND_SCHEMA, CANDS, packs=[LAC, GRANTS]).to_dict()
    assert [(p["id"], p["type"]) for p in receipt["packs"]] == [
        ("grants-x-test", "kind"),
        ("words-x-test", "vocabulary"),
    ]
    assert receipt["packs"][0]["sha256"] == pack_digest(GRANTS)
    by_id = {d["candidate_id"]: d["packs"] for d in receipt["decisions"]}
    assert by_id == {"a": ["grants-x-test", "words-x-test"], "b": ["words-x-test"]}


def test_a_kind_pack_with_no_needs_reads_the_base_only() -> None:
    plain = kind(fields={"grant": {"type": "integer"}})
    receipt = gg.admit(DOC, KIND_SCHEMA, CANDS, packs=[plain]).to_dict()
    assert _outcomes(receipt) == {"a": "admitted", "b": "admitted"}
    assert {d["candidate_id"]: d["packs"] for d in receipt["decisions"]} == {
        "a": ["grants-x-test"],
        "b": [],
    }


def test_load_pack_reads_a_kind_pack(tmp_path: Path) -> None:
    f = tmp_path / "grants.json"
    f.write_text(json.dumps(GRANTS), encoding="utf-8")
    assert gg.load_pack(f) == GRANTS
    f.write_text(json.dumps({**GRANTS, "fields": {"grant": {"keys": ["2025"]}}}), encoding="utf-8")
    with pytest.raises(gg.PacketError, match="L9"):
        gg.load_pack(f)


def test_the_digest_of_a_kind_pack_reads_it_after_defaults() -> None:
    assert pack_digest(kind()) == pack_digest(kind(description="", status=[], needs=[], fields={}))
    assert pack_digest(kind()) != pack_digest({**kind(), "type": "vocabulary"})


def test_the_schema_can_pin_a_needed_pack() -> None:
    pin = {"id": "words-x-test", "version": "1.0.0", "sha256": pack_digest(LAC)}
    pinned = {**KIND_SCHEMA, "packs": [*KIND_SCHEMA["packs"], pin]}  # type: ignore[list-item]
    assert gg.admit(DOC, pinned, CANDS, packs=[GRANTS, LAC]).to_dict()["packs"][1] == {
        **pin,
        "type": "vocabulary",
    }
    other = pack(scale={"words": {"lac": 5}}, description="another copy")
    with pytest.raises(gg.PacketError, match="not the pin"):
        gg.admit(DOC, pinned, CANDS, packs=[GRANTS, other])


@pytest.mark.parametrize(
    ("field", "match"),
    [
        ({"template": "grants-x-test/grant", "type": "integer", "unit": "USD"}, "unit differs"),
        ({"template": "grants-x-test/grant", "type": "number"}, "type differs"),
        ({"template": "grants-x-test/fee"}, "no template 'fee'"),
        ({"template": "words-x-test/grant"}, "not a kind pack"),
        ({"template": 7}, "must be"),
    ],
    ids=["unit", "type", "no template", "vocabulary pack", "not a string"],
)
def test_a_template_that_breaks_l10(field: dict[str, Any], match: str) -> None:
    g = kind(needs=GRANTS["needs"], fields={"grant": {"type": "integer", "unit": "EUR"}})
    schema = {**KIND_SCHEMA, "fields": {"grant": field}}
    with pytest.raises(gg.PacketError, match=match):
        gg.Schema.from_dict(schema, [g, LAC])


def test_a_template_has_no_defaults_of_its_own() -> None:
    untyped = kind(needs=GRANTS["needs"], fields={"grant": {"unit": "USD"}})
    schema = gg.Schema.from_dict(KIND_SCHEMA, [untyped, LAC])
    assert schema.to_dict()["fields"]["grant"]["type"] == "number"
    text = {"template": "grants-x-test/grant", "type": "text"}
    typed = {**KIND_SCHEMA, "fields": {"grant": text}}
    with pytest.raises(gg.PacketError, match=r"unknown type 'text'.*\(L10\)"):
        gg.Schema.from_dict(typed, [untyped, LAC])
