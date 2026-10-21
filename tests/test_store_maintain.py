"""`groundgate store check`, `rebuild` and `forget` (docs/design/store.md §7.4, §8, #404)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from groundgate.canonical import jcs
from groundgate.cli import main
from groundgate.extract import extract
from groundgate.store import FolderStore, Locked, StoreError, Torn, key, reviewer_key, set_key
from groundgate.store.maintain import REMOVED, check, forget_packet, kind_of, rebuild
from groundgate.store.packets import admit_packet, put_reading

TEXT = "Invoice\n\nThe amount is 5 dollars. Pay it by Friday.\n"
SCHEMA: dict[str, Any] = {"fields": {"amount": {"type": "integer"}}}


def clock() -> datetime:
    return datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)


def client(prompt: str) -> str:
    item = {"source": "document", "role": "value", "text": "5"}
    candidate = {"field": "amount", "value": "5", "unit": None, "key": None, "evidence": [item]}
    return json.dumps({"candidates": [candidate], "not_found": []})


def save_run(
    store: FolderStore, text: str = TEXT, *, model_id: str = "fixed-1", document_id: str = "inv-1"
) -> str:
    """Write a run into the store as issue 4 will, and return the packet key. The run record
    names its objects by run keys, so each object is put as its store kind."""
    result = extract(text, SCHEMA, client=client, model_id=model_id, document_id=document_id)
    art = result.artifacts
    inputs = result.record[0]["inputs"]
    for line in result.record:
        for member, kind in (
            ("prompt_sha256", "prompt@1"),
            ("reply_sha256", "reply@1"),
            ("admission_sha256", "admission@1"),
        ):
            if member in line:
                store.put(kind, art[line[member]].encode("utf-8"))
    run = "".join(jcs(line) + "\n" for line in result.record).encode("utf-8")
    number = result.record[0]["runner"].removeprefix("groundgate-run/")
    packet = {
        "format": "packet@1",
        "spec": result.receipt.to_dict()["groundgate"],
        "document": {
            "id": document_id,
            "source": None,
            "text": store.put("text@1", art[inputs["document"]["sha256"]].encode("utf-8")),
        },
        "reading": None,
        "schema": store.put("schema@1", art[inputs["schema_sha256"]].encode("utf-8")),
        "policy": store.put("policy@1", art[inputs["policy_sha256"]].encode("utf-8")),
        "references": [],
        "packs": [],
        "candidates": store.put("candidates@1", jcs(result.candidates).encode("utf-8")),
        "judgments": None,
        "receipt": store.put("receipt@1", jcs(result.receipt.to_dict()).encode("utf-8")),
        "run": store.put(f"run@{number}", run),
    }
    return store.put("packet@1", jcs(packet).encode("utf-8"))


def candidates(text: str = TEXT) -> list[Any]:
    start = text.encode().index(b"5 dollars")
    evidence = {"start": start, "end": start + 1, "text": "5"}
    return [{"id": "a", "field": "amount", "value": 5, "evidence": evidence}]


def path_of(root: Path, k: str) -> Path:
    return root / "objects" / k[7:9] / k[9:]


def all_keys(root: Path) -> dict[str, str | None]:
    with FolderStore(root) as store:
        keys, _ = store.object_keys()
        return {k: kind_of(k, store.object_bytes(k)) for k in keys}


def test_check_a_good_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "s"
    pdf = tmp_path / "a.txt"
    pdf.write_text(TEXT, encoding="utf-8")
    with FolderStore(root) as store:
        reading, _ = put_reading(store, pdf)
        save_run(store)
        admit_packet(store, TEXT, SCHEMA, candidates(), reading=reading)
        store.append(("splits", set_key("requested4")), {"split": "development"})
    with FolderStore(root) as store:
        report = check(store)
    assert report.findings == [] and report.cut == [] and report.deleted == []
    assert report.logs == 1 and report.objects == len(all_keys(root))
    assert None not in all_keys(root).values()  # each object has a known kind
    assert main(["store", "check", "--store", str(root)]) == 0
    out = capsys.readouterr().out
    assert out == f"checked {report.objects} objects and 1 logs: 0 findings\n"


def test_check_finds_a_changed_object_a_broken_chain_and_a_torn_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet, _ = admit_packet(store, TEXT, SCHEMA, candidates())
        named = json.loads(store.get("packet@1", packet))
        store.append(("splits", set_key("one")), {"split": "development"})
        store.append(("splits", set_key("one")), {"split": "held-out"})
        store.append(("splits", set_key("two")), {"split": "development"})
    changed = path_of(root, named["candidates"])
    changed.write_bytes(changed.read_bytes().replace(b'"value":5', b'"value":6'))
    one = root / "logs" / "splits" / f"{set_key('one')[7:]}.jsonl"
    one.write_bytes(one.read_bytes().replace(b"held-out", b"heldout!"))
    two = root / "logs" / "splits" / f"{set_key('two')[7:]}.jsonl"
    with two.open("ab") as f:
        f.write(b'{"sequence":2')

    assert main(["store", "check", "--store", str(root)]) == 1
    out = capsys.readouterr().out.splitlines()
    rel = f"objects/{named['candidates'][7:9]}/{named['candidates'][9:]}"
    assert f"finding: {rel} does not match its key as any kind: it changed" in out
    assert (
        f"finding: the packet {packet} names the candidates@1 object {named['candidates']}, "
        f"but {rel} is not one"
    ) in out
    assert (
        f"finding: logs/splits/{set_key('one')[7:]}.jsonl: line 2 does not continue the chain"
        in out
    )
    torn = f"logs/splits/{set_key('two')[7:]}.jsonl has a torn last line: it has no line break"
    assert f"finding: {torn}" in out
    assert out[-1] == "checked 5 objects and 2 logs: 4 findings"


def test_repair_cuts_a_torn_line_and_prints_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    log = ("answers", key("packet@1", b"{}"), reviewer_key("ana"))
    with FolderStore(root) as store:
        store.append(log, {"answer": "yes"})
    path = root / "logs" / "answers" / log[1][7:] / f"{log[2][7:]}.jsonl"
    good = path.read_bytes()
    with path.open("ab") as f:
        f.write(b'{"answer":"n\x1b[31m')
    lock = path.with_suffix(".lock")
    lock.write_bytes(b"1\n")
    with FolderStore(root) as store, pytest.raises(Locked):
        store.repair(log)
    lock.unlink()
    assert main(["store", "check", "--store", str(root), "--repair"]) == 0
    out = capsys.readouterr().out
    rel = f"logs/answers/{log[1][7:]}/{log[2][7:]}.jsonl"
    assert out == (
        f'cut from {rel}: {{"answer":"n\\u001b[31m\nchecked 0 objects and 1 logs: 0 findings\n'
    )
    assert path.read_bytes() == good and not lock.exists()
    with FolderStore(root) as store:
        assert store.repair(log) is None
        assert store.read(log)[0]["answer"] == "yes"


def test_check_compares_the_packet_with_its_run_header(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
        obj = json.loads(store.get("packet@1", packet))
        obj["document"]["id"] = "inv-2"
        obj["policy"] = None  # the default policy: the same as the run header
        other = store.put("packet@1", jcs(obj).encode("utf-8"))
        obj["schema"] = store.put("schema@1", b'{"fields":{}}')
        third = store.put("packet@1", jcs(obj).encode("utf-8"))
    with FolderStore(root) as store:
        findings = check(store).findings
    assert sorted(findings) == sorted(
        [
            f"the packet {other}: the run header names another document id",
            f"the packet {third}: the run header names another document id",
            f"the packet {third}: the run header names another schema",
        ]
    )


def test_check_finds_a_broken_run_chain(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
        obj = json.loads(store.get("packet@1", packet))
        run = store.get("run@3", obj["run"]).replace(b'"fixed-1"', b'"fixed-2"')
        obj["run"] = store.put("run@3", run)
        broken = store.put("packet@1", jcs(obj).encode("utf-8"))
    with FolderStore(root) as store:
        assert check(store).findings == [
            f"the run record {obj['run']}: line 1 does not continue the chain"
        ]
    assert broken


def test_rebuild_gives_the_same_view_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    doc = tmp_path / "a.txt"
    doc.write_text(TEXT, encoding="utf-8")
    with FolderStore(root) as store:
        reading, _ = put_reading(store, doc)
        again, _ = put_reading(store, doc, pages=[1])
        admit_packet(store, TEXT, SCHEMA, candidates(), reading=reading)
    assert main(["store", "rebuild", "--store", str(root)]) == 0
    assert capsys.readouterr().out == "wrote views/readings.json\n"
    view = root / "views" / "readings.json"
    first = view.read_bytes()
    found = json.loads(first)
    source = json.loads(store.get("reading@1", reading))["source"]
    reader = json.loads(store.get("reading@1", reading))["reader"]
    assert found == {
        "format": "reading-cache@1",
        "readings": sorted(
            [
                {
                    "options": {"pages": None},
                    "reader": reader,
                    "readings": [reading],
                    "source": source,
                },
                {
                    "options": {"pages": [1]},
                    "reader": reader,
                    "readings": [again],
                    "source": source,
                },
            ],
            key=lambda row: jcs({k: v for k, v in row.items() if k != "readings"}),
        ),
    }
    view.unlink()
    (root / "views").rmdir()
    with FolderStore(root) as store:
        assert rebuild(store) == ["views/readings.json"]
    assert view.read_bytes() == first
    with FolderStore(root) as store:
        store.forget(json.loads(store.get("reading@1", again))["text"], "test")
        rebuild(store)
    assert json.loads(view.read_bytes())["readings"] == []  # both readings share the text


def test_forget_removes_the_document_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    doc = tmp_path / "a.txt"
    doc.write_text(TEXT, encoding="utf-8")
    with FolderStore(root, clock=clock) as store:
        packet = save_run(store)
        reading, _ = put_reading(store, doc)
        admitted, _ = admit_packet(store, TEXT, SCHEMA, candidates(), reading=reading)
    before = all_keys(root)
    assert main(["store", "forget", "--store", str(root), admitted, "--reason", "asked"]) == 0
    out = capsys.readouterr().out.splitlines()
    after = all_keys(root)
    gone = {k for k in before if k not in after}
    assert sorted(before[k] for k in gone) == ["candidates@1", "source@1", "text@1"]
    assert {line.split(" (")[0] for line in out} == {f"deleted {before[k]} {k}" for k in gone}
    text_key = next(k for k in gone if before[k] == "text@1")
    assert f"deleted text@1 {text_key} (1 other packet names it)" in out
    # The run of the other packet keeps its prompt, reply and admission until it is forgotten.
    # Its text is gone now, so forget cannot check the run record, and the record goes too.
    assert main(["store", "forget", "--store", str(root), packet, "--reason", "asked"]) == 0
    assert "absent text@1" in capsys.readouterr().out
    after = all_keys(root)
    assert not [k for k, kind in after.items() if kind in REMOVED]
    gone = {k for k in before if k not in after}
    assert sorted({before[k] for k in gone}) == sorted(
        ["text@1", "candidates@1", "source@1", "prompt@1", "reply@1", "admission@1", "run@3"]
    )
    assert {kind for kind in after.values()} == {
        "packet@1",
        "reading@1",
        "receipt@1",
        "schema@1",
        "policy@1",
    }
    with FolderStore(root) as store:
        records = store.read(("deleted",))
    assert sorted(r["key"] for r in records) == sorted(gone)
    assert {r["reason"] for r in records} == {"asked"}
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", r["time"]) for r in records)

    for k in (admitted, packet):  # the text is shared: verify says "input deleted" for both
        assert main(["verify", "--store", str(root), k]) == 2
        err = capsys.readouterr().err
        assert "input deleted: the text@1 object" in err and "reason: asked" in err
        assert "mismatch" not in err

    assert main(["store", "check", "--store", str(root)]) == 0
    out = capsys.readouterr().out
    assert f"input deleted: text@1 {text_key}\n" in out

    assert main(["store", "forget", "--store", str(root), admitted, "--reason", "again"]) == 0
    assert set(capsys.readouterr().out.split()) >= {"absent", "text@1"}
    with FolderStore(root) as store:
        assert len(store.read(("deleted",))) == len(gone)  # an absent object gets no record


def test_one_text_that_two_packets_share_goes_for_both(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        one, _ = admit_packet(store, TEXT, SCHEMA, candidates(), document_id="one")
        two, _ = admit_packet(store, TEXT, SCHEMA, candidates(), document_id="two")
        text = json.loads(store.get("packet@1", one))["document"]["text"]
        assert json.loads(store.get("packet@1", two))["document"]["text"] == text
        done = forget_packet(store, one, "the tenant asked")
    assert ("text@1", text, "deleted", 1) in done
    assert not path_of(root, text).exists()
    with FolderStore(root) as store:
        assert forget_packet(store, two, "the tenant asked")[0] == ("text@1", text, "absent", 1)


def test_forget_removes_a_run_record_with_document_text(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store, model_id="Pay it by Friday")
        run = json.loads(store.get("packet@1", packet))["run"]
    with FolderStore(root) as store:
        findings = check(store).findings
        assert f"the run record {run}: line 1 holds document text" in findings
        assert all(f.endswith("holds document text") for f in findings)
        done = forget_packet(store, packet, "text in the record")
    assert ("run@3", run, "deleted", 0) in done
    assert not path_of(root, run).exists()

    root = tmp_path / "plain"
    with FolderStore(root) as store:  # a document id that is in the text is kept data
        packet = save_run(store, model_id="fixed-1", document_id="The amount is")
        run = json.loads(store.get("packet@1", packet))["run"]
        assert check(store).findings == []
        forget_packet(store, packet, "asked")
    assert path_of(root, run).exists()


def test_forget_all_removes_each_object_and_log_of_the_packet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    with FolderStore(root, clock=clock) as store:
        packet = save_run(store)
        other, _ = admit_packet(store, TEXT, SCHEMA, candidates(), document_id="b")
        log = ("answers", packet, reviewer_key("ana"))
        store.append(log, {"answer": "yes"})
        store.append(("answers", other, reviewer_key("ana")), {"answer": "no"})
    before = all_keys(root)
    cmd = ["store", "forget", "--store", str(root), "--all", packet, "--reason", "all"]
    assert main(cmd) == 0
    out = capsys.readouterr().out.splitlines()
    rel = f"logs/answers/{packet[7:]}/{reviewer_key('ana')[7:]}.jsonl"
    assert f"deleted {rel}" in out and out[-1] == f"deleted packet@1 {packet}"
    assert not (root / "logs" / "answers" / packet[7:]).exists()
    after = all_keys(root)
    with FolderStore(root) as store:
        kept = json.loads(store.get("packet@1", other))
        records = store.read(("deleted",))
        assert store.read(("answers", other, reviewer_key("ana")))[0]["answer"] == "no"
    assert packet not in after and all(path_of(root, k).exists() for k in (kept["receipt"],))
    # The text is shared with the other packet, so it goes for both. The kept objects that
    # the other packet names stay.
    assert kept["document"]["text"] not in after
    assert f"deleted text@1 {kept['document']['text']} (1 other packet names it)" in out
    assert {r.get("key") for r in records} - {None} == set(before) - set(after)
    assert [r["log"] for r in records if "log" in r] == [list(log)]


def test_forget_input_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet, _ = admit_packet(store, TEXT, SCHEMA, candidates())
    absent = key("packet@1", b"{}")
    assert main(["store", "forget", "--store", str(root), absent, "--reason", "x"]) == 2
    assert f"the packet {absent} is not in the store" in capsys.readouterr().err
    assert main(["store", "forget", "--store", str(root), "../x", "--reason", "x"]) == 2
    assert "is not a store key" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["store", "forget", "--store", str(root), packet])  # --reason is required
    assert main(["store", "check", "--store", str(tmp_path / "none")]) == 2
    assert "the store folder is not there" in capsys.readouterr().err
    with FolderStore(root) as store, pytest.raises(ValueError):
        store.write_view("../x.json", b"{}")


def test_check_names_strange_entries(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        admit_packet(store, TEXT, SCHEMA, candidates())
    (root / "objects" / "zz").mkdir()
    (root / "objects" / "ab").mkdir(exist_ok=True)
    (root / "objects" / "ab" / ".tmp-1").write_bytes(b"x")  # a killed put: not a finding
    (root / "objects" / "ab" / "name").write_bytes(b"x")
    (root / "logs").mkdir()
    (root / "logs" / "other.jsonl").write_bytes(b"")
    os.symlink(root / "logs" / "other.jsonl", root / "logs" / "deleted.jsonl")
    loose = b'{ "fields": {} }'  # the right key, but not canonical JSON
    bad = key("schema@1", loose)
    path_of(root, bad).parent.mkdir(exist_ok=True)
    path_of(root, bad).write_bytes(loose)
    with FolderStore(root) as store:
        findings = check(store).findings
    assert findings[2].startswith(f"objects/{bad[7:9]}/{bad[9:]} is not a valid schema@1 object")
    assert findings[:2] + findings[3:] == [
        "objects/ab/name is not an object file",
        "objects/zz is not an object folder",
        "logs/deleted.jsonl is not a log",
        "logs/other.jsonl is not a log",
    ]


def test_forget_all_keeps_a_schema_that_another_packet_names(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        one, _ = admit_packet(store, TEXT, SCHEMA, candidates(), document_id="one")
        two, _ = admit_packet(store, "Other: 5 dollars.", SCHEMA, [], document_id="two")
        schema = json.loads(store.get("packet@1", one))["schema"]
        done = forget_packet(store, one, "all", everything=True)
    assert ("schema@1", schema, "kept", 1) in done
    assert path_of(root, schema).exists() and not path_of(root, one).exists()
    assert main(["verify", "--store", str(root), two]) == 0


def test_forget_removes_a_run_record_whose_text_is_gone(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store, model_id="Pay it by Friday")
        obj = json.loads(store.get("packet@1", packet))
        store.forget(obj["document"]["text"], "an earlier forget that stopped")
        done = forget_packet(store, packet, "again")
    assert done[0] == ("run@3", obj["run"], "deleted", 0)  # the run record goes first
    assert not path_of(root, obj["run"]).exists()


def test_forget_log_and_repair_take_the_lock(tmp_path: Path) -> None:
    root = tmp_path / "s"
    log = ("answers", key("packet@1", b"{}"), reviewer_key("ana"))
    with FolderStore(root) as store:
        store.append(log, {"answer": "yes"})
        with pytest.raises(StoreError, match="this writer holds the log"):
            store.forget_log(log, "x")
    path = root / "logs" / "answers" / log[1][7:] / f"{log[2][7:]}.jsonl"
    with path.open("ab") as f:
        f.write(b"{")
    with FolderStore(root) as store:
        with pytest.raises(Torn):
            store.read(log)
        path.with_suffix(".lock").write_bytes(b"1\n")
        with pytest.raises(Locked):
            store.forget_log(log, "x")
        path.with_suffix(".lock").unlink()
        store.forget_log(log, "x")
    assert not path.exists() and not path.parent.exists()
