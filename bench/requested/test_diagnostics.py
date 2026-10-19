"""Source-independent diagnostic contracts with hand-authored worker outcomes."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from requested import diagnostics as d


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(d.encoded(obj))
    return d.digest(path.read_bytes())


def fixture(tmp_path):
    directory, sources, inputs, cache = (
        tmp_path / n for n in ("set", "sources", "inputs", "cache")
    )
    sources.mkdir()
    text = "\u03bc\nLimit\t1\t9"
    (sources / "doc.pdf").write_bytes(b"synthetic PDF")
    (sources / "doc.txt").write_text(text)
    schema = {
        "fields": {
            "low": {"type": "number", "unit": "V", "comparator": "ge"},
            "high": {"type": "number", "unit": "V", "comparator": "le"},
        }
    }
    manifest = {
        "status": "frozen",
        "selection_complete": True,
        "schemas": {"kind": schema},
        "documents": [
            {
                "id": "doc",
                "kind": "kind",
                "split": "heldout",
                "source": "https://example.org/source.pdf",
                "source_pages": 1,
                "source_bytes": 13,
                "approved_max_bytes": 100,
                "source_sha256": d.digest(b"synthetic PDF"),
                "text_sha256": d.digest(text.encode()),
            }
        ],
    }
    labels = {
        "status": "sealed",
        "documents": [
            {
                "id": "doc",
                "fields": [
                    {
                        "field": field,
                        "key": None,
                        "status": "present",
                        "values": [{"value": value, "unit": "V"}],
                        "page": 1,
                    }
                    for field, value in (("low", "1"), ("high", "9"))
                ],
            }
        ],
    }
    view = {
        "id": "endpoints",
        "document": "doc",
        "comparator_adapter": "keyed_endpoint_eq",
        "schema": {
            "fields": {
                "limit": {
                    "type": "number",
                    "unit": "V",
                    "keys": ["minimum", "maximum"],
                    "comparator": "eq",
                }
            }
        },
        "mapping": [
            {
                "field": "limit",
                "key": key,
                "source_field": field,
                "source_key": None,
                "source_comparator": comparator,
                "target_comparator": "eq",
            }
            for field, key, comparator in (("low", "minimum", "ge"), ("high", "maximum", "le"))
        ],
    }
    # Intentionally wrong value in the requested minimum slot, copied from the maximum cell.
    candidate = {
        "id": "c",
        "field": "limit",
        "key": "minimum",
        "value": "9",
        "unit": "V",
        "evidence": [{"source": "document", "role": "value", "start": 11, "end": 12}],
    }
    packet = {
        "text": text,
        "schema": view["schema"],
        "candidates": [candidate],
        "policy": {},
        "document_id": "doc",
        "document_source": manifest["documents"][0]["source"],
        "references": [],
        "judgments": [],
    }
    packet_sha = write(inputs / "packet.json", packet)
    plan = {
        "format": "requested-diagnostics/1",
        "status": "frozen",
        "split": "heldout",
        "manifest_sha256": write(directory / "manifest.json", manifest),
        "labels_sha256": write(directory / "labels.json", labels),
        "reader": {
            "id": "new-reader",
            "commit": "fixed",
            "code_sha256": d.digest(b"reader"),
            "serializer": "pdf-delimiters/1",
        },
        "versions": [
            {
                "id": version,
                "package_version": version + ".0",
                "spec_version": version,
                "code_sha256": d.digest(version.encode()),
                "python": sys.executable,
                "python_sha256": d.file_digest(Path(sys.executable).resolve()),
                "commit": "fixed",
            }
            for version in ("0.8", "0.9")
        ],
        "views": [view],
        "packets": [
            {
                "id": "packet",
                "document": "doc",
                "view": "endpoints",
                "path": "packet.json",
                "sha256": packet_sha,
                "acquisition": "genuine",
                "proposer_binding_sha256": d.digest(b"frozen-client"),
            }
        ],
        "layout": None,
    }
    path = tmp_path / "plan.json"
    plan_sha = write(path, plan)

    def session():
        return d.DiagnosticSession(path, directory, sources, inputs, cache, plan_sha256=plan_sha)

    return session, plan, packet, path, inputs, cache


def fake_worker(version, packet):
    # Expected outcomes are authored here; no groundgate decision generates them.
    candidate = packet["candidates"][0]
    outcome, codes = (
        ("admitted", []) if version["id"] == "0.8" else ("needs_verification", ["KEY_NOT_AT_VALUE"])
    )
    decision = {
        "candidate_id": "c",
        "candidate_sha256": d.core_digest(version["spec_version"], "candidate", candidate),
        "field": candidate["field"],
        "key": candidate.get("key"),
        "value": candidate["value"],
        "unit": candidate.get("unit"),
        "outcome": outcome,
        "codes": codes,
        "evidence": {"start": 11, "end": 12},
        "source": "document",
        "ref": None,
        "url": None,
        "parts": [],
        "missing": [],
    }
    schema = d.gg.Schema.from_dict(packet["schema"]).to_dict()
    policy = d.gg.Policy.from_dict(packet["policy"]).to_dict()
    receipt = {
        "groundgate": version["spec_version"],
        "document": {
            "id": "doc",
            "source": packet["document_source"],
            "sha256": d.core_digest(version["spec_version"], "document", {"text": packet["text"]}),
        },
        "schema_sha256": d.core_digest(version["spec_version"], "schema", schema),
        "policy_sha256": d.core_digest(version["spec_version"], "policy", policy),
        "decisions": [decision],
        "references": [],
        "packs": [],
        "coverage": [],
        "judgments": [],
        "summary": {
            "admitted": int(outcome == "admitted"),
            "needs_verification": int(outcome == "needs_verification"),
            "rejected": 0,
        },
    }
    receipt["receipt_sha256"] = d.core_digest(version["spec_version"], "receipt", receipt)
    return {
        "package_version": version["package_version"],
        "spec_version": version["spec_version"],
        "code_sha256": version["code_sha256"],
        "packet_sha256": d.digest(d.encoded(packet)),
        "schema": schema,
        "policy": policy,
        "receipt": receipt,
    }


def test_identical_packet_pair_cache_and_offline_replay(tmp_path):
    factory, _, packet, _, _, _ = fixture(tmp_path)
    calls = []

    def worker(version, body):
        calls.append((version["id"], d.encoded(body)))
        return fake_worker(version, body)

    session = factory()
    result = session.run(worker=worker)
    assert [x[0] for x in calls] == ["0.8", "0.9"]
    assert calls[0][1] == calls[1][1] == d.encoded(packet)
    assert result["diagnostics"]["decision_pair"]["transitions"] == {
        "admitted->needs_verification": 1
    }
    assert result["diagnostics"]["decision_pair"]["added_codes"] == {"KEY_NOT_AT_VALUE": 1}
    assert result["diagnostics"]["decision_pair"]["by_view"]["endpoints"]["0.8"]["escapes"] == 1
    assert result["diagnostics"]["decision_pair"]["by_view"]["endpoints"]["0.9"]["escapes"] == 0
    assert session.run(replay_only=True) == result
    assert len(calls) == 2
    assert "not_found" not in json.dumps(result)
    assert "evidence" not in result["diagnostics"]["decision_pair"]


@pytest.mark.parametrize(
    "change", ["derived", "comparator", "mapping", "packet", "text", "source", "seal"]
)
def test_gate_refuses_before_any_worker(tmp_path, change):
    factory, plan, packet, path, inputs, _ = fixture(tmp_path)
    if change == "derived":
        plan["packets"][0]["acquisition"] = "derived"
    elif change == "comparator":
        plan["views"][0]["comparator_adapter"] = None
    elif change == "mapping":
        plan["views"][0]["mapping"][1]["key"] = "minimum"
    elif change == "packet":
        packet["candidates"][0]["evidence"][0]["start"] = 1
        write(inputs / "packet.json", packet)
    elif change == "text":
        (tmp_path / "sources/doc.txt").write_text("changed")
    elif change == "source":
        (tmp_path / "sources/doc.pdf").write_bytes(b"changed")
    elif change == "seal":
        labels = json.loads((tmp_path / "set/labels.json").read_text())
        labels["status"] = "draft"
        plan["labels_sha256"] = write(tmp_path / "set/labels.json", labels)
    if change in {"derived", "comparator", "mapping", "seal"}:
        new_sha = write(path, plan)

        def factory():
            return d.DiagnosticSession(
                path,
                tmp_path / "set",
                tmp_path / "sources",
                inputs,
                tmp_path / "cache",
                plan_sha256=new_sha,
            )

    with pytest.raises(d.DiagnosticError):
        factory().run(worker=lambda *_: pytest.fail("worker called before gate"))


def test_failure_is_cached_not_retried_and_missing_replay_refuses(tmp_path):
    factory, _, _, _, _, cache = fixture(tmp_path)
    with pytest.raises(d.DiagnosticError):
        factory().run(replay_only=True)
    calls = []

    def fail(version, packet):
        calls.append(version["id"])
        raise TimeoutError("private transport detail")

    result = factory().run(worker=fail)
    assert len(result["diagnostics"]["decision_pair"]["failures"]) == 2
    assert factory().run(replay_only=True) == result
    assert calls == ["0.8", "0.9"]
    assert all("private transport detail" not in p.read_text() for p in cache.rglob("*.json"))


def test_worker_fingerprint_and_receipt_tampering_refuse(tmp_path):
    factory, _, _, _, _, _ = fixture(tmp_path)

    def bad(version, packet):
        result = fake_worker(version, packet)
        result["receipt"]["decisions"][0]["value"] = "1"
        return result

    with pytest.raises(d.DiagnosticError):
        factory().run(worker=bad)


def test_observable_tabs_preserve_real_empty_slots_and_utf8_geometry():
    text = "\u03bc\t\t9\n\fX"
    layout = {
        "groundgate_layout": "0.1",
        "document_sha256": d.gg.digest("document", {"text": text}),
        "pages": [
            {"page": 1, "width": 100, "height": 100, "start": 0, "end": 5},
            {"page": 2, "width": 100, "height": 100, "start": 7, "end": 8},
        ],
        "words": [[0, 2, 1, 0, 0, 10, 10], [4, 5, 1, 30, 0, 40, 10], [7, 8, 2, 0, 0, 10, 10]],
    }
    trace = d.serialized_layout(text, layout)
    assert [(c["start"], c["end"]) for c in trace["rows"][0]["cells"]] == [(0, 2), (3, 3), (4, 5)]
    assert trace["rows"][0]["cells"][1]["empty"] is True
    assert trace["rows"][0]["cells"][2]["words"][0]["box"] == [30, 0, 40, 10]
    broken = copy.deepcopy(layout)
    broken["words"][0][1] = 1
    with pytest.raises(d.DiagnosticError):
        d.serialized_layout(text, broken)


def test_partial_and_unjoinable_layout_is_not_success_or_fabricated_case():
    assert d.score_layout([], []) == {
        "status": "unassessed",
        "routes": {},
        "limitations": ["No sealed layout annotations supplied."],
    }


def test_diagnostic_export_adds_section_without_changing_primary_units_or_bounds(tmp_path):
    from report import render_requested
    from requested.metrics import score_set

    factory, plan, _, _, _, _ = fixture(tmp_path)
    header = {"manifest_sha256": plan["manifest_sha256"], "labels_sha256": plan["labels_sha256"]}
    write(
        tmp_path / "set/runs/baseline.json",
        {
            "manifest_sha256": plan["manifest_sha256"],
            "labels_sha256": plan["labels_sha256"],
            "arm": "baseline",
            "provenance": header,
            "binding_sha256": d.digest(d.gg.jcs(header).encode()),
            "split": "heldout",
            "documents": [
                {
                    "id": "doc",
                    "decisions": [],
                    "not_found": [],
                    "complete": True,
                    "transport_error": False,
                    "transport_retries": 0,
                }
            ],
        },
    )
    original = score_set(tmp_path / "set", "heldout")
    output = factory().run(worker=fake_worker)
    export = tmp_path / "diagnostics.json"
    export_sha = write(export, output)
    result = score_set(
        tmp_path / "set", "heldout", diagnostics=export, diagnostics_sha256=export_sha
    )
    assert result["runs"] == original["runs"]
    assert result["runs"]["baseline"]["total"]["present"] == 2
    missing = copy.deepcopy(result)
    missing["diagnostics"]["reader_layout"]["missing_observations"] = ["doc"]
    assert "1 annotated documents have no reader observation" in render_requested(missing)
    assert "no reader observation" not in render_requested(result)
    assert result["diagnostics"]["export_sha256"] == export_sha
    assert "Separate diagnostics" in render_requested(result)
    assert "Separate diagnostics" not in render_requested(original)
    with pytest.raises(ValueError):
        score_set(tmp_path / "set", "heldout", diagnostics=export)
    output["labels_sha256"] = d.digest(b"different seal")
    changed_sha = write(export, output)
    with pytest.raises(d.DiagnosticError):
        score_set(tmp_path / "set", "heldout", diagnostics=export, diagnostics_sha256=changed_sha)


@pytest.mark.parametrize("mutation", ["plan", "packet", "labels", "code"])
def test_frozen_state_change_between_workers_refuses(tmp_path, monkeypatch, mutation):
    factory, _, _, _, _, _ = fixture(tmp_path)
    session = factory()
    calls = []

    def worker(version, packet):
        calls.append(version["id"])
        result = fake_worker(version, packet)
        if mutation == "plan":
            session.plan["reader"]["id"] = "changed"
        elif mutation == "packet":
            session.packets[0][1]["candidates"][0]["value"] = "1"
        elif mutation == "labels":
            session.labels["documents"][0]["fields"][0]["values"][0]["value"] = "9"
        else:
            original = d.file_digest
            monkeypatch.setattr(
                d,
                "file_digest",
                lambda path, *args: (
                    d.digest(b"changed") if path.name == "diagnostics.py" else original(path, *args)
                ),
            )
        return result

    with pytest.raises(d.DiagnosticError):
        session.run(worker=worker)
    assert calls == ["0.8"]


def test_cache_tampering_extra_records_and_unresolved_reservation_refuse(tmp_path):
    factory, _, _, _, _, _ = fixture(tmp_path)
    session = factory()
    session.run(worker=fake_worker)
    (session.folder / "extra.json").write_text("{}")
    with pytest.raises(d.DiagnosticError):
        factory().run(replay_only=True)
    (session.folder / "extra.json").unlink()
    result = session.folder / (
        d.digest(d.encoded(["packet", "0.8"])).removeprefix("sha256:") + ".json"
    )
    body = json.loads(result.read_text())
    body["value"]["receipt"]["decisions"][0]["value"] = "1"
    result.write_text(json.dumps(body))
    with pytest.raises(d.DiagnosticError):
        factory().run(replay_only=True)


def test_real_offset_boundary_is_checked_after_packet_hash_is_updated(tmp_path):
    _, plan, packet, path, inputs, cache = fixture(tmp_path)
    packet["candidates"][0]["evidence"][0]["start"] = 1
    plan["packets"][0]["sha256"] = write(inputs / "packet.json", packet)
    seal = write(path, plan)
    with pytest.raises(d.DiagnosticError, match="UTF-8"):
        d.DiagnosticSession(
            path, tmp_path / "set", tmp_path / "sources", inputs, cache, plan_sha256=seal
        )


def test_geometry_work_caps_prevent_tab_object_amplification():
    text = "\t" * 200001
    layout = {
        "groundgate_layout": "0.1",
        "document_sha256": d.gg.digest("document", {"text": text}),
        "pages": [],
        "words": [],
    }
    with pytest.raises(d.DiagnosticError, match="cap"):
        d.serialized_layout(text, layout)


def test_partial_layout_empty_cell_and_missing_head_remain_honest():
    text = "A\t\t9"
    layout = {
        "groundgate_layout": "0.1",
        "document_sha256": d.core_digest("0.9", "document", {"text": text}),
        "pages": [{"page": 1, "width": 100, "height": 100, "start": 0, "end": 4}],
        "words": [[0, 1, 1, 0, 0, 10, 10], [3, 4, 1, 30, 0, 40, 10]],
    }
    trace = d.serialized_layout(text, layout)
    cases = [
        {
            "id": "blank",
            "page": 1,
            "state": "observed",
            "box": [0, 0, 10, 10],
            "expected": 1,
            "reason": "",
        }
    ]
    ann = [
        {
            "id": "doc",
            "source_pages": 2,
            "reviewed_pages": [1],
            "complete": False,
            "routes": [
                {"route": "empty_cells", "assessment": "applicable", "cases": cases},
                {
                    "route": "running_heads",
                    "assessment": "applicable",
                    "cases": [
                        {
                            "id": "head",
                            "target": {"page": 1, "box": [0, 0, 10, 10]},
                            "page": 1,
                            "state": "observed",
                            "box": [0, 80, 40, 90],
                            "expected": False,
                            "reason": "",
                        }
                    ],
                },
            ],
        }
    ]
    result = d.score_layout(ann, [{"document": "doc", "reader": "draft", "trace": trace}])
    assert result["routes"]["draft/empty_cells"]["correct"] == 1
    head = result["routes"]["draft/running_heads"]
    assert (head["evaluated"], head["unassessed"], head["rate"]) == (0, 1, None)
    assert head["partial_documents"] == head["unreviewed_pages"] == 1
    missing = d.score_layout(ann, [])
    assert missing["status"] == "unassessed" and missing["missing_observations"] == ["doc"]
    ann[0]["routes"][0] = {"route": "empty_cells", "assessment": "not_applicable", "cases": []}
    with pytest.raises(d.DiagnosticError):
        d.score_layout(ann, [{"document": "doc", "reader": "draft", "trace": trace}])


def test_layout_work_counts_only_rows_on_the_case_page(monkeypatch):
    text = "A\t\t9"
    layout = {
        "groundgate_layout": "0.1",
        "document_sha256": d.core_digest("0.9", "document", {"text": text}),
        "pages": [{"page": 1, "width": 100, "height": 100, "start": 0, "end": 4}],
        "words": [[0, 1, 1, 0, 0, 10, 10], [3, 4, 1, 30, 0, 40, 10]],
    }
    trace = d.serialized_layout(text, layout)
    # A full observation has many rows on pages that no case is on.
    trace["rows"] += [copy.deepcopy(trace["rows"][0]) | {"page": 2} for _ in range(100)]
    case = {"id": "blank", "page": 1, "state": "observed", "box": [0, 0, 10, 10]}
    ann = [
        {
            "id": "doc",
            "source_pages": 2,
            "reviewed_pages": [1],
            "complete": False,
            "routes": [
                {
                    "route": "empty_cells",
                    "assessment": "applicable",
                    "cases": [case | {"expected": 1, "reason": ""}],
                }
            ],
        }
    ]
    observations = [{"document": "doc", "reader": "draft", "trace": trace}]
    monkeypatch.setattr(d, "_LAYOUT_WORK", 10)
    assert d.score_layout(ann, observations)["routes"]["draft/empty_cells"]["correct"] == 1
    monkeypatch.setattr(d, "_LAYOUT_WORK", 0)
    with pytest.raises(d.DiagnosticError, match="layout geometry work cap"):
        d.score_layout(ann, observations)


def test_duplicate_candidate_occurrences_and_reference_domain_are_preserved(tmp_path):
    _, plan, packet, _, _, _ = fixture(tmp_path)
    version = plan["versions"][0]
    packet["references"] = [
        {"id": "z", "text": "reference Z", "source": "https://example.org/z"},
        {"id": "a", "text": "reference A"},
    ]
    packet["candidates"].append(copy.deepcopy(packet["candidates"][0]))
    result = fake_worker(version, packet)
    receipt = result["receipt"]
    receipt["references"] = [
        {
            "id": r["id"],
            "source": r.get("source"),
            "sha256": d.core_digest("0.8", "reference", {"text": r["text"]}),
        }
        for r in sorted(packet["references"], key=lambda r: r["id"])
    ]
    receipt["decisions"] *= 2
    receipt["summary"]["admitted"] = 2
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = d.core_digest("0.8", "receipt", receipt)
    ordered = d.DiagnosticSession._receipt(version, packet, result)
    assert len(ordered) == 2 and ordered[0] == ordered[1]
    receipt["decisions"].pop()
    receipt["summary"]["admitted"] = 1
    receipt.pop("receipt_sha256")
    receipt["receipt_sha256"] = d.core_digest("0.8", "receipt", receipt)
    with pytest.raises(d.DiagnosticError, match="missing or extra"):
        d.DiagnosticSession._receipt(version, packet, result)


def test_sealed_observation_layout_is_kind_sliced_and_replayed(tmp_path):
    _, plan, packet, path, inputs, cache = fixture(tmp_path)
    ann = {
        "format": "requested-layout-labels/1",
        "status": "sealed",
        "manifest_sha256": plan["manifest_sha256"],
        "labels_sha256": plan["labels_sha256"],
        "documents": [
            {
                "id": "doc",
                "source_sha256": d.digest(b"synthetic PDF"),
                "source_pages": 1,
                "reviewed_pages": [1],
                "complete": True,
                "routes": [
                    {"route": "empty_cells", "assessment": "not_applicable", "cases": []},
                    {
                        "route": "ambiguous_columns",
                        "assessment": "applicable",
                        "cases": [
                            {
                                "id": "max",
                                "page": 1,
                                "state": "observed",
                                "box": [40, 20, 50, 30],
                                "expected": 2,
                                "reason": "",
                            }
                        ],
                    },
                ],
            }
        ],
    }
    obs = {
        "source_sha256": d.digest(b"synthetic PDF"),
        "reader": "new-reader",
        "commit": "fixed",
        "code_sha256": d.digest(b"reader"),
        "text": packet["text"],
        "text_sha256": d.digest(packet["text"].encode()),
        "layout": {
            "groundgate_layout": "0.1",
            "document_sha256": d.core_digest("0.9", "document", {"text": packet["text"]}),
            "pages": [{"page": 1, "start": 0, "end": 12, "width": 100, "height": 100}],
            "words": [
                [0, 2, 1, 0, 0, 10, 10],
                [3, 8, 1, 0, 20, 20, 30],
                [9, 10, 1, 30, 20, 35, 30],
                [11, 12, 1, 40, 20, 50, 30],
            ],
        },
    }
    ann["documents"][0]["routes"].append(
        {
            "route": "running_heads",
            "assessment": "applicable",
            "cases": [
                {
                    "id": "mu-head",
                    "page": 1,
                    "state": "observed",
                    "box": [0, 0, 10, 10],
                    "target": {"page": 1, "box": [0, 20, 20, 30]},
                    "expected": True,
                    "reason": "Same emitted block in this synthetic observation.",
                }
            ],
        }
    )
    plan["layout"] = {
        "annotations": {
            "path": "annotations.json",
            "sha256": write(inputs / "annotations.json", ann),
        },
        "observations": [
            {
                "document": "doc",
                "reader": "new-reader",
                "commit": "fixed",
                "code_sha256": d.digest(b"reader"),
                "path": "observation.json",
                "sha256": write(inputs / "observation.json", obs),
            }
        ],
    }
    seal = write(path, plan)
    session = d.DiagnosticSession(
        path, tmp_path / "set", tmp_path / "sources", inputs, cache, plan_sha256=seal
    )
    result = session.run(worker=fake_worker)
    routes = result["diagnostics"]["reader_layout"]["routes"]
    assert routes["kind/new-reader/empty_cells"]["not_applicable"] == 1
    assert routes["kind/new-reader/empty_cells"]["rate"] is None
    assert routes["kind/new-reader/ambiguous_columns"]["rate"] == 1
    assert session.run(replay_only=True) == result
    assert routes["kind/new-reader/running_heads"]["correct"] == 1
    head = ann["documents"][0]["routes"][-1]["cases"][0]
    target = head.pop("target")
    plan["layout"]["annotations"]["sha256"] = write(inputs / "annotations.json", ann)
    seal = write(path, plan)
    with pytest.raises(d.DiagnosticError, match="member"):
        d.DiagnosticSession(
            path, tmp_path / "set", tmp_path / "sources", inputs, cache, plan_sha256=seal
        )
    head["target"] = target
    plan["layout"]["annotations"]["sha256"] = write(inputs / "annotations.json", ann)
    obs["layout"]["words"][0][1] = 1  # Splits the actual UTF-8 character.
    plan["layout"]["observations"][0]["sha256"] = write(inputs / "observation.json", obs)
    seal = write(path, plan)
    with pytest.raises(d.DiagnosticError, match="UTF-8"):
        d.DiagnosticSession(
            path, tmp_path / "set", tmp_path / "sources", inputs, cache, plan_sha256=seal
        )
    obs["layout"]["words"][0][1] = 2
    plan["layout"]["observations"][0]["sha256"] = write(inputs / "observation.json", obs)
    seal = write(path, plan)
    session = d.DiagnosticSession(
        path, tmp_path / "set", tmp_path / "sources", inputs, cache, plan_sha256=seal
    )
    # An observation that names its own reader or text consistently still needs the frozen ones.
    session.plan["reader"]["commit"] = "other"
    with pytest.raises(d.DiagnosticError, match="provenance differs"):
        session._layout()
    session.plan["reader"]["commit"] = "fixed"
    other = obs | {"text": "Other text.", "text_sha256": d.digest(b"Other text.")}
    refs = session.plan["layout"]["observations"]
    refs[0]["sha256"] = write(inputs / "observation.json", other)
    with pytest.raises(d.DiagnosticError, match="provenance differs"):
        session._layout()
    refs[0]["sha256"] = write(inputs / "observation.json", obs)
    session._layout()
    # The cap is on the sum of the observation files, and a file at the cap passes.
    size = (inputs / "observation.json").stat().st_size
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(d, "_LAYOUT_TOTAL", size - 1)
        with pytest.raises(d.DiagnosticError, match="layout input total cap"):
            session._layout()
        patch.setattr(d, "_LAYOUT_TOTAL", size)
        session._layout()
    # The only document is held out, so a development plan must refuse its layout cases.
    session.plan["split"] = "development"
    with pytest.raises(d.DiagnosticError, match="layout split differs"):
        session._layout()
    ann["documents"] = []
    session.plan["layout"]["annotations"]["sha256"] = write(inputs / "annotations.json", ann)
    with pytest.raises(d.DiagnosticError, match="layout split differs"):
        session._layout()


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_isolated_worker_output_pipes_are_bounded_without_core_calls(
    tmp_path, monkeypatch, channel
):
    shim = tmp_path / "fake-python"
    # This executable ignores the fixed worker script. It makes no decision or model call.
    shim.write_text(
        "#!/usr/bin/env python3\nimport sys\nsys." + channel + '.buffer.write(b"x" * 100000)\n'
    )
    shim.chmod(0o700)
    version = {"python": str(shim), "python_sha256": d.file_digest(shim)}
    monkeypatch.setattr(d, "_MAX", 1024)
    with pytest.raises(d.DiagnosticError, match="cap"):
        d.run_worker(version, {}, temporary=tmp_path)


def test_unknown_companion_key_admit_is_an_escape_not_dropped(tmp_path):
    _, plan, packet, path, inputs, cache = fixture(tmp_path)
    packet["candidates"][0]["key"] = "undeclared"
    plan["packets"][0]["sha256"] = write(inputs / "packet.json", packet)
    seal = write(path, plan)
    session = d.DiagnosticSession(
        path, tmp_path / "set", tmp_path / "sources", inputs, cache, plan_sha256=seal
    )
    result = session.run(worker=fake_worker)["diagnostics"]["decision_pair"]
    assert result["by_view"]["endpoints"]["0.8"]["escapes"] == 1
    assert result["by_view"]["endpoints"]["0.8"]["admitted"] == 1
    assert result["by_view"]["endpoints"]["0.9"]["reviews"] == 0
    assert result["transitions"] == {"admitted->needs_verification": 1}


@pytest.mark.parametrize(
    "fields",
    [
        {"f" + str(i): {"keys": ["k"]} for i in range(1025)},
        {"f": {"keys": ["k"] * 4097}},
        {"f": {"keys": ["k"] * 3000}, "g": {"keys": ["k"] * 3000}},
    ],
)
def test_keyed_schema_expansion_refuses_before_schema_or_worker(fields, monkeypatch):
    session = object.__new__(d.DiagnosticSession)
    session.docs = {"doc": {"split": "heldout"}}
    session.plan = {"split": "heldout"}
    session.views = {}

    def forbidden(*args):
        pytest.fail("oversized keyed schema reached schema construction")

    monkeypatch.setattr(d.gg.Schema, "from_dict", forbidden)
    with pytest.raises(d.DiagnosticError, match="cap"):
        session._view(
            {
                "id": "v",
                "document": "doc",
                "schema": {"fields": fields},
                "mapping": [],
                "comparator_adapter": None,
            }
        )


def test_actual_isolated_public_worker_matches_hand_authored_simple_expectation(tmp_path):
    # Expected outcome is fixed before execution, never derived by running the core.
    expected_outcome, expected_codes = "admitted", []
    fingerprint_code = """
import hashlib, json
from pathlib import Path
import groundgate as gg
from groundgate.canonical import SPEC_VERSION
root = Path(gg.__file__).parent
files = {str(p.relative_to(root)): 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(root.rglob('*')) if p.suffix in {'.py', '.json'}}
print(json.dumps({'package_version': gg.__version__, 'spec_version': SPEC_VERSION,
                  'code_sha256': 'sha256:' + hashlib.sha256(gg.jcs(files).encode()).hexdigest()}))
"""
    version = json.loads(
        subprocess.check_output([sys.executable, "-I", "-c", fingerprint_code], timeout=10)
    )
    assert version["spec_version"] in {"0.8", "0.9", "0.10"}
    version.update(
        id=version["spec_version"],
        python=sys.executable,
        python_sha256=d.file_digest(Path(sys.executable).resolve()),
        commit="synthetic",
    )
    packet = {
        "text": "amount 5",
        "schema": {"fields": {"amount": {"type": "number"}}},
        "candidates": [
            {
                "id": "simple",
                "field": "amount",
                "value": "5",
                "evidence": [{"source": "document", "role": "value", "start": 7, "end": 8}],
            }
        ],
        "policy": {},
        "document_id": "synthetic",
        "document_source": None,
        "references": [],
        "judgments": [],
    }
    value = d.run_worker(version, packet, temporary=tmp_path)
    ordered = d.DiagnosticSession._receipt(version, packet, value)
    assert len(ordered) == 1
    assert (ordered[0]["outcome"], ordered[0]["codes"]) == (expected_outcome, expected_codes)
    assert ordered[0]["value"] == "5" and ordered[0]["field"] == "amount"


def test_retained_running_head_is_scored_by_target_block_not_text_presence():
    annotation = [
        {
            "id": "doc",
            "source_pages": 1,
            "reviewed_pages": [1],
            "complete": True,
            "routes": [
                {
                    "route": "running_heads",
                    "assessment": "applicable",
                    "cases": [
                        {
                            "id": "head",
                            "page": 1,
                            "state": "observed",
                            "box": [0, 0, 20, 10],
                            "target": {"page": 1, "box": [0, 20, 10, 30]},
                            "expected": False,
                            "reason": "Target row must be in a separate serialized block.",
                        }
                    ],
                }
            ],
        }
    ]
    observations = []
    for reader, separator in (("old", "\n"), ("new", "\n\n")):
        text = "Head" + separator + "A\t9"
        start = 4 + len(separator)
        layout = {
            "groundgate_layout": "0.1",
            "document_sha256": d.core_digest("0.9", "document", {"text": text}),
            "pages": [{"page": 1, "start": 0, "end": len(text), "width": 100, "height": 100}],
            "words": [
                [0, 4, 1, 0, 0, 20, 10],
                [start, start + 1, 1, 0, 20, 10, 30],
                [start + 2, start + 3, 1, 30, 20, 40, 30],
            ],
        }
        observations.append(
            {"document": "doc", "reader": reader, "trace": d.serialized_layout(text, layout)}
        )
    routes = d.score_layout(annotation, observations)["routes"]
    assert routes["old/running_heads"]["evaluated"] == 1
    assert routes["old/running_heads"]["correct"] == 0
    assert routes["new/running_heads"]["correct"] == 1
    # Both versions still contain the head. A missing/ambiguous target cannot count as success.
    annotation[0]["routes"][0]["cases"][0]["target"]["box"] = [0, 80, 40, 90]
    missing = d.score_layout(annotation, observations)["routes"]
    assert all(
        r["evaluated"] == 0 and r["unassessed"] == 1 and r["rate"] is None for r in missing.values()
    )
    annotation[0]["routes"][0]["cases"][0]["target"]["box"] = [0, 20, 40, 30]
    ambiguous = d.score_layout(annotation, observations)["routes"]
    assert all(r["evaluated"] == 0 and r["unassessed"] == 1 for r in ambiguous.values())
