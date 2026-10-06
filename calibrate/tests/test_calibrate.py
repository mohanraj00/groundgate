"""The calibration tool from sample to report, on hand-written text, with a fake judge."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from groundgate_calibrate import cli, judges, label
from groundgate_calibrate import questions as q
from groundgate_calibrate.stats import needed, pick, upper_95

from groundgate.canonical import SPEC_VERSION

TEXT = "In fiscal 2024 sales fell.\nRevenue was 4,100.\nIn fiscal 2025 revenue was 5,200.\n"
SCHEMA = {
    "fields": {
        "revenue": {"type": "number", "multiple": True, "keys": ["fiscal 2025", "fiscal 2024"]}
    }
}


def evidence(text: str, s: str) -> dict[str, int]:
    i = text.encode().index(s.encode())
    return {"start": i, "end": i + len(s.encode())}


def inputs(tmp: Path, docs: int) -> tuple[Path, Path, Path]:
    d, c = tmp / "docs", tmp / "cands"
    d.mkdir()
    c.mkdir()
    for n in range(docs):
        (d / f"doc{n}.txt").write_text(TEXT)
        cands = [
            {"field": "revenue", "value": "4100", "key": "fiscal 2025",
             "evidence": evidence(TEXT, "Revenue was 4,100.")},
            {"field": "revenue", "value": "5200", "key": "fiscal 2025",
             "evidence": evidence(TEXT, "revenue was 5,200")},
        ]  # fmt: skip
        (c / f"doc{n}.json").write_text(json.dumps(cands))
    s = tmp / "schema.json"
    s.write_text(json.dumps(SCHEMA))
    return d, c, s


def test_upper_95_and_the_clears_that_each_ceiling_needs() -> None:
    assert upper_95(0, 0) == 1.0
    assert upper_95(0, 59) < 0.05 <= upper_95(0, 58)
    assert [needed(c) for c in (0.05, 0.1, 0.2)] == [59, 29, 14]
    assert upper_95(3, 20) == 0.3437  # the same as the bench judges' bound on small counts
    assert 0.1 < upper_95(960, 10000) < 0.102  # no underflow on a large count
    bound = {0.5: 0.3, 0.7: 0.04, 0.9: 0.01}.__getitem__
    assert pick((0.5, 0.7, 0.9), bound, 0.05, "lowest") == 0.7
    assert pick((0.5, 0.7, 0.9), bound, 0.05, "highest") == 0.9
    assert pick((0.5,), bound, 0.05, "lowest") is None


def test_sample_takes_key_flags_and_admitted_values() -> None:
    cands = json.loads(json.dumps([
        {"field": "revenue", "value": "4100", "key": "fiscal 2025",
         "evidence": evidence(TEXT, "Revenue was 4,100.")},
        {"field": "revenue", "value": "5200", "key": "fiscal 2025",
         "evidence": evidence(TEXT, "revenue was 5,200")},
    ]))  # fmt: skip
    (key,) = q.sample("key", "d", TEXT, SCHEMA, cands)
    assert key["key"] == "fiscal 2025" and key["keys"] == ["fiscal 2025", "fiscal 2024"]
    a, b = key["mark"]
    assert TEXT[a:b] == "4,100"  # the value, not the whole evidence
    (field,) = q.sample("field", "d", TEXT, SCHEMA, cands)
    assert field["id"] == "d:1"
    st, qs = q.prompt("key", TEXT, key, "The text is from a 10-K filing.", {})
    assert "[4,100]" in st
    assert qs["key"]["criteria"] == {
        "k1": "fiscal 2025",
        "k2": "fiscal 2024",
        "none": qs["key"]["criteria"]["none"],
    }
    assert qs["key"]["instructions"].startswith("The text is from a 10-K filing. The text marks")


def test_a_label_is_checked_and_the_page_hides_the_candidates_key() -> None:
    it = {
        "id": "d:0",
        "keys": ["fiscal 2025", "fiscal 2024"],
        "mark": [37, 42],
        "key": "fiscal 2025",
    }
    assert q.valid_label("key", it, ["fiscal 2024"])
    assert q.valid_label("key", it, None)
    assert not q.valid_label("key", it, ["fiscal 2023"])
    assert q.valid_label("field", it, False)
    assert not q.valid_label("field", it, "no")
    html = label.page(TEXT, [it, {**it, "id": "d:1", "mark": [38, 44]}])
    assert html.count("<mark") == 1 and 'data-ids="d:0 d:1"' in html
    assert f">{TEXT[37:44]}</mark>" in html  # one mark over both values


class Fake:
    id = "fake"
    digest = "fake-1"

    def __init__(self, answers: dict[str, dict[str, Any]]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def ask(self, state: str, qs: dict[str, Any]) -> dict[str, Any]:
        self.asked.append(state)
        return {k: self.answers[k] for k in qs}


def fake(answers: dict[str, dict[str, Any]]) -> Any:
    return lambda: Fake(answers)


def test_the_steps_from_sample_to_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d, c, s = inputs(tmp_path, 4)
    work = tmp_path / "work"
    run = ["--work", str(work)]
    cli.main(["sample", *run, "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--question", "key"])  # fmt: skip
    items = json.loads((work / "items.json").read_text())
    assert len(items) == 4
    monkeypatch.setitem(
        judges.BUILT_IN, "fake", fake({"key": {"choice": "k1", "confidence": 0.97}})
    )
    with pytest.raises(SystemExit, match=r"split\.json"):
        cli.main(["ask", *run, "--judge", "fake"])
    cli.main(["split", *run])
    with pytest.raises(SystemExit, match="label before a judge answers"):
        cli.main(["ask", *run, "--judge", "fake"])
    labels = {it["id"]: ["fiscal 2025"] for it in items}
    (work / "labels.json").write_text(json.dumps(labels))
    cli.main(["ask", *run, "--judge", "fake"])
    with pytest.raises(SystemExit, match="already"):
        cli.main(["split", *run])
    (work / "labels.json").write_text(json.dumps({**labels, items[0]["id"]: []}))
    with pytest.raises(SystemExit, match="labels changed"):
        cli.main(["report", *run])
    (work / "labels.json").write_text(json.dumps(labels))
    split = json.loads((work / "split.json").read_text())
    moved = {k: "calibration" for k in split}
    (work / "split.json").write_text(json.dumps(moved))
    with pytest.raises(SystemExit, match="split changed"):
        cli.main(["report", *run])
    (work / "split.json").write_text(json.dumps(split, indent=1, sort_keys=True) + "\n")
    cli.main(["report", *run])
    rep = json.loads((work / "report.json").read_text())["judges"]["fake"]
    parts = json.loads((work / "split.json").read_text())
    cal = sum(v == "calibration" for v in parts.values())
    assert rep["calibration"]["by_threshold"]["0.95"]["clears_right"] == cal
    assert rep["calibration"]["by_threshold"]["0.99"]["clears_right"] == 0
    assert "Calibration report" in (work / "REPORT.md").read_text()
    cli.main(["report", *run, "--check"])


def test_field_scoring_catches_wrong_values_and_counts_right_ones_doubted() -> None:
    items = [{"id": f"d{n}:0", "doc": f"d{n}"} for n in range(4)]
    labels = {"d0:0": True, "d1:0": False, "d2:0": True, "d3:0": None}
    parts = {it["id"]: "calibration" for it in items}
    answers = {"d0:0": {"p": 0.9}, "d1:0": {"p": 0.02}, "d2:0": {"p": 0.04}, "d3:0": {"p": 0.0}}
    s = q.score("field", items, labels, parts, answers)
    cal = s["calibration"]
    assert (cal["items"], cal["right"], cal["wrong"]) == (3, 2, 1)
    assert cal["by_threshold"]["0.05"] == {
        "wrong_caught": 1,
        "right_doubted": 1,
        "right_doubted_upper_95": upper_95(1, 2),
    }
    assert s["by_ceiling"]["0.05"]["threshold"] is None


def test_a_document_without_its_candidates_stops_the_sample(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path, 2)
    (c / "doc1.json").unlink()
    with pytest.raises(SystemExit, match="write"):
        cli.main(["sample", "--work", str(tmp_path / "w"), "--docs", str(d), "--candidates",
                  str(c), "--schema", str(s), "--question", "key"])  # fmt: skip


def test_the_policy_blocks_use_the_names_of_the_design() -> None:
    meta = {"judge": "jev", "model": "jev-1.13.0"}
    assert cli.policy("key", meta, 0.9)["judge"]["clear"] == {"KEY_NOT_AT_VALUE": 0.9}
    assert cli.policy("field", meta, 0.2)["judge"]["doubt"] == {"field_match": 0.2}


def test_a_text_that_is_not_nfc_stops_the_sample(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path, 1)
    (d / "doc0.txt").write_text("Cafe\u0301 " + TEXT)
    with pytest.raises(SystemExit, match="NFC"):
        cli.main(["sample", "--work", str(tmp_path / "w"), "--docs", str(d), "--candidates",
                  str(c), "--schema", str(s), "--question", "key"])  # fmt: skip


def test_answers_to_other_prompts_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d, c, s = inputs(tmp_path, 2)
    work = tmp_path / "work"
    run = ["--work", str(work)]
    cli.main(["sample", *run, "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--question", "key"])  # fmt: skip
    monkeypatch.setitem(judges.BUILT_IN, "fake", fake({"key": {"choice": "k1", "confidence": 0.9}}))
    cli.main(["split", *run])
    cfg = json.loads((work / "config.json").read_text())
    (work / "config.json").write_text(json.dumps({**cfg, "context": "Another context."}))
    with pytest.raises(SystemExit, match="changed after the split"):
        cli.main(["ask", *run, "--judge", "fake"])
    (work / "config.json").write_text(json.dumps(cfg))
    labels = {i["id"]: ["fiscal 2025"] for i in json.loads((work / "items.json").read_text())}
    (work / "labels.json").write_text(json.dumps(labels))
    cli.main(["ask", *run, "--judge", "fake"])
    rec = json.loads((work / "answers-fake.json").read_text())
    rec["meta"]["prompts_sha256"] = "0" * 64
    (work / "answers-fake.json").write_text(json.dumps(rec))
    with pytest.raises(SystemExit, match="other prompts"):
        cli.main(["report", *run])


def test_a_sample_with_no_items_stops(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path, 1)
    (c / "doc0.json").write_text("[]")
    with pytest.raises(SystemExit, match="nothing to label"):
        cli.main(["sample", "--work", str(tmp_path / "w"), "--docs", str(d), "--candidates",
                  str(c), "--schema", str(s), "--question", "key"])  # fmt: skip


def test_a_work_directory_of_another_spec_is_refused(tmp_path: Path) -> None:
    d, c, s = inputs(tmp_path, 2)
    work = tmp_path / "work"
    cli.main(["sample", "--work", str(work), "--docs", str(d), "--candidates", str(c),
              "--schema", str(s), "--question", "key"])  # fmt: skip
    cfg = json.loads((work / "config.json").read_text())
    (work / "config.json").write_text(json.dumps({**cfg, "spec": "0.2"}))
    with pytest.raises(SystemExit, match=r"sampled under spec 0\.2"):
        cli.main(["split", "--work", str(work)])


def test_a_plug_in_judge_comes_from_an_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    class EP:
        def __init__(self, name: str) -> None:
            self.name = name

        def load(self) -> Any:
            return fake({})

    monkeypatch.setattr(judges, "entry_points", lambda group: [EP("fake")])
    assert judges.load("fake").digest == "fake-1"
    monkeypatch.setattr(judges, "entry_points", lambda group: [EP("mine")])
    with pytest.raises(SystemExit, match="must be equal"):
        judges.load("mine")
    with pytest.raises(SystemExit, match="no judge"):
        judges.load("other")
    monkeypatch.setattr(judges, "entry_points", lambda group: [EP("jev")])
    with pytest.raises(SystemExit, match="two judges"):
        judges.load("jev")

    class Broken(EP):
        def load(self) -> Any:
            raise ImportError("a broken plug-in")

    monkeypatch.setattr(judges, "entry_points", lambda group: [Broken("broken"), EP("fake")])
    assert judges.load("fake").id == "fake"  # the broken plug-in is never imported


def calibrated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path, Path]:
    """A key calibration of the fake judge on 2 documents, and its inputs."""
    d, c, s = inputs(tmp_path, 2)
    for n in range(2):  # judged candidates need ids
        cands = json.loads((c / f"doc{n}.json").read_text())
        (c / f"doc{n}.json").write_text(
            json.dumps([{**x, "id": f"c{i}"} for i, x in enumerate(cands)])
        )
    work = tmp_path / "work"
    run = ["--work", str(work)]
    cli.main(["sample", *run, "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--question", "key"])  # fmt: skip
    monkeypatch.setitem(
        judges.BUILT_IN, "fake", fake({"key": {"choice": "k1", "confidence": 0.97}})
    )
    cli.main(["split", *run])
    labels = {i["id"]: ["fiscal 2025"] for i in json.loads((work / "items.json").read_text())}
    (work / "labels.json").write_text(json.dumps(labels))
    cli.main(["ask", *run, "--judge", "fake"])
    return d, c, s, work


def test_judge_writes_recorded_judgments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d, c, s, work = calibrated(tmp_path, monkeypatch)
    policy = tmp_path / "policy.json"
    block = {"id": "fake", "digest": "fake-1", "clear": {"KEY_NOT_AT_VALUE": 0.9}}
    policy.write_text(json.dumps({"judge": block}))
    out = tmp_path / "judgments"
    run = ["--docs", str(d), "--candidates", str(c), "--schema", str(s), "--policy", str(policy)]
    cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])
    js = json.loads((out / "doc0.json").read_text())
    assert js == [
        {"candidate_id": "c0", "judge": {"id": "fake", "digest": "fake-1"}, "question": "key",
         "answer": "fiscal 2025", "p": 0.97}
    ]  # fmt: skip
    # a field threshold without a field calibration is refused
    policy.write_text(json.dumps({"judge": {**block, "doubt": {"field_match": 0.2}}}))
    with pytest.raises(SystemExit, match="give its calibration"):
        cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])
    # a judged candidate with an id that a judgment cannot name is refused
    policy.write_text(json.dumps({"judge": block}))
    good = (c / "doc0.json").read_text()
    cands = json.loads(good)
    (c / "doc0.json").write_text(json.dumps([{**cands[0], "id": True}, *cands[1:]]))
    with pytest.raises(SystemExit, match="string or int id"):
        cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])
    (c / "doc0.json").write_text(good)
    # a calibration whose context changed after its run is refused
    cfg = json.loads((work / "config.json").read_text())
    (work / "config.json").write_text(json.dumps({**cfg, "context": "Another context."}))
    policy.write_text(json.dumps({"judge": block}))
    with pytest.raises(SystemExit, match="calibrate again"):
        cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])
    (work / "config.json").write_text(json.dumps(cfg))
    # another model version is refused
    policy.write_text(json.dumps({"judge": {**block, "digest": "fake-2"}}))
    with pytest.raises(SystemExit, match="fake-2"):
        cli.main(["judge", *run, "--calibration", str(work), "--out", str(out)])


@pytest.mark.skipif(SPEC_VERSION < "0.4", reason="recorded judgments are spec 0.4 (#116)")
def test_recorded_judgments_clear_the_flag_in_groundgate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import groundgate as gg

    d, c, s, work = calibrated(tmp_path, monkeypatch)
    pol = {"judge": {"id": "fake", "digest": "fake-1", "clear": {"KEY_NOT_AT_VALUE": 0.9}}}
    (tmp_path / "policy.json").write_text(json.dumps(pol))
    out = tmp_path / "judgments"
    pol_path = str(tmp_path / "policy.json")
    cli.main(["judge", "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--policy", pol_path, "--calibration", str(work), "--out", str(out)])  # fmt: skip
    cands = json.loads((c / "doc0.json").read_text())
    js = json.loads((out / "doc0.json").read_text())
    r = gg.admit(TEXT, SCHEMA, cands, pol, judgments=js)
    (d0,) = [x for x in r.decisions if x.candidate_id == "c0"]
    assert (d0.outcome, d0.codes) == ("admitted", ("MODEL_CLEARED",))
