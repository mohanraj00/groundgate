"""``RunResult.save`` writes a run into the store, and ``RunResult.load`` replays it from there
(docs/design/store.md §9, #405, #429)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

import groundgate as gg
from groundgate.canonical import jcs
from groundgate.extract import RunResult, extract
from groundgate.extract.runner import _STORE_KINDS, _hash
from groundgate.model import PacketError
from groundgate.store import FolderStore, key
from groundgate.store.packets import InputGone, admit_packet, load_packet

SCHEMA = {"fields": {"amount": {"type": "integer"}}}
LAC = {
    "groundgate_pack": 1,
    "type": "vocabulary",
    "id": "lac-x-test",
    "version": "1.0.0",
    "scale": {"words": {"lac": 5}},
}
AMOUNTS = {
    "groundgate_pack": 1,
    "type": "kind",
    "id": "amounts-x-test",
    "version": "1.0.0",
    "needs": [{"id": "lac-x-test", "version": "1.0.0"}],
    "fields": {"amount": {"type": "integer", "aliases": ["amount"]}},
}
PACKED = {
    "packs": [{"id": "amounts-x-test", "version": "1.0.0"}],
    "fields": {"amount": {"template": "amounts-x-test/amount"}},
}


def run(text: str, value: str, schema: Any = SCHEMA, **kwargs: Any) -> RunResult:
    reply = {
        "candidates": [
            {
                "field": "amount",
                "value": value,
                "unit": None,
                "key": None,
                "evidence": [{"source": "document", "role": "value", "text": value}],
            }
        ],
        "not_found": [],
    }
    replies = [json.dumps(reply)]

    def client(prompt: str) -> str:
        return replies.pop(0)

    return extract(text, schema, client=client, model_id="fixed-1", **kwargs)


def kind_of(result: RunResult, k: str) -> str:
    return next(_STORE_KINDS[n] for n in _STORE_KINDS if _hash(n, result.artifacts[k]) == k)


def test_save_writes_the_objects_the_record_and_the_packet(tmp_path: Path) -> None:
    result = run("Amount 5.", "5", document_id="doc-1", document_source="https://example.org/d")
    with FolderStore(tmp_path / "store") as store:
        k = result.save(store)
        for name, body in result.artifacts.items():
            data = body.encode("utf-8")
            assert store.get(kind_of(result, name), key(kind_of(result, name), data)) == data
        found = load_packet(store, k)
        assert found.receipt == result.receipt.to_dict()
        assert found.candidates == result.candidates
        assert found.document_source == "https://example.org/d"
        check = gg.verify(
            found.receipt, found.text, found.schema, found.candidates, **found.inputs()
        )
        assert check.ok, check.problems
        packet = json.loads(store.get("packet@1", k))
        record = store.get("run@5", packet["run"])
        # The same run gives the same packet key.
        assert result.save(store) == k
    # The record of `save` is the log of `write`, and `read` replays the folder.
    result.write(tmp_path / "run")
    assert (tmp_path / "run" / "run.jsonl").read_bytes() == record
    assert RunResult.read(tmp_path / "run").receipt == result.receipt
    # The record names each object by its run key and its store key (#429).
    header = json.loads(record.splitlines()[0])
    assert header["runner"] == "groundgate-run/5"
    text = result.artifacts[header["inputs"]["document"]["sha256"]]
    assert header["inputs"]["document"]["key"] == key("text@1", text.encode("utf-8"))


def test_save_writes_the_packs_and_the_references(tmp_path: Path) -> None:
    packs = [AMOUNTS, LAC]
    result = run("Amount 5 lac.", "5", PACKED, packs=packs)
    with FolderStore(tmp_path) as store:
        found = load_packet(store, result.save(store, packs=packs))
        assert found.packs == packs
        assert gg.verify(
            found.receipt, found.text, found.schema, found.candidates, **found.inputs()
        ).ok
    reference = {"id": "r", "text": "Revenue 5,000."}
    schema = {"fields": {"amount": {"type": "integer"}}}
    reply = {
        "candidates": [
            {
                "field": "amount",
                "value": "5000",
                "unit": None,
                "key": None,
                "evidence": [{"source": "reference", "ref": "r", "role": "value", "text": "5,000"}],
            }
        ],
        "not_found": [],
    }
    result = extract(
        "Nothing here.",
        schema,
        client=lambda prompt: json.dumps(reply),
        model_id="fixed-1",
        references=[reference],
    )
    with FolderStore(tmp_path / "refs") as store:
        found = load_packet(store, result.save(store))
        assert found.references == [reference]
        assert gg.verify(
            found.receipt, found.text, found.schema, found.candidates, **found.inputs()
        ).ok


def test_save_without_the_packs_writes_nothing(tmp_path: Path) -> None:
    result = run("Amount 5 lac.", "5", PACKED, packs=[AMOUNTS, LAC])
    with FolderStore(tmp_path) as store, pytest.raises(PacketError):
        result.save(store)
    assert not (tmp_path / "objects").exists() or not any((tmp_path / "objects").iterdir())


def test_save_refuses_a_changed_artifact_before_it_writes(tmp_path: Path) -> None:
    result = run("Amount 5.", "5")
    reply = next(e for e in result.record if e["kind"] == "call")["reply_sha256"]
    changed = RunResult(
        result.receipt,
        result.candidates,
        result.record,
        {**result.artifacts, reply: "{}"},
        result.complete,
    )
    missing = RunResult(
        result.receipt,
        result.candidates,
        result.record,
        {k: v for k, v in result.artifacts.items() if k != reply},
        result.complete,
    )
    other = RunResult(
        run("Amount 5.", "5", document_id="other").receipt,
        result.candidates,
        result.record,
        result.artifacts,
        result.complete,
    )
    with FolderStore(tmp_path) as store:
        with pytest.raises(ValueError, match="does not match its key"):
            changed.save(store)
        with pytest.raises(ValueError, match="missing object"):
            missing.save(store)
        with pytest.raises(PacketError, match="another receipt"):
            other.save(store)
    assert not (tmp_path / "objects").exists() or not any((tmp_path / "objects").iterdir())


def test_save_writes_only_the_objects_that_the_record_names(tmp_path: Path) -> None:
    result = run("Amount 5.", "5")
    extra = RunResult(
        result.receipt,
        result.candidates,
        result.record,
        {**result.artifacts, "sha256:" + "0" * 64: "not named"},
        result.complete,
    )

    def files(folder: Path) -> set[str]:
        return {p.name for p in (folder / "objects").rglob("*") if p.is_file()}

    with FolderStore(tmp_path / "a") as a, FolderStore(tmp_path / "b") as b:
        assert extra.save(a) == result.save(b)
    assert files(tmp_path / "a") == files(tmp_path / "b")


def same_run(a: RunResult, b: RunResult) -> None:
    assert jcs(a.record) == jcs(b.record)
    assert a.artifacts == b.artifacts and a.candidates == b.candidates
    assert a.receipt == b.receipt and a.complete == b.complete


def test_load_replays_a_saved_run_from_its_packet_key(tmp_path: Path) -> None:
    result = run("Amount 5.", "5", document_id="doc-1", document_source="https://example.org/d")
    with FolderStore(tmp_path) as store:
        k = result.save(store)
    # A new handle on the folder has only the store: no folder run, no client, no model.
    with FolderStore(tmp_path) as store:
        same_run(RunResult.load(store, k), result)


def test_load_takes_the_packs_from_the_packet(tmp_path: Path) -> None:
    packs = [AMOUNTS, LAC]
    result = run("Amount 5 lac.", "5", PACKED, packs=packs)
    with FolderStore(tmp_path) as store:
        same_run(RunResult.load(store, result.save(store, packs=packs)), result)


def test_load_replays_a_run_with_a_repair_and_a_client_error(tmp_path: Path) -> None:
    reference = {"id": "r", "text": "Units are dollars."}
    good = {
        "field": "amount",
        "value": "5",
        "unit": None,
        "key": None,
        "evidence": [{"source": "document", "role": "value", "text": "5"}],
    }
    bad = {**good, "evidence": [{"source": "document", "role": "value", "text": "6"}]}
    replies: list[Any] = [json.dumps({"candidates": [bad], "not_found": []}), RuntimeError()]

    def client(prompt: str) -> str:
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return cast(str, reply)

    result = extract("Amount 5.", SCHEMA, client=client, model_id="fixed-1", references=[reference])
    calls = [e for e in result.record if e["kind"] == "call"]
    assert [c["status"] for c in calls] == ["ok", "client_error"]
    assert "reply_key" not in calls[1]
    with FolderStore(tmp_path) as store:
        same_run(RunResult.load(store, result.save(store)), result)


def test_load_names_a_deleted_reply(tmp_path: Path) -> None:
    result = run("Amount 5.", "5")
    call = next(e for e in result.record if e["kind"] == "call")
    with FolderStore(tmp_path) as store:
        k = result.save(store)
        store.forget(call["reply_key"], "the app deletes replies")
        with pytest.raises(InputGone, match="input deleted") as gone:
            RunResult.load(store, k)
        assert gone.value.key == call["reply_key"]


def test_load_refuses_a_packet_with_no_run_or_another_run(tmp_path: Path) -> None:
    result = run("Amount 5.", "5")
    with FolderStore(tmp_path) as store:
        alone, _ = admit_packet(store, "Amount 5.", SCHEMA, result.candidates)
        with pytest.raises(ValueError, match="names no run record"):
            RunResult.load(store, alone)
        k = result.save(store)
        packet = json.loads(store.get("packet@1", k))
        lines = store.get("run@5", packet["run"]).decode("utf-8")
        old = lines.replace("groundgate-run/5", "groundgate-run/4").encode("utf-8")
        other = store.put("packet@1", jcs({**packet, "run": store.put("run@4", old)}).encode())
        with pytest.raises(ValueError, match="is not a groundgate-run/5 record"):
            RunResult.load(store, other)
        for limit in (len(lines) - 1, len(lines)):
            with pytest.raises(ValueError, match="larger than max_bytes"):
                RunResult.load(store, k, max_bytes=limit)


def test_load_refuses_a_packet_of_another_receipt(tmp_path: Path) -> None:
    five = run("Amount 5.", "5")
    with FolderStore(tmp_path) as store:
        packet = json.loads(store.get("packet@1", five.save(store)))
        other = run("Amount 5. Amount 6.", "6")
        run_key = json.loads(store.get("packet@1", other.save(store)))["run"]
        mixed = store.put("packet@1", jcs({**packet, "run": run_key}).encode())
        with pytest.raises(ValueError, match="another receipt"):
            RunResult.load(store, mixed)


def test_save_refuses_a_record_with_another_store_key(tmp_path: Path) -> None:
    result = run("Amount 5.", "5")
    record = [dict(line) for line in result.record]
    call = next(e for e in record if e["kind"] == "call")
    call["reply_key"] = call["prompt_key"]
    changed = RunResult(result.receipt, result.candidates, record, result.artifacts, True)
    with FolderStore(tmp_path) as store, pytest.raises(ValueError, match="another store key"):
        changed.save(store)
