"""Source pins (SPEC §4.14, §5; #616)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.cli import main
from groundgate.pin import check_pin, pin_digest, source_digest
from groundgate.store import FolderStore
from groundgate.store.maintain import check, forget_packet
from groundgate.store.packets import admit_packet, load_packet, put_reading

ROOT = Path(__file__).parent.parent
PINS = sorted((ROOT / "conformance" / "pins").glob("*.json"))
TEXT = "Fee\t$90\n"
SCHEMA = {"fields": {"fee": {"type": "integer", "unit": "USD", "aliases": ["Fee"]}}}
CANDS = [{"id": "p1", "field": "fee", "value": 90, "unit": "USD",
          "evidence": [{"start": 4, "end": 7, "text": "$90"},
                       {"role": "field", "start": 0, "end": 3, "text": "Fee"}]}]  # fmt: skip
SOURCE = b"%PDF-1.7 the bytes of the standard\n"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _pin(**over: Any) -> dict[str, Any]:
    return {"groundgate_pin": 1, "source_sha256": source_digest(SOURCE),
            "url": "https://example.org/standard.pdf", "retrieved": "2026-11-09",
            "edition": "2024 revision 2", "origin": "fetched"} | over  # fmt: skip


@pytest.mark.parametrize("path", PINS, ids=lambda p: p.stem)
def test_pin_vector(path: Path) -> None:
    v = _load(path)
    more = {"document_source": v.get("document_source"), "pin": v["pin"]}
    if v["expected"].get("error"):
        with pytest.raises(gg.PacketError):
            gg.admit(v["document"], v["schema"], v["candidates"], **more)
        return
    receipt = gg.admit(v["document"], v["schema"], v["candidates"], **more).to_dict()
    for cand, want in zip(v["candidates"], v["expected"]["decisions"], strict=True):
        got = next(
            d for d in receipt["decisions"] if d["candidate_sha256"] == gg.digest("candidate", cand)
        )
        assert (got["outcome"], got["codes"]) == (want["outcome"], want["codes"])
    assert receipt["pin"] == v["expected"]["pin"]
    assert receipt["pin"]["sha256"] == pin_digest(v["pin"])
    assert gg.verify(receipt, v["document"], v["schema"], v["candidates"], **more).ok


def test_pin_vectors_cover_each_check() -> None:
    checks = {f"S{n}" for n in range(1, 7)}
    found = {c for p in PINS for c in checks if f"({c})" in _load(p)["description"]}
    assert found == checks


def test_a_changed_edition_gives_another_pin_digest() -> None:
    first = _load(ROOT / "conformance" / "pins" / "pin-01-fetched.json")["expected"]["pin"]
    later = _load(ROOT / "conformance" / "pins" / "pin-03-changed-edition.json")["expected"]["pin"]
    assert first["url"] == later["url"] and first["edition"] != later["edition"]
    assert first["sha256"] != later["sha256"]


def test_a_pin_changes_no_decision() -> None:
    pinned = gg.admit(TEXT, SCHEMA, CANDS, pin=_pin()).to_dict()
    plain = gg.admit(TEXT, SCHEMA, CANDS).to_dict()
    assert "pin" not in plain
    body = {k: v for k, v in pinned.items() if k not in ("pin", "receipt_sha256")}
    assert body == {k: v for k, v in plain.items() if k != "receipt_sha256"}
    assert pinned["receipt_sha256"] != plain["receipt_sha256"]
    assert list(pinned).index("pin") == list(pinned).index("packs") + 1


def test_verify_finds_a_changed_or_missing_pin() -> None:
    receipt = gg.admit(TEXT, SCHEMA, CANDS, pin=_pin()).to_dict()
    assert gg.verify(receipt, TEXT, SCHEMA, CANDS, pin=_pin()).ok
    other = gg.verify(receipt, TEXT, SCHEMA, CANDS, pin=_pin(edition="2026 revision 1"))
    assert not other.ok and "pin differs from the re-derived receipt" in other.problems
    assert not gg.verify(receipt, TEXT, SCHEMA, CANDS).ok


@pytest.mark.parametrize(
    "bad",
    [None, [], {"groundgate_pin": True}, _pin(groundgate_pin=1.0), _pin(url=""),
     _pin(url="x" * 2049), _pin(edition="\ud800"), _pin(retrieved=20261109),
     _pin(origin=["fetched"]), _pin(source_sha256=None)],
)  # fmt: skip
def test_a_malformed_pin_is_refused(bad: Any) -> None:
    with pytest.raises(gg.PacketError, match="pin"):
        check_pin(bad)


def test_an_integer_out_of_range_in_a_pin_is_an_invalid_packet() -> None:
    with pytest.raises(gg.PacketError):
        gg.admit(TEXT, SCHEMA, CANDS, pin=_pin(groundgate_pin=2**60))


def _stored(root: Path, source: bytes = TEXT.encode()) -> tuple[FolderStore, str]:
    """A store with a reading of a text file, and a packet whose pin names ``source``."""
    root.mkdir(parents=True)
    path = root / "doc.txt"
    path.write_bytes(TEXT.encode())
    store = FolderStore(root / "store")
    reading, _ = put_reading(store, path)
    pin = _pin(source_sha256=source_digest(source))
    k, _ = admit_packet(store, TEXT, SCHEMA, CANDS, reading=reading, pin=pin)
    return store, k


def test_the_packet_names_the_pin_and_verify_reads_it(tmp_path: Path) -> None:
    store, k = _stored(tmp_path / "s")
    with store:
        packet = load_packet(store, k)
        assert packet.pin == _pin(source_sha256=source_digest(TEXT.encode()))
        assert packet.receipt["pin"]["source_sha256"] == source_digest(TEXT.encode())
        assert gg.verify(packet.receipt, packet.text, packet.schema, packet.candidates,
                         **packet.inputs()).ok  # fmt: skip
        assert check(store).findings == []
        plain, _ = admit_packet(store, TEXT, SCHEMA, CANDS)
        assert plain != k and load_packet(store, plain).pin is None


def test_store_check_finds_a_pin_whose_bytes_do_not_match(tmp_path: Path) -> None:
    store, k = _stored(tmp_path / "s", SOURCE)  # the pin names other bytes than the source
    with store:
        findings = check(store).findings
        assert len(findings) == 1
        assert f"the packet {k}" in findings[0] and "has other bytes" in findings[0]


def test_forget_keeps_the_pin(tmp_path: Path) -> None:
    store, k = _stored(tmp_path / "s")
    with store:
        states = {kind: state for kind, _, state, _ in forget_packet(store, k, "test")}
        assert states["source@1"] == "deleted" and "pin@1" not in states
        assert check(store).findings == []  # no bytes to compare after forget


def test_the_commands_pin_a_source_and_admit_with_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "standard.pdf"
    source.write_bytes(SOURCE)
    root = str(tmp_path / "s")
    assert main(["store", "pin", "--store", root, str(source), "--origin", "supplied",
                 "--retrieved", "2026-11-10", "--label", "unofficial copy"]) == 0  # fmt: skip
    pin = json.loads(capsys.readouterr().out)
    assert pin == {"groundgate_pin": 1, "source_sha256": source_digest(SOURCE), "url": None,
                   "retrieved": "2026-11-10", "edition": None, "origin": "supplied",
                   "label": "unofficial copy"}  # fmt: skip
    assert main(["store", "pin", "--store", root, str(source), "--origin", "fetched",
                 "--retrieved", "2026-11-10"]) == 2  # fmt: skip
    assert "a fetched pin must give the url" in capsys.readouterr().err
    written = {"doc.txt": TEXT, "schema.json": json.dumps(SCHEMA),
               "cands.json": json.dumps(CANDS), "pin.json": json.dumps(pin)}  # fmt: skip
    for name, value in written.items():
        (tmp_path / name).write_text(value, encoding="utf-8")
    files = [str(tmp_path / n) for n in ("doc.txt", "schema.json", "cands.json")]
    assert main(["admit", *files, "--pin", str(tmp_path / "pin.json"), "--store", root]) == 0
    k = capsys.readouterr().out.strip()
    assert main(["verify", "--store", root, k]) == 0
    with FolderStore(Path(root)) as store:
        assert load_packet(store, k).receipt["pin"]["label"] == "unofficial copy"
