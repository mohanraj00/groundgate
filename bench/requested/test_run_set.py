"""Requested-set harness checks with synthetic sources and fixed transport replies only."""

from __future__ import annotations

import builtins
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from requested import run_set as harness


class Client:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.replies:
            pytest.fail("unexpected transport call")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)


def candidate(value="5", field="amount", quote=None, **extra):
    return {
        "field": field,
        "value": value,
        "unit": None,
        "key": None,
        "evidence": [
            {"source": "document", "role": "value", "text": value if quote is None else quote}
        ],
        **extra,
    }


def envelope(*items):
    return {"candidates": list(items)}


def runner_envelope(*items, missing=()):
    return envelope(*items) | {"not_found": list(missing)}


def fixture(tmp_path, text="Amount 5.", fields=None, settings=None, mutate=None):
    directory = tmp_path / "set"
    sources = tmp_path / "sources"
    cache = tmp_path / "cache"
    directory.mkdir(parents=True)
    sources.mkdir()
    (sources / "doc.pdf").write_bytes(b"synthetic source bytes")
    (sources / "doc.txt").write_text(text, encoding="utf-8")
    fields = fields or {"amount": {"type": "number"}}
    manifest = {
        "status": "frozen",
        "selection_complete": True,
        "schemas": {"kind": {"fields": fields}},
        "documents": [
            {
                "id": "doc",
                "kind": "kind",
                "split": "heldout",
                "source": "https://example.org/synthetic.pdf",
                "source_bytes": 22,
                "source_pages": 1,
                "approved_max_bytes": 1024,
                "source_sha256": harness.digest((sources / "doc.pdf").read_bytes()),
                "text_sha256": harness.digest(text.encode()),
            }
        ],
    }
    slots = []
    for name, spec in fields.items():
        for key in spec.get("keys") or [None]:
            slot = {"field": name, "key": key, "page": 1}
            if name == "missing":
                slot |= {
                    "status": "absent",
                    "second_check": True,
                    "note": "secret-absence-annotation",
                }
            elif name == "unclear":
                slot |= {"status": "unclear", "reason": "secret-unclear-annotation"}
            else:
                value = "secret-gold-string" if spec.get("type") == "string" else "987654321"
                slot |= {
                    "status": "present",
                    "values": [{"value": value, "unit": spec.get("unit")}],
                    "note": "secret-gold-annotation",
                }
            slots.append(slot)
    labels = {"status": "sealed", "documents": [{"id": "doc", "fields": slots}]}
    config = {
        "model_id": "fixed-model-1",
        "transport": {"id": "fake", "version": "1", "effort": "fixed"},
        "policy": {},
        "source_commit": "synthetic-source-commit",
        "reader": {
            "id": "synthetic-reader",
            "commit": "synthetic-reader-commit",
            "code_sha256": "synthetic-reader-digest",
        },
        "baseline_guide_commit": "synthetic-guide-commit",
        "code_sha256": harness.source_code_digest(),
        "run_policy": {
            "chunk_chars": 12000,
            "overlap_chars": 1000,
            "max_repair_rounds": 2,
            "targeted": True,
            "search_context_chars": 1000,
            "max_target_regions": 8,
            "max_calls": 128,
            "max_prompt_chars": 65536,
            "max_reply_bytes": 1048576,
            "max_candidates_per_reply": 256,
            "max_total_candidates": 1024,
            "max_admission_bytes": 8388608,
        },
    }
    config["run_policy"].update(settings or {})
    if mutate:
        mutate(manifest, labels, config)
    paths = {
        "manifest": directory / "manifest.json",
        "labels": directory / "labels.json",
        "configuration": tmp_path / "configuration.json",
    }
    for name, value in (("manifest", manifest), ("labels", labels), ("configuration", config)):
        paths[name].write_bytes(harness.encoded(value))
    kwargs = {name + "_sha256": harness.digest(path.read_bytes()) for name, path in paths.items()}
    session = harness.FrozenSet(directory, sources, cache, paths["configuration"], **kwargs)
    return session, paths


def output(result):
    return result["documents"][0]


def local(session, name):
    return next(session.cache.rglob(name))


@pytest.mark.parametrize(
    "change",
    [
        lambda m, labels, c: m.update(status="draft"),
        lambda m, labels, c: m.update(selection_complete=False),
        lambda m, labels, c: labels.update(status="draft"),
        lambda m, labels, c: m["documents"][0].update(source_sha256="sha256:" + "0" * 64),
        lambda m, labels, c: m["documents"][0].update(text_sha256="sha256:" + "0" * 64),
        lambda m, labels, c: c.update(code_sha256="sha256:" + "0" * 64),
    ],
)
def test_gates_refuse_before_any_transport(tmp_path, change):
    with pytest.raises(harness.CacheError):
        fixture(tmp_path, mutate=change)


@pytest.mark.parametrize("target", ["manifest", "labels", "configuration", "source", "text"])
def test_mutated_frozen_files_refuse_before_call(tmp_path, target):
    session, paths = fixture(tmp_path)
    path = paths.get(target) or session.sources / ("doc.pdf" if target == "source" else "doc.txt")
    path.write_bytes(path.read_bytes() + b" ")
    client = Client(envelope(candidate()))
    with pytest.raises(harness.CacheError):
        session.run("baseline", client)
    assert client.prompts == []


def test_baseline_retains_initial_admit_and_asks_feedback_once(tmp_path):
    fields = {"amount": {"type": "number"}, "other": {"type": "number"}}
    session, _ = fixture(tmp_path, "Amount 5. Other 6.", fields)
    client = Client(
        envelope(candidate(), candidate("6", "other", quote="missing")),
        envelope(candidate("6", "other")),
    )
    result = session.run("baseline", client)
    assert len(client.prompts) == 2
    assert "feedback" not in json.loads(client.prompts[0])
    assert "QUOTE_NOT_FOUND" in json.loads(client.prompts[1])["feedback"]
    admitted = {d["field"] for d in output(result)["decisions"] if d["outcome"] == "admitted"}
    assert admitted == {"amount", "other"}
    saved = json.loads(local(session, "result.json").read_bytes())
    assert len(saved["rounds"]) == 2 and saved["rounds"][1]["retry"] is True
    assert session.run("baseline") == result
    no_repeat = Client()
    assert session.run("baseline", no_repeat) == result and not no_repeat.prompts


def test_failed_retry_stops_after_one_and_terminal_value_has_no_retry(tmp_path):
    session, _ = fixture(tmp_path)
    client = Client(envelope(candidate(quote="missing")), envelope(candidate(quote="missing")))
    result = session.run("baseline", client)
    assert len(client.prompts) == 2 and output(result)["complete"]
    assert all(d["outcome"] != "admitted" for d in output(result)["decisions"])
    other, _ = fixture(tmp_path / "other", text="Amount 5.")
    terminal = Client(envelope(candidate("6", quote="5")))
    other.run("baseline", terminal)
    assert len(terminal.prompts) == 1


def test_app_conflict_filter_uses_only_independent_admits(tmp_path):
    fields = {"amount": {"type": "number"}, "other": {"type": "number"}}
    session, _ = fixture(tmp_path, "Amount 5. Amount 7. Other 6.", fields)
    client = Client(
        envelope(candidate(), candidate("6", "other", quote="missing")), envelope(candidate("7"))
    )
    result = session.run("baseline", client)
    conflicts = [d for d in output(result)["decisions"] if d["field"] == "amount"]
    assert {d["value"] for d in conflicts} == {"5", "7"}
    assert all(
        d["outcome"] == "needs_verification" and d["core_outcome"] == "admitted" for d in conflicts
    )
    assert all(d["application_reason"] == "conflicting_round_admits" for d in conflicts)
    saved = json.loads(local(session, "result.json").read_bytes())
    assert all(
        d["outcome"] == "admitted"
        for r in saved["rounds"]
        for d in r["receipt"]["decisions"]
        if d["field"] == "amount"
    )
    assert session.run("baseline") == result

    other, _ = fixture(tmp_path / "other", "Amount 5. Amount 7. Other 6.", fields)
    result = other.run(
        "baseline",
        Client(
            envelope(candidate("7", quote="5"), candidate("6", "other", quote="missing")),
            envelope(candidate("7")),
        ),
    )
    admitted = [d for d in output(result)["decisions"] if d["outcome"] == "admitted"]
    assert len(admitted) == 1 and admitted[0]["value"] == "7"
    assert not any("application_reason" in d for d in output(result)["decisions"])


def test_chunks_share_limits_stop_at_end_and_bound_core_quote_region(tmp_path):
    text = "Amount 5.\nAmount 6."
    session, _ = fixture(tmp_path, text, settings={"chunk_chars": 10, "overlap_chars": 0})
    client = Client(envelope(candidate()), envelope(candidate("6")))
    result = session.run("baseline", client)
    assert [json.loads(p)["text"] for p in client.prompts] == ["Amount 5.\n", "Amount 6."]
    assert all(d["outcome"] == "needs_verification" for d in output(result)["decisions"])
    saved = json.loads(local(session, "result.json").read_bytes())
    assert saved["rounds"][0]["candidates"][0]["search_region"] == {"start": 0, "end": 10}
    assert (
        saved["rounds"][1]["receipt"]["document"]["sha256"]
        == saved["rounds"][0]["receipt"]["document"]["sha256"]
    )


def test_equivalent_and_multiple_admits_do_not_create_app_conflicts():
    def decision(value, outcome="admitted"):
        return {
            "candidate_id": value,
            "field": "amount",
            "key": None,
            "unit": None,
            "value": value,
            "outcome": outcome,
            "codes": [],
        }

    rounds = [{"receipt": {"decisions": [decision("5"), decision("5")]}}]
    assert all(
        d["outcome"] == "admitted"
        for d in harness.storage_outcomes(rounds, {"fields": {"amount": {}}})
    )
    rounds[0]["receipt"]["decisions"].append(decision("6"))
    assert all(
        d["outcome"] == "admitted"
        for d in harness.storage_outcomes(rounds, {"fields": {"amount": {"multiple": True}}})
    )


def test_label_content_never_reaches_prompt_and_export_has_no_evidence(tmp_path):
    fields = {name: {"type": "number"} for name in ("amount", "missing", "unclear")}
    session, _ = fixture(tmp_path, fields=fields)
    client = Client(envelope(candidate()))
    result = session.run("baseline", client)
    prompt = client.prompts[0]
    assert set(json.loads(prompt)["schema"]["fields"]) == set(fields)
    assert json.loads(prompt)["instructions"] == harness.BASELINE_INSTRUCTIONS
    for secret in (
        "987654321",
        "secret-gold-annotation",
        "secret-absence-annotation",
        "secret-unclear-annotation",
    ):
        assert secret not in prompt
    public = harness.encoded(result).decode()
    assert "Amount 5." not in public and '"evidence"' not in public and '"reply"' not in public
    assert output(result)["not_found"] == []


def test_budget_refuses_all_initial_prompts_before_call(tmp_path):
    session, _ = fixture(tmp_path, settings={"max_prompt_chars": 1})
    client = Client()
    with pytest.raises(harness.CacheError, match="initial prompt"):
        session.run("baseline", client)
    assert client.prompts == []


def test_cache_tampering_and_unresolved_reservation_refuse_reuse(tmp_path):
    session, _ = fixture(tmp_path)
    session.run("baseline", Client(envelope(candidate())))
    call = local(session, "0001.json")
    saved = json.loads(call.read_bytes())
    saved["reply"] = "tampered"
    call.write_bytes(harness.encoded(saved))
    client = Client()
    with pytest.raises(harness.CacheError, match="cached call differs"):
        session.run("baseline", client)
    assert not client.prompts

    other, _ = fixture(tmp_path / "other")
    crash = Client(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        other.run("baseline", crash)
    assert local(other, "0001.pending.json").exists()
    with pytest.raises(harness.CacheError, match="unresolved"):
        other.run("baseline", Client())


def test_resume_after_cached_initial_reply_calls_only_retry(tmp_path, monkeypatch):
    session, _ = fixture(tmp_path)
    original = harness._baseline_reply

    def crash(*args):
        raise RuntimeError("synthetic process stop after durable reply")

    monkeypatch.setattr(harness, "_baseline_reply", crash)
    with pytest.raises(RuntimeError):
        session.run("baseline", Client(envelope(candidate(quote="missing"))))
    monkeypatch.setattr(harness, "_baseline_reply", original)
    remaining = Client(envelope(candidate()))
    result = session.run("baseline", remaining)
    assert len(remaining.prompts) == 1 and "feedback" in json.loads(remaining.prompts[0])
    assert session.run("baseline") == result


def test_failure_cache_retains_no_exception_message(tmp_path):
    session, _ = fixture(tmp_path)
    result = session.run("baseline", Client(RuntimeError("private-transport-secret")))
    assert not output(result)["complete"]
    assert "private-transport-secret" not in local(session, "0001.json").read_text()
    assert session.run("baseline") == result


def test_missing_runner_module_refuses_before_transport(tmp_path, monkeypatch):
    session, _ = fixture(tmp_path)
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "groundgate.extract":
            raise ImportError("synthetic missing integration")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    client = Client()
    with pytest.raises(harness.CacheError, match="integrated runner API"):
        session.run("runner", client)
    assert not client.prompts


requires_runner = pytest.mark.skipif(
    importlib.util.find_spec("groundgate.extract") is None, reason="runner integration pending"
)


@requires_runner
@pytest.mark.parametrize("later", [candidate("6"), candidate("7", quote="6")])
def test_runner_multichunk_initial_omission_is_not_final_absence(tmp_path, later):
    session, _ = fixture(
        tmp_path, "Amount 5.\nAmount 6.", settings={"chunk_chars": 10, "overlap_chars": 0}
    )
    client = Client(runner_envelope(missing=("amount",)), runner_envelope(later))
    result = session.run("runner", client)
    assert output(result)["not_found"] == []
    assert session.run("runner") == result


@requires_runner
@pytest.mark.parametrize(
    "keys,description,max_calls",
    [
        (None, None, 128),
        (["one"], None, 128),
        (None, " ".join(f"term{i}" for i in range(100)), 128),
        (None, None, 1),
    ],
)
def test_runner_absence_needs_completed_untruncated_unkeyed_search(
    tmp_path, keys, description, max_calls
):
    spec = {"type": "number"}
    if keys:
        spec["keys"] = keys
    if description:
        spec["description"] = description
    session, _ = fixture(tmp_path, fields={"amount": spec}, settings={"max_calls": max_calls})
    client = Client(runner_envelope(missing=("amount",)), runner_envelope(missing=("amount",)))
    result = session.run("runner", client)
    assert bool(output(result)["not_found"]) == (
        keys is None and description is None and max_calls > 1
    )
    assert session.run("runner") == result


def test_expected_seals_and_code_snapshot_are_checked(tmp_path, monkeypatch):
    session, paths = fixture(tmp_path)
    with pytest.raises(harness.CacheError, match="digest differs"):
        harness.FrozenSet(
            session.directory,
            session.sources,
            session.cache,
            paths["configuration"],
            manifest_sha256=harness.digest(paths["manifest"].read_bytes()),
            labels_sha256="sha256:" + "0" * 64,
            configuration_sha256=harness.digest(paths["configuration"].read_bytes()),
        )
    monkeypatch.setattr(harness, "source_code_digest", lambda: "sha256:" + "0" * 64)
    client = Client()
    with pytest.raises(harness.CacheError, match="source code changed"):
        session.run("baseline", client)
    assert not client.prompts


def test_source_change_between_calls_refuses_next_transport(tmp_path):
    session, _ = fixture(tmp_path)
    calls = []

    def client(prompt):
        calls.append(prompt)
        (session.sources / "doc.txt").write_text("changed source", encoding="utf-8")
        return json.dumps(envelope(candidate(quote="missing")))

    with pytest.raises(harness.CacheError, match="changed"):
        session.run("baseline", client)
    assert len(calls) == 1
    assert not list(session.cache.rglob("result.json"))


@pytest.mark.parametrize(
    "bad",
    [
        '{"candidates":[],"candidates":[]}',
        '{"candidates":[],"not_found":["amount"]}',
        '{"candidates":[],"x":NaN}',
        envelope(candidate(id="model-controlled")),
        envelope(
            candidate(evidence=[{"source": "document", "role": "value", "text": "5", "start": 0}])
        ),
    ],
)
def test_baseline_invalid_reply_is_cached_and_replays_without_salvage(tmp_path, bad):
    session, _ = fixture(tmp_path)
    result = session.run("baseline", Client(bad))
    assert not output(result)["complete"] and output(result)["decisions"] == []
    assert session.run("baseline") == result


def test_linked_source_and_linked_cache_parents_are_refused(tmp_path):
    session, _ = fixture(tmp_path)
    source = session.sources / "doc.txt"
    target = tmp_path / "elsewhere.txt"
    source.rename(target)
    source.symlink_to(target)
    with pytest.raises(harness.CacheError):
        session.run("baseline", Client())
    source.unlink()
    target.rename(source)
    result = session.run("baseline", Client(envelope(candidate())))
    folder = local(session, "result.json").parent
    moved = tmp_path / "moved-cache"
    folder.rename(moved)
    folder.symlink_to(moved, target_is_directory=True)
    with pytest.raises(harness.CacheError, match="symlink"):
        session.run("baseline")
    assert result["arm"] == "baseline"


def test_baseline_external_and_knowledge_sources_keep_default_review(tmp_path):
    session, _ = fixture(tmp_path)
    known = candidate(evidence=[{"source": "knowledge", "text": "The synthetic amount is 5."}])
    external = candidate(
        evidence=[
            {
                "source": "external",
                "text": "Amount 5.",
                "url": "https://example.org/source",
                "retrieved": "2026-01-01",
            }
        ]
    )
    client = Client(envelope(known, external))
    result = session.run("baseline", client)
    assert len(client.prompts) == 1
    assert all(d["outcome"] == "needs_verification" for d in output(result)["decisions"])
    assert session.run("baseline") == result


@pytest.mark.parametrize(
    "invalid",
    [
        "empty_documents",
        "unknown_document",
        "missing_field",
        "duplicate_field",
        "unknown_field",
        "numeric_value",
        "unit",
        "missing_page",
        "zero_page",
        "page_past_source",
        "boolean_page",
        "unclear_without_reason",
        "absent_without_second_check",
        "unlabeled",
    ],
)
def test_invalid_full_label_seal_refuses_before_client_or_cache(tmp_path, invalid):
    def change(manifest, labels, config):
        slots = labels["documents"][0]["fields"]
        slot = slots[0]
        if invalid == "empty_documents":
            labels["documents"] = []
        elif invalid == "unknown_document":
            labels["documents"][0]["id"] = "unrequested"
        elif invalid == "missing_field":
            slots.clear()
        elif invalid == "duplicate_field":
            slots.append(copy.deepcopy(slot))
        elif invalid == "unknown_field":
            slot["field"] = "unrequested"
        elif invalid == "numeric_value":
            slot["values"][0]["value"] = "not a number"
        elif invalid == "unit":
            slot["values"][0]["unit"] = "USD"
        elif invalid == "missing_page":
            slot.pop("page")
        elif invalid == "zero_page":
            slot["page"] = 0
        elif invalid == "page_past_source":
            slot["page"] = 2
        elif invalid == "boolean_page":
            slot["page"] = True
        elif invalid == "unclear_without_reason":
            slot.update(status="unclear", values=[], reason=" ")
        elif invalid == "absent_without_second_check":
            slot.update(status="absent", values=[], second_check=False)
        else:
            slot.update(status="unlabeled", values=[])

    client = Client()
    with pytest.raises(harness.CacheError, match="blind labels"):
        session, _ = fixture(tmp_path, mutate=change)
        session.run("baseline", client)
    assert client.prompts == []
    assert not (tmp_path / "cache").exists()


def test_missing_requested_key_refuses_before_client_or_cache(tmp_path):
    def change(manifest, labels, config):
        labels["documents"][0]["fields"].pop()

    client = Client()
    with pytest.raises(harness.CacheError, match="blind labels"):
        session, _ = fixture(tmp_path, fields={"amount": {"keys": ["one", "two"]}}, mutate=change)
        session.run("baseline", client)
    assert client.prompts == []
    assert not (tmp_path / "cache").exists()


def add_development_document(tmp_path, manifest, labels):
    document = copy.deepcopy(manifest["documents"][0])
    document.update(id="dev", split="development")
    manifest["documents"].append(document)
    gold = copy.deepcopy(labels["documents"][0])
    gold["id"] = "dev"
    labels["documents"].append(gold)
    for suffix in ("pdf", "txt"):
        (tmp_path / "sources" / f"dev.{suffix}").write_bytes(
            (tmp_path / "sources" / f"doc.{suffix}").read_bytes()
        )


@pytest.mark.parametrize("missing", ["doc", "dev"])
def test_missing_label_from_either_split_blocks_heldout_client(tmp_path, missing):
    def change(manifest, labels, config):
        add_development_document(tmp_path, manifest, labels)
        labels["documents"] = [doc for doc in labels["documents"] if doc["id"] != missing]

    client = Client()
    with pytest.raises(harness.CacheError, match="blind labels"):
        session, _ = fixture(tmp_path, mutate=change)
        session.run("baseline", client, split="heldout")
    assert client.prompts == []
    assert not (tmp_path / "cache").exists()


def test_complete_both_split_labels_run_only_the_selected_document(tmp_path):
    def change(manifest, labels, config):
        add_development_document(tmp_path, manifest, labels)

    session, _ = fixture(tmp_path, mutate=change)
    client = Client(envelope(candidate()))
    result = session.run("baseline", client, split="heldout")
    assert [doc["id"] for doc in result["documents"]] == ["doc"]
    assert len(client.prompts) == 1
    assert "secret-gold-annotation" not in client.prompts[0]


def test_metrics_helper_code_changes_invalidate_frozen_configuration(tmp_path, monkeypatch):
    session, _ = fixture(tmp_path)
    original = harness._read
    target = Path(harness.__file__).with_name("metrics.py")

    def changed(path, cap=harness._MAX_FILE):
        raw = original(path, cap)
        return raw + b"\n# synthetic helper change\n" if path == target else raw

    monkeypatch.setattr(harness, "_read", changed)
    client = Client()
    with pytest.raises(harness.CacheError, match="source code changed"):
        session.run("baseline", client)
    assert client.prompts == []
    assert not session.cache.exists()


@pytest.mark.parametrize("artifact", ["result.json", "projection.json"])
def test_final_artifact_tampering_cannot_replace_replayed_projection(tmp_path, artifact):
    session, _ = fixture(tmp_path)
    session.run("baseline", Client(envelope(candidate())))
    path = local(session, artifact)
    changed = json.loads(path.read_bytes()) | {"synthetic_tamper": True}
    path.write_bytes(harness.encoded(changed))
    client = Client()
    with pytest.raises(harness.CacheError, match="immutable cache differs"):
        session.run("baseline", client)
    assert client.prompts == []
    assert json.loads(path.read_bytes())["synthetic_tamper"] is True


@pytest.mark.parametrize("arm", ["baseline", "runner"])
@pytest.mark.parametrize(
    "context",
    [
        {"subject": "Synthetic device Alpha", "scope": "Main supply at reference condition"},
        {"scope": "Consolidated group year ended 2031-03-31", "subject": "Synthetic group Beta"},
    ],
)
def test_request_context_reaches_effective_schema_prompts_receipts_and_replay(
    tmp_path, arm, context
):
    if arm == "runner" and importlib.util.find_spec("groundgate.extract") is None:
        pytest.skip("runner integration pending")
    fields = {
        "amount": {
            "type": "number",
            "description": "Preserve this field description.",
            "aliases": ["Amount", "Measured amount"],
            "multiple": True,
        },
        "missing": {"type": "number"},
        "unclear": {"type": "number"},
    }

    def change(manifest, labels, config):
        manifest["documents"][0].update(
            request_context=context,
            named_source="secret-named-source",
            label_scope_note="secret-label-scope",
        )

    session, paths = fixture(tmp_path, fields=fields, settings={"targeted": False}, mutate=change)
    original = copy.deepcopy(session.manifest)
    expected = harness.gg.Schema.from_dict({"fields": fields}).to_dict()
    for spec in expected["fields"].values():
        original_description = spec.get("description")
        suffix = "Request context: " + harness.encoded(context).decode()
        spec["description"] = (
            original_description + "\n\n" + suffix if original_description else suffix
        )
    effective = session.schema(session.documents["doc"])
    assert effective == expected
    assert session.manifest == original
    # Schema callers cannot mutate the manifest/template by modifying the returned result.
    effective["fields"]["amount"]["description"] = "caller edit"
    assert session.schema(session.documents["doc"]) == expected
    reply = (
        envelope(candidate())
        if arm == "baseline"
        else runner_envelope(candidate(), missing=("missing", "unclear"))
    )
    client = Client(reply)
    result = session.run(arm, client)
    assert client.prompts
    for prompt in client.prompts:
        assert json.loads(prompt.rsplit("\n", 1)[-1])["schema"] == expected
        for secret in (
            "secret-named-source",
            "secret-label-scope",
            "987654321",
            "secret-gold-annotation",
            "secret-absence-annotation",
            "secret-unclear-annotation",
            '"status":"present"',
            '"status":"absent"',
            '"status":"unclear"',
        ):
            assert secret not in prompt
    saved = json.loads(local(session, "result.json").read_bytes())
    expected_sha = harness.digest(harness.encoded(expected))
    assert saved["schema_sha256"] == expected_sha
    receipts = (
        [round_["receipt"] for round_ in saved["rounds"]]
        if arm == "baseline"
        else [saved["receipt"]]
    )
    receipt_sha = harness.gg.admit("Amount 5.", expected, [], session.policy).schema_sha256
    assert receipts and all(r["schema_sha256"] == receipt_sha for r in receipts)
    assert session.manifest == original
    assert harness._json(paths["manifest"].read_bytes()) == original
    assert session.run(arm) == result
    no_repeat = Client()
    assert session.run(arm, no_repeat) == result and no_repeat.prompts == []


@pytest.mark.parametrize(
    "context",
    [
        None,
        [],
        "not an object",
        {},
        {"subject": "device"},
        {"scope": "year"},
        {"subject": "device", "scope": "year", "note": "secret"},
        {"subject": "", "scope": "year"},
        {"subject": "device", "scope": " \n"},
        {"subject": 12, "scope": "year"},
        {"subject": "device", "scope": False},
        {"subject": [], "scope": "year"},
        {"subject": "device", "scope": {}},
        {"subject": "s" * 4097, "scope": "year"},
        {"subject": "device", "scope": "s" * 4097},
    ],
)
def test_invalid_request_context_refuses_before_client_and_cache(tmp_path, context):
    def change(manifest, labels, config):
        manifest["documents"][0]["request_context"] = context

    client = Client()
    with pytest.raises(harness.CacheError, match="request_context"):
        session, _ = fixture(tmp_path, mutate=change)
        session.run("baseline", client)
    assert client.prompts == []
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("member", ["subject", "scope"])
def test_request_context_accepts_exact_character_bound_without_mutating_template(tmp_path, member):
    context = {"subject": "device", "scope": "year"}
    context[member] = "é" * 4096

    def change(manifest, labels, config):
        manifest["documents"][0]["request_context"] = context

    session, _ = fixture(tmp_path, mutate=change)
    assert (
        context[member]
        in session.schema(session.documents["doc"])["fields"]["amount"]["description"]
    )
    assert "description" not in session.manifest["schemas"]["kind"]["fields"]["amount"]


@pytest.mark.parametrize("target", ["file", "manifest", "document"])
def test_frozen_request_context_mutation_refuses_before_reservation(tmp_path, target):
    def change(manifest, labels, config):
        manifest["documents"][0]["request_context"] = {
            "subject": "device Alpha",
            "scope": "year2031",
        }

    session, paths = fixture(tmp_path, mutate=change)
    if target == "file":
        manifest = harness._json(paths["manifest"].read_bytes())
        manifest["documents"][0]["request_context"]["subject"] = "device Beta"
        paths["manifest"].write_bytes(harness.encoded(manifest))
    elif target == "manifest":
        session.manifest["documents"][0]["request_context"]["subject"] = "device Beta"
    else:
        session.documents["doc"]["request_context"]["scope"] = "year2032"
    client = Client(envelope(candidate()))
    with pytest.raises(harness.CacheError, match="changed"):
        session.run("baseline", client)
    assert client.prompts == []
    assert not session.cache.exists()


@pytest.mark.parametrize("arm", ["baseline", "runner"])
def test_legacy_documents_do_not_read_label_notes_or_named_source_as_context(tmp_path, arm):
    if arm == "runner" and importlib.util.find_spec("groundgate.extract") is None:
        pytest.skip("runner integration pending")

    def change(manifest, labels, config):
        manifest["documents"][0].update(
            named_source="secret-device-from-annotation",
            label_scope_note="secret-scope-from-annotation",
        )

    session, _ = fixture(tmp_path, mutate=change)
    expected = harness.gg.Schema.from_dict({"fields": {"amount": {"type": "number"}}}).to_dict()
    assert session.schema(session.documents["doc"]) == expected
    client = Client(envelope(candidate()) if arm == "baseline" else runner_envelope(candidate()))
    result = session.run(arm, client)
    assert all(json.loads(p.rsplit("\n", 1)[-1])["schema"] == expected for p in client.prompts)
    assert all("secret-" not in p for p in client.prompts)
    assert session.run(arm) == result


@pytest.mark.parametrize("count,description_size,context_size", [(200, 0, 1024), (32, 2000, 64)])
def test_request_context_expansion_refuses_before_schema_admission_or_cache(
    tmp_path, monkeypatch, count, description_size, context_size
):
    fields = {
        f"field{i}": {"type": "number"}
        | ({"description": "d" * description_size} if description_size else {})
        for i in range(count)
    }

    def change(manifest, labels, config):
        manifest["documents"][0]["request_context"] = {
            "subject": "s" * context_size,
            "scope": "c" * context_size,
        }

    original_admit = harness.gg.admit

    def no_amplified_admission(text, schema, *args, **kwargs):
        if any(
            "Request context:" in spec.get("description", "") for spec in schema["fields"].values()
        ):
            pytest.fail("expanded descriptions reached schema admission before the size guard")
        return original_admit(text, schema, *args, **kwargs)

    monkeypatch.setattr(harness.gg, "admit", no_amplified_admission)
    client = Client()
    with pytest.raises(harness.CacheError, match=r"request_context.*budget"):
        session, _ = fixture(tmp_path, fields=fields, mutate=change)
        session.run("baseline", client)
    assert client.prompts == []
    assert not (tmp_path / "cache").exists()


def test_partial_document_run_publishes_no_projection_and_full_run_reuses_it(tmp_path):
    session, _ = fixture(tmp_path)
    with pytest.raises(harness.CacheError):
        session.run("baseline", Client(), documents=["other"])
    with pytest.raises(harness.CacheError):
        session.run("baseline", Client(), documents=[])
    client = Client(envelope(candidate()))
    partial = session.run("baseline", client, documents=["doc"])
    assert partial["partial"] is True and len(client.prompts) == 1
    folder = local(session, "result.json").parents[1]
    assert not (folder / "projection.json").exists()
    no_repeat = Client()
    full = session.run("baseline", no_repeat)
    assert not no_repeat.prompts and (folder / "projection.json").exists()
    assert full["documents"] == partial["documents"]
    assert session.run("baseline") == full


@pytest.mark.parametrize(
    "change",
    [
        # A second document of the same kind with another scope.
        lambda m, labels: m["documents"][1]["request_context"].update(scope="year2032"),
        # A second document of the same kind with no request context.
        lambda m, labels: m["documents"][1].pop("request_context"),
        # A scope that holds a label note.
        lambda m, labels: [
            doc["request_context"].update(scope="year2031 secret-gold-annotation")
            for doc in m["documents"]
        ],
        # A subject that equals an unclear reason, with other whitespace.
        lambda m, labels: m["documents"][0]["request_context"].update(
            subject="  secret-unclear-annotation\n"
        ),
        # A subject that holds a manifest label scope note.
        lambda m, labels: (
            m["documents"][1].update(label_scope_note="device Alpha"),
            m["documents"][0]["request_context"].update(subject="The device Alpha part"),
        ),
    ],
)
def test_request_context_varying_in_a_kind_or_holding_a_note_refuses(tmp_path, change):
    fields = {"amount": {"type": "number"}, "unclear": {"type": "number"}}

    def mutate(manifest, labels, config):
        add_development_document(tmp_path, manifest, labels)
        for doc in manifest["documents"]:
            doc["request_context"] = {"subject": "device Beta", "scope": "year2031"}
        change(manifest, labels)

    client = Client()
    with pytest.raises(harness.CacheError, match="request_context"):
        session, _ = fixture(tmp_path, fields=fields, mutate=mutate)
        session.run("baseline", client)
    assert client.prompts == []
    assert not (tmp_path / "cache").exists()


def test_documents_of_one_kind_may_have_their_own_subject(tmp_path):
    def mutate(manifest, labels, config):
        add_development_document(tmp_path, manifest, labels)
        for name, doc in zip(("device Alpha", "device Beta"), manifest["documents"], strict=True):
            doc["request_context"] = {"subject": name, "scope": "year2031"}

    session, _ = fixture(tmp_path, mutate=mutate)
    assert "device Alpha" in json.dumps(session.schema(session.documents["doc"]))


def test_tracked_manifest_has_one_request_context_for_each_kind():
    """The frozen set: one scope for each kind, identity-only subjects and no label notes."""
    directory = Path(__file__).parent
    manifest = json.loads((directory / "manifest.json").read_bytes())
    labels = json.loads((directory / "labels.json").read_bytes())
    harness._validate_request_contexts(manifest, labels)
    subjects: dict[str, set[str]] = {}
    for doc in manifest["documents"]:
        assert set(doc["request_context"]) == {"subject", "scope"}
        subjects.setdefault(doc["kind"], set()).add(doc["request_context"]["subject"])
    assert set(subjects) == {"annual", "component", "sbc"}
    # A plan or a group needs no identity. A datasheet can cover more parts, so the request
    # names its part number only.
    assert len(subjects["annual"]) == len(subjects["sbc"]) == 1
    assert all(re.fullmatch(r"[A-Z0-9][A-Z0-9-]*", s) for s in subjects["component"])


def test_transport_error_retries_only_on_request_and_keeps_the_archive(tmp_path):
    session, _ = fixture(tmp_path)
    failed = session.run("baseline", Client(RuntimeError("synthetic outage")))
    assert not output(failed)["complete"] and output(failed)["transport_error"]
    assert output(failed)["transport_retries"] == 0
    folder = local(session, "result.json").parent
    split = folder.parent
    failed_call = (folder / "calls/0001.json").read_bytes()
    failed_result = (folder / "result.json").read_bytes()
    failed_projection = (split / "projection.json").read_bytes()

    # Without the option, the recorded failure replays and no transport occurs.
    unused = Client(envelope(candidate()))
    assert session.run("baseline", unused) == failed and unused.prompts == []
    with pytest.raises(harness.CacheError, match="needs a client"):
        session.run("baseline", retry_transport_errors=True)

    client = Client(envelope(candidate()))
    retried = session.run("baseline", client, retry_transport_errors=True)
    assert len(client.prompts) == 1
    assert output(retried)["complete"] and not output(retried)["transport_error"]
    assert output(retried)["transport_retries"] == 1
    archive = folder / "attempts/0001"
    assert (archive / "call.json").read_bytes() == failed_call
    assert (archive / "call.pending.json").exists()
    assert (archive / "result.json").read_bytes() == failed_result
    assert (split / "_attempts/projection-0001.json").read_bytes() == failed_projection
    # A completed document is not retried again, and replay needs no client.
    again = Client()
    assert session.run("baseline", again, retry_transport_errors=True) == retried
    assert again.prompts == []
    assert session.run("baseline") == retried


def test_retry_of_a_second_failure_adds_a_second_attempt(tmp_path):
    session, _ = fixture(tmp_path)
    session.run("baseline", Client(RuntimeError("first")))
    second = session.run("baseline", Client(RuntimeError("second")), retry_transport_errors=True)
    assert output(second)["transport_error"] and output(second)["transport_retries"] == 1
    third = session.run("baseline", Client(envelope(candidate())), retry_transport_errors=True)
    assert output(third)["complete"] and output(third)["transport_retries"] == 2
    folder = local(session, "result.json").parent
    assert sorted(p.name for p in (folder / "attempts").iterdir()) == ["0001", "0002"]


def test_retry_refuses_an_unresolved_reservation(tmp_path):
    session, _ = fixture(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        session.run("baseline", Client(KeyboardInterrupt()))
    client = Client(envelope(candidate()))
    with pytest.raises(harness.CacheError, match="unresolved"):
        session.run("baseline", client, retry_transport_errors=True)
    assert client.prompts == []


def write_call(calls, binding, sequence, status):
    entry = {
        "binding_sha256": binding,
        "sequence": sequence,
        "prompt": "p",
        "prompt_sha256": harness.digest(b"p"),
        "status": status,
    }
    entry["entry_sha256"] = harness.digest(harness.encoded(entry))
    (calls / f"{sequence:04}.json").write_bytes(harness.encoded(entry))
    (calls / f"{sequence:04}.pending.json").write_bytes(b"{}")


def test_transport_error_before_the_last_call_stays_refused(tmp_path):
    document = tmp_path / "doc"
    calls = document / "calls"
    calls.mkdir(parents=True)
    write_call(calls, "sha256:b", 1, "transport_error")
    write_call(calls, "sha256:b", 2, "ok")
    with pytest.raises(harness.CacheError, match="before the last call"):
        harness._archive_transport_error(document, "sha256:b")
    with pytest.raises(harness.CacheError, match="cached call differs"):
        harness._archive_transport_error(document, "sha256:other")
    assert sorted(p.name for p in calls.iterdir()) == [
        "0001.json",
        "0001.pending.json",
        "0002.json",
        "0002.pending.json",
    ]
    assert not (document / "attempts").exists()
