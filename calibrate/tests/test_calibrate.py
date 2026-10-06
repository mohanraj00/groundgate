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
    html = label.page(TEXT, [it, {**it, "id": "d:1"}])
    assert html.count("<mark") == 1 and 'data-ids="d:0 d:1"' in html


def fake(answers: dict[str, dict[str, Any]]) -> Any:
    def make() -> tuple[dict[str, str], judges.Ask]:
        def ask(st: str, qs: dict[str, Any]) -> dict[str, Any]:
            return {k: answers[k] for k in qs}

        return {"judge": "fake", "model": "fake-1"}, ask

    return make


def test_the_steps_from_sample_to_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d, c, s = inputs(tmp_path, 4)
    work = tmp_path / "work"
    run = ["--work", str(work)]
    cli.main(["sample", *run, "--docs", str(d), "--candidates", str(c), "--schema", str(s),
              "--question", "key"])  # fmt: skip
    items = json.loads((work / "items.json").read_text())
    assert len(items) == 4
    monkeypatch.setitem(cli.JUDGES, "fake", fake({"key": {"choice": "k1", "confidence": 0.97}}))
    with pytest.raises(SystemExit, match=r"split\.json"):
        cli.main(["ask", *run, "--judge", "fake"])
    cli.main(["split", *run])
    cli.main(["ask", *run, "--judge", "fake"])
    with pytest.raises(SystemExit, match="already"):
        cli.main(["split", *run])
    with pytest.raises(SystemExit, match="not labeled"):
        cli.main(["report", *run])
    labels = {it["id"]: ["fiscal 2025"] for it in items}
    (work / "labels.json").write_text(json.dumps(labels))
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
