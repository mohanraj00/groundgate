"""Learning-loop records on a synthetic set with one development and one held-out document."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from requested import loop
from requested.metrics import score_set

from groundgate import jcs

CODE = "sha256:" + "a" * 64
CONFIG = "sha256:" + "b" * 64


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def make_set(directory: Path) -> None:
    fields = {"amount": {"type": "number"}}
    manifest = {
        "schemas": {"kind": {"fields": fields}},
        "documents": [
            {"id": "dev", "kind": "kind", "split": "development"},
            {"id": "held", "kind": "kind", "split": "heldout"},
        ],
    }
    labels = {
        "status": "sealed",
        "documents": [
            {
                "id": i,
                "fields": [{"field": "amount", "status": "present", "values": [{"value": v}]}],
            }
            for i, v in (("dev", "5"), ("held", "7"))
        ],
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "labels.json").write_text(json.dumps(labels))


def dev_run(directory: Path, iteration: int, decisions: list[dict[str, Any]]) -> Path:
    """Write a development runner projection and its score into loop/NN."""
    header = {
        "manifest_sha256": digest(directory / "manifest.json"),
        "labels_sha256": digest(directory / "labels.json"),
        "configuration_sha256": CONFIG,
        "code_sha256": CODE,
    }
    run = {
        "manifest_sha256": header["manifest_sha256"],
        "labels_sha256": header["labels_sha256"],
        "binding_sha256": "sha256:" + hashlib.sha256(jcs(header).encode()).hexdigest(),
        "arm": "runner",
        "split": "development",
        "provenance": header,
        "documents": [
            {
                "id": "dev",
                "decisions": decisions,
                "not_found": [],
                "complete": True,
                "transport_error": False,
                "transport_retries": 0,
                "search_limit": 0,
            }
        ],
    }
    folder = directory / "loop" / f"{iteration:02}"
    (folder / "runs").mkdir(parents=True, exist_ok=True)
    (folder / "runs/runner.json").write_text(json.dumps(run))
    results = score_set(directory, "development", runs=folder / "runs")
    (folder / "results.json").write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    return folder


REVIEWS = [
    {"field": "amount", "value": "5", "outcome": "needs_verification", "codes": ["A", "B"]},
    {"field": "amount", "value": "6", "outcome": "needs_verification", "codes": ["A"]},
    {"field": "amount", "value": "6", "outcome": "rejected", "codes": ["C"]},
]
PROPOSE = {"change": "feedback", "reference": "#400", "summary": "Say which quote failed."}


def test_record_holds_the_six_steps_and_check_accepts_it(tmp_path: Path) -> None:
    make_set(tmp_path)
    dev_run(tmp_path, 1, REVIEWS)
    path = loop.record(tmp_path, 1, **PROPOSE)
    record = json.loads(path.read_text())
    assert record["run"]["split"] == "development"
    assert record["run"]["code_sha256"] == CODE
    assert record["run"]["documents"] == ["dev"]
    assert record["score"]["by_arm"]["runner"]["total"]["miss_rate"]["k"] == 1
    assert record["score"]["by_arm"]["runner"]["kind"]["search_limit_fields"] == 0
    # A rejected decision is not a review decision.
    assert record["diagnose"]["review_codes"] == {
        "runner": {
            "A": {"right": 1, "wrong": 1, "unclear": 0},
            "B": {"right": 1, "wrong": 0, "unclear": 0},
        }
    }
    assert record["calibrate"] is None and record["decide"] is None
    assert record["propose"] == PROPOSE
    assert len(loop.check(tmp_path)) == 1
    with pytest.raises(ValueError, match="next loop record"):
        loop.record(tmp_path, 1, **PROPOSE)


def test_second_iteration_decides_the_first_change(tmp_path: Path) -> None:
    make_set(tmp_path)
    dev_run(tmp_path, 1, REVIEWS)
    loop.record(tmp_path, 1, **PROPOSE)
    dev_run(tmp_path, 2, REVIEWS[:1])
    answers = tmp_path / "loop/02/answers.json"
    answers.write_text("{}")
    with pytest.raises(ValueError, match="decide"):
        loop.record(tmp_path, 2, change=None, reference=None, summary=None)
    path = loop.record(
        tmp_path, 2, change=None, reference=None, summary=None, decide="keep", calibration=answers
    )
    record = json.loads(path.read_text())
    assert record["decide"] == {"previous": "loop/01.json", "outcome": "keep"}
    assert record["calibrate"]["answers"] == "loop/02/answers.json"
    assert len(loop.check(tmp_path)) == 2
    answers.write_text('{"changed": 1}')
    with pytest.raises(ValueError, match="calibration answers"):
        loop.check(tmp_path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r["run"].update(split="heldout"), "development split"),
        (lambda r: r["run"]["documents"].append("held"), "held-out documents"),
        (lambda r: r["score"].update(results_sha256=CODE), "results.json differs"),
        (lambda r: r["score"]["by_arm"]["runner"]["total"].update(escapes=9), "summary"),
        (lambda r: r["diagnose"]["review_codes"]["runner"].pop("B"), "review-code"),
        (lambda r: r.update(decide={"previous": "loop/00.json", "outcome": "keep"}), "first"),
        (lambda r: r["propose"].update(change="model"), "proposal"),
        (lambda r: r["propose"].update(reference="400"), "proposal"),
        (lambda r: r.pop("calibrate"), "step"),
        (lambda r: r.update(iteration=2), "iteration"),
    ],
)
def test_check_refuses_a_changed_record(tmp_path: Path, change: Any, message: str) -> None:
    make_set(tmp_path)
    dev_run(tmp_path, 1, REVIEWS)
    path = loop.record(tmp_path, 1, **PROPOSE)
    record = json.loads(path.read_text())
    change(record)
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match=message):
        loop.check(tmp_path)


def test_check_refuses_a_run_that_holds_a_heldout_document(tmp_path: Path) -> None:
    make_set(tmp_path)
    folder = dev_run(tmp_path, 1, REVIEWS)
    loop.record(tmp_path, 1, **PROPOSE)
    run = json.loads((folder / "runs/runner.json").read_text())
    run["documents"].append(copy.deepcopy(run["documents"][0]) | {"id": "held"})
    (folder / "runs/runner.json").write_text(json.dumps(run))
    with pytest.raises(ValueError, match="held-out documents: held"):
        loop.check(tmp_path)
    run["documents"].pop()
    run["documents"][0]["id"] = "other"
    (folder / "runs/runner.json").write_text(json.dumps(run))
    with pytest.raises(ValueError, match="not the development documents"):
        loop.check(tmp_path)
    run["documents"][0]["id"] = "dev"
    run["split"] = "heldout"
    (folder / "runs/runner.json").write_text(json.dumps(run))
    with pytest.raises(ValueError, match="not a development run"):
        loop.check(tmp_path)


def test_records_are_numbered_without_a_gap(tmp_path: Path) -> None:
    make_set(tmp_path)
    dev_run(tmp_path, 1, REVIEWS)
    path = loop.record(tmp_path, 1, **PROPOSE)
    path.rename(tmp_path / "loop/02.json")
    with pytest.raises(ValueError, match="no gap"):
        loop.check(tmp_path)


def freeze(directory: Path, **change: Any) -> None:
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["code_freeze"] = {
        "applies_to": "heldout",
        "code_sha256": CODE,
        "last_loop": "loop/01.json",
    } | change
    (directory / "manifest.json").write_text(json.dumps(manifest))


def test_heldout_freeze_names_the_last_record_and_its_code(tmp_path: Path) -> None:
    make_set(tmp_path)
    freeze(tmp_path)
    with pytest.raises(ValueError, match="has none"):
        loop.check(tmp_path)
    make_set(tmp_path)
    dev_run(tmp_path, 1, REVIEWS)
    loop.record(tmp_path, 1, **PROPOSE)
    # The freeze PR writes only code_freeze; the loop records stay valid.
    freeze(tmp_path)
    assert len(loop.check(tmp_path)) == 1
    for change, message in (
        ({"last_loop": "loop/02.json"}, "name the last"),
        ({"code_sha256": "sha256:" + "c" * 64}, "frozen code digest"),
    ):
        freeze(tmp_path, **change)
        with pytest.raises(ValueError, match=message):
            loop.check(tmp_path)
    freeze(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["documents"][1]["source"] = "https://example.org/other.pdf"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="more than its code_freeze"):
        loop.check(tmp_path)


def test_no_record_after_the_heldout_freeze(tmp_path: Path) -> None:
    make_set(tmp_path)
    freeze(tmp_path, last_loop="loop/00.json")
    with pytest.raises(ValueError):
        loop.record(tmp_path, 1, **PROPOSE)


def test_cli_check_and_record(tmp_path: Path) -> None:
    make_set(tmp_path)
    dev_run(tmp_path, 1, REVIEWS)
    env = {"PYTHONPATH": str(Path(__file__).parents[1])}
    base = [sys.executable, "-m", "requested.loop"]
    args = [*base, "record", "--set", str(tmp_path), "--iteration", "1", "--change", "pack"]
    args += ["--reference", "#401", "--summary", "A pack rule."]
    subprocess.run(args, check=True, capture_output=True, env=env)
    done = subprocess.run(
        [*base, "check", "--set", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "1 loop records are valid" in done.stdout


def test_check_refuses_held_out_ids_in_a_proposal_and_answers_outside_the_set(
    tmp_path: Path,
) -> None:
    make_set(tmp_path)
    dev_run(tmp_path, 1, REVIEWS)
    with pytest.raises(ValueError, match="held-out documents: held"):
        loop.record(tmp_path, 1, **(PROPOSE | {"summary": "The held document misses."}))
    # Only a whole id counts: "withheld" and "held2" do not name "held".
    path = loop.record(tmp_path, 1, **(PROPOSE | {"summary": "A withheld held2 note."}))
    dev_run(tmp_path, 2, REVIEWS)
    record = json.loads(path.read_text())
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}")
    record["calibrate"] = {"answers": "../outside.json", "answers_sha256": digest(outside)}
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="in the set folder"):
        loop.check(tmp_path)
