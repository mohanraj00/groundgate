"""The blind audit sample (SPEC §4.18, #643): the vectors in ``conformance/audit/`` and
``calibrate measure --audit``. The expectations of the vectors are written by hand."""

from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from groundgate import admit
from groundgate.calibrate import audit
from groundgate.calibrate.cli import main
from groundgate.canonical import jcs
from groundgate.profile import check_profile

ROOT = Path(__file__).parent.parent / "conformance" / "audit"
VECTORS = [json.loads(p.read_text("utf-8")) for p in sorted(ROOT.glob("*.json"))]


def of(kind: str) -> list[Any]:
    return [pytest.param(v, id=v["name"]) for v in VECTORS if v["kind"] == kind]


def _log(v: dict[str, Any]) -> str:
    return "".join(line + "\n" for line in v["log"])


@pytest.mark.parametrize("v", of("pick"))
def test_pick_vector(v: dict[str, Any]) -> None:
    entries = audit.read_log(_log(v))
    for row in v["expected"]["hashes"]:
        (entry,) = [e for e in entries if e.get("document") == row["document"]]
        h = audit.pick_hash(v["seed"], entry["profile"], row["document"])
        assert f"{h:016x}" == row["first_8_bytes"]
    assert audit.pick(v["seed"], entries) == v["expected"]["pick"]
    assert audit.pick(v["seed"], audit.read_log(_log(v))) == v["expected"]["pick"]  # a replay


def test_another_seed_gives_another_pick() -> None:
    (v,) = [v for v in VECTORS if v["name"] == "audit-pick-01-rates"]
    entries = audit.read_log(_log(v))
    other = audit.pick("another seed", entries)
    assert other != v["expected"]["pick"]
    # the minimum does not depend on the seed
    assert [p for p in other if p["reason"] == "minimum"] == [
        p for p in v["expected"]["pick"] if p["reason"] == "minimum"
    ]


def test_a_longer_log_keeps_the_earlier_pick() -> None:
    (v,) = [v for v in VECTORS if v["name"] == "audit-pick-01-rates"]
    entries = audit.read_log(_log(v))
    for n in range(len(entries)):
        part = audit.pick(v["seed"], entries[:n])
        assert part == v["expected"]["pick"][: len(part)]


@pytest.mark.parametrize("v", of("log"))
def test_invalid_log_vector(v: dict[str, Any]) -> None:
    with pytest.raises(audit.AuditError):
        audit.read_log(_log(v))


def test_pick_checks_each_entry() -> None:
    with pytest.raises(audit.AuditError, match="wrong or a missing member"):
        audit.pick("s", [{"entry": "rate", "profile": "sha256:" + "a" * 64, "rate": "0.5"}])
    with pytest.raises(audit.AuditError, match="seed"):
        audit.pick(7, [])  # type: ignore[arg-type]


def test_a_log_needs_a_line_break_at_the_end() -> None:
    line = jcs({"entry": "rate", "profile": "sha256:" + "a" * 64, "rate": "0.02"})
    assert len(audit.read_log(line + "\n")) == 1
    with pytest.raises(audit.AuditError, match="line break"):
        audit.read_log(line)
    with pytest.raises(audit.AuditError, match="line 2"):
        audit.read_log(line + "\n\n")


@pytest.mark.parametrize("v", of("tasks"))
def test_tasks_vector(v: dict[str, Any]) -> None:
    digest = check_profile(v["profile"]).sha256
    want = [
        {"groundgate_audit_task": 1, "document": t["document"], "profile": digest,
         "field": t["field"], "key": t["key"]}
        for t in v["expected"]["tasks"]
    ]  # fmt: skip
    got = audit.tasks(v["profile"], v["document"])
    assert got == want
    members = {"groundgate_audit_task", "document", "profile", "field", "key"}
    assert all(set(t) == members for t in got)  # no value, no evidence, no outcome


@pytest.mark.parametrize("v", of("label"))
def test_label_vector(v: dict[str, Any]) -> None:
    if v["expected"]["valid"]:
        assert audit.check_label(v["label"]) == v["label"]
        assert audit.read_labels(jcs(v["label"]) + "\n") == [v["label"]]
    else:
        with pytest.raises(audit.AuditError):
            audit.check_label(v["label"])
        with pytest.raises(audit.AuditError):
            audit.read_labels(jcs(v["label"]) + "\n")


@pytest.mark.parametrize("v", of("rate"))
def test_rate_vector(v: dict[str, Any]) -> None:
    assert audit.rate(v["routes"], v["covered"]) == v["expected"]["rate"]


def test_each_kind_has_a_vector() -> None:
    assert {v["kind"] for v in VECTORS} == {"pick", "log", "tasks", "label", "rate"}


# ----------------------------------------------------------------- measure with --audit

PROFILE = {
    "groundgate_profile": 1, "id": "items-test", "version": "1.0.0",
    "schema": {"fields": {"items": {"type": "integer"}}},
}  # fmt: skip
DIGEST = check_profile(PROFILE).sha256
SEED = "test-seed"


def _document(folder: Path, name: str, value: int) -> None:
    for sub in ("docs", "candidates"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    (folder / "docs" / f"{name}.txt").write_text(f"Items: {value}\n", "utf-8")
    cand = [{"id": "c1", "field": "items", "value": value, "evidence": {"text": str(value)}}]
    (folder / "candidates" / f"{name}.json").write_text(json.dumps(cand), "utf-8")


def _label(name: str, value: str | None, **more: Any) -> dict[str, Any]:
    return {
        "groundgate_audit_label": 1, "document": name, "profile": DIGEST, "field": "items",
        "key": None, "value": value, "labeler": "ana", "date": "2026-11-15", **more,
    }  # fmt: skip


class Case:
    """A gold set with 1 calibration and 2 test documents, and an audit set with 30 picked
    documents of one admitted value each. Each label is right."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.profile = tmp / "profile.json"
        self.profile.write_text(json.dumps(PROFILE), "utf-8")
        self.gold = tmp / "gold"
        for i in (1, 2, 3):
            _document(self.gold, f"g{i}", 500 + i)
        labels = {f"g{i}": {"items": str(500 + i)} for i in (1, 2, 3)}
        (self.gold / "labels.json").write_text(
            json.dumps({"groundgate_gold": 1, "labels": labels}), "utf-8"
        )
        self.split = tmp / "split.json"
        parts = {"g1": "calibration", "g2": "test", "g3": "test"}
        self.split.write_text(json.dumps({"groundgate_split": 1, "documents": parts}), "utf-8")
        self.audit = tmp / "audit"
        self.audit.mkdir()
        (self.audit / "audit.json").write_text(
            json.dumps({"groundgate_audit": 1, "seed": SEED}), "utf-8"
        )
        self.names = [f"a{i:02d}" for i in range(1, 31)]
        self.labels = []
        entries = []
        for i, name in enumerate(self.names, 1):
            _document(self.audit, name, 100 + i)
            entries.append({"entry": "document", "document": name, "profile": DIGEST, "items": 1})
            self.labels.append(_label(name, str(100 + i)))
        self.write_log(entries)
        self.write_labels()

    def write_log(self, entries: list[dict[str, Any]]) -> None:
        self.entries = entries
        (self.audit / "log.jsonl").write_text("".join(jcs(e) + "\n" for e in entries), "utf-8")

    def write_labels(self) -> None:
        text = "".join(jcs(x) + "\n" for x in self.labels)
        (self.audit / "labels.jsonl").write_text(text, "utf-8")

    def run(self, out: str, *more: str, audit_set: bool = True) -> dict[str, Any]:
        args = ["measure", "--profile", str(self.profile), "--gold", str(self.gold),
                "--split", str(self.split), "--out", str(self.tmp / out), "--target", "0.1",
                "--date", "2026-11-15", *more]  # fmt: skip
        if audit_set:
            args += ["--audit", str(self.audit)]
        main(args)
        return json.loads((self.tmp / out / "report.json").read_text("utf-8"))  # type: ignore[no-any-return]


def test_measure_counts_the_audit_labels_with_the_gold_labels(tmp_path: Path) -> None:
    case = Case(tmp_path)
    alone = case.run("alone", audit_set=False)
    assert "audit" not in alone
    checked = alone["fields"]["items"]["routes"]["checked"]
    # 2 admitted values with no error: the bound is 1 - 0.05^(1/2) = 0.7764
    assert (checked["admitted"], checked["errors"], checked["bound"]) == (2, 0, "0.7764")
    assert checked["status"] == "draft"

    report = case.run("with")
    checked = report["fields"]["items"]["routes"]["checked"]
    # 2 + 30 admitted values with no error: the bound is 1 - 0.05^(1/32) = 0.0894
    assert (checked["admitted"], checked["errors"], checked["bound"]) == (32, 0, "0.0894")
    assert checked["status"] == "measured"
    assert report["fields"]["items"]["scored"] == 32
    a = report["audit"]
    assert (a["seed"], a["since"], a["picked"], a["documents"], a["admitted"], a["skipped"]) == (
        SEED, None, 30, 30, 30, 0,
    )  # fmt: skip
    assert (a["rate"], a["alerts"]) == ("0.02", [])
    assert a["routes"] == [{"field": "items", "route": "checked", **checked}]
    assert report["documents"] == {"calibration": 1, "test": 2}
    draft = json.loads((tmp_path / "with" / "profile.json").read_text("utf-8"))
    assert draft["routes"] == [
        {"field": "items", "route": "checked", "status": "measured", "date": "2026-11-15",
         "documents": 32, "bound": "0.0894"}
    ]  # fmt: skip
    assert "Blind audit" in (tmp_path / "with" / "REPORT.md").read_text("utf-8")


def test_a_route_with_no_label_keeps_the_rate(tmp_path: Path) -> None:
    """The last audit document also admits ``other``, and no label covers it. The route of
    ``other`` has an admitted value and no label, so the rate stays 0.1."""
    case = Case(tmp_path)
    profile = {**PROFILE, "schema": {"fields": {"items": {"type": "integer"},
                                                "other": {"type": "integer"}}}}  # fmt: skip
    case.profile.write_text(json.dumps(profile), "utf-8")
    digest = check_profile(profile).sha256
    (case.audit / "docs" / "a30.txt").write_text("Items: 130\nOther: 730\n", "utf-8")
    cand = [
        {"id": "c1", "field": "items", "value": 130, "evidence": {"text": "130"}},
        {"id": "c2", "field": "other", "value": 730, "evidence": {"text": "730"}},
    ]
    (case.audit / "candidates" / "a30.json").write_text(json.dumps(cand), "utf-8")
    entries = [{**e, "profile": digest} for e in case.entries]
    entries[-1]["items"] = 2  # 29 items before it, so the pick has all 30 documents
    case.write_log(entries)
    case.labels = [{**x, "profile": digest} for x in case.labels]
    case.write_labels()
    report = case.run("out")
    items = report["fields"]["items"]["routes"]["checked"]
    other = report["fields"]["other"]["routes"]["checked"]
    assert (items["admitted"], items["unscored"], items["status"]) == (32, 0, "measured")
    assert (other["admitted"], other["unscored"], other["status"]) == (0, 1, "draft")
    a = report["audit"]
    assert (a["picked"], a["admitted"], a["rate"], a["alerts"]) == (30, 30, "0.1", [])


def test_the_rate_comes_from_the_profile_of_the_log_and_not_from_the_draft(
    tmp_path: Path,
) -> None:
    """The profile clears a key judgment at 0.5. The split has no calibration document, so the
    draft has no clear threshold. Each of the 30 audit documents has a cleared value that its
    label calls wrong. The draft admits none of them. The profile of the log admits each one,
    so the rate stays 0.1 and the cleared route gives an alert."""
    vector = Path(__file__).parent / "vectors" / "calibrate" / "two-routes"
    src = tmp_path / "in"
    shutil.copytree(vector, src)
    gold = src / "gold"
    for sub in ("docs", "candidates", "judgments"):
        for f in (gold / sub).iterdir():
            if f.stem != "t1":  # t1 has a right total and a right standard rate, both checked
                f.unlink()
    labels = json.loads((gold / "labels.json").read_text("utf-8"))
    labels["labels"] = {"t1": labels["labels"]["t1"]}
    (gold / "labels.json").write_text(json.dumps(labels), "utf-8")
    split = {"groundgate_split": 1, "documents": {"t1": "test"}}
    (src / "split.json").write_text(json.dumps(split), "utf-8")
    digest = check_profile(json.loads((src / "profile.json").read_text("utf-8"))).sha256
    folder = tmp_path / "audit"
    for sub in ("docs", "candidates", "judgments"):
        (folder / sub).mkdir(parents=True)
    (folder / "audit.json").write_text(json.dumps({"groundgate_audit": 1, "seed": SEED}), "utf-8")
    log, given = [], []
    for i in range(1, 31):
        name = f"a{i:02d}"
        for sub, end in (("docs", "txt"), ("candidates", "json"), ("judgments", "json")):
            # c1: the judge clears the standard rate 10 with p 0.9
            shutil.copy(vector / "gold" / sub / f"c1.{end}", folder / sub / f"{name}.{end}")
        log.append({"entry": "document", "document": name, "profile": digest, "items": 1})
        given.append({**_label(name, "11"), "profile": digest, "field": "rate",
                      "key": "standard"})  # fmt: skip
    (folder / "log.jsonl").write_text("".join(jcs(e) + "\n" for e in log), "utf-8")
    (folder / "labels.jsonl").write_text("".join(jcs(x) + "\n" for x in given), "utf-8")
    main(["measure", "--profile", str(src / "profile.json"), "--gold", str(gold),
          "--split", str(src / "split.json"), "--out", str(tmp_path / "out"), "--target", "0.1",
          "--date", "2026-11-15", "--audit", str(folder)])  # fmt: skip
    report = json.loads((tmp_path / "out" / "report.json").read_text("utf-8"))
    assert report["operating_point"]["KEY_NOT_AT_VALUE"] is None
    draft = report["fields"]["rate"]["routes"]["cleared"]
    assert (draft["admitted"], draft["errors"]) == (0, 0)  # the draft clears no value
    a = report["audit"]
    rows = {(x["field"], x["route"]): x for x in a["routes"]}
    assert sorted(rows) == [("rate", "checked"), ("rate", "cleared"), ("total", "checked")]
    cleared = rows["rate", "cleared"]
    # 30 admitted values, each one wrong: the bound is 1
    assert (cleared["admitted"], cleared["errors"], cleared["unscored"]) == (30, 30, 0)
    assert (cleared["bound"], cleared["status"]) == ("1", "draft")
    assert (a["admitted"], a["rate"]) == (30, "0.1")
    assert {"field": "rate", "route": "cleared", "bound": "1"} in a["alerts"]
    text = (tmp_path / "out" / "REPORT.md").read_text("utf-8")
    assert "rate cleared: 30 admitted, 30 errors, 0 with no label, bound 1 (draft)." in text


def test_a_wrong_admitted_value_raises_the_rate_and_gives_an_alert(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = Case(tmp_path)
    case.labels[4] = _label("a05", "999")  # the blind label says that the admitted 105 is wrong
    case.write_labels()
    report = case.run("out")
    checked = report["fields"]["items"]["routes"]["checked"]
    assert (checked["admitted"], checked["errors"], checked["status"]) == (32, 1, "draft")
    assert Decimal(checked["bound"]) >= Decimal("0.1")
    a = report["audit"]
    assert a["rate"] == "0.1"
    assert a["alerts"] == [{"field": "items", "route": "checked", "bound": checked["bound"]}]
    assert "alert: the bound of 'items' on the route checked" in capsys.readouterr().out


def test_the_last_label_of_a_field_counts(tmp_path: Path) -> None:
    case = Case(tmp_path)
    case.labels.insert(0, _label("a05", "999"))  # replaced by the later, right label
    case.write_labels()
    assert case.run("out")["fields"]["items"]["routes"]["checked"]["errors"] == 0


def test_a_label_outside_the_pick_stops_the_measure(tmp_path: Path) -> None:
    case = Case(tmp_path)
    # after 30 picked items, the hash decides: find a document that the pick leaves out
    name = next(
        n for n in (f"b{i:02d}" for i in range(1, 100))
        if not audit.audit_picked(audit.pick_hash(SEED, DIGEST, n), "0.1")
    )  # fmt: skip
    entry = {"entry": "document", "document": name, "profile": DIGEST, "items": 1}
    case.write_log([*case.entries, entry])
    assert name not in {p["document"] for p in audit.pick(SEED, case.entries)}
    _document(case.audit, name, 777)
    case.labels.append(_label(name, "777"))
    case.write_labels()
    with pytest.raises(SystemExit, match="not in the blind audit pick"):
        case.run("out")
    case.labels[-1] = _label("never-logged", "1")
    case.write_labels()
    with pytest.raises(SystemExit, match="not in the blind audit pick"):
        case.run("out2")


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"format": "answer@1", "task": "t", "reviewer": "ana", "verdict": "confirm"},
         "members of format 1 only"),
        ({**_label("a01", "101"), "approver": "bo", "decision": "approved"},
         "members of format 1 only"),
        (_label("a01", "101", profile="sha256:" + "f" * 64), "another profile than its log entry"),
    ],
)  # fmt: skip
def test_a_review_answer_or_an_approval_is_not_a_label(
    tmp_path: Path, record: dict[str, Any], message: str
) -> None:
    case = Case(tmp_path)
    case.labels.append(record)
    case.write_labels()
    with pytest.raises(SystemExit, match=message):
        case.run("out")


def test_measure_has_no_input_for_review_answers() -> None:
    """The bound reads the gold set and the audit set only: no store, no answer log."""
    source = Path(audit.__file__).with_name("measure.py").read_text("utf-8")
    for word in ("groundgate.review", "groundgate.store", "answers", "resolution"):
        assert word not in source, word
    source = Path(audit.__file__).read_text("utf-8")
    assert "groundgate.store" not in source and "resolve" not in source


def test_labels_of_another_profile_version_and_period_do_not_count(tmp_path: Path) -> None:
    case = Case(tmp_path)
    other = "sha256:" + "e" * 64
    entry = {"entry": "document", "document": "old-1", "profile": other, "items": 1}
    case.write_log([*case.entries, entry])
    case.labels.append(_label("old-1", "5", profile=other))
    case.labels[0] = _label("a01", "101", date="2026-10-01")
    case.write_labels()
    a = case.run("all")["audit"]
    assert (a["documents"], a["admitted"], a["skipped"], a["rate"]) == (30, 30, 1, "0.02")
    a = case.run("since", "--audit-since", "2026-11-01")["audit"]
    assert (a["since"], a["documents"], a["admitted"], a["skipped"]) == ("2026-11-01", 29, 29, 2)
    assert a["rate"] == "0.1"  # 29 admitted values are fewer than the minimum
    with pytest.raises(SystemExit, match="--audit-since"):
        case.run("bad", "--audit-since", "2026-13-01")
    with pytest.raises(SystemExit, match="--audit-since"):
        case.run("bad2", "--audit-since", "2026-11-01", audit_set=False)


def test_the_audit_steps(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    case = Case(tmp_path)
    receipt = admit(
        "Items: 7\n", None,
        [{"id": "c1", "field": "items", "value": 7, "evidence": {"text": "7"}},
         {"id": "c2", "field": "items", "value": 7, "evidence": {"text": "7"}}],
        profile=PROFILE,
    ).to_dict()  # fmt: skip
    assert audit.items(receipt) == 1  # two candidates with one value are one admitted value
    (tmp_path / "receipt.json").write_text(json.dumps(receipt), "utf-8")
    add = ["audit", "add", "--audit", str(case.audit), "--receipt", str(tmp_path / "receipt.json")]
    main([*add, "--name", "new-1"])
    assert capsys.readouterr().out == "added new-1 with 1 items\n"
    with pytest.raises(SystemExit, match="two entries for new-1"):
        main([*add, "--name", "new-1"])
    with pytest.raises(SystemExit, match="wrong or a missing member"):
        main([*add, "--name", "../x"])
    last = (case.audit / "log.jsonl").read_text("utf-8").splitlines()[-1]
    assert json.loads(last) == {"entry": "document", "document": "new-1", "profile": DIGEST,
                                "items": 1}  # fmt: skip

    main(["audit", "pick", "--audit", str(case.audit), "--profile", str(case.profile),
          "--out", str(tmp_path / "pick.json")])  # fmt: skip
    picked = json.loads((tmp_path / "pick.json").read_text("utf-8"))
    assert [p["document"] for p in picked["picks"]][:30] == case.names
    assert picked["tasks"][0] == {"groundgate_audit_task": 1, "document": "a01",
                                  "profile": DIGEST, "field": "items", "key": None}  # fmt: skip
    assert len(picked["tasks"]) == len(picked["picks"])
    main(["audit", "pick", "--audit", str(case.audit)])
    assert json.loads(capsys.readouterr().out)["picks"] == picked["picks"]  # a replay

    case.run("out")
    capsys.readouterr()
    main(["audit", "rate", "--audit", str(case.audit),
          "--report", str(tmp_path / "out" / "report.json")])  # fmt: skip
    assert capsys.readouterr().out == f"the audit rate of {DIGEST} is 0.02\n"
    last = (case.audit / "log.jsonl").read_text("utf-8").splitlines()[-1]
    assert json.loads(last) == {"entry": "rate", "profile": DIGEST, "rate": "0.02"}
    case.run("gold-only", audit_set=False)
    with pytest.raises(SystemExit, match="not a report of a measure with --audit"):
        main(["audit", "rate", "--audit", str(case.audit),
              "--report", str(tmp_path / "gold-only" / "report.json")])  # fmt: skip
    other = tmp_path / "other"
    other.mkdir()
    (other / "audit.json").write_text(json.dumps({"groundgate_audit": 1, "seed": "x"}), "utf-8")
    with pytest.raises(SystemExit, match="another seed"):
        main(["audit", "rate", "--audit", str(other),
              "--report", str(tmp_path / "out" / "report.json")])  # fmt: skip
    assert not (other / "log.jsonl").exists()


def test_a_receipt_with_no_profile_has_no_entry() -> None:
    receipt = admit("Items: 7\n", {"fields": {"items": {"type": "integer"}}}, []).to_dict()
    with pytest.raises(audit.AuditError, match="names no profile"):
        audit.document_entry("d", receipt)


@pytest.mark.parametrize("name", ["log.jsonl", "labels.jsonl", "audit.json", "docs"])
def test_an_audit_set_holds_its_own_files(tmp_path: Path, name: str) -> None:
    case = Case(tmp_path)
    target = case.audit / name
    moved = tmp_path / f"moved-{name}"
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(SystemExit, match=r"link|not a regular file"):
        case.run("out")
