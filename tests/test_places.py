"""Places and locators (SPEC §4.15, §5, §5.1; #614)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.cli import main
from groundgate.places import MAX_COORDINATE, layout_places
from groundgate.read import read
from groundgate.store import FolderStore
from groundgate.store.export import admitted_facts
from groundgate.store.maintain import check, forget_packet
from groundgate.store.packets import admit_packet, load_packet, put_reading

from pdfgen import make_pdf

ROOT = Path(__file__).parent.parent
PLACES = sorted((ROOT / "conformance" / "places").glob("*.json"))
TEXT = "Fee\t$90\n"
SCHEMA = {"fields": {"fee": {"type": "integer", "unit": "USD", "aliases": ["Fee"]}}}
CANDS = [{"id": "p1", "field": "fee", "value": 90, "unit": "USD",
          "evidence": [{"start": 4, "end": 7, "text": "$90"},
                       {"role": "field", "start": 0, "end": 3, "text": "Fee"}]}]  # fmt: skip
WORDS = [[0, 3, 1, 7200, 10000, 9000, 11200], [4, 7, 1, 10000, 10000, 12050, 11200]]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.mark.parametrize("path", PLACES, ids=lambda p: p.stem)
def test_places_vector(path: Path) -> None:
    v = _load(path)
    more = {"doubt": v.get("doubt"), "places": v["places"]}
    if v["expected"].get("error"):
        with pytest.raises(gg.PacketError, match="places"):
            gg.admit(v["document"], v["schema"], v["candidates"], **more)
        return
    receipt = gg.admit(v["document"], v["schema"], v["candidates"], **more).to_dict()
    for cand, want in zip(v["candidates"], v["expected"]["decisions"], strict=True):
        got = next(
            d for d in receipt["decisions"] if d["candidate_sha256"] == gg.digest("candidate", cand)
        )
        assert (got["outcome"], got["codes"]) == (want["outcome"], want["codes"])
        assert got["locator"] == want["locator"]
        assert list(got)[-1] == "locator"
    assert receipt["places_sha256"] == v["expected"]["places_sha256"]
    assert gg.verify(receipt, v["document"], v["schema"], v["candidates"], **more).ok


def test_the_vectors_cover_digital_text_and_ocr_text() -> None:
    text = " ".join(_load(p)["description"] for p in PLACES)
    assert "Digital text" in text and "OCR text" in text


def test_places_change_no_outcome_and_no_other_member() -> None:
    placed = gg.admit(TEXT, SCHEMA, CANDS, places=WORDS).to_dict()
    plain = gg.admit(TEXT, SCHEMA, CANDS).to_dict()
    assert "places_sha256" not in plain and "locator" not in plain["decisions"][0]
    for d in placed["decisions"]:
        del d["locator"]
    body = {k: v for k, v in placed.items() if k not in ("places_sha256", "receipt_sha256")}
    assert body == {k: v for k, v in plain.items() if k != "receipt_sha256"}
    assert placed["receipt_sha256"] != plain["receipt_sha256"]


def test_verify_finds_changed_places() -> None:
    receipt = gg.admit(TEXT, SCHEMA, CANDS, places=WORDS).to_dict()
    moved = [WORDS[0], [4, 7, 1, 10000, 10000, 12051, 11200]]
    result = gg.verify(receipt, TEXT, SCHEMA, CANDS, places=moved)
    assert not result.ok and "places_sha256 differs from the re-derived receipt" in result.problems
    assert not gg.verify(receipt, TEXT, SCHEMA, CANDS).ok


def test_a_reference_decision_has_a_null_locator() -> None:
    refs = [{"id": "r", "text": "Fee\t$90\n"}]
    cand = {"id": "c", "field": "fee", "value": 90, "unit": "USD",
            "evidence": [{"source": "reference", "ref": "r", "start": 4, "end": 7, "text": "$90"},
                         {"source": "reference", "ref": "r", "role": "field", "start": 0, "end": 3,
                          "text": "Fee"}]}  # fmt: skip
    (d,) = gg.admit("Other text.\n", SCHEMA, [cand], references=refs,
                    places=[[0, 5, 1, 0, 0, 100, 100]]).to_dict()["decisions"]  # fmt: skip
    assert d["source"] == "reference" and d["locator"] is None


@pytest.mark.parametrize(
    "bad",
    ["[]", [[0, 3, 1, 0, 0, 1]], [[0, 3, 1, 0, 0, 1, MAX_COORDINATE + 1]], [[0, 3, 1, -1, 0, 1, 1]],
     [["0", 3, 1, 0, 0, 1, 1]], [[3, 3, 1, 0, 0, 1, 1]], [[0, 3, 1, 0, 5, 1, 4]], [None]],
)  # fmt: skip
def test_malformed_places_are_refused(bad: Any) -> None:
    with pytest.raises(gg.PacketError, match="places"):
        gg.admit(TEXT, SCHEMA, CANDS, places=bad)


def test_a_place_inside_a_character_is_refused() -> None:
    with pytest.raises(gg.PacketError, match="valid span"):
        gg.admit("Café\t$90\n", SCHEMA, [], places=[[0, 4, 1, 0, 0, 1, 1]])


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "sheet.pdf"
    lines = [(72, 720, "Datasheet"), (72, 690, "Fee $90 per year.")]
    path.write_bytes(make_pdf([[(72, 720, "Cover")], lines]))
    return path


FEE_SCHEMA = {"fields": {"fee": {"type": "integer", "unit": "USD", "aliases": ["Fee"]}}}


def _fee(text: str) -> list[dict[str, Any]]:
    raw = text.encode()
    at, name = raw.index(b"$90"), raw.index(b"Fee")
    value = {"start": at, "end": at + 3, "text": "$90"}
    field = {"role": "field", "start": name, "end": name + 3, "text": "Fee"}
    return [{"id": "c", "field": "fee", "value": 90, "unit": "USD", "evidence": [value, field]}]


def test_a_digital_pdf_gives_the_page_and_the_box_of_a_value(pdf: Path) -> None:
    doc = read(pdf)
    assert doc.layout is not None
    places = layout_places(doc.layout)
    assert places and all(type(v) is int for p in places for v in p)
    (d,) = gg.admit(doc.text, FEE_SCHEMA, _fee(doc.text), places=places).to_dict()["decisions"]
    at = doc.text.encode().index(b"$90")
    (box,) = doc.layout.locate(at, at + 3)
    assert d["outcome"] == "admitted"
    assert d["locator"] == {
        "page": 2,
        "box": [round(v * 100) for v in (box.x0, box.top, box.x1, box.bottom)],
    }


def test_the_store_keeps_the_places_and_the_export_gives_the_locator(
    pdf: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path / "s")
    with FolderStore(Path(root)) as store:
        reading, doc = put_reading(store, pdf)
        assert doc.layout is not None
        places = layout_places(doc.layout)
        k, receipt = admit_packet(store, doc.text, FEE_SCHEMA, _fee(doc.text), reading=reading,
                                  places=places)  # fmt: skip
        packet = load_packet(store, k)
        assert packet.places == places
        assert gg.verify(packet.receipt, packet.text, packet.schema, packet.candidates,
                         **packet.inputs()).ok  # fmt: skip
        (fact,) = admitted_facts(store, packet)["facts"]
        assert fact["citation"]["locator"] == receipt.to_dict()["decisions"][0]["locator"]
        assert list(fact["citation"])[-1] == "locator"
        plain, _ = admit_packet(store, doc.text, FEE_SCHEMA, _fee(doc.text), reading=reading)
        (old,) = admitted_facts(store, load_packet(store, plain))["facts"]
        assert "locator" not in old["citation"]  # a fact with no locator keeps its bytes
        assert check(store).findings == []
    # the commands: --locate takes the places from the layout of the reading
    for name, value in (("doc.txt", doc.text), ("schema.json", json.dumps(FEE_SCHEMA)),
                        ("cands.json", json.dumps(_fee(doc.text)))):  # fmt: skip
        (tmp_path / name).write_text(value, encoding="utf-8")
    files = [str(tmp_path / n) for n in ("doc.txt", "schema.json", "cands.json")]
    assert main(["admit", *files, "--store", root, "--reading", reading, "--locate"]) == 0
    assert capsys.readouterr().out.strip() == k
    assert main(["export", "--store", root, k]) == 0
    assert json.loads(capsys.readouterr().out)["facts"][0]["citation"]["locator"]["page"] == 2
    assert main(["report", "--store", root, k, "-o", str(tmp_path / "r.html")]) == 0
    with FolderStore(Path(root)) as store:
        states = {kind: state for kind, _, state, _ in forget_packet(store, k, "test")}
        assert states["places@1"] == "deleted"


def test_the_layout_option_gives_the_locator_without_a_store(
    pdf: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = read(pdf)
    assert doc.layout is not None
    written = {"doc.txt": doc.text, "schema.json": json.dumps(FEE_SCHEMA),
               "cands.json": json.dumps(_fee(doc.text)),
               "layout.json": json.dumps(doc.layout.to_dict())}  # fmt: skip
    for name, value in written.items():
        (tmp_path / name).write_text(value, encoding="utf-8")
    files = [str(tmp_path / n) for n in ("doc.txt", "schema.json", "cands.json")]
    layout = ["--layout", str(tmp_path / "layout.json")]
    out = str(tmp_path / "receipt.json")
    assert main(["admit", *files, *layout, "-o", out]) == 0
    assert _load(Path(out))["decisions"][0]["locator"]["page"] == 2
    assert main(["verify", out, *files, *layout]) == 0
    assert main(["verify", out, *files]) == 1
    capsys.readouterr()
    assert main(["report", out, *files, *layout, "-o", str(tmp_path / "r.html")]) == 0
    box = _load(Path(out))["decisions"][0]["locator"]["box"]
    shown = ", ".join(f"{v // 100}.{v % 100:02d}" for v in box)
    assert f"page 2 · box {shown} pt" in (tmp_path / "r.html").read_text(encoding="utf-8")
    (tmp_path / "other.txt").write_text("Other.\n", encoding="utf-8")
    assert main(["admit", str(tmp_path / "other.txt"), *files[1:], *layout]) == 2
    assert capsys.readouterr().err
