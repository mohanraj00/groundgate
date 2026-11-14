"""groundgate calibrate measure (#640): the report vectors and the input checks."""

from __future__ import annotations

import json
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

from groundgate.calibrate import measure
from groundgate.calibrate.cli import main

VECTORS = Path(__file__).parent / "vectors" / "calibrate"
CASES = sorted(p for p in VECTORS.iterdir() if p.is_dir())


def _copy(case: Path, tmp: Path) -> Path:
    """The vector in a directory outside the repository, as a gold set of a user is."""
    dst = tmp / "in"
    shutil.copytree(case, dst)
    return dst


def _run(src: Path, out: Path, **over: str) -> None:
    args = json.loads((src / "args.json").read_text(encoding="utf-8")) | over
    main([
        "measure", "--profile", str(src / "profile.json"), "--gold", str(src / "gold"),
        "--split", str(src / "split.json"), "--out", str(out),
        "--target", args["target"], "--date", args["date"],
    ])  # fmt: skip


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_report_matches_its_vector(
    case: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _copy(case, tmp_path)
    before = (src / "profile.json").read_bytes()

    def no_network(*_: Any, **__: Any) -> None:
        raise AssertionError("a recorded run makes no network call")

    monkeypatch.setattr(socket, "socket", no_network)
    _run(src, tmp_path / "out")
    for name in ("report", "profile"):
        got = json.loads((tmp_path / "out" / f"{name}.json").read_text(encoding="utf-8"))
        want = json.loads((case / f"expected-{name}.json").read_text(encoding="utf-8"))
        assert got == want, name
    assert (src / "profile.json").read_bytes() == before  # never changed in place
    assert not [m for m in sys.modules if m == "bench" or m.startswith("bench.")]
    md = (tmp_path / "out" / "REPORT.md").read_text(encoding="utf-8")
    assert "| total | checked | 5 | 1 | 0.2 | 0.6574 | measured | 0 | 0.3333 |" in md


def test_the_measure_does_not_import_bench() -> None:
    source = Path(measure.__file__).read_text(encoding="utf-8")
    assert "import bench" not in source and "from bench" not in source


def test_the_output_directory_is_new(tmp_path: Path) -> None:
    src = _copy(CASES[0], tmp_path)
    _run(src, tmp_path / "out")
    with pytest.raises(SystemExit, match="use a new directory"):
        _run(src, tmp_path / "out")


def test_the_draft_profile_is_a_valid_profile(tmp_path: Path) -> None:
    from groundgate.profile import load_profile

    src = _copy(CASES[0], tmp_path)
    _run(src, tmp_path / "out")
    draft = load_profile(tmp_path / "out" / "profile.json")
    assert draft["version"] == "1.0.1"
    assert draft["policy"]["judge"]["clear"]["KEY_NOT_AT_VALUE"] == 0.7


def _edit(path: Path, change: Any) -> None:
    obj = json.loads(path.read_text(encoding="utf-8"))
    change(obj)
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_no_threshold_passes(tmp_path: Path) -> None:
    """With a target that no threshold meets, the draft has no clear threshold."""
    src = _copy(CASES[0], tmp_path)
    _run(src, tmp_path / "out", target="0.5")
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["operating_point"]["KEY_NOT_AT_VALUE"] is None
    assert not any(t["passes"] for t in report["operating_point"]["tried"])
    draft = json.loads((tmp_path / "out" / "profile.json").read_text(encoding="utf-8"))
    assert "clear" not in draft["policy"]["judge"]
    rate = report["fields"]["rate"]["routes"]
    assert rate["cleared"]["admitted"] == 0  # nothing is cleared without a threshold


def test_a_profile_with_no_judge(tmp_path: Path) -> None:
    src = _copy(CASES[0], tmp_path)
    _edit(src / "profile.json", lambda p: p.pop("policy"))
    _run(src, tmp_path / "out")
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["operating_point"] == {"judge": None, "KEY_NOT_AT_VALUE": None, "tried": []}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda s: s / "gold" / "labels.json", "groundgate_gold must be 1"),
        (lambda s: s / "split.json", "a part for each gold document"),
        (lambda s: s / "gold" / "docs" / "c9.txt", "each document of docs/"),
        (lambda s: s / "gold" / "candidates" / "t1.json", "must be a list"),
        (lambda s: s / "gold" / "docs" / "t1.txt", "not NFC"),
        (lambda s: s / "gold" / "labels.json#field", "which the profile has not"),
        (lambda s: s / "gold" / "labels.json#type", "a string or null"),
        (lambda s: s / "gold" / "docs" / "t1.txt#link", "not a regular file"),
    ],
    ids=["format", "split", "extra-doc", "candidates", "nfc", "field", "label-type", "link"],
)
def test_bad_input_is_refused(tmp_path: Path, change: Any, message: str) -> None:
    src = _copy(CASES[0], tmp_path)
    target = change(src)
    name = target.name
    if name == "labels.json":
        _edit(target, lambda o: o.update(groundgate_gold=2))
    elif name == "labels.json#field":
        _edit(target.with_name("labels.json"), lambda o: o["labels"]["t1"].update(other="1"))
    elif name == "labels.json#type":
        _edit(target.with_name("labels.json"), lambda o: o["labels"]["t1"].update(total=90))
    elif name == "split.json":
        _edit(target, lambda o: o["documents"].pop("t1"))
    elif name == "c9.txt":
        target.write_text("Total\t$1\n", encoding="utf-8")
    elif name == "t1.json":
        target.write_text("{}", encoding="utf-8")
    elif name == "t1.txt":
        target.write_text("Café\n", encoding="utf-8")
    else:
        real = target.with_name("t1.txt")
        outside = tmp_path / "outside.txt"
        outside.write_bytes(real.read_bytes())
        real.unlink()
        real.symlink_to(outside)
    with pytest.raises(SystemExit, match=message):
        _run(src, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("over", "message"),
    [({"target": "0"}, "in \\(0, 1\\]"), ({"target": "x"}, "decimal"),
     ({"date": "2026-02-30"}, "real day")],
)  # fmt: skip
def test_bad_arguments_are_refused(tmp_path: Path, over: dict[str, str], message: str) -> None:
    src = _copy(CASES[0], tmp_path)
    with pytest.raises(SystemExit, match=message):
        _run(src, tmp_path / "out", **over)


def test_a_table_cell_escapes_a_pipe() -> None:
    assert measure._cell("a|b\nc") == "a\\|b c"


def test_a_linked_gold_folder_is_refused(tmp_path: Path) -> None:
    src = _copy(CASES[0], tmp_path)
    moved = tmp_path / "elsewhere"
    (src / "gold" / "docs").rename(moved)
    (src / "gold" / "docs").symlink_to(moved, target_is_directory=True)
    with pytest.raises(SystemExit, match="is a link"):
        _run(src, tmp_path / "out")


def test_many_thresholds_are_rounded_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(measure, "MAX_THRESHOLDS", 2)
    judge = {"id": "j", "digest": "j-1"}
    js = [{"question": "key", "judge": judge, "p": p} for p in (0.611, 0.612, 0.7)]
    gold = measure.Gold({"d": measure.GoldDoc("d", "", [], js, {})}, "sha256:0")
    profile = {"policy": {"judge": judge}}
    assert measure._thresholds(profile, gold, ["d"]) == [0.62, 0.7]


def test_number_equality_is_only_for_number_fields(tmp_path: Path) -> None:
    """The string "001" is not the label "1". The number 90 is the label "90.0"."""
    assert measure._same("90", "90.0", True)
    assert not measure._same("001", "1", False)
    text = "Code\t001\n"
    cand = {"id": "c", "field": "code", "value": "001",
            "evidence": [{"start": 5, "end": 8, "text": "001"},
                         {"role": "field", "start": 0, "end": 4, "text": "Code"}]}  # fmt: skip
    profile = {"groundgate_profile": 1, "id": "codes-test", "version": "1.0.0",
               "schema": {"fields": {"code": {"type": "string", "aliases": ["Code"]}}}}  # fmt: skip
    gold = measure.Gold({"d": measure.GoldDoc("d", text, [cand], None, {"code": "1"})}, "sha256:0")
    s = measure.score(profile, gold, ["d"])["code"]
    assert (s.routes["checked"].admitted, s.routes["checked"].errors, s.missed) == (1, 1, 1)


def test_a_value_is_right_only_under_its_own_key(tmp_path: Path) -> None:
    """t5 of the vector admits the express value 25 under the key standard. The label of
    standard is 10, so the value is an error, although 25 is the label of express."""
    src = _copy(CASES[0], tmp_path)
    labels = json.loads((src / "gold" / "labels.json").read_text(encoding="utf-8"))["labels"]
    assert labels["t5"]["rate"] == {"express": "25", "standard": "10"}
    _run(src, tmp_path / "out")
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["fields"]["rate"]["routes"]["cleared"]["errors"] == 1


@pytest.mark.parametrize(
    ("label", "message"),
    [("10", "has keys"), ({"overnight": "10"}, "is not a key"),
     ({"Standard": "10"}, "is not a key")],
    ids=["plain", "unknown-key", "other-case"],
)  # fmt: skip
def test_a_bad_keyed_label_is_refused(tmp_path: Path, label: Any, message: str) -> None:
    src = _copy(CASES[0], tmp_path)
    _edit(src / "gold" / "labels.json", lambda o: o["labels"]["t1"].update(rate=label))
    with pytest.raises(SystemExit, match=message):
        _run(src, tmp_path / "out")


def test_an_admitted_value_with_no_label_stops_a_measured_route(tmp_path: Path) -> None:
    """t6 admits a rate under express. With no label for express, nothing says that the value
    is right, so the route is not measured, at any bound."""
    src = _copy(CASES[0], tmp_path)
    _edit(src / "gold" / "labels.json", lambda o: o["labels"]["t6"].update(rate={"standard": None}))
    _run(src, tmp_path / "out", target="1")
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    checked = report["fields"]["rate"]["routes"]["checked"]
    assert (checked["admitted"], checked["unscored"], checked["status"]) == (1, 1, "draft")
    assert report["fields"]["total"]["routes"]["checked"]["status"] == "measured"


def test_a_threshold_that_clears_a_value_with_no_label_does_not_pass(tmp_path: Path) -> None:
    """Without the standard label of c1, the threshold 0.7 has 2 cleared values, no error and
    the bound 0.7764. It also clears the value of c1, which no label covers. So it fails."""
    src = _copy(CASES[0], tmp_path)
    _edit(src / "gold" / "labels.json", lambda o: o["labels"]["c1"].update(rate={"express": None}))
    _run(src, tmp_path / "out", target="0.8")
    point = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))[
        "operating_point"
    ]
    row = next(t for t in point["tried"] if t["threshold"] == 0.7)
    assert (row["admitted"], row["errors"], row["bound"], row["unscored"]) == (2, 0, "0.7764", 1)
    assert not row["passes"] and point["KEY_NOT_AT_VALUE"] is None


def test_two_schema_keys_with_one_fold_stay_apart() -> None:
    """The gate keeps the keys Maße and Masse apart, so the measure does too."""
    assert measure._units("d", "f", {"Maße": "20"}, ("Maße", "Masse")) == {"Maße": "20"}
    both = {"Maße": "20", "Masse": "30"}
    assert measure._units("d", "f", both, ("Maße", "Masse")) == both
    text = "Masse\nThe size is 20 mm.\n"
    cand = {"id": "c", "field": "size", "value": 20, "unit": "mm", "key": "Masse",
            "evidence": [{"start": 18, "end": 23, "text": "20 mm"}]}  # fmt: skip
    profile = {"groundgate_profile": 1, "id": "sizes-test", "version": "1.0.0",
               "schema": {"fields": {"size": {"type": "integer", "unit": "mm",
                                              "keys": ["Maße", "Masse"]}}}}  # fmt: skip
    gold = measure.Gold(
        {"d": measure.GoldDoc("d", text, [cand], None, {"size": {"Maße": "20"}})}, "sha256:0"
    )
    s = measure.score(profile, gold, ["d"])["size"]
    assert (s.routes["checked"].admitted, s.routes["checked"].unscored, s.missed) == (0, 1, 1)
