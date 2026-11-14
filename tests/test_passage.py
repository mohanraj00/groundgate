"""Passages (SPEC §4.17, §5, §5.1; #638)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.canonical import Offsets
from groundgate.cli import main
from groundgate.passage import MAX_LEVEL, Outline, document_outline, has_label, label_words
from groundgate.read.document import read_document
from groundgate.store import FolderStore
from groundgate.store.export import admitted_facts
from groundgate.store.maintain import check, forget_packet
from groundgate.store.packets import admit_packet, load_packet, put_reading

HTML = (
    "<html><body><h1>4 Payment</h1><h2>4.1 Rent</h2><p>The rent is $900.</p>"
    "<h2>4.2 Café fees</h2><p>The late fee is $25.</p><h3>4.2.1 Waiver</h3>"
    "<p>The owner can waive the fee.</p><h1>5 Term</h1><p>The term is 12 months.</p>"
    "</body></html>"
)
SCHEMA = {"fields": {"section": {"type": "passage", "multiple": True}}}


def _read(tmp_path: Path) -> tuple[str, list[dict[str, int]]]:
    path = tmp_path / "lease.html"
    path.write_text(HTML, encoding="utf-8")
    extracted, document = read_document(path)
    return extracted.text, document_outline(document)


def _section(text: str, outline: list[dict[str, int]], heading: str) -> dict[str, int]:
    """The span of the section of ``heading``, from the rule of ``Document.section``."""
    data = text.encode("utf-8")
    at = data.index(heading.encode("utf-8"))
    (entry,) = [e for e in outline if e["start"] == at]
    limit = len(data)
    for e in outline:
        if e["start"] > at and e["level"] <= entry["level"]:
            limit = e["start"]
            break
    body = data[at:limit].decode("utf-8").rstrip()
    return {"start": at, "end": at + len(body.encode("utf-8"))}


def _cand(cid: str, label: str, span: dict[str, int], **more: Any) -> dict[str, Any]:
    return {"id": cid, "field": "section", "value": label, "evidence": [{**span, **more}]}


def test_the_reader_gives_the_outline_and_the_gate_admits_each_section(tmp_path: Path) -> None:
    text, outline = _read(tmp_path)
    assert [e["level"] for e in outline] == [1, 2, 2, 3, 1]
    cands = [
        _cand("a", "4.2", _section(text, outline, "4.2 Café fees")),
        _cand("b", "4", _section(text, outline, "4 Payment")),
        _cand("c", "5", _section(text, outline, "5 Term")),
    ]
    receipt = gg.admit(text, SCHEMA, cands, outline=outline).to_dict()
    assert [d["outcome"] for d in receipt["decisions"]] == ["admitted"] * 3
    assert receipt["outline_sha256"] == gg.digest("outline", {"outline": outline})
    by_id = {d["candidate_id"]: d for d in receipt["decisions"]}
    span = by_id["a"]["evidence"]
    passage = text.encode("utf-8")[span["start"] : span["end"]].decode("utf-8")
    assert passage.startswith("4.2 Café fees") and passage.endswith("The owner can waive the fee.")
    assert by_id["a"]["passage_sha256"] == gg.digest("passage", {"text": passage})
    assert by_id["a"]["value"] == "4.2" and by_id["a"]["parts"] == []
    assert gg.verify(receipt, text, SCHEMA, cands, outline=outline).ok
    assert not gg.verify(receipt, text, SCHEMA, cands).ok
    moved = [dict(e) for e in outline]
    moved[-1]["level"] = 3  # then section 4 runs to the end of the document
    assert not gg.verify(receipt, text, SCHEMA, cands, outline=moved).ok


def test_a_span_after_a_character_of_two_bytes_is_compared_in_bytes(tmp_path: Path) -> None:
    text, outline = _read(tmp_path)
    span = _section(text, outline, "4.2 Café fees")
    short = {"start": span["start"], "end": span["end"] - 1}
    codes = [
        gg.admit(text, SCHEMA, [_cand("a", "4.2", s)], outline=outline).to_dict()["decisions"][0]
        for s in (short, {"start": span["start"], "end": span["end"] + 1})
    ]
    assert [d["codes"] for d in codes] == [["PASSAGE_CUT_SHORT"], ["PASSAGE_OVERRUN"]]
    assert all(d["passage_sha256"] is None and d["outcome"] == "rejected" for d in codes)


def test_a_passage_schema_with_defaults_is_valid_again() -> None:
    schema = gg.Schema.from_dict(SCHEMA)
    assert schema.copy().to_dict() == schema.to_dict()
    assert gg.Schema.from_dict(schema.to_dict()).to_dict() == schema.to_dict()
    for bad in ({"unit": "USD"}, {"comparator": "ge"}, {"formats": ["%Y"]}):
        with pytest.raises(gg.PacketError, match="passage field"):
            gg.Schema.from_dict({"fields": {"section": {"type": "passage", **bad}}})


def test_a_receipt_with_no_passage_field_keeps_its_bytes() -> None:
    schema = {"fields": {"fee": {"type": "integer", "unit": "USD"}}}
    cand = {"id": "a", "field": "fee", "value": 90, "unit": "USD", "evidence": [{"text": "$90"}]}
    plain = gg.admit("Fee: $90\n", schema, [cand]).to_dict()
    assert "outline_sha256" not in plain and "passage_sha256" not in plain["decisions"][0]
    with_outline = gg.admit("Fee: $90\n", schema, [cand],
                            outline=[{"start": 0, "end": 3, "level": 1}]).to_dict()  # fmt: skip
    assert with_outline["decisions"] == plain["decisions"]
    assert with_outline["outline_sha256"] != plain.get("outline_sha256")


def test_a_passage_takes_the_flags_of_each_field(tmp_path: Path) -> None:
    text, outline = _read(tmp_path)
    span = _section(text, outline, "5 Term")
    single = {"fields": {"section": {"type": "passage"}}}
    cands = [_cand("a", "5", span), _cand("b", "Term", span, text="5 Term")]
    got = {d["candidate_id"]: d for d in
           gg.admit(text, single, cands, outline=outline).to_dict()["decisions"]}  # fmt: skip
    assert got["a"]["codes"] == ["CONFLICTING_CANDIDATES"]
    assert got["b"]["codes"] == ["NON_VERBATIM_EVIDENCE", "CONFLICTING_CANDIDATES"]
    doubt = [{"start": span["start"], "end": span["start"] + 1, "confidence": 0.2}]
    policy = {"min_read_confidence": 0.5}
    (d,) = gg.admit(text, single, cands[:1], policy, outline=outline, doubt=doubt).to_dict()[
        "decisions"
    ]
    assert d["outcome"] == "needs_verification" and d["codes"] == ["READ_DOUBT"]
    assert d["passage_sha256"] is not None


@pytest.mark.parametrize(
    ("heading", "label", "want"),
    [
        ("4.2 Fees", "4.2", True),
        ("Section 4.2. Fees", "4.2", True),
        ("§4.2 Fees", "4.2", True),
        ("§ 4.2 Fees", "§4.2", True),
        ("(a) Notice", "a", True),
        ("ARTICLE IV: TERM", "article iv", True),
        ("4.2.1 Late fees", "4.2", False),
        ("14.2 Fees", "4.2", False),
        ("Article 2 Fees", "Fees", False),
        ("4.2 Fees", "", False),
        ("4.2 Fees", "§", False),
        ("", "4.2", False),
    ],
)
def test_has_label(heading: str, label: str, want: bool) -> None:
    assert has_label(heading, label) is want


def test_label_words_fold_each_letter_and_drop_empty_words() -> None:
    assert label_words("  § 4.2.  (Fees):  ") == ["4.2", "fees"]


def test_the_outline_gives_each_limit_in_one_pass() -> None:
    text = "A\nb\nB\nc\nC\n"
    entries = [{"start": 0, "end": 1, "level": 2}, {"start": 4, "end": 5, "level": 3},
               {"start": 8, "end": 9, "level": 1}]  # fmt: skip
    outline = Outline(text, Offsets(text), entries)
    assert [outline.section_end(i) for i in range(3)] == [7, 7, 9]
    assert outline.heading(4) == 1 and outline.heading(5) is None
    assert MAX_LEVEL == 6


def test_the_store_the_export_and_the_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text, outline = _read(tmp_path)
    cands = [_cand("a", "4.2", _section(text, outline, "4.2 Café fees"))]
    root = str(tmp_path / "s")
    with FolderStore(Path(root)) as store:
        reading, _ = put_reading(store, tmp_path / "lease.html", document=True)
        k, receipt = admit_packet(store, text, SCHEMA, cands, reading=reading, outline=outline)
        packet = load_packet(store, k)
        assert packet.outline == outline
        assert gg.verify(packet.receipt, packet.text, packet.schema, packet.candidates,
                         **packet.inputs()).ok  # fmt: skip
        (fact,) = admitted_facts(store, packet)["facts"]
        decision = receipt.to_dict()["decisions"][0]
        assert fact["value"] == "4.2" and fact["citation"]["span"] == decision["evidence"]
        assert fact["citation"]["passage_sha256"] == decision["passage_sha256"]
        assert check(store).findings == []
    files = []
    for name, value in (("doc.txt", text), ("schema.json", json.dumps(SCHEMA)),
                        ("cands.json", json.dumps(cands))):  # fmt: skip
        (tmp_path / name).write_text(value, encoding="utf-8")
        files.append(str(tmp_path / name))
    # with a passage field, the command takes the outline from the document model of the reading
    assert main(["admit", *files, "--store", root, "--reading", reading]) == 0
    with FolderStore(Path(root)) as store:
        again = load_packet(store, capsys.readouterr().out.strip())
        assert again.outline == outline
        assert again.receipt["decisions"][0]["outcome"] == "admitted"
        states = {kind: state for kind, _, state, _ in forget_packet(store, k, "test")}
        assert states.get("outline@1") != "deleted"
    # without a store: the outline as a list, or as the document model of read --document
    (tmp_path / "outline.json").write_text(json.dumps(outline), encoding="utf-8")
    model = str(tmp_path / "model.json")
    assert main(["read", str(tmp_path / "lease.html"), "--document", model,
                 "-o", str(tmp_path / "again.txt")]) == 0  # fmt: skip
    out = str(tmp_path / "receipt.json")
    for given in (str(tmp_path / "outline.json"), model):
        assert main(["admit", *files, "--outline", given, "-o", out]) == 0
        got = json.loads(Path(out).read_text(encoding="utf-8"))
        assert got["decisions"][0]["outcome"] == "admitted"
        assert main(["verify", out, *files, "--outline", given]) == 0
    assert main(["verify", out, *files]) == 1
    assert main(["admit", *files, "-o", out]) == 0  # no outline: no heading
    got = json.loads(Path(out).read_text(encoding="utf-8"))
    assert got["decisions"][0]["codes"] == ["PASSAGE_NOT_AT_HEADING"]
    capsys.readouterr()
    (tmp_path / "other.txt").write_text("Other text.\n", encoding="utf-8")
    assert main(["admit", str(tmp_path / "other.txt"), *files[1:], "--outline", model]) == 2
    assert "--outline" in capsys.readouterr().err


PAGED = "1 Scope\nOne flat.\n\n2 Rent\nThe rent is $900.\nDue on day 1.\n\n3 Term\n12 months.\n"
PAGED_OUTLINE = [{"start": 0, "end": 7, "level": 1}, {"start": 19, "end": 25, "level": 1},
                 {"start": 59, "end": 65, "level": 1}]  # fmt: skip
# Section 2 has the word Rent on page 1 and the word Due on page 3.
PAGED_WORDS = [[2, 7, 1, 0, 0, 10, 10], [21, 25, 1, 0, 20, 10, 30], [44, 47, 3, 0, 0, 10, 10],
               [61, 65, 3, 0, 20, 10, 30]]  # fmt: skip
PAGED_SPANS = {"1": (0, 17), "2": (19, 57), "3": (59, 76)}


def _paged(missing: list[int], places: list[list[int]] | None) -> dict[str, list[str]]:
    """The codes of each section of PAGED, with ``missing`` pages that gave no text."""
    cands = [_cand(label, label, {"start": a, "end": b}) for label, (a, b) in PAGED_SPANS.items()]
    read = {"status": "partial" if missing else "complete",
            "missing": [{"page": p, "reason": "ocr_off"} for p in missing]}  # fmt: skip
    more: dict[str, Any] = {"outline": PAGED_OUTLINE, "completeness": read, "places": places}
    receipt = gg.admit(PAGED, SCHEMA, cands, **more)
    assert gg.verify(receipt.to_dict(), PAGED, SCHEMA, cands, **more).ok
    return {d.value: list(d.codes) for d in receipt.decisions}


def test_a_passage_with_a_page_not_read_inside_goes_to_review() -> None:
    """#672: the places say which sections can have a part on a page that gave no text."""
    flag = ["PASSAGE_NOT_READ"]
    assert _paged([2], PAGED_WORDS) == {"1": [], "2": flag, "3": []}
    assert _paged([4], PAGED_WORDS) == {"1": [], "2": [], "3": flag}
    assert _paged([2, 4], PAGED_WORDS) == {"1": [], "2": flag, "3": flag}
    assert _paged([], PAGED_WORDS) == {"1": [], "2": [], "3": []}


def test_a_passage_of_a_partial_reading_with_no_places_goes_to_review() -> None:
    flag = ["PASSAGE_NOT_READ"]
    assert _paged([2], None) == {"1": flag, "2": flag, "3": flag}
    assert _paged([2], []) == {"1": flag, "2": flag, "3": flag}
    assert _paged([2], PAGED_WORDS[1:]) == {"1": flag, "2": flag, "3": []}
    assert _paged([], None) == {"1": [], "2": [], "3": []}


def test_a_passage_with_the_flag_is_not_an_admitted_fact() -> None:
    cands = [_cand("a", "2", {"start": 19, "end": 57})]
    read = {"status": "partial", "missing": [{"page": 2, "reason": "ocr_off"}]}
    receipt = gg.admit(PAGED, SCHEMA, cands, outline=PAGED_OUTLINE, completeness=read)
    (d,) = receipt.to_dict()["decisions"]
    assert d["outcome"] == "needs_verification" and d["passage_sha256"] is not None
