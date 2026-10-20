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
from requested.metrics import (
    check_split_rule,
    final_search_limits,
    measure,
    score_set,
    search_limit_fields,
    split_of,
    upper95,
)

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


def test_bounds_have_a_fixed_number_of_digits() -> None:
    # The last float bit can change with the Python version; results.json must not.
    for errors, trials in [(0, 7), (0, 300), (3, 41), (11, 300)]:
        bound = upper95(errors, trials)
        assert bound is not None
        assert bound == round(bound, 10)
    # Rounding goes up, so the bound stays above the exact endpoint.
    assert upper95(0, 15) == 0.1810362726
    assert upper95(0, 15) >= 1 - 0.05 ** (1 / 15)


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
    assert (out["rejected_right_values"], out["no_right_candidate"]) == (1, 2)
    assert out["absence_hits"] == 0 and out["unreported_absences"] == 1
    assert out["bounds"]["value_upper95"] is None
    assert out["bounds"]["combined_upper95"] is None
    # No document admitted a value, so no document bound exists.
    assert out["bounds"]["document_trials"] == 0
    assert out["bounds"]["document_upper95"] is None


def test_silent_misses_split_into_rejected_right_values_and_no_right_candidate() -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = [
        decision("amount", "100", "rejected", unit="USD"),
        decision("amount", "300", "rejected", unit="USD"),
        decision("name", "A B", "rejected"),
        decision("name", "A B", "needs_verification"),
    ]
    out = measure(m, labels, run, "heldout")
    total = out["total"]
    # 100 is a rejected right value. 200 has no candidate: a wrong rejected value does not count.
    # The name has a review, so its rejected copy is not a silent miss.
    assert (total["reviews"], total["silent_misses"]) == (1, 2)
    assert (total["rejected_right_values"], total["no_right_candidate"]) == (1, 1)
    assert total["rejected_right_value_share"]["rate"] == pytest.approx(1 / 3)
    assert total["no_right_candidate_share"]["rate"] == pytest.approx(1 / 3)
    assert total["miss_rate"]["rate"] == pytest.approx(1)
    for row in [total, *out["by_field"].values()]:
        assert row["rejected_right_values"] + row["no_right_candidate"] == row["silent_misses"]
    assert out["by_field"]["amount"]["rejected_right_values"] == 1


def test_admitted_right_value_with_a_rejected_copy_is_a_hit_not_a_rejected_right_value() -> None:
    m, labels, run = data()
    run["documents"][0]["decisions"] = [
        decision("amount", "100", unit="USD"),
        decision("amount", "100", "rejected", unit="USD"),
    ]
    total = measure(m, labels, run, "heldout")["total"]
    assert total["value_hits"] == 1
    assert (total["rejected_right_values"], total["no_right_candidate"]) == (0, 2)


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


def test_replay_arm_is_scored_beside_the_other_arms(tmp_path: Path) -> None:
    # runner_drop_rounded replays the runner calls with one binding (#376).
    _, _, run = cache(tmp_path)
    for arm in ("runner", "runner_drop_rounded"):
        (tmp_path / f"runs/{arm}.json").write_text(json.dumps(bind(copy.deepcopy(run), arm)))
    runs = score_set(tmp_path, "heldout")["runs"]
    assert set(runs) == {"baseline", "runner", "runner_drop_rounded"}
    assert "## runner_drop_rounded" in render_requested(score_set(tmp_path, "heldout"))


RUN2 = "groundgate-run/2"


def test_search_limit_fields_count_the_final_states_of_a_runner_record() -> None:
    header = {"kind": "header", "runner": "groundgate-run/3"}
    final = {"kind": "final", "fields": {"a": ["proposed", "search_limit"], "b": ["proposed"]}}
    assert search_limit_fields([header, {"kind": "call"}, final]) == 1
    for bad in (
        [],
        [header, {"kind": "call"}],
        [header, {"kind": "final", "fields": {"a": "search_limit"}}],
        [final],
        # A run/2 record is read only by limits.py, for the requested3 cache.
        [header | {"runner": "groundgate-run/2"}, final],
    ):
        with pytest.raises(ValueError):
            search_limit_fields(bad)
    assert final_search_limits([header | {"runner": "groundgate-run/2"}, final], RUN2) == 1


def test_search_limit_counts_appear_only_for_runs_that_carry_them(tmp_path: Path) -> None:
    m, labels, run = data()
    old = measure(m, labels, run, "heldout")["document_states"]["total"]
    assert set(old) == {"documents", "incomplete", "transport_error", "transport_retries"}
    run["documents"][0]["search_limit"] = 3
    states = measure(m, labels, run, "heldout")["document_states"]
    assert states["total"]["search_limit_documents"] == 1
    assert states["by_kind"]["kind"]["search_limit_fields"] == 3
    m["documents"].append({"id": "d2", "kind": "kind", "split": "heldout"})
    gold = copy.deepcopy(labels["documents"][0])
    gold["id"] = "d2"
    labels["documents"].append(gold)
    run["documents"].append({"id": "d2", "decisions": []})
    with pytest.raises(ValueError, match="every run document"):
        measure(m, labels, run, "heldout")
    run["documents"][1]["search_limit"] = -1
    with pytest.raises(ValueError, match="nonnegative"):
        measure(m, labels, run, "heldout")
    _, _, cached = cache(tmp_path)
    cached["documents"][0]["search_limit"] = 2
    (tmp_path / "runs/baseline.json").write_text(json.dumps(cached))
    report = render_requested(score_set(tmp_path, "heldout"))
    assert "| search_limit docs | search_limit fields |" in report
    assert "| total | 1 | 0 | 0 | 0 | 1 | 2 |" in report


def family_set(rule: dict[str, Any]) -> dict[str, Any]:
    """A manifest whose splits follow the rule; one family has two documents."""
    docs = []
    for i, family in enumerate(["fa", "fa", "fb", "fc", "fd", "fe", "ff", "fg"]):
        docs.append(
            {
                "id": f"d{i}",
                "kind": "kind",
                "source_family_group": family,
                "split": split_of(rule, family),
            }
        )
    return {"split_rule": rule, "documents": docs}


RULE = {
    "method": "family-hash/1",
    "salt": "fixed-salt",
    "development_share": 0.5,
    "fixed_on": "2026-10-20",
}


def test_split_rule_recomputes_each_split_by_source_family() -> None:
    manifest = family_set(RULE)
    check_split_rule(manifest)
    assert {d["split"] for d in manifest["documents"]} == {"development", "heldout"}
    first = hashlib.sha256(b"fixed-saltfa").digest()[0]
    assert split_of(RULE, "fa") == ("development" if first < 128 else "heldout")
    # A wrong split, or one family in two splits, is refused.
    wrong = copy.deepcopy(manifest)
    doc = wrong["documents"][3]
    doc["split"] = "heldout" if doc["split"] == "development" else "development"
    with pytest.raises(ValueError, match="split_rule"):
        check_split_rule(wrong)
    wrong = copy.deepcopy(manifest)
    doc = wrong["documents"][1]
    doc["split"] = "heldout" if doc["split"] == "development" else "development"
    with pytest.raises(ValueError, match="d1"):
        check_split_rule(wrong)


def test_a_pilot_family_is_development_and_a_set_without_a_rule_is_not_checked() -> None:
    manifest = family_set(RULE)
    held = next(d for d in manifest["documents"] if d["split"] == "heldout")
    held["pilot"] = True
    with pytest.raises(ValueError, match="development"):
        check_split_rule(manifest)
    for d in manifest["documents"]:
        if d["source_family_group"] == held["source_family_group"]:
            d["split"] = "development"
    check_split_rule(manifest)
    manifest.pop("split_rule")
    manifest["documents"][0]["split"] = "heldout"
    check_split_rule(manifest)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(method="family-hash/2"),
        lambda r: r.update(salt=" "),
        lambda r: r.update(development_share=1),
        lambda r: r.update(development_share=True),
        lambda r: r.pop("fixed_on"),
        lambda r: r.update(extra=1),
    ],
)
def test_invalid_split_rule_is_refused(change: Any) -> None:
    rule = dict(RULE)
    change(rule)
    with pytest.raises(ValueError, match="split_rule"):
        check_split_rule({"split_rule": rule, "documents": []})


@pytest.mark.parametrize("pilot", [1, 0, "yes", [], None])
def test_pilot_must_be_a_boolean(pilot: Any) -> None:
    manifest = family_set(RULE)
    manifest["documents"][0]["pilot"] = pilot
    with pytest.raises(ValueError, match="pilot"):
        check_split_rule(manifest)


def test_a_split_rule_needs_a_family_on_each_document() -> None:
    manifest = family_set(RULE)
    manifest["documents"][0].pop("source_family_group")
    with pytest.raises(ValueError, match="source_family_group"):
        check_split_rule(manifest)


def test_development_results_go_to_their_own_folder(tmp_path: Path) -> None:
    m, _, run = cache(tmp_path)
    m["documents"][0]["split"] = "development"
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    run["manifest_sha256"] = (
        "sha256:" + hashlib.sha256((tmp_path / "manifest.json").read_bytes()).hexdigest()
    )
    run["split"] = "development"
    loop = tmp_path / "loop/01"
    (loop / "runs").mkdir(parents=True)
    (loop / "runs/runner.json").write_text(json.dumps(bind(run, "runner")))
    scorer = Path(__file__).parents[1] / "score.py"
    args = [sys.executable, str(scorer), "--requested", "--set", str(tmp_path)]
    args += ["--split", "development", "--runs", str(loop / "runs")]
    refused = subprocess.run(args, capture_output=True, text=True)
    assert refused.returncode != 0 and "--out" in refused.stderr
    refused = subprocess.run([*args, "--out", str(tmp_path)], capture_output=True, text=True)
    assert refused.returncode != 0
    subprocess.run([*args, "--out", str(loop)], check=True, capture_output=True)
    subprocess.run([*args, "--out", str(loop), "--check"], check=True, capture_output=True)
    results = json.loads((loop / "results.json").read_text())
    assert results["runs"]["runner"]["split"] == "development"
    assert not (tmp_path / "results.json").exists()


REQUESTED3 = Path(__file__).parents[1] / "requested3"


def test_requested3_limits_belong_to_its_published_runs() -> None:
    limits = json.loads((REQUESTED3 / "limits.json").read_text())
    results = json.loads((REQUESTED3 / "results.json").read_text())
    assert limits["format"] == "requested-limits/1"
    assert limits["manifest_sha256"] == results["manifest_sha256"]
    assert limits["labels_sha256"] == results["labels_sha256"]
    assert set(limits["runs"]) == set(results["runs"])
    for arm, run in limits["runs"].items():
        published = results["runs"][arm]
        assert run["run_sha256"] == published["cache_sha256"]
        assert run["run_sha256"] == (
            "sha256:"
            + hashlib.sha256((REQUESTED3 / "runs" / f"{arm}.json").read_bytes()).hexdigest()
        )
        states = published["document_states"]
        for kind, row in run["document_states"]["by_kind"].items():
            assert row["documents"] == states["by_kind"][kind]["documents"]
            # A search_limit document stops the run, so it is also an incomplete document.
            assert row["search_limit_documents"] <= states["by_kind"][kind]["incomplete"]


def test_compare_puts_search_limit_beside_the_published_numbers(tmp_path: Path) -> None:
    report = Path(__file__).parents[1] / "report.py"
    results = REQUESTED3 / "results.json"
    out = tmp_path / "compare.md"
    args = [sys.executable, str(report), "--compare", str(results), str(results)]
    subprocess.run([*args, "--out", str(out)], check=True, capture_output=True)
    text = out.read_text()
    limits = json.loads((REQUESTED3 / "limits.json").read_text())
    total = limits["runs"]["runner"]["document_states"]["total"]
    cell = f"{total['search_limit_documents']} docs, {total['search_limit_fields']} fields"
    row = next(line for line in text.splitlines() if line.startswith("| runner | total |"))
    assert row.count(cell) == 2
    miss = json.loads(results.read_text())["runs"]["runner"]["total"]["miss_rate"]
    assert f"{miss['k']}/{miss['n']}" in row
