"""The completeness of a reading (SPEC §4.16, §5, §5.1; #615)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.cli import main
from groundgate.completeness import completeness_of
from groundgate.read import read
from groundgate.read.document import read_document
from groundgate.store import FolderStore
from groundgate.store.export import admitted_facts
from groundgate.store.maintain import check, forget_packet
from groundgate.store.packets import admit_packet, load_packet, load_reading, put_reading

from pdfgen import make_pdf, make_scan

TEXT = "Annual fee: $90\n"
SCHEMA = {"fields": {"fee": {"type": "integer", "unit": "USD", "aliases": ["Annual fee"]}}}
FOUND = {"id": "a", "field": "fee", "value": 90, "unit": "USD", "evidence": [{"text": "$90"}]}
GONE = {"id": "b", "field": "fee", "value": 95, "unit": "USD", "evidence": [{"text": "$95"}]}
PARTIAL = {"status": "partial", "missing": [{"page": 2, "reason": "ocr_off"}]}
COMPLETE = {"status": "complete", "missing": []}


def _codes(receipt: dict[str, Any]) -> dict[str, list[str]]:
    by_sha = {d["candidate_sha256"]: d["codes"] for d in receipt["decisions"]}
    return {c["id"]: by_sha[gg.digest("candidate", c)] for c in (FOUND, GONE)}


def test_a_packet_with_no_completeness_keeps_its_receipt() -> None:
    plain = gg.admit(TEXT, SCHEMA, [FOUND, GONE]).to_dict()
    assert "completeness" not in plain
    assert _codes(plain)["b"] == ["QUOTE_NOT_FOUND"]
    full = gg.admit(TEXT, SCHEMA, [FOUND, GONE], completeness=COMPLETE).to_dict()
    assert full["completeness"] == COMPLETE
    assert full["decisions"] == plain["decisions"]
    assert full["receipt_sha256"] != plain["receipt_sha256"]


def test_a_partial_reading_changes_only_the_code_of_a_quote_that_is_not_found() -> None:
    plain = gg.admit(TEXT, SCHEMA, [FOUND, GONE]).to_dict()
    partial = gg.admit(TEXT, SCHEMA, [FOUND, GONE], completeness=PARTIAL).to_dict()
    assert partial["completeness"] == PARTIAL
    assert _codes(partial) == {"a": _codes(plain)["a"], "b": ["SOURCE_NOT_READ"]}
    assert partial["summary"] == plain["summary"]
    assert gg.verify(partial, TEXT, SCHEMA, [FOUND, GONE], completeness=PARTIAL).ok
    for other in (None, COMPLETE):
        result = gg.verify(partial, TEXT, SCHEMA, [FOUND, GONE], completeness=other)
        assert "completeness differs from the re-derived receipt" in result.problems


def test_the_receipt_does_not_share_the_list_of_the_caller() -> None:
    given = json.loads(json.dumps(PARTIAL))
    receipt = gg.admit(TEXT, SCHEMA, [], completeness=given)
    given["missing"].append({"page": 9, "reason": "ocr_off"})
    assert receipt.to_dict()["completeness"] == PARTIAL


def test_a_float_page_is_refused() -> None:
    with pytest.raises(gg.PacketError):
        bad = {"status": "partial", "missing": [{"page": 2.0, "reason": "ocr_off"}]}
        gg.admit(TEXT, SCHEMA, [], completeness=bad)


def test_completeness_of_gives_the_status_and_the_pages_in_order() -> None:
    assert completeness_of("a") == COMPLETE
    assert completeness_of(" \n\t") == {"status": "no_text", "missing": []}
    assert completeness_of("a", [(3, "ocr_off"), (1, "no_text_layer")]) == {
        "status": "partial",
        "missing": [{"page": 1, "reason": "no_text_layer"}, {"page": 3, "reason": "ocr_off"}],
    }


# The reader


def test_a_text_file_is_complete_and_a_file_with_no_text_has_no_text(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Fee: $90\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text(" \n", encoding="utf-8")
    assert read(tmp_path / "a.txt").completeness == COMPLETE
    assert read(tmp_path / "b.txt").completeness == {"status": "no_text", "missing": []}
    doc, _ = read_document(tmp_path / "a.txt")
    assert doc.completeness == COMPLETE


def test_a_pdf_with_text_on_each_page_is_complete(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf([[(72, 720, "Annual fee: $90")], [(72, 720, "Terms")]]))
    assert read(path).completeness == COMPLETE


def test_a_page_with_no_marks_is_not_missing(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf([[(72, 720, "Annual fee: $90")], []]))
    doc = read(path)
    assert doc.completeness == COMPLETE
    assert any("page 2 has no text layer" in w for w in doc.warnings)  # the warning stays


RULE = b"72 700 m 300 700 l S\n"  # one line across the page


def test_a_page_with_marks_and_no_text_makes_the_reading_partial(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf([[(72, 720, "Annual fee: $90")], []], drawings=[b"", RULE]))
    want = {"status": "partial", "missing": [{"page": 2, "reason": "no_text_layer"}]}
    assert read(path).completeness == want
    assert read_document(path)[0].completeness == want
    assert read(path, [1]).completeness == COMPLETE  # a page selection is not a missing part


def test_a_scan_with_ocr_off_has_no_text_and_names_each_image_page(tmp_path: Path) -> None:
    gray = (40, 20, b"\xff" * 800)
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_scan([gray, None, gray]))
    assert read(path).completeness == {
        "status": "no_text",
        "missing": [{"page": 1, "reason": "ocr_off"}, {"page": 3, "reason": "ocr_off"}],
    }


# The store and the commands


def _files(tmp_path: Path, text: str) -> list[str]:
    for name, value in (("doc.txt", text), ("schema.json", json.dumps(SCHEMA)),
                        ("cands.json", json.dumps([FOUND, GONE]))):  # fmt: skip
        (tmp_path / name).write_text(value, encoding="utf-8")
    return [str(tmp_path / n) for n in ("doc.txt", "schema.json", "cands.json")]


def test_the_store_keeps_the_completeness_of_the_reading_and_of_the_packet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(make_pdf([[(72, 720, "Annual fee: $90")], []], drawings=[b"", RULE]))
    want = {"status": "partial", "missing": [{"page": 2, "reason": "no_text_layer"}]}
    root = str(tmp_path / "s")
    with FolderStore(Path(root)) as store:
        reading, doc = put_reading(store, pdf)
        assert load_reading(store, reading)["completeness"] == want
        again, cached = put_reading(store, pdf)  # the cache gives the same completeness
        assert again == reading and cached.completeness == want
        k, receipt = admit_packet(store, doc.text, SCHEMA, [FOUND, GONE], reading=reading,
                                  completeness=doc.completeness)  # fmt: skip
        assert _codes(receipt.to_dict())["b"] == ["SOURCE_NOT_READ"]
        packet = load_packet(store, k)
        assert packet.completeness == want
        assert gg.verify(packet.receipt, packet.text, packet.schema, packet.candidates,
                         **packet.inputs()).ok  # fmt: skip
        export = admitted_facts(store, packet)
        assert export["completeness"] == want and list(export)[-1] == "completeness"
        plain, _ = admit_packet(store, doc.text, SCHEMA, [FOUND, GONE], reading=reading)
        assert plain != k
        assert "completeness" not in admitted_facts(store, load_packet(store, plain))
        assert check(store).findings == []
    # the command takes the completeness from the reading
    files = _files(tmp_path, doc.text)
    assert main(["admit", *files, "--store", root, "--reading", reading]) == 0
    assert capsys.readouterr().out.strip() == k
    assert main(["verify", "--store", root, k]) == 0
    capsys.readouterr()
    assert main(["export", "--store", root, k]) == 0
    assert json.loads(capsys.readouterr().out)["completeness"] == want
    assert main(["report", "--store", root, k, "-o", str(tmp_path / "r.html")]) == 0
    page = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "reading: partial · pages with no text: 2 (no_text_layer)" in page
    with FolderStore(Path(root)) as store:
        states = {kind: state for kind, _, state, _ in forget_packet(store, k, "test")}
        assert "completeness@1" not in states or states["completeness@1"] != "deleted"


def test_the_commands_pass_the_completeness_without_a_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(make_pdf([[(72, 720, "Annual fee: $90")], []], drawings=[b"", RULE]))
    done = str(tmp_path / "completeness.json")
    assert main(["read", str(pdf), "-o", str(tmp_path / "doc.txt"), "--completeness", done]) == 0
    assert json.loads(Path(done).read_text(encoding="utf-8"))["status"] == "partial"
    files = _files(tmp_path, (tmp_path / "doc.txt").read_text(encoding="utf-8"))
    out = str(tmp_path / "receipt.json")
    assert main(["admit", *files, "--completeness", done, "-o", out]) == 0
    receipt = json.loads(Path(out).read_text(encoding="utf-8"))
    assert _codes(receipt)["b"] == ["SOURCE_NOT_READ"]
    assert main(["verify", out, *files, "--completeness", done]) == 0
    assert main(["verify", out, *files]) == 1
    capsys.readouterr()
    assert (
        main(["report", out, *files, "--completeness", done, "-o", str(tmp_path / "r.html")]) == 0
    )
    assert "reading: partial" in (tmp_path / "r.html").read_text(encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"status": "complete", "missing": [1]}', encoding="utf-8")
    assert main(["admit", *files, "--completeness", str(tmp_path / "bad.json")]) == 2
    assert "completeness" in capsys.readouterr().err


def test_a_reading_of_an_older_version_has_no_completeness_and_never_hits_the_cache(
    tmp_path: Path,
) -> None:
    from groundgate.canonical import jcs
    from groundgate.store.maintain import rebuild

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(make_pdf([[(72, 720, "Annual fee: $90")]]))
    with FolderStore(tmp_path / "s") as store:
        k, _ = put_reading(store, pdf)
        obj = json.loads(store.get("reading@2", k))
        del obj["completeness"]
        old = store.put("reading@2", jcs(obj).encode())
        assert "completeness" not in load_reading(store, old)  # the store still reads it
        store.forget(k, "test")
        rebuild(store)
        again, doc = put_reading(store, pdf)  # a miss: read runs again
        assert again == k and doc.completeness == COMPLETE
        assert check(store).findings == []
