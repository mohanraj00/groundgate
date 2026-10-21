"""The splits log of #383 (store.md §10): the view, the writer, store check and calibrate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from groundgate.calibrate import cli
from groundgate.cli import main
from groundgate.store import FolderStore, key, set_key
from groundgate.store.maintain import check
from groundgate.store.splits import read_split, write_split

A, B = "sha256:" + "a" * 64, "sha256:" + "b" * 64
TEXT = "Revenue was 4,100 in fiscal 2025.\n"
SCHEMA = {"fields": {"revenue": {"type": "number", "keys": ["fiscal 2025", "fiscal 2024"]}}}


def text(n: int, same: bool) -> str:
    return TEXT if same else TEXT + f"Note {n}.\n"


def _sample(tmp: Path, work: Path, names: list[str], *, same: bool = False) -> None:
    """Sample the key question on one document for each name. Each candidate has the key
    fiscal 2024, so it is flagged and is an item."""
    d, c = tmp / "docs", tmp / "cands"
    d.mkdir()
    c.mkdir()
    for n, name in enumerate(names):
        (d / f"{name}.txt").write_text(text(n, same), encoding="utf-8")
        start = TEXT.index("4,100")
        cand = {"field": "revenue", "value": "4100", "key": "fiscal 2024",
                "evidence": {"start": start, "end": start + 5}}  # fmt: skip
        (c / f"{name}.json").write_text(json.dumps([cand]), encoding="utf-8")
    (tmp / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    cli.main(["sample", "--work", str(work), "--docs", str(d), "--candidates", str(c),
              "--schema", str(tmp / "schema.json"), "--question", "key"])  # fmt: skip


def test_write_split_adds_each_document_once(tmp_path: Path) -> None:
    with FolderStore(tmp_path / "s") as s:
        assert read_split(s, "set-a") == {}
        assert write_split(s, "set-a", {B: "held-out", A: "development"}) == 2
        assert write_split(s, "set-a", {A: "development"}) == 0
        assert read_split(s, "set-a") == {A: "development", B: "held-out"}
        records = s.read(("splits", set_key("set-a")))
    assert [r["document"] for r in records] == [A, B]  # key order
    assert records[0]["set"] == "set-a" and records[0]["split"] == "development"


def test_a_second_split_for_one_document_stops_the_view(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as s:
        write_split(s, "set-a", {A: "development"})
        with pytest.raises(ValueError, match=r"gives the document .* the split development, not"):
            write_split(s, "set-a", {B: "development", A: "held-out"})
        assert read_split(s, "set-a") == {A: "development"}  # no record of the call was added
        s.append(("splits", set_key("set-a")), {"set": "set-a", "document": A, "split": "x"})
        with pytest.raises(ValueError, match=f"gives the document {A} two splits"):
            read_split(s, "set-a")
        with pytest.raises(ValueError, match="two splits"):
            write_split(s, "set-a", {B: "development"})
    with FolderStore(root) as s:
        report = check(s)
    rel = f"logs/splits/{set_key('set-a')[7:]}.jsonl"
    assert report.findings == [f"{rel}: the splits log gives the document {A} two splits"]
    assert main(["review", "measures", "--store", str(root), "--set", "set-a",
                 "--split", "development"]) == 2  # fmt: skip


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"set": "set-b", "document": A, "split": "development"}, "names another set"),
        ({"document": A, "split": "development"}, "names another set"),
        ({"set": "set-a", "document": "lease.pdf", "split": "development"}, "has no document key"),
        ({"set": "set-a", "document": A, "split": ""}, "has no split"),
        ({"set": "set-a", "document": A}, "has no split"),
    ],
)
def test_a_bad_record_stops_the_view(tmp_path: Path, record: dict[str, str], message: str) -> None:
    with FolderStore(tmp_path / "s") as s:
        s.append(("splits", set_key("set-a")), record)
        with pytest.raises(ValueError, match=f"splits record 1 {message}"):
            read_split(s, "set-a")
        report = check(s)
    assert len(report.findings) == 1 and message in report.findings[0]


def test_write_split_refuses_a_bad_argument(tmp_path: Path) -> None:
    with FolderStore(tmp_path / "s") as s:
        with pytest.raises(ValueError, match="set name"):
            write_split(s, " ", {A: "development"})
        with pytest.raises(ValueError, match="not a document key"):
            write_split(s, "set-a", {"../x": "development"})
        with pytest.raises(ValueError, match="not a name"):
            write_split(s, "set-a", {A: ""})
    assert not (tmp_path / "s" / "logs").exists()


def test_calibrate_split_writes_the_splits_log(tmp_path: Path) -> None:
    work, store = tmp_path / "work", tmp_path / "store"
    names = ["doc0", "doc1", "doc2", "doc3"]
    _sample(tmp_path, work, names)
    with pytest.raises(SystemExit, match="together"):
        cli.main(["split", "--work", str(work), "--store", str(store)])
    run = ["split", "--work", str(work), "--store", str(store), "--set", "cal-a"]
    cli.main(run)
    parts = json.loads((work / "split.json").read_text())
    assert parts == {f"{name}:0": cli.part(name) for name in names}
    assert set(parts.values()) == {"calibration", "test"}
    with FolderStore(store) as s:
        logged = read_split(s, "cal-a")
    want = {key("text@1", text(n, False).encode("utf-8")): cli.part(name)
            for n, name in enumerate(names)}  # fmt: skip
    assert logged == want
    # the same documents in a new work folder: the log has them already, with the same parts
    cli.main(["split", "--work", str(_again(tmp_path, work)), "--store", str(store),
              "--set", "cal-a"])  # fmt: skip
    with FolderStore(store) as s:
        assert len(s.read(("splits", set_key("cal-a")))) == 4


def _again(tmp: Path, work: Path) -> Path:
    other = tmp / "work2"
    other.mkdir()
    (other / "docs").mkdir()
    for name in ("config.json", "items.json"):
        (other / name).write_bytes((work / name).read_bytes())
    for p in (work / "docs").iterdir():
        (other / "docs" / p.name).write_bytes(p.read_bytes())
    return other


def test_calibrate_split_stops_on_another_split(tmp_path: Path) -> None:
    work, store = tmp_path / "work", tmp_path / "store"
    _sample(tmp_path, work, ["doc0"])
    document = key("text@1", text(0, False).encode("utf-8"))
    mine = cli.part("doc0")
    with FolderStore(store) as st:
        write_split(st, "cal-a", {document: "other"})
    run = ["split", "--work", str(work), "--store", str(store), "--set", "cal-a"]
    with pytest.raises(SystemExit, match=f"split other, not {mine}"):
        cli.main(run)
    assert not (work / "split.json").exists()
    cli.main([*run[:-1], "cal-b"])  # another set has its own log
    assert json.loads((work / "split.json").read_text()) == {"doc0:0": mine}


def test_calibrate_split_with_a_store_comes_before_the_labels(tmp_path: Path) -> None:
    work = tmp_path / "work"
    _sample(tmp_path, work, ["doc0"])
    (work / "labels.json").write_text(json.dumps({"doc0:0": ["fiscal 2025"]}))
    with pytest.raises(SystemExit, match="before any label"):
        cli.main(["split", "--work", str(work), "--store", str(tmp_path / "s"), "--set", "x"])
    assert not (work / "split.json").exists() and not (tmp_path / "s").exists()
    cli.main(["split", "--work", str(work)])  # a work folder with no store works as in 0.10
    assert (work / "split.json").exists()


def test_two_documents_with_one_text_and_two_parts_stop_the_split(tmp_path: Path) -> None:
    work = tmp_path / "work"
    assert cli.part("doc1") != cli.part("doc2")
    _sample(tmp_path, work, ["doc1", "doc2"], same=True)
    with pytest.raises(SystemExit, match="doc1 and doc2 have the same text but not the same"):
        cli.main(["split", "--work", str(work), "--store", str(tmp_path / "s"), "--set", "x"])
    assert not (work / "split.json").exists()
