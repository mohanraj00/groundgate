"""A second set folder of the regulatory family (#750), on synthetic data only."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from bench.regulatory import passes, run, slots, sources
    from bench.regulatory.test_run import REQUESTS, SCHEMA, TEXT, TRANSPORT, XML, Client, pretty

ROOT = Path(__file__).parent.parent
HERE = ROOT / "bench" / "regulatory2"


@pytest.fixture(scope="module", autouse=True)
def _bench() -> Iterator[None]:
    """Import the bench modules for this file only. Other tests check that no ``bench``
    module is loaded, so the teardown removes them again."""
    path, loaded = list(sys.path), set(sys.modules)
    sys.path.insert(0, str(ROOT))
    names = {m: f"bench.regulatory.{m}" for m in ("passes", "run", "slots", "sources")}
    g = globals()
    for name, module in names.items():
        g[name] = importlib.import_module(module)
    test_run = importlib.import_module("bench.regulatory.test_run")
    for name in ("REQUESTS", "SCHEMA", "TEXT", "TRANSPORT", "XML", "Client", "pretty"):
        g[name] = getattr(test_run, name)
    yield
    sys.path[:] = path
    for m in set(sys.modules) - loaded:
        if m == "bench" or m.startswith("bench."):
            del sys.modules[m]


def part_xml(part: int, word: str = "rate") -> bytes:
    return (
        f'<?xml version="1.0"?><DIV5 N="{part}" TYPE="PART" hierarchy_metadata='
        f'"{{&amp;quot;citation&amp;quot;:&amp;quot;9 CFR Part {part}&amp;quot;}}">'
        f'<HEAD>PART {part}—FEES</HEAD><DIV8 N="{part}.1" TYPE="SECTION">'
        f"<HEAD>§ {part}.1 Fees.</HEAD><P>The fee of the section and the {word} for each "
        "hour to the Agency.</P></DIV8></DIV5>"
    ).encode()


def members(approved: str | None, parts: tuple[int, ...] = (391, 392)) -> dict[str, Any]:
    return {
        "format": "regulatory-members/1",
        "point_in_time": "2026-11-24",
        "calibration_set": "bench/regulatory",
        "splits": {"heldout": len(parts)},
        "download_approved": approved,
        "notice_review": None,
        "members": [{"title": 9, "part": p, "heading_words": "FEES", "sections": 1} for p in parts],
    }


def source_set(tmp_path: Path, approved: str | None) -> tuple[Path, Path]:
    here, out = tmp_path / "set", tmp_path / "out"
    here.mkdir()
    out.mkdir()
    (here / "members.json").write_text(json.dumps(members(approved)))
    for p in (391, 392):
        (out / f"cfr-9-{p}.xml").write_bytes(part_xml(p))
    return here, out


def test_the_committed_member_list_is_new_and_has_its_source_checks() -> None:
    body = json.loads((HERE / "members.json").read_text())
    config = sources.set_config(HERE)
    assert config.from_file and config.calibration == 0
    assert config.download_approved == "2026-11-27" and config.notice_review
    assert len(config.members) == body["splits"]["heldout"] == 14
    first = {sources.member_id(t, p) for t, p, _, _ in sources.MEMBERS}
    second = {sources.member_id(t, p) for t, p, _, _ in config.members}
    spares = {sources.member_id(m["title"], m["part"]) for m in body["spares"]}
    assert not first & second and not first & spares and not second & spares
    manifest = json.loads((HERE / "manifest.json").read_text())
    docs = manifest["documents"]
    assert manifest["selection_complete"] is True
    assert [d["id"] for d in docs] == [sources.member_id(t, p) for t, p, _, _ in config.members]
    assert {(d["selection_status"], d["split"]) for d in docs} == {("frozen_member", "heldout")}
    seed = sources.split_seed([d["source_sha256"] for d in docs])
    assert manifest["split_rule"]["seed"] == seed
    checks = json.loads((HERE / "source_checks.json").read_text())["documents"]
    assert [c["id"] for c in checks] == [d["id"] for d in docs]
    assert all(not c["problems"] and c["notice"]["review"] == body["notice_review"] for c in checks)
    assert not (HERE / "labels.json").exists() and "labels" not in manifest


def test_the_committed_slots_follow_the_draw_rule_and_the_manifest_pins_them() -> None:
    raw = (HERE / "slots.json").read_bytes()
    body = json.loads(raw)
    manifest = json.loads((HERE / "manifest.json").read_text())
    assert manifest["slots"] == {
        "file": "slots.json", "count": len(body["slots"]), "calibration": 0,
        "heldout": len(body["slots"]), "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }  # fmt: skip
    assert body["seed"] == manifest["split_rule"]["seed"] and body["schema"] == slots.SCHEMA
    rows = body["slots"]
    assert [s["slot"] for s in rows] == [f"r{n:03d}" for n in range(1, len(rows) + 1)]
    ids = [d["id"] for d in manifest["documents"]]
    assert [s["id"] for s in rows] == sorted((s["id"] for s in rows), key=ids.index)
    for d in ids:
        got = Counter(s["field"] for s in rows if s["id"] == d)
        assert all(got[f] <= k for f, (_, k) in slots.FIELDS.items()), d
    assert {s["split"] for s in rows} == {"heldout"}
    assert all(s["request_text"] == slots.request_text(s) for s in rows)


def test_sources_refuse_a_set_without_the_download_approval(tmp_path: Path) -> None:
    here, out = source_set(tmp_path, None)
    with pytest.raises(SystemExit):
        sources.main(["--set", str(here), "--out", str(out)])
    assert not (here / "manifest.json").exists()


def test_sources_pin_a_set_with_only_heldout_parts(tmp_path: Path) -> None:
    here, out = source_set(tmp_path, "2026-11-28")
    assert sources.main(["--set", str(here), "--out", str(out)]) == 0
    manifest = json.loads((here / "manifest.json").read_text())
    docs = manifest["documents"]
    assert [d["split"] for d in docs] == ["heldout", "heldout"]
    assert {d["point_in_time"] for d in docs} == {"2026-11-24"}
    assert {d["download_approved"] for d in docs} == {"2026-11-28"}
    assert docs[0]["source"].endswith("/full/2026-11-24/title-9.xml?part=391")
    assert manifest["selection_complete"] is True
    assert manifest["split_rule"]["rule"].startswith("all members are heldout")
    seed = sources.split_seed([d["source_sha256"] for d in docs])
    assert manifest["split_rule"]["seed"] == seed
    checks = json.loads((here / "source_checks.json").read_text())
    assert checks["date"] == "2026-11-24"
    # A member that fails its check is on hold, and the selection is not complete.
    (out / "cfr-9-392.xml").write_bytes(part_xml(393))
    assert sources.main(["--set", str(here), "--out", str(out), "--repin"]) == 0
    manifest = json.loads((here / "manifest.json").read_text())
    assert manifest["selection_complete"] is False
    assert manifest["documents"][1]["selection_status"] == "on_hold"


@pytest.mark.parametrize(
    "change",
    [{"splits": {"heldout": 3}}, {"format": "other"}, {"members": [{"title": 9}]}],
)
def test_sources_refuse_a_member_list_that_is_not_valid(tmp_path: Path, change: Any) -> None:
    here, out = source_set(tmp_path, "2026-11-28")
    (here / "members.json").write_text(json.dumps(members("2026-11-28") | change))
    with pytest.raises(SystemExit):
        sources.main(["--set", str(here), "--out", str(out)])


def test_slots_write_their_pin_and_stay_frozen_after_the_seal(tmp_path: Path) -> None:
    here, out = source_set(tmp_path, "2026-11-28")
    assert sources.main(["--set", str(here), "--out", str(out)]) == 0
    with pytest.raises(SystemExit):  # the notice review comes first
        slots.main(["--set", str(here), "--sources", str(out)])
    body = members("2026-11-28") | {"notice_review": "No notice of the publisher."}
    (here / "members.json").write_text(json.dumps(body))
    assert slots.main(["--set", str(here), "--sources", str(out)]) == 0
    raw = (here / "slots.json").read_bytes()
    pin = json.loads((here / "manifest.json").read_text())["slots"]
    assert pin["sha256"] == run.digest(raw)
    assert pin["count"] == pin["heldout"] == len(json.loads(raw)["slots"]) > 0
    assert pin["calibration"] == 0
    manifest = json.loads((here / "manifest.json").read_text())
    (here / "manifest.json").write_text(json.dumps(manifest | {"labels": {}}))
    with pytest.raises(SystemExit):
        slots.main(["--set", str(here), "--sources", str(out)])


def test_seal_writes_into_the_set_and_refuses_a_second_seal(tmp_path: Path) -> None:
    here, work = tmp_path / "set", tmp_path / "work"
    here.mkdir()
    work.mkdir()
    (here / "members.json").write_text(json.dumps(members(None)))
    slot = {"slot": "r001", "id": "cfr-9-391", "split": "heldout", "field": "section_text"}
    (here / "slots.json").write_text(json.dumps({"slots": [slot | {"kind": "passage"}]}))
    (here / "manifest.json").write_text(json.dumps({"documents": []}))
    answer = {"status": "value", "value": "The fee."}
    rows = [{"slot": "r001", "state": "agree", "a": answer}]
    (work / "compare.json").write_text(json.dumps(rows))
    args = ["seal", "--set", str(here), "--work", str(work)]
    assert passes.main(args) == 0
    labels = json.loads((here / "labels.json").read_text())["labels"]
    assert labels == [slot | {"status": "value", "value": "The fee.", "unit": None,
                              "decided_by": "agree"}]  # fmt: skip
    sealed = (here / "manifest.json").read_bytes()
    assert passes.main(args) == 1
    assert (here / "manifest.json").read_bytes() == sealed


def write_set(directory: Path, sources_dir: Path, parts: dict[str, str]) -> None:
    """A sealed synthetic set: one entry of ``parts`` for each part id and its split."""
    directory.mkdir()
    docs, slot_rows, labels = [], [], []
    for name, side in parts.items():
        docs.append({
            "id": name, "citation": "Part 1", "split": side, "selection_status": "frozen_member",
            "source_bytes": len(XML), "source_sha256": run.digest(XML),
            "text_sha256": run.digest(TEXT),
        })  # fmt: skip
        (sources_dir / f"{name}.xml").write_bytes(XML)
        (sources_dir / f"{name}.txt").write_bytes(TEXT)
        for field, section, request, gold, unit in REQUESTS:
            keys = {"slot": f"r{len(slot_rows) + 1:03}", "id": name, "field": field, "split": side}
            slot_rows.append(keys | {
                "kind": SCHEMA[field]["type"], "request": {"section": section} | request,
                "request_text": f"The {field} of {section}",
            })  # fmt: skip
            labels.append(keys | {"status": "value", "value": gold, "unit": unit})
    slot_body = pretty({"format": "regulatory-slots/1", "seed": "seed", "schema": SCHEMA,
                        "slots": slot_rows})  # fmt: skip
    (directory / "slots.json").write_bytes(slot_body)
    label_body = pretty({"format": "regulatory-labels/1", "labels": labels})
    (directory / "labels.json").write_bytes(label_body)
    ranges = []
    for row in labels:
        if row["split"] == "calibration":
            block = b"\n".join(b"  " + line for line in pretty(row).splitlines())
            start = label_body.index(block)
            ranges.append((start, start + len(block)))
    count = {s: sum(r["split"] == s for r in slot_rows) for s in ("calibration", "heldout")}
    manifest = {
        "selection_complete": True, "split_rule": {"seed": "seed"}, "documents": docs,
        "slots": {"sha256": run.digest(slot_body), "count": len(slot_rows)} | count,
        "labels": {"file": "labels.json", "sha256": run.digest(label_body),
                   "sealed": "2026-11-28", "calibration_ranges": ranges,
                   "calibration_sha256": run.digest(b",".join(label_body[a:b] for a, b in ranges))},
    }  # fmt: skip
    (directory / "manifest.json").write_bytes(pretty(manifest))


@pytest.fixture
def two_sets(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    first, second = tmp_path / "first", tmp_path / "second"
    source_dir, cache = tmp_path / "sources", tmp_path / "cache"
    source_dir.mkdir()
    write_set(first, source_dir, {
        f"cfr-1-{i}": "calibration" if i % 3 == 1 else "heldout" for i in range(1, 15)
    })  # fmt: skip
    write_set(second, source_dir, {f"cfr-2-{i}": "heldout" for i in range(1, 5)})
    (second / "members.json").write_text(json.dumps({
        "format": "regulatory-members/1", "splits": {"heldout": 4},
        "calibration_set": str(first), "report_intro": "This is the second split.",
    }))  # fmt: skip
    return first, second, source_dir, cache


def test_a_heldout_set_calibrates_on_its_calibration_set(two_sets: Any) -> None:
    first, second, source_dir, cache = two_sets
    before = {f: (first / f).read_bytes() for f in ("manifest.json", "slots.json", "labels.json")}
    calibration = Client()
    run.Benchmark(second, source_dir, cache).calibrate(TRANSPORT, calibration)
    assert len(calibration.prompts) == 5
    run.Benchmark(second, source_dir, cache).freeze("2026-11-28")
    assert {f: (first / f).read_bytes() for f in before} == before
    bench = run.Benchmark(second, source_dir, cache)
    assert bench.manifest["freeze"]["profile_sha256"] == run.profile_digest(
        bench.manifest["freeze"]["profile"]
    )
    heldout = Client()
    bench.heldout(TRANSPORT, heldout)
    assert len(heldout.prompts) == 4
    result = json.loads((second / "results.json").read_text())
    assert result["total"]["admitted_right"] == 20
    other = run.Benchmark(first, source_dir, cache)
    assert result["run"]["calibration_set"] == {
        "set_sha256": other.unfrozen,
        "slots_sha256": run.digest(other.slots_raw),
        "labels_sha256": other.manifest["labels"]["sha256"],
    }
    report = (second / "RESULTS.md").read_text()
    assert "This is the second split." in report and "#686" not in report
    assert {f: (first / f).read_bytes() for f in before} == before


def test_a_change_to_the_calibration_set_after_the_freeze_stops_the_heldout_run(
    two_sets: Any,
) -> None:
    first, second, source_dir, cache = two_sets
    run.Benchmark(second, source_dir, cache).calibrate(TRANSPORT, Client())
    run.Benchmark(second, source_dir, cache).freeze("2026-11-28")
    frozen = json.loads((second / "manifest.json").read_text())["freeze"]
    assert (
        frozen["calibration_set"] == run.Benchmark(second, source_dir, cache).calibration_identity()
    )
    manifest = json.loads((first / "manifest.json").read_text())
    (first / "manifest.json").write_bytes(pretty(manifest | {"note": "changed"}))
    heldout = Client()
    with pytest.raises(ValueError, match="calibration set differs from the freeze"):
        run.Benchmark(second, source_dir, cache).heldout(TRANSPORT, heldout)
    assert heldout.prompts == []
    assert not (second / "results.json").exists()


def test_a_change_to_the_calibration_set_stops_the_run(two_sets: Any) -> None:
    first, second, source_dir, cache = two_sets
    bench = run.Benchmark(second, source_dir, cache)
    manifest = json.loads((first / "manifest.json").read_text())
    (first / "manifest.json").write_bytes(pretty(manifest | {"note": "changed"}))
    with pytest.raises(ValueError, match="run inputs changed"):
        bench.check_inputs()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"splits": {"heldout": 4, "calibration": 1}}, "only held-out parts"),
        ({"splits": {"heldout": "4"}}, "not valid"),
        ({"calibration_set": None}, "needs calibration parts"),
        ({"calibration_set": "same"}, "only held-out parts"),
        ({"format": "other"}, "not valid"),
    ],
)
def test_the_run_refuses_a_member_list_that_is_not_valid(
    two_sets: Any, change: dict[str, Any], message: str
) -> None:
    _, second, source_dir, cache = two_sets
    body = json.loads((second / "members.json").read_text()) | change
    if body.get("calibration_set") == "same":
        body["calibration_set"] = str(second)
    (second / "members.json").write_text(json.dumps(body))
    with pytest.raises(ValueError, match=message):
        run.Benchmark(second, source_dir, cache)


def test_the_run_refuses_a_part_in_both_sets(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    write_set(first, source_dir, {f"cfr-1-{i}": "calibration" if i % 3 == 1 else "heldout"
                                  for i in range(1, 15)})  # fmt: skip
    write_set(second, source_dir, {"cfr-1-2": "heldout"})
    (second / "members.json").write_text(json.dumps({
        "format": "regulatory-members/1", "splits": {"heldout": 1},
        "calibration_set": str(first),
    }))  # fmt: skip
    with pytest.raises(ValueError, match="in its calibration set"):
        run.Benchmark(second, source_dir, tmp_path / "cache")
