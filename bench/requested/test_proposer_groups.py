"""Synthetic checks for the measure of each proposer and of agreement (#511)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from requested.metrics import measure
from requested.proposers import measure_groups, proposer_set, render
from requested.run_set import _projection

from groundgate import jcs


def data() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fields = {
        "amount": {"type": "number", "unit": "USD", "multiple": True},
        "name": {"type": "string"},
        "absent": {"type": "number"},
        "unclear": {"type": "number"},
        "rate": {"type": "number", "keys": ["a", "b"]},
    }
    manifest = {
        "schemas": {"kind": {"fields": fields}},
        "documents": [{"id": "d", "kind": "kind", "split": "heldout"}],
    }
    labels = {
        "status": "sealed",
        "documents": [
            {
                "id": "d",
                "fields": [
                    {
                        "field": "amount",
                        "status": "present",
                        "values": [
                            {"value": "100", "unit": "USD"},
                            {"value": "200", "unit": "USD"},
                        ],
                    },
                    {"field": "name", "status": "present", "values": [{"value": "A B"}]},
                    {"field": "absent", "status": "absent"},
                    {"field": "unclear", "status": "unclear"},
                    {"field": "rate", "key": "a", "status": "present", "values": [{"value": "5"}]},
                    {"field": "rate", "key": "b", "status": "absent"},
                ],
            }
        ],
    }
    run = {"documents": [{"id": "d", "decisions": [], "not_found": []}]}
    return manifest, labels, run


def decision(field: str, value: Any, outcome: str = "admitted", **kw: Any) -> dict[str, Any]:
    return {"field": field, "value": value, "outcome": outcome} | kw


def decisions() -> list[dict[str, Any]]:
    return [
        # 100: the model and the structure reader agree.
        decision("amount", "100", unit="USD"),
        decision("amount", "100", unit="USD", proposer="structure"),
        # 200: only the structure reader admits it; the model's copy is rejected.
        decision("amount", "200", unit="USD", proposer="structure"),
        decision("amount", "200", "rejected", unit="USD"),
        # A wrong name from the model, and the right one only from the structure reader.
        decision("name", "X"),
        decision("name", "A B", "needs_verification", proposer="structure"),
        # A wrong admit on an absent slot, from the structure reader.
        decision("absent", "0", proposer="structure"),
        # An unclear slot adds nothing.
        decision("unclear", "1"),
        # A right keyed value from the model, and an unknown key from the structure reader.
        decision("rate", "5", key="a"),
        decision("rate", "7", key="z", proposer="structure"),
    ]


def test_each_admitted_value_goes_to_one_group() -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = decisions()
    groups = measure_groups(m, labels, run, "heldout")
    assert sorted(groups) == ["agreement", "proposer:structure", "unnamed"]
    totals = {g: (r["total"]["admitted"], r["total"]["escapes"]) for g, r in groups.items()}
    assert totals == {"agreement": (1, 0), "proposer:structure": (3, 2), "unnamed": (2, 1)}
    # The groups add up to the totals of results.json, and never share a value.
    whole = measure(m, labels, run, "heldout")["total"]
    assert sum(a for a, _ in totals.values()) == whole["admitted"] == 6
    assert sum(e for _, e in totals.values()) == whole["escapes"] == 3
    structure = groups["proposer:structure"]
    assert structure["by_field"]["absent"]["escapes"] == 1
    assert structure["by_field"]["rate"]["escapes"] == 1
    assert "unclear" not in groups["unnamed"]["by_field"]
    assert structure["total"]["admitted_error_rate"] == {"k": 2, "n": 3, "rate": 2 / 3}
    assert groups["agreement"]["total"]["bounds"]["effective_trials"] == 1


def test_right_values_found_by_one_proposer_count_by_their_best_outcome() -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = decisions()
    groups = measure_groups(m, labels, run, "heldout")
    structure = groups["proposer:structure"]["total"]
    # "A B" is only in review from the structure reader. 200 has two proposers.
    assert (structure["only_admitted"], structure["only_needs_verification"]) == (0, 1)
    assert structure["only_rejected"] == 0
    # 5 on key a is only from the model, and admitted.
    assert groups["unnamed"]["total"]["only_admitted"] == 1
    assert groups["agreement"]["total"]["only_admitted"] == 0


def test_a_run_without_proposers_is_one_unnamed_group() -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = [
        {k: v for k, v in d.items() if k != "proposer"} for d in decisions()
    ]
    groups = measure_groups(m, labels, run, "heldout")
    assert list(groups) == ["unnamed"]
    whole = measure(m, labels, run, "heldout")["total"]
    total = groups["unnamed"]["total"]
    assert (total["admitted"], total["escapes"]) == (whole["admitted"], whole["escapes"])
    assert total["bounds"] == whole["bounds"]


@pytest.mark.parametrize("bad", ["", " ", 3, ["structure"]])
def test_a_blank_or_non_string_proposer_is_refused(bad: Any) -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = [decision("name", "A B", proposer=bad)]
    with pytest.raises(ValueError, match="proposer"):
        measure_groups(m, labels, run, "heldout")


def test_projection_keeps_a_proposer_only_when_the_decision_has_one() -> None:
    base = {
        "candidate_id": "c1",
        "field": "name",
        "key": None,
        "value": "A B",
        "unit": None,
        "outcome": "admitted",
        "codes": [],
        "source": "ignored",
    }
    assert _projection(base | {"proposer": None}) == {
        k: v for k, v in base.items() if k != "source"
    }
    assert _projection(base | {"proposer": "structure"})["proposer"] == "structure"


def cache(directory: Path) -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = decisions()
    (directory / "runs").mkdir(parents=True)
    for name, content in (("manifest.json", m), ("labels.json", labels)):
        (directory / name).write_text(json.dumps(content))
    for name in ("manifest", "labels"):
        raw = (directory / (name + ".json")).read_bytes()
        run[name + "_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    run["split"] = "heldout"
    for doc in run["documents"]:
        doc |= {"complete": True, "transport_error": False, "transport_retries": 0}
    header = {
        "manifest_sha256": run["manifest_sha256"],
        "labels_sha256": run["labels_sha256"],
        "configuration_sha256": "frozen",
    }
    run |= {
        "arm": "runner",
        "provenance": header,
        "binding_sha256": "sha256:" + hashlib.sha256(jcs(header).encode()).hexdigest(),
    }
    (directory / "runs/runner.json").write_text(json.dumps(run))


def test_set_binds_the_seals_and_the_cli_reproduces(tmp_path: Path) -> None:
    cache(tmp_path)
    results = proposer_set(tmp_path, "heldout")
    assert results["format"] == "requested-proposers/1"
    assert results["runs"]["runner"]["cache_sha256"].startswith("sha256:")
    report = render(results)
    assert "| proposer:structure | total | 3 | 2 | 66.67% |" in report
    assert "| agreement | total | 1 | 0 | 0.00% |" in report
    script = Path(__file__).with_name("proposers.py")
    args = [sys.executable, str(script), "--set", str(tmp_path), "--split", "heldout"]
    subprocess.run(args, check=True, capture_output=True)
    assert json.loads((tmp_path / "proposers.json").read_text()) == results
    assert (tmp_path / "PROPOSERS.md").read_text() == report
    assert not (tmp_path / "results.json").exists()
    subprocess.run([*args, "--check"], check=True, capture_output=True)
    (tmp_path / "PROPOSERS.md").write_text("changed\n")
    stale = subprocess.run([*args, "--check"], capture_output=True, text=True)
    assert stale.returncode != 0 and "out of date: PROPOSERS.md" in stale.stderr
    other = subprocess.run([*args, "--out", str(tmp_path / "x")], capture_output=True, text=True)
    assert other.returncode != 0 and "held-out results go only to the set folder" in other.stderr
    dev = subprocess.run(
        [sys.executable, str(script), "--set", str(tmp_path), "--split", "development"],
        capture_output=True,
        text=True,
    )
    assert dev.returncode != 0 and "--out other than the set folder" in dev.stderr
