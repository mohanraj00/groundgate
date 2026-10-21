"""The item builder and the scorer of the Codex judge. No test calls a model."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).parent


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


items = _load("codex_judge_items", "items.py")
score = _load("codex_judge_score", "score.py")

TEXT = "Prix: café 12,5 V\nSupply voltage max 3.6 V\n"
FIELD = TEXT.encode().index(b"Supply voltage")  # a byte offset after a two-byte character


def sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def decision(cid: str, field: str, value: str, outcome: str) -> dict[str, Any]:
    return {
        "candidate_id": cid,
        "codes": [],
        "field": field,
        "key": None,
        "origin": "core_receipt",
        "outcome": outcome,
        "unit": "V",
        "value": value,
    }


def receipt(d: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    return {k: d[k] for k in ("candidate_id", "field", "key", "outcome", "unit", "value")} | {
        "source": "document",
        "evidence": {"start": start, "end": end},
        "parts": [{"role": "field", "start": FIELD, "end": FIELD + 14, "passed": False}],
    }


def fixture(tmp_path: Path, split: str = "development") -> tuple[dict[str, Any], ...]:
    raw = TEXT.encode()
    b = raw.index(b"3.6")
    decisions = [
        decision("c1", "supply_voltage_max", "3.6", "needs_verification"),
        decision("c2", "supply_voltage_max", "12.5", "needs_verification"),
        decision("c3", "supply_voltage_min", "1.8", "admitted"),
        decision("c4", "supply_voltage_min", "1.7", "needs_verification"),
        decision("c5", "supply_current_typ", "5", "rejected"),
    ]
    spans = [(b, b + 3), (raw.index(b"12,5"), raw.index(b"12,5") + 4), (0, 1), (0, 1), (0, 1)]
    run = {"split": split, "documents": [{"id": "component-x", "decisions": decisions}]}
    manifest = {
        "documents": [
            {
                "id": "component-x",
                "kind": "component",
                "split": split,
                "text_sha256": sha(raw),
                "request_context": {"subject": "AB1", "scope": "Recommended conditions."},
            }
        ],
        "schemas": {
            "component": {
                "fields": {
                    "supply_voltage_max": {"description": "Max supply.", "unit": "V"},
                    "supply_voltage_min": {"description": "Min supply.", "unit": "V"},
                    "supply_current_typ": {"description": "Current.", "unit": "mA"},
                }
            }
        },
    }
    results = tmp_path / "results"
    (results / "component-x").mkdir(parents=True)
    cached = {
        "output": {"decisions": decisions},
        "receipt": {"decisions": [receipt(d, *s) for d, s in zip(decisions, spans, strict=True)]},
    }
    (results / "component-x" / "result.json").write_text(json.dumps(cached))
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "component-x.txt").write_bytes(raw)
    return run, manifest, {"results": results, "texts": texts}


def test_a_field_with_an_admitted_value_or_no_review_is_not_an_item(tmp_path: Path) -> None:
    run, *_ = fixture(tmp_path)
    got = items.review_fields(run["documents"][0]["decisions"])
    assert list(got) == ["supply_voltage_max"]
    assert [d["candidate_id"] for d in got["supply_voltage_max"]] == ["c1", "c2"]


def test_build_gives_code_point_spans_and_the_whole_text(tmp_path: Path) -> None:
    run, manifest, p = fixture(tmp_path)
    built = items.build(run, manifest, p["results"], p["texts"])
    assert len(built) == 1
    it = built[0]
    assert it["id"] == "component-x/supply_voltage_max"
    assert it["text"] == TEXT
    assert it["description"] == "Max supply. The request: AB1. Recommended conditions."
    first = it["candidates"][0]
    a, b = next(s for s in first["spans"] if TEXT[s[0] : s[1]] == "3.6")
    assert TEXT[a:b] == "3.6"
    assert [TEXT[s[0] : s[1]] for s in it["candidates"][1]["spans"]] == [
        "12,5",
        "Supply voltage",
    ]
    assert first["scale"] is None and first["unit"] == "V"


def test_build_refuses_a_heldout_run_without_the_flag(tmp_path: Path) -> None:
    run, manifest, p = fixture(tmp_path, split="heldout")
    with pytest.raises(items.ItemsError, match="needs approval"):
        items.build(run, manifest, p["results"], p["texts"])
    assert items.build(run, manifest, p["results"], p["texts"], allow_heldout=True)


def test_build_refuses_another_text_or_other_decisions(tmp_path: Path) -> None:
    run, manifest, p = fixture(tmp_path)
    (p["texts"] / "component-x.txt").write_bytes(TEXT.encode() + b" ")
    with pytest.raises(items.ItemsError, match="reader text"):
        items.build(run, manifest, p["results"], p["texts"])
    run, manifest, p = fixture(tmp_path / "b")
    changed = copy.deepcopy(run)
    changed["documents"][0]["decisions"][0]["value"] = "3.7"
    with pytest.raises(items.ItemsError, match="differ"):
        items.build(changed, manifest, p["results"], p["texts"])


def test_build_refuses_a_document_of_another_split(tmp_path: Path) -> None:
    run, manifest, p = fixture(tmp_path)
    manifest["documents"][0]["split"] = "heldout"
    with pytest.raises(items.ItemsError, match="manifest puts"):
        items.build(run, manifest, p["results"], p["texts"])


def item(kind: str, options: list[str], label: list[str] | None) -> dict[str, Any]:
    return {
        "kind": kind,
        "type": "number",
        "options": {score.sig(v, "V", "number") for v in options},
        "label": None if label is None else {score.sig(v, "V", "number") for v in label},
    }


def ans(value: str | None, p: float) -> dict[str, Any]:
    choice = None if value is None else {"value": value, "scale": None, "unit": "V"}
    return {"option": "none" if value is None else "c1", "choice": choice, "confidence": p}


def test_counts_clears_escapes_and_bins() -> None:
    rows = [
        (item("a", ["1", "2"], ["1"]), ans("1", 0.99)),  # right clear at every t
        (item("a", ["1", "2"], ["1"]), ans("2", 0.75)),  # escape at 0.5 and 0.7
        (item("a", ["3"], []), ans("3", 0.95)),  # escape on an absent slot up to 0.95
        (item("a", ["4"], ["5"]), ans(None, 0.8)),  # a right none
        (item("a", ["1.0"], ["1"]), ans("1.0", 0.6)),  # the match rule: 1.0 is 1
    ]
    got = score.counts(rows)
    assert got["right_candidate"] == 3
    assert got["choices"] == {"right": 2, "wrong": 2, "none_right": 1, "none_wrong": 0}
    assert got["by_threshold"]["0.5"] | {} == {
        "clears_right": 2,
        "escapes": 2,
        "escape_rate_upper_95": score.upper_95(2, 4),
    }
    assert got["by_threshold"]["0.8"]["clears_right"] == 1
    assert got["by_threshold"]["0.8"]["escapes"] == 1
    assert got["by_threshold"]["0.99"]["escapes"] == 0
    assert sum(b["items"] for b in got["bins"]) == 5
    assert sum(b["correct"] for b in got["bins"]) == 3


def test_a_choice_that_is_not_a_candidate_is_refused() -> None:
    with pytest.raises(score.ScoreError, match="not a candidate"):
        score.chosen(item("a", ["1"], ["1"]), ans("9", 0.9))


def answers_file(items_: dict[str, Any], picks: dict[str, Any], run: int = 1) -> dict[str, Any]:
    return {
        "format": "codex-judge-answers/1",
        "meta": {
            "model": "m",
            "effort": "low",
            "run": run,
            "codex_versions": ["codex-cli 0"],
            "prompts_sha256": "p",
            "template_sha256": "t",
            "manifest_sha256": "x",
        },
        "answers": picks,
        "calls": len(picks),
    }


def test_the_threshold_is_the_lowest_t_under_the_ceiling() -> None:
    its = {f"d/{n}": item("a", ["1", "2"], ["1"]) for n in range(80)}
    picks = {i: ans("1", 0.99) for i in its}
    picks["d/0"] = ans("2", 0.6)  # one escape below 0.7
    loop = {
        "runs": {
            "runner": {
                "total": {"miss_rate": {"k": 90, "n": 100}, "escapes": 1},
                "by_kind": {"a": {"miss_rate": {"k": 90, "n": 100}, "escapes": 1}},
            }
        }
    }
    got = score.judge_scores(answers_file(its, picks), its, loop)
    row = got["by_ceiling"]["0.05"]
    assert row["threshold"] == 0.7
    assert row["total"]["clears_right"] == 79
    assert row["total"]["miss_with_clears"] == {"k": 11, "n": 100}
    assert row["total"]["escapes_with_clears"] == 1
    assert got["by_ceiling"]["0.2"]["threshold"] == 0.5


def test_unclear_slots_are_left_out() -> None:
    its = {"d/a": item("a", ["1"], None), "d/b": item("a", ["1"], ["1"])}
    loop = {
        "runs": {
            "runner": {
                "total": {"miss_rate": {"k": 1, "n": 1}, "escapes": 0},
                "by_kind": {"a": {"miss_rate": {"k": 1, "n": 1}, "escapes": 0}},
            }
        }
    }
    got = score.judge_scores(
        answers_file(its, {"d/a": ans("1", 1.0), "d/b": ans("1", 1.0)}), its, loop
    )
    assert got["unclear"] == 1
    assert got["total"]["items"] == 1


def test_compare_counts_the_same_wrong_candidate() -> None:
    its = {"d/a": item("a", ["1", "2"], ["1"]), "d/b": item("a", ["1", "2"], ["1"])}
    a = answers_file(its, {"d/a": ans("2", 0.9), "d/b": ans("1", 0.9)})
    b = answers_file(its, {"d/a": ans("2", 0.6), "d/b": ans("2", 0.9)}, run=2)
    got = score.compare(a, b, its)
    assert (got["same_option"], got["wrong_both"], got["same_wrong"]) == (1, 1, 1)
    assert got["clears"]["0.8"] == {"both": 1, "first_only": 1, "second_only": 0}


def test_the_committed_results_come_from_the_committed_answers() -> None:
    out = score.SET / "judge"
    answers = sorted((out / "answers").glob("*.json"))
    if not answers:
        pytest.skip("no committed answers")
    score.main(["--answers", *map(str, answers), "--out", str(out), "--check"])
