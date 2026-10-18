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

from groundgate import jcs


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
    # No document admitted a value, so no document bound exists.
    assert out["bounds"]["document_trials"] == 0
    assert out["bounds"]["document_upper95"] is None


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
    run["split"] = "heldout"
    for doc in run["documents"]:
        doc |= {"complete": True, "transport_error": False, "transport_retries": 0}
    bind(run, "baseline")
    (directory / "runs/baseline.json").write_text(json.dumps(run))
    return m, labels, run


def bind(run: dict[str, Any], arm: str, config: str = "frozen") -> dict[str, Any]:
    header = {
        "manifest_sha256": run["manifest_sha256"],
        "labels_sha256": run["labels_sha256"],
        "configuration_sha256": config,
    }
    encoded = jcs(header).encode("utf-8")
    run |= {
        "arm": arm,
        "provenance": header,
        "binding_sha256": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }
    return run


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


@pytest.mark.parametrize("bad_key", ["", "  ", 7, [], {}])
def test_malformed_admitted_key_is_an_escape(bad_key: Any) -> None:
    m, labels, run = data()
    m["schemas"]["kind"]["fields"]["name"]["keys"] = ["Adult"]
    labels["documents"][0]["fields"][1]["key"] = "Adult"
    run["documents"][0]["decisions"] = [decision("name", "A B", key=bad_key)]
    out = measure(m, labels, run, "heldout")["total"]
    assert out["escapes"] == out["admitted"] == 1
    assert out["hits"] == 0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda run: run.update(split="development", documents=[]), "split"),
        (lambda run: run.pop("split"), "split"),
        (lambda run: run.update(documents=[]), "exactly"),
        (lambda run: run["documents"].append(dict(run["documents"][0], id="x")), "exactly"),
        (lambda run: run["documents"][0].pop("complete"), "transport state"),
        (lambda run: run["documents"][0].update(transport_retries=-1), "transport state"),
        (lambda run: run["documents"].append(dict(run["documents"][0])), "exactly"),
        (lambda run: run["documents"][0].update(id=7), "exactly"),
        (lambda run: run.update(documents={}), "list"),
        (lambda run: run.update(partial=True), "partial"),
    ],
)
def test_run_of_another_split_or_with_other_documents_is_refused(
    tmp_path: Path, change: Any, message: str
) -> None:
    _, _, run = cache(tmp_path)
    change(run)
    (tmp_path / "runs/baseline.json").write_text(json.dumps(run))
    with pytest.raises(ValueError, match=message):
        score_set(tmp_path, "heldout")


def test_runs_must_share_one_binding_and_be_named_for_their_arm(tmp_path: Path) -> None:
    _, _, run = cache(tmp_path)
    runner = tmp_path / "runs/runner.json"
    runner.write_text(json.dumps(bind(copy.deepcopy(run), "runner")))
    assert set(score_set(tmp_path, "heldout")["runs"]) == {"baseline", "runner"}
    # A baseline projection copied under the runner name keeps its own arm.
    runner.write_text(json.dumps(run))
    with pytest.raises(ValueError, match="named for its arm"):
        score_set(tmp_path, "heldout")
    runner.write_text(json.dumps(bind(copy.deepcopy(run), "runner", config="other")))
    with pytest.raises(ValueError, match="share one"):
        score_set(tmp_path, "heldout")
    tampered = bind(copy.deepcopy(run), "runner")
    tampered["provenance"]["configuration_sha256"] = "other"
    runner.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="provenance"):
        score_set(tmp_path, "heldout")
    runner.unlink()
    (tmp_path / "runs/primary.json").write_text(json.dumps(run))
    with pytest.raises(ValueError, match="named for its arm"):
        score_set(tmp_path, "heldout")


def test_document_with_only_unclear_slots_counts_in_the_sample() -> None:
    m, labels, run = data()
    m["documents"].append({"id": "d2", "kind": "kind", "split": "heldout"})
    unclear = [{"field": f, "status": "unclear"} for f in ("amount", "name", "absent", "unclear")]
    labels["documents"].append({"id": "d2", "fields": unclear})
    run["documents"].append({"id": "d2", "decisions": [], "not_found": []})
    out = measure(m, labels, run, "heldout")
    assert out["total"]["documents"] == out["document_states"]["total"]["documents"] == 2
    assert out["by_kind"]["kind"]["documents"] == 2


def test_projection_with_a_missing_document_is_refused(tmp_path: Path) -> None:
    m, labels, run = cache(tmp_path)
    m["documents"].append({"id": "d2", "kind": "kind", "split": "heldout"})
    second = copy.deepcopy(labels["documents"][0])
    second["id"] = "d2"
    labels["documents"].append(second)
    for name, content in (("manifest.json", m), ("labels.json", labels)):
        (tmp_path / name).write_text(json.dumps(content))
    for name in ("manifest", "labels"):
        run[name + "_sha256"] = (
            "sha256:" + hashlib.sha256((tmp_path / (name + ".json")).read_bytes()).hexdigest()
        )
    bind(run, "baseline")
    (tmp_path / "runs/baseline.json").write_text(json.dumps(run))
    with pytest.raises(ValueError, match="exactly the heldout documents"):
        score_set(tmp_path, "heldout")
    run["documents"].append(
        {"id": "d2", "decisions": [], "not_found": []}
        | {"complete": True, "transport_error": False, "transport_retries": 0}
    )
    (tmp_path / "runs/baseline.json").write_text(json.dumps(run))
    assert score_set(tmp_path, "heldout")["runs"]["baseline"]["total"]["documents"] == 2


def test_document_bound_counts_only_documents_with_admits() -> None:
    m, labels, run = data()
    for ident in ("d2", "d3"):
        m["documents"].append({"id": ident, "kind": "kind", "split": "heldout"})
        gold = copy.deepcopy(labels["documents"][0])
        gold["id"] = ident
        labels["documents"].append(gold)
    run["documents"][0]["decisions"] = [decision("amount", "300", unit="USD")]
    run["documents"] += [{"id": "d2", "decisions": []}, {"id": "d3", "decisions": []}]
    out = measure(m, labels, run, "heldout")["total"]
    assert out["documents"] == 3 and out["documents_with_admits"] == 1
    assert out["bounds"]["document_trials"] == 1 and out["bounds"]["document_errors"] == 1
    assert out["bounds"]["document_upper95"] == 1.0
    run["documents"][0]["decisions"] = [decision("amount", "100", unit="USD")]
    run["documents"][1]["decisions"] = [decision("amount", "200", unit="USD")]
    out = measure(m, labels, run, "heldout")["total"]
    assert out["bounds"]["document_trials"] == 2 and out["bounds"]["document_errors"] == 0
    assert out["bounds"]["document_upper95"] == pytest.approx(upper95(0, 2))


def test_incomplete_and_transport_documents_are_counted_for_each_kind(tmp_path: Path) -> None:
    m, labels, run = cache(tmp_path)
    m["schemas"]["other"] = copy.deepcopy(m["schemas"]["kind"])
    for ident, kind in (("d2", "kind"), ("d3", "other")):
        m["documents"].append({"id": ident, "kind": kind, "split": "heldout"})
        gold = copy.deepcopy(labels["documents"][0])
        gold["id"] = ident
        labels["documents"].append(gold)
    for name, content in (("manifest.json", m), ("labels.json", labels)):
        (tmp_path / name).write_text(json.dumps(content))
    for name in ("manifest", "labels"):
        run[name + "_sha256"] = (
            "sha256:" + hashlib.sha256((tmp_path / (name + ".json")).read_bytes()).hexdigest()
        )
    bind(run, "baseline")
    state = {"decisions": [], "not_found": []}
    run["documents"] += [
        state | {"id": "d2", "complete": False, "transport_error": True, "transport_retries": 2},
        state | {"id": "d3", "complete": False, "transport_error": False, "transport_retries": 1},
    ]
    (tmp_path / "runs/baseline.json").write_text(json.dumps(run))
    results = score_set(tmp_path, "heldout")
    states = results["runs"]["baseline"]["document_states"]
    assert states["by_kind"]["kind"] == {
        "documents": 2,
        "incomplete": 1,
        "transport_error": 1,
        "transport_retries": 2,
    }
    assert states["by_kind"]["other"] == {
        "documents": 1,
        "incomplete": 1,
        "transport_error": 0,
        "transport_retries": 1,
    }
    assert states["total"] == {
        "documents": 3,
        "incomplete": 2,
        "transport_error": 1,
        "transport_retries": 3,
    }
    report = render_requested(results)
    assert "| Kind | Docs | Incomplete | Transport error | Transport retries |" in report
    assert "| total | 3 | 2 | 1 | 3 |" in report
    assert "| kind | 2 | 1 | 1 | 2 |" in report
    assert "| other | 1 | 1 | 0 | 1 |" in report
