"""Synthetic checks for requested-field counting, seals and document bounds."""

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
from report import render_requested
from requested.metrics import measure, score_set, upper95


def data() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fields = {
        "amount": {"type": "number", "unit": "USD", "multiple": True},
        "name": {"type": "string"},
        "absent": {"type": "number"},
        "unclear": {"type": "number"},
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
                ],
            }
        ],
    }
    run = {"documents": [{"id": "d", "decisions": [], "not_found": []}]}
    return manifest, labels, run


def decision(field: str, value: Any, outcome: str = "admitted", **kw: Any) -> dict[str, Any]:
    return {"field": field, "value": value, "outcome": outcome} | kw


def test_zero_error_exact_bound_is_positive() -> None:
    assert upper95(0, 20) == pytest.approx(1 - 0.05 ** (1 / 20))
    assert upper95(0, 1) == pytest.approx(0.95)
    assert upper95(0, 0) is None
    assert upper95(10, 10) == 1
    assert upper95(5, 10) == pytest.approx(0.77755889899)
    with pytest.raises(ValueError):
        upper95(2, 1)


def test_extra_wrong_admit_and_right_review_are_both_counted() -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = [
        decision("amount", "100", unit="USD"),
        decision("amount", "100.0", unit="USD"),
        decision("amount", "300", unit="USD"),
        decision("amount", "200", "needs_verification", unit="USD"),
        decision("amount", "400", "needs_verification", unit="USD"),
        decision("name", "A   B"),
        decision("unclear", "123"),
    ]
    run["documents"][0]["not_found"] = [{"field": "absent"}]
    out = measure(m, labels, run, "heldout")
    total = out["total"]
    assert (total["admitted"], total["escapes"], total["present"]) == (3, 1, 3)
    assert (total["hits"], total["value_hits"], total["absence_hits"]) == (3, 2, 1)
    assert (total["reviews"], total["silent_misses"], total["catches"], total["excluded"]) == (
        1,
        0,
        1,
        1,
    )
    assert total["miss_rate"]["rate"] == pytest.approx(1 / 3)
    assert total["admitted_error_rate"]["rate"] == pytest.approx(1 / 3)
    assert total["bounds"]["design_effect"] == 3
    assert total["bounds"]["effective_trials"] == 1
    assert total["bounds"]["effective_errors"] == 1
    assert out["by_kind"]["kind"] == total
    assert out["by_kind_field"]["kind"]["amount"]["escapes"] == 1


def test_wrong_unit_sign_case_and_absent_admissions_are_escapes() -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = [
        decision("amount", "100", unit="EUR"),
        decision("amount", "-200", unit="USD"),
        decision("name", "a b"),
        decision("absent", "0"),
    ]
    total = measure(m, labels, run, "heldout")["total"]
    assert total["escapes"] == total["admitted"] == 4
    assert total["silent_misses"] == total["present"] == 3
    assert total["absence_hits"] == total["reviews"] == 0


def test_rejection_is_a_silent_miss_and_no_output_is_not_an_absence_hit() -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = [decision("amount", "100", "rejected", unit="USD")]
    out = measure(m, labels, run, "heldout")["total"]
    assert out["silent_misses"] == 3
    assert out["absence_hits"] == 0 and out["unreported_absences"] == 1
    assert out["bounds"]["value_upper95"] is None
    assert out["bounds"]["combined_upper95"] is None
    assert out["bounds"]["document_upper95"] > 0


def test_keys_are_exact_and_unknown_key_duplicates_are_canonicalized() -> None:
    m, labels, run = data()
    m["schemas"]["kind"]["fields"]["name"]["keys"] = ["Adult"]
    labels["documents"][0]["fields"][1]["key"] = "Adult"
    run["documents"][0]["decisions"] = [decision("name", "A B", key="ADULT")]
    out = measure(m, labels, run, "heldout")["total"]
    assert out["escapes"] == 1 and out["hits"] == 0
    spec = m["schemas"]["kind"]["fields"]["amount"]
    spec["keys"] = ["now"]
    labels["documents"][0]["fields"][0]["key"] = "now"
    run["documents"][0]["decisions"] = [
        decision("amount", v, key="old", unit="USD") for v in (100, "100.0")
    ]
    out = measure(m, labels, run, "heldout")["total"]
    assert out["admitted"] == out["escapes"] == 1


def test_bound_clusters_documents_and_keeps_separate_slices() -> None:
    m, labels, run = data()
    m["schemas"]["other"] = copy.deepcopy(m["schemas"]["kind"])
    m["documents"].append({"id": "d2", "kind": "other", "split": "heldout"})
    second = copy.deepcopy(labels["documents"][0])
    second["id"] = "d2"
    labels["documents"].append(second)
    run["documents"][0]["decisions"] = [decision("amount", "100", unit="USD")]
    run["documents"].append({"id": "d2", "decisions": [decision("amount", "200", unit="USD")]})
    out = measure(m, labels, run, "heldout")
    assert out["total"]["documents"] == out["total"]["kinds"] == 2
    assert out["total"]["bounds"]["document_upper95"] == pytest.approx(upper95(0, 2))
    assert out["by_kind"]["kind"]["bounds"]["document_upper95"] == pytest.approx(0.95)
    assert out["by_field"]["amount"]["admitted"] == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "unsealed",
        "missing",
        "duplicate",
        "invalid_integer",
        "blank_string",
        "wrong_label_unit",
        "incomplete_other_split",
    ],
)
def test_invalid_labels_fail_closed(mutation: str) -> None:
    m, labels, run = data()
    if mutation == "unsealed":
        labels["status"] = "draft"
    elif mutation == "missing":
        labels["documents"][0]["fields"].pop()
    elif mutation == "duplicate":
        labels["documents"][0]["fields"].append(labels["documents"][0]["fields"][0])
    elif mutation == "invalid_integer":
        m["schemas"]["kind"]["fields"]["amount"]["type"] = "integer"
        labels["documents"][0]["fields"][0]["values"][0]["value"] = "1.5"
    elif mutation == "blank_string":
        labels["documents"][0]["fields"][1]["values"][0]["value"] = "  "
    elif mutation == "wrong_label_unit":
        labels["documents"][0]["fields"][0]["values"][0]["unit"] = "EUR"
    else:
        m["documents"].append({"id": "dev", "kind": "kind", "split": "development"})
        labels["documents"].append({"id": "dev", "fields": []})
    with pytest.raises(ValueError):
        measure(m, labels, run, "heldout")


def cache(directory: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    m, labels, run = data()
    (directory / "runs").mkdir()
    for name, content in (("manifest.json", m), ("labels.json", labels)):
        (directory / name).write_text(json.dumps(content))
    for name in ("manifest", "labels"):
        run[name + "_sha256"] = (
            "sha256:" + hashlib.sha256((directory / (name + ".json")).read_bytes()).hexdigest()
        )
    (directory / "runs/baseline.json").write_text(json.dumps(run))
    return m, labels, run


def test_cache_binds_manifest_and_label_seals_and_cli_reproduces(tmp_path: Path) -> None:
    m, _, _ = cache(tmp_path)
    results = score_set(tmp_path, "heldout")
    assert "Requested-field results" in render_requested(results)
    scorer = Path(__file__).parents[1] / "score.py"
    args = [sys.executable, str(scorer), "--requested", "--set", str(tmp_path)]
    subprocess.run(args, check=True, capture_output=True)
    subprocess.run([*args, "--check"], check=True, capture_output=True)
    m["documents"][0]["split"] = "development"
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="manifest"):
        score_set(tmp_path, "heldout")
