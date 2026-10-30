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
from groundgate.extract.runner import _VERSION as RUNNER
from groundgate.store import (
    FolderStore,
    Locked,
    NotFound,
    StoreError,
    Torn,
    key,
    reviewer_key,
    set_key,
)
from groundgate.store.maintain import (
    REMOVED,
    _log_rel,
    _Objects,
    _rel,
    check,
    forget_packet,
    kind_of,
    rebuild,
    run_hash,
)
from groundgate.store.packets import admit_packet, put_reading

# The current runner version and its store kind, such as "run@6".
RUN_NUMBER = int(RUNNER.rsplit("/", 1)[1])
RUN_KIND = f"run@{RUN_NUMBER}"
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
    """Run the extractor with a fixed client, save the run into the store (#430), and return
    the packet key."""
    result = extract(text, SCHEMA, client=client, model_id=model_id, document_id=document_id)
    return result.save(store)


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
        record = {"set": "requested4", "document": "sha256:" + "a" * 64, "split": "development"}
        store.append(("splits", set_key("requested4")), record)
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
        run = store.get(RUN_KIND, obj["run"]).replace(b'"fixed-1"', b'"fixed-2"')
        obj["run"] = store.put(RUN_KIND, run)
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
    out = "wrote views/readings.json\nwrote views/calibrate-labels.json\n"
    assert capsys.readouterr().out == out
    view = root / "views" / "readings.json"
    first = view.read_bytes()
    found = json.loads(first)
    source = json.loads(store.get("reading@2", reading))["source"]
    reader = json.loads(store.get("reading@2", reading))["reader"]
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
    (root / "views" / "calibrate-labels.json").unlink()
    (root / "views").rmdir()
    with FolderStore(root) as store:
        assert rebuild(store) == ["views/readings.json", "views/calibrate-labels.json"]
    assert view.read_bytes() == first
    with FolderStore(root) as store:
        store.forget(json.loads(store.get("reading@2", again))["text"], "test")
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
        ["text@1", "candidates@1", "source@1", "prompt@1", "reply@1", "admission@1", RUN_KIND]
    )
    assert {kind for kind in after.values()} == {
        "packet@1",
        "reading@2",
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


def test_forget_removes_the_document_model_of_a_reading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A reading names its ``document@1``, so check sees it and forget removes it (#407)."""
    root = tmp_path / "s"
    doc = tmp_path / "a.txt"
    doc.write_text(TEXT, encoding="utf-8")
    with FolderStore(root, clock=clock) as store:
        reading, _ = put_reading(store, doc, document=True)
        model = json.loads(store.get("reading@2", reading))["document"]
        admitted, _ = admit_packet(store, TEXT, SCHEMA, candidates(), reading=reading)
    assert all_keys(root)[model] == "document@1"
    assert main(["store", "check", "--store", str(root)]) == 0
    capsys.readouterr()
    assert main(["store", "forget", "--store", str(root), admitted, "--reason", "asked"]) == 0
    assert f"deleted document@1 {model}" in capsys.readouterr().out
    after = all_keys(root)
    assert model not in after and "reading@2" in after.values()
    assert main(["store", "check", "--store", str(root)]) == 0
    assert f"input deleted: document@1 {model}" in capsys.readouterr().out


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
    assert (RUN_KIND, run, "deleted", 0) in done
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
    with FolderStore(root) as store:
        report = check(store)
        assert report.findings == [] and report.unchecked == [obj["run"]]
        done = forget_packet(store, packet, "again")
    assert (RUN_KIND, obj["run"], "deleted", 0) in done
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


def test_forget_names_only_the_objects_of_its_packet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        one = save_run(store)
        two = save_run(store, "Other text. The amount is 5 dollars.", document_id="inv-2")
        obj = json.loads(store.get("packet@1", one))
    data = b"\xff\xfe"  # not UTF-8, with the key of these bytes as reply@1: of no packet
    bad = key("reply@1", data)
    path_of(root, bad).parent.mkdir(exist_ok=True)
    path_of(root, bad).write_bytes(data)
    assert main(["store", "forget", "--store", str(root), one, "--reason", "asked"]) == 0
    out = capsys.readouterr().out
    assert bad not in out and "unchecked" not in out
    assert f"deleted text@1 {obj['document']['text']}" in out
    assert path_of(root, bad).exists()
    # The other packet keeps its prompts, replies and admissions.
    with FolderStore(root) as store:
        assert check(store).findings == [
            f"{_rel(bad)} is not a valid reply@1 object: a reply@1 object is not UTF-8"
        ]
        done = forget_packet(store, two, "asked")
    # The reply is the same for both runs, so the first forget removed it for both.
    assert {kind for kind, _, state, _ in done if state == "deleted"} >= {
        "prompt@1",
        "admission@1",
    }


def test_forget_removes_the_run_record_after_its_objects(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store, model_id="Pay it by Friday")
        run = json.loads(store.get("packet@1", packet))["run"]
        done = forget_packet(store, packet, "asked")
    kinds = [kind for kind, _, state, _ in done if state == "deleted"]
    assert kinds.index(RUN_KIND) > max(kinds.index(k) for k in ("prompt@1", "reply@1"))
    assert (RUN_KIND, run, "deleted", 0) in done


def _bad_run_packet(
    store: FolderStore, root: Path, *, header: bool = False
) -> tuple[str, dict[str, Any], Path]:
    """A packet whose run record has a line that is not a JSON object: the last line, or with
    ``header`` the first line. The bytes match the key of the record. The record names the
    prompts and replies of the run, which only this packet names now."""
    packet = save_run(store)
    obj = json.loads(store.get("packet@1", packet))
    run = store.get(RUN_KIND, obj["run"])
    bad_run = b"[1]\n" + run if header else run + b"[1]\n"
    obj["run"] = key(RUN_KIND, bad_run)
    path = path_of(root, obj["run"])
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(bad_run)
    other = store.put("packet@1", jcs(obj).encode("utf-8"))
    path_of(root, packet).unlink()
    return other, obj, path


@pytest.mark.parametrize("header", [False, True])
@pytest.mark.parametrize("everything", [False, True])
def test_forget_keeps_a_run_record_with_a_bad_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], everything: bool, header: bool
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        other, obj, path = _bad_run_packet(store, root, header=header)
    bad_run = path.read_bytes()
    named = [k for k, v in all_keys(root).items() if v in ("prompt@1", "reply@1")]
    assert named
    args = ["store", "forget", "--store", str(root), other, "--reason", "asked"]
    assert main(args + ["--all"] * everything) == 1
    out = capsys.readouterr().out
    kind = "run@N" if header else RUN_KIND  # with no header, the version is not known
    assert out.startswith(f"unchecked {kind} {obj['run']}\n")
    assert "deleted run@" not in out
    assert path.read_bytes() == bad_run  # kept, not removed
    assert f"deleted text@1 {obj['document']['text']}" in out
    # The prompts and replies stay, because only the kept record names them.
    assert all(path_of(root, k).exists() for k in named)
    # With --all, the packet stays too: it is the way to the kept record.
    assert path_of(root, other).exists()
    assert (f"kept packet@1 {other}" in out) is everything


def test_forget_all_finishes_after_a_manual_removal_of_a_bad_run_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        other, obj, path = _bad_run_packet(store, root, header=True)
    args = ["store", "forget", "--store", str(root), other, "--reason", "asked", "--all"]
    assert main(args) == 1
    with FolderStore(root) as store:  # the manual step of store.md §8 rule 3
        store.forget(obj["run"], "the record cannot be read")
    capsys.readouterr()
    assert main(args) == 0
    out = capsys.readouterr().out
    assert f"absent run@N {obj['run']}" in out and f"deleted packet@1 {other}" in out
    assert not path.exists() and not path_of(root, other).exists()


def test_kind_of_hashes_an_object_at_most_once_for_each_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large object that is not a run record gets no extra hash for the run kinds."""
    from groundgate.store import maintain

    calls: list[str] = []
    real = maintain.key

    def counted(kind: str, data: bytes) -> str:
        calls.append(kind)
        return real(kind, data)

    monkeypatch.setattr(maintain, "key", counted)
    data = b"x" * (1 << 20)
    assert kind_of(key("source@1", data), data) == "source@1"
    assert calls.count("source@1") == 1 and not any(c.startswith("run@") for c in calls)
    calls.clear()
    bad_run = b"[1]\n" + b"{}\n" * 1000  # a run record with a header that cannot be read
    assert kind_of(key(RUN_KIND, bad_run), bad_run) is None
    assert len(calls) == len(set(calls)) and not any(c.startswith("run@") for c in calls)


def _changed_run_packet(store: FolderStore, root: Path) -> tuple[str, str, Path, bytes]:
    """A packet whose run record has one changed byte in its last line. The header can still
    be read, but the bytes match their key as no kind. Return the packet key, the record key,
    the record path and the original bytes."""
    packet = save_run(store)
    run = json.loads(store.get("packet@1", packet))["run"]
    path = path_of(root, run)
    original = path.read_bytes()
    data = bytearray(original)
    data[data.rindex(b'"sequence"') + 1] = ord("S")
    path.write_bytes(bytes(data))
    return packet, run, path, original


@pytest.mark.parametrize("everything", [False, True])
def test_forget_keeps_a_run_record_that_matches_no_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], everything: bool
) -> None:
    """A record whose bytes changed stays, with its prompts and replies (#486)."""
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet, run, path, _ = _changed_run_packet(store, root)
    changed = path.read_bytes()
    named = [k for k, v in all_keys(root).items() if v in ("prompt@1", "reply@1")]
    assert named
    args = ["store", "forget", "--store", str(root), packet, "--reason", "asked"]
    assert main(args + ["--all"] * everything) == 1
    out = capsys.readouterr().out
    assert out.startswith(f"unchecked run@N {run}\n")
    assert "deleted run@" not in out
    assert path.read_bytes() == changed
    assert all(path_of(root, k).exists() for k in named)
    assert path_of(root, packet).exists()
    assert (f"kept packet@1 {packet}" in out) is everything


@pytest.mark.parametrize("manual", [False, True])
def test_forget_finishes_after_a_repair_of_a_changed_run_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], manual: bool
) -> None:
    """Put back the original record, or remove it by its key: then a second forget works."""
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet, run, path, original = _changed_run_packet(store, root)
    named = [k for k, v in all_keys(root).items() if v in ("prompt@1", "reply@1")]
    args = ["store", "forget", "--store", str(root), packet, "--reason", "asked", "--all"]
    assert main(args) == 1
    if manual:
        with FolderStore(root) as store:
            store.forget(run, "the record changed")
    else:
        path.write_bytes(original)
    capsys.readouterr()
    assert main(args) == 0
    out = capsys.readouterr().out
    assert f"deleted packet@1 {packet}" in out and not path_of(root, packet).exists()
    assert not path.exists()
    # Put back, the record names its prompts and replies again, and they go too.
    assert all(path_of(root, k).exists() for k in named) is manual


def test_forget_keeps_a_run_record_that_the_store_refuses(tmp_path: Path) -> None:
    """A run record file that the store does not read, here a symlink, stays (#486)."""
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
        run = json.loads(store.get("packet@1", packet))["run"]
    path = path_of(root, run)
    target = tmp_path / "elsewhere"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    with FolderStore(root) as store:
        done = forget_packet(store, packet, "asked", everything=True)
    assert ("run@N", run, "unchecked", 0) in done
    assert ("packet@1", packet, "kept", 0) in done
    assert path.is_symlink() and path_of(root, packet).exists()


def _shared_reply(store: FolderStore, root: Path) -> tuple[str, str, str]:
    """Two packets that share one reply. Return the two packet keys and the reply key."""
    one = save_run(store)
    two = save_run(store, "Other text. The amount is 5 dollars.", document_id="inv-2")
    replies = [k for k, v in all_keys(root).items() if v == "reply@1"]
    assert len(replies) == 1
    return one, two, replies[0]


def _changed_object(root: Path) -> str:
    """An object file whose bytes do not match its key. No packet names it."""
    bad = key("text@1", b"junk")
    path = path_of(root, bad)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"changed")
    return bad


def test_forget_finds_a_shared_reply_that_an_earlier_forget_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second packet names a reply that the forget of the first packet removed. The deleted
    log names its run key, so it is "absent", not a reason for "unchecked" (#442)."""
    root = tmp_path / "s"
    with FolderStore(root) as store:
        one, two, reply = _shared_reply(store, root)
        data = store.get("reply@1", reply)
    assert main(["store", "forget", "--store", str(root), one, "--reason", "asked"]) == 0
    with FolderStore(root) as store:
        entries = store.read(("deleted",))
    by_key = {e["key"]: e for e in entries}
    assert by_key[reply]["run_keys"] == [run_hash(RUNNER, "reply", data)]
    text = json.loads(path_of(root, one).read_bytes())["document"]["text"]
    assert "run_keys" not in by_key[text]
    bad = _changed_object(root)
    capsys.readouterr()
    assert main(["store", "forget", "--store", str(root), two, "--reason", "asked"]) == 0
    out = capsys.readouterr().out
    assert f"absent reply@1 {reply}" in out
    assert "unchecked" not in out and bad not in out


def test_forget_of_a_reply_records_a_run_key_for_each_runner_version(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        _, two, reply = _shared_reply(store, root)
        data = store.get("reply@1", reply)
        run = store.get(RUN_KIND, json.loads(store.get("packet@1", two))["run"])
        # The same record as the earlier runner version: the store holds two versions.
        older = f"groundgate-run/{RUN_NUMBER - 1}"
        store.put(f"run@{RUN_NUMBER - 1}", run.replace(RUNNER.encode(), older.encode(), 1))
        store.forget(reply, "asked", run_keys=_Objects(store).run_keys(reply))
        entry = store.read(("deleted",))[-1]
    assert entry["run_keys"] == sorted(run_hash(v, "reply", data) for v in (older, RUNNER))


def test_forget_builds_the_run_key_index_one_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A forget of many prompts, replies and admissions builds the run-key index one time,
    so its work grows with the number of objects, not with its square."""
    from groundgate.store import maintain

    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
    calls: list[int] = []
    real = maintain._run_keys_index

    def counted(objects: _Objects) -> dict[str, list[str]]:
        calls.append(1)
        return real(objects)

    monkeypatch.setattr(maintain, "_run_keys_index", counted)
    with FolderStore(root) as store:
        done = forget_packet(store, packet, "asked")
        entries = store.read(("deleted",))
    removed = [
        k for kind, k, state, _ in done if state == "deleted" and kind in maintain._RUN_KINDS
    ]
    assert len(removed) >= 3 and calls == [1]
    assert all(e.get("run_keys") for e in entries if e["key"] in removed)


def test_forget_after_an_old_deletion_with_no_run_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deletion from 0.12 has no run keys: an object that cannot be read is "unchecked"."""
    root = tmp_path / "s"
    with FolderStore(root) as store:
        _, two, reply = _shared_reply(store, root)
        store.forget(reply, "asked")  # as 0.12 forget wrote it
        assert "run_keys" not in store.read(("deleted",))[-1]
    bad = _changed_object(root)
    assert main(["store", "forget", "--store", str(root), two, "--reason", "asked"]) == 1
    assert f"unchecked object {bad}" in capsys.readouterr().out


def test_forget_keeps_the_run_keys_of_an_earlier_deletion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reply goes with its run keys, comes back, and goes again with no run keys. The
    first entry still counts, so a forget of the other packet exits 0."""
    root = tmp_path / "s"
    with FolderStore(root) as store:
        one, two, reply = _shared_reply(store, root)
        data = store.get("reply@1", reply)
    assert main(["store", "forget", "--store", str(root), one, "--reason", "asked"]) == 0
    with FolderStore(root) as store:
        assert store.put("reply@1", data) == reply
        store.forget(reply, "again")  # the two-argument form: no run keys
        assert "run_keys" not in store.read(("deleted",))[-1]
    bad = _changed_object(root)
    capsys.readouterr()
    assert main(["store", "forget", "--store", str(root), two, "--reason", "asked"]) == 0
    out = capsys.readouterr().out
    assert f"absent reply@1 {reply}" in out
    assert "unchecked" not in out and bad not in out


def _deletion(root: Path, entry: dict[str, Any]) -> None:
    """Append a record to the deleted log by hand, as a person with write access can."""
    with FolderStore(root) as store:
        store._append(("deleted",), entry)


@pytest.mark.parametrize("bad", ["one", [1], ["sha256:x"], None])
def test_forget_ignores_bad_run_keys_in_the_deleted_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], bad: Any
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        _, two, reply = _shared_reply(store, root)
        store.forget(reply, "asked")
    _deletion(root, {"key": reply, "reason": "x", "time": "t", "run_keys": bad})
    bad_object = _changed_object(root)
    assert main(["store", "forget", "--store", str(root), two, "--reason", "asked"]) == 1
    assert f"unchecked object {bad_object}" in capsys.readouterr().out


def test_forget_does_not_trust_a_deletion_of_an_object_that_is_there(tmp_path: Path) -> None:
    """A deleted-log entry maps the run key of a missing reply to a schema of the store. The
    schema is there, so forget keeps it and does not remove it in place of the reply."""
    root = tmp_path / "s"
    with FolderStore(root) as store:
        _, two, reply = _shared_reply(store, root)
        data = store.get("reply@1", reply)
        store.forget(reply, "asked")
        schema = json.loads(store.get("packet@1", two))["schema"]
    run_key = run_hash("groundgate-run/4", "reply", data)
    _deletion(root, {"key": schema, "reason": "x", "time": "t", "run_keys": [run_key]})
    with FolderStore(root) as store:
        done = forget_packet(store, two, "asked")
    assert path_of(root, schema).exists()
    assert not any(k == schema for _, k, _, _ in done)


def test_folder_store_forget_checks_its_run_keys(tmp_path: Path) -> None:
    with FolderStore(tmp_path / "s") as store:
        k = store.put("text@1", b"x")
        with pytest.raises(ValueError, match="not a store key"):
            store.forget(k, "asked", run_keys=["sha256:x"])
        with pytest.raises(ValueError, match="one string"):
            store.forget(k, "asked", run_keys=k)
        r = "sha256:" + "1" * 64
        store.forget(k, "asked", run_keys=[r, r])
        assert store.read(("deleted",))[-1]["run_keys"] == [r]


def test_forget_all_keeps_a_schema_of_a_packet_with_a_bad_run_line(tmp_path: Path) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
        obj = json.loads(store.get("packet@1", packet))
        bad_run = store.get(RUN_KIND, obj["run"]) + b"[1]\n"
        obj["run"] = key(RUN_KIND, bad_run)
        path = path_of(root, obj["run"])
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(bad_run)
        other = store.put("packet@1", jcs(obj).encode("utf-8"))
        path_of(root, packet).unlink()  # only the packet with the bad run line names the schema
        one = save_run(store, "Other: 5 dollars.", document_id="one")
        assert json.loads(store.get("packet@1", one))["schema"] == obj["schema"]
        done = forget_packet(store, one, "all", everything=True)
    assert ("schema@1", obj["schema"], "kept", 1) in done
    assert path_of(root, obj["schema"]).exists() and path_of(root, other).exists()


def test_forget_ignores_a_symlink_that_is_not_an_object(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
    target = tmp_path / "outside"
    target.write_bytes(b"x")
    link = path_of(root, key("reply@1", b"x"))
    link.parent.mkdir(exist_ok=True)
    os.symlink(target, link)  # get refuses a symlink
    assert main(["store", "forget", "--store", str(root), packet, "--reason", "asked"]) == 0
    assert "deleted reply@1" in capsys.readouterr().out
    assert link.is_symlink() and target.read_bytes() == b"x"


@pytest.mark.parametrize(("depth", "unread"), [(100, False), (5000, True)])
def test_forget_and_check_go_on_past_a_deep_run_line(
    tmp_path: Path, depth: int, unread: bool
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
        obj = json.loads(store.get("packet@1", packet))
        header = store.get(RUN_KIND, obj["run"]).split(b"\n")[0]
        deep = b'{"a":' + b"[" * depth + b'"x"' + b"]" * depth + b"}"
        run = header + b"\n" + deep + b"\n"
        obj["run"] = key(RUN_KIND, run)
        path_of(root, obj["run"]).parent.mkdir(exist_ok=True)
        path_of(root, obj["run"]).write_bytes(run)
        other = store.put("packet@1", jcs(obj).encode("utf-8"))
        assert check(store).findings  # a finding, not a crash
        done = forget_packet(store, other, "asked")
    assert ("text@1", obj["document"]["text"], "deleted", 1) in done
    # A line that parses and holds no text keeps the record. A line that cannot be read keeps
    # it too, and makes it "unchecked".
    assert ((RUN_KIND, obj["run"], "unchecked", 0) in done) is unread
    assert (RUN_KIND, obj["run"], "deleted", 0) not in done
    assert path_of(root, obj["run"]).exists()


def test_forget_reports_a_run_object_that_it_cannot_find(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
    replies = [k for k, kind in all_keys(root).items() if kind == "reply@1"]
    assert len(replies) == 1
    path_of(root, replies[0]).write_bytes(b"other bytes")  # the walk cannot match it
    cmd = ["store", "forget", "--store", str(root), packet, "--reason", "asked"]
    assert main(cmd) == 1
    out = capsys.readouterr().out
    assert f"unchecked object {replies[0]}" in out and "deleted text@1" in out
    path_of(root, replies[0]).unlink()  # the user removes it by key
    assert main(cmd) == 0  # a second forget finds nothing that it cannot read
    assert "unchecked" not in capsys.readouterr().out


def test_forget_reports_a_run_object_that_get_refuses_after_the_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
    reply = next(k for k, kind in all_keys(root).items() if kind == "reply@1")
    get = FolderStore.get

    def refuse(self: FolderStore, kind: str, k: str) -> bytes:
        if k == reply:
            raise StoreError("refused")
        return get(self, kind, k)

    monkeypatch.setattr(FolderStore, "get", refuse)
    with FolderStore(root) as store:
        done = forget_packet(store, packet, "asked")
    assert ("object", reply, "unchecked", 0) in done
    assert path_of(root, reply).exists()
    assert {kind for kind, _, state, _ in done if state == "deleted"} >= {"prompt@1", "text@1"}


def test_forget_counts_a_run_object_that_another_run_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        one = save_run(store)
        save_run(store, "Other text. The amount is 5 dollars.", document_id="inv-2")
    assert main(["store", "forget", "--store", str(root), one, "--reason", "asked"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"deleted reply@1 sha256:[0-9a-f]{64} \(1 other packet names it\)", out)


def test_forget_all_after_another_forget_of_the_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        packet = save_run(store)
        log = ("answers", packet, reviewer_key("ana"))
        store.append(log, {"answer": "yes"})
    forget, forget_log = FolderStore.forget, FolderStore.forget_log

    def race(self: FolderStore, k: str, reason: str, **kw: Any) -> None:
        forget(self, k, reason, **kw)
        if k == packet:  # raises NotFound, as for the second of two forgets
            forget(self, k, reason, **kw)

    def race_log(self: FolderStore, name: tuple[str, ...], reason: str) -> None:
        forget_log(self, name, reason)
        forget_log(self, name, reason)  # raises NotFound, as for the second of two forgets

    monkeypatch.setattr(FolderStore, "forget", race)
    monkeypatch.setattr(FolderStore, "forget_log", race_log)
    with FolderStore(root) as store:
        done = forget_packet(store, packet, "all", everything=True)
    assert done[-1] == ("packet@1", packet, "absent", 0)
    assert ("log", _log_rel(log), "absent", 0) in done


@pytest.mark.parametrize("folder_too", [False, True])
def test_forget_log_after_another_forget_took_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, folder_too: bool
) -> None:
    root = tmp_path / "s"
    log = ("answers", key("packet@1", b"{}"), reviewer_key("ana"))
    with FolderStore(root) as store:
        store.append(log, {"answer": "yes"})
    hold = FolderStore._hold

    def late(self: FolderStore, folder: Path, name: str) -> Any:
        (folder / f"{name}.jsonl").unlink()  # the other forget, after the lstat
        if folder_too:
            folder.rmdir()
        return hold(self, folder, name)

    monkeypatch.setattr(FolderStore, "_hold", late)
    with FolderStore(root) as store:
        with pytest.raises(NotFound):
            store.forget_log(log, "asked")
        assert store.read(("deleted",)) == []
