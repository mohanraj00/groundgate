"""The blind label tasks of the audit pick, and their answers as audit labels (SPEC §4.18,
docs/design/review.md §5.5, #695). The expectations are written by hand."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_calibrate_audit import DIGEST, PROFILE, Case
from test_review_http import (
    CLOCK,
    ISSUERS,
    KEY,
    NO_AUDIT,
    at,
    claim,
    error,
    id_of,
    make_store,
    serving,
    u16,
)

from groundgate import admit
from groundgate.calibrate import audit
from groundgate.calibrate.cli import main
from groundgate.canonical import jcs
from groundgate.model import Schema
from groundgate.review import api
from groundgate.review.api import Service
from groundgate.review.blind import blind_tasks, is_label_task, write_blind_tasks
from groundgate.review.resolve import write_resolution
from groundgate.review.serve import Review
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore
from groundgate.store.packets import admit_packet

TEXT = "Items: 7\n"
SCHEMA: dict[str, Any] = {"fields": {"items": {"type": "integer"}}}  # the schema of PROFILE
CANDIDATES = [{"id": "c1", "field": "items", "value": 7, "evidence": {"text": "7"}}]
SEVEN = {"start": 7, "end": 8}  # the span of 7 in TEXT, in UTF-8 bytes


class Blind:
    """The audit set of ``Case``, with the document d1 first in the log, and a store with the
    packet of d1. The pick takes d1 and a01 to a29 by the minimum, so a30 is not in the pick."""

    def __init__(self, tmp: Path) -> None:
        self.case = Case(tmp)
        self.store = tmp / "store"
        with FolderStore(self.store) as s:
            self.packet, _ = admit_packet(s, TEXT, SCHEMA, CANDIDATES, None, "d1")
        receipt = admit(TEXT, None, CANDIDATES, None, "d1", profile=PROFILE).to_dict()
        self.case.write_log([audit.document_entry("d1", receipt), *self.case.entries[:29]])
        self.case.labels = self.case.labels[:29]
        self.case.write_labels()
        self.audit = self.case.audit

    def tasks(self, *more: str) -> None:
        main(["audit", "tasks", "--audit", str(self.audit), "--store", str(self.store),
              "--packet", self.packet, "--name", "d1", "--profile", str(self.case.profile),
              *more])  # fmt: skip

    def labels(self) -> None:
        main(["audit", "labels", "--audit", str(self.audit), "--store", str(self.store)])

    def task(self) -> str:
        with FolderStore(self.store) as s:
            (tk,) = [k for k in _keys(s) if is_label_task(json.loads(s.get("task@1", k)))]
        return tk

    def answer(self, name: str, verdict: str, **more: Any) -> None:
        with FolderStore(self.store) as s:
            Review(s, name, clock=lambda: CLOCK).write(
                {"task": self.task(), "verdict": verdict, "decision": None, "codes_kept": [],
                 "reason_seen": False, "keys": 0, "ms": 0, **more}
            )  # fmt: skip

    def last_labels(self, n: int) -> list[dict[str, Any]]:
        lines = (self.audit / "labels.jsonl").read_text("utf-8").splitlines()
        return [json.loads(line) for line in lines[-n:]]


def _keys(store: FolderStore) -> list[str]:
    keys, _ = store.object_keys()
    out = []
    for k in keys:
        try:
            json.loads(store.get("task@1", k))
        except Exception:
            continue
        out.append(k)
    return out


def _label(value: str | None, labeler: str) -> dict[str, Any]:
    return {"groundgate_audit_label": 1, "document": "d1", "profile": DIGEST, "field": "items",
            "key": None, "value": value, "labeler": labeler, "date": "2026-11-19"}  # fmt: skip


def test_the_schema_is_the_schema_of_the_profile() -> None:
    assert PROFILE["schema"] == SCHEMA


def test_a_label_task_has_no_decision_and_is_the_same_with_no_admitted_value() -> None:
    schema = Schema.from_dict(
        {"fields": {"n": {"type": "integer", "unit": "USD"}, "k": {"type": "string",
         "keys": ["b", "a"]}, "o": {"type": "string", "options": ["x", "y"]}}}
    )  # fmt: skip
    found = blind_tasks("sha256:" + "0" * 64, schema)
    assert [(s.field, s.key, s.decisions) for s, _ in found.values()] == [
        ("k", "a", ()), ("k", "b", ()), ("n", None, ()), ("o", None, ()),
    ]  # fmt: skip
    task = next(t for s, t in found.values() if s.field == "n")
    assert task == {
        "format": "task@1", "packet": "sha256:" + "0" * 64,
        "slot": {"field": "n", "key": None, "decisions": []}, "item": "number", "mode": "audit",
        "template": "number@1", "question": "What is n, in USD?", "parts": ["unit", "field"],
        "codes": [], "choices": [], "places": [],
    }  # fmt: skip
    other = next(t for s, t in found.values() if s.field == "o")
    assert (other["item"], other["options"]) == ("closed_set", ["x", "y"])
    assert all(is_label_task(t) for _, t in found.values())


def test_the_blind_answers_become_audit_labels_and_the_measure_counts_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    b = Blind(tmp_path)
    b.tasks()
    assert capsys.readouterr().out == "wrote 1 label tasks of d1\n"
    b.tasks()  # the same tasks again: no new line, no change
    assert (b.audit / "blind.jsonl").read_text("utf-8") == json.dumps(
        {"document": "d1", "packet": b.packet, "profile": DIGEST}, separators=(",", ":")
    ) + "\n"
    assert (b.audit / "docs" / "d1.txt").read_text("utf-8") == TEXT
    tk = b.task()
    with FolderStore(b.store) as s:
        stored = s.get("task@1", tk).decode("utf-8")
    assert '"decisions":[]' in stored and "7" not in stored.replace(b.packet, "")

    service = Service(b.store, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
    with serving(api.server(service), {"Authorization": claim()}) as call:
        listed = json.loads(call("GET", "/v1/tasks")[2])
        assert [t["task"] for t in listed["tasks"]] == [id_of(tk)]
        view = json.loads(call("GET", f"/v1/tasks/{id_of(tk)}")[2])
        assert (view["mode"], view["field"], view["body"]) == ("audit", "items", None)
        body = {"task": id_of(tk), "verdict": "correct", "span": SEVEN}
        assert error(call("POST", "/v1/answers", {"task": id_of(tk), "verdict": "confirm"})) == (
            400, "bad_answer",
        )  # fmt: skip
        response = call("POST", "/v1/answers", body)
        assert response[0] == 201 and json.loads(response[2])["record"] is None
    capsys.readouterr()
    b.labels()
    assert capsys.readouterr().out == "added 1 labels\n"
    assert b.last_labels(1) == [_label("7", "ana")]
    b.labels()  # a second run adds no line
    assert capsys.readouterr().out == "added 0 labels\n"

    report = b.case.run("out")
    checked = report["fields"]["items"]["routes"]["checked"]
    # 2 gold values, 29 labels of a01 to a29 and the label of d1, with no error
    assert (checked["admitted"], checked["errors"]) == (32, 0)
    assert report["audit"]["documents"] == 30


def test_a_wrong_blind_answer_is_an_error_of_the_measure(tmp_path: Path) -> None:
    b = Blind(tmp_path)
    b.tasks()
    b.answer("ana", "not_in_document")
    b.labels()
    assert b.last_labels(1) == [_label(None, "ana")]
    checked = b.case.run("out")["fields"]["items"]["routes"]["checked"]
    assert (checked["admitted"], checked["errors"]) == (32, 1)


def test_the_last_answer_of_each_reviewer_counts_and_two_values_give_no_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    b = Blind(tmp_path)
    b.tasks()
    b.answer("ana", "not_in_document")
    b.answer("ana", "unsure")  # the last answer of ana gives no label
    capsys.readouterr()
    b.labels()
    assert (
        capsys.readouterr().out == "no label: d1 items: no answer gives a label\nadded 0 labels\n"
    )
    b.answer("bob", "not_in_document")
    b.answer("ana", "correct", start=7, end=8)  # UTF-16 offsets, as the page sends them
    b.labels()
    out = capsys.readouterr().out
    assert out == "no label: d1 items: the reviewers give different values\nadded 0 labels\n"


def test_a_later_answer_takes_out_the_label_of_an_earlier_answer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    b = Blind(tmp_path)
    b.tasks()
    before = (b.audit / "labels.jsonl").read_text("utf-8")
    b.answer("ana", "correct", start=7, end=8)
    b.labels()
    assert b.last_labels(1) == [_label("7", "ana")]
    b.answer("ana", "unsure")  # the last answer of ana gives no label now
    capsys.readouterr()
    b.labels()
    assert capsys.readouterr().out == (
        "no label: d1 items: no answer gives a label\nremoved 1 labels\nadded 0 labels\n"
    )
    assert (b.audit / "labels.jsonl").read_text("utf-8") == before
    assert b.case.run("out")["audit"]["documents"] == 29


def test_a_label_task_settles_no_slot_and_changes_no_receipt(tmp_path: Path) -> None:
    b = Blind(tmp_path)
    b.tasks()
    with FolderStore(b.store) as s:
        before = write_resolution(s, b.packet, None, ["ana"]).resolution
    b.answer("ana", "not_in_document")
    with FolderStore(b.store) as s:
        keys = set(s.object_keys()[0])
        after = write_resolution(s, b.packet, None, ["ana"]).resolution
        new = set(s.object_keys()[0]) - keys
    assert before is not None and after is not None
    assert after["slots"] == before["slots"]
    assert [(x["status"], x["value"], x["task"]) for x in after["slots"]] == [
        ("admitted", "7", None)
    ]
    assert len(new) == 1  # the resolution object, and no correction packet or receipt


def test_the_label_tasks_need_a_picked_document_and_its_profile(tmp_path: Path) -> None:
    b = Blind(tmp_path)
    with pytest.raises(SystemExit, match="not in the blind audit pick"):
        main(["audit", "tasks", "--audit", str(b.audit), "--store", str(b.store),
              "--packet", b.packet, "--name", "a30", "--profile", str(b.case.profile)])  # fmt: skip
    other = tmp_path / "other.json"
    other.write_text(json.dumps({**PROFILE, "version": "1.0.1"}), "utf-8")
    with pytest.raises(SystemExit, match="another profile"):
        b.tasks("--profile", str(other))
    with FolderStore(b.store) as s:
        k, _ = admit_packet(s, TEXT, SCHEMA, [], None, "d1")  # 0 items, not 1
    with pytest.raises(SystemExit, match="does not decide the packet"):
        main(["audit", "tasks", "--audit", str(b.audit), "--store", str(b.store),
              "--packet", k, "--name", "d1", "--profile", str(b.case.profile)])  # fmt: skip
    with FolderStore(b.store) as s:
        wide = {"fields": {**SCHEMA["fields"], "boxes": {"type": "integer"}}}
        k, _ = admit_packet(s, TEXT, wide, CANDIDATES, None, "d1")  # a field more
    with pytest.raises(SystemExit, match="is not the schema of the profile"):
        main(["audit", "tasks", "--audit", str(b.audit), "--store", str(b.store),
              "--packet", k, "--name", "d1", "--profile", str(b.case.profile)])  # fmt: skip
    assert not (b.audit / "blind.jsonl").exists()
    with FolderStore(b.store) as s:
        # a review task of the packet in the store, as a review policy gives one
        ((_, task),) = blind_tasks(b.packet, Schema.from_dict(SCHEMA)).values()
        review = {**task, "mode": "review"}
        s.put("task@1", jcs(review).encode("utf-8"))
    with pytest.raises(SystemExit, match="come before its review tasks"):
        b.tasks()


@pytest.mark.parametrize("path", ["api", "page"])
def test_a_blind_correct_with_the_admitted_value_keeps_the_slot_admitted(
    tmp_path: Path, path: str
) -> None:
    """Rule 7: the audit task of the review policy shows no value. A correct answer with the
    admitted value is a confirm, so the slot keeps the admitted value of the packet."""
    root = tmp_path / "store"
    k, tasks = make_store(root)
    if path == "api":
        service = Service(root, ISSUERS, clock=lambda: CLOCK, id_key=KEY)
        with serving(api.server(service), {"Authorization": claim()}) as call:
            body = {"task": id_of(tasks["net_income"]), "verdict": "correct",
                    "span": at("310 thousand")}  # fmt: skip
            assert call("POST", "/v1/answers", body)[0] == 201
    else:
        with FolderStore(root) as s:
            Review(s, "ana", clock=lambda: CLOCK).write(
                {"task": tasks["net_income"], "verdict": "correct", "decision": None,
                 "codes_kept": [], "reason_seen": False, "keys": 0, "ms": 0,
                 **u16("310 thousand")}
            )  # fmt: skip
    with FolderStore(root) as s:
        resolution = write_resolution(s, k, None, ["ana"]).resolution
        packet_receipt = json.loads(s.get("packet@1", k))["receipt"]
    assert resolution is not None
    (slot,) = [x for x in resolution["slots"] if x["field"] == "net_income"]
    assert (slot["status"], slot["value"], slot["receipt"]) == (
        "admitted",
        "310000",
        packet_receipt,
    )


def test_the_page_checks_a_label_task_with_the_persons_candidate_only(tmp_path: Path) -> None:
    """The other candidates of the packet stay out of the check of a label task, as in
    ``audit labels``. Here the admitted candidate 7 would conflict with the answer 8."""
    text = "Items: 7. Items: 8.\n"
    eight = text.index("8")
    with FolderStore(tmp_path / "store") as s:
        k, _ = admit_packet(s, text, SCHEMA, CANDIDATES, None, "d1")
        ((tk, _),) = write_blind_tasks(s, k)
        review = Review(s, "ana", clock=lambda: CLOCK)
        span = {"start": eight, "end": eight + 1}
        checked = review.check({"task": tk, "verdict": "correct", **span})
        assert (checked["outcome"], checked["codes"]) == ("admitted", [])
        record, _ = review.write(
            {"task": tk, "verdict": "correct", "decision": None, "codes_kept": [],
             "reason_seen": False, "keys": 0, "ms": 0, **span}
        )  # fmt: skip
    assert record["candidate"]["value"] == "8"


def test_audit_labels_writes_no_file_through_a_link(tmp_path: Path) -> None:
    b = Blind(tmp_path)
    b.tasks()
    b.answer("ana", "not_in_document")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n", "utf-8")
    (b.audit / "labels.jsonl.tmp").symlink_to(outside)
    b.labels()
    assert outside.read_text("utf-8") == "keep\n"
    assert not (b.audit / "labels.jsonl").is_symlink()
    assert b.last_labels(1) == [_label(None, "ana")]
    assert sorted(p.name for p in b.audit.glob("*.tmp")) == ["labels.jsonl.tmp"]


def test_the_page_gives_no_label_task_next_to_a_task_that_shows_a_value(tmp_path: Path) -> None:
    text = "Items: 7. Items: 8.\n"
    two = [*CANDIDATES, {"id": "c2", "field": "items", "value": 8, "evidence": {"text": "8"}}]
    with FolderStore(tmp_path / "store") as s:
        k, _ = admit_packet(s, text, SCHEMA, two, None, "d1")  # the two values conflict
        ((tk, _),) = write_blind_tasks(s, k)
        assert Review(s, "ana", clock=lambda: CLOCK).docs[k].tasks == [tk]
        written = write_tasks(s, k, NO_AUDIT).tasks  # a review task with the choices 7 and 8
        assert [(t["mode"], len(t["choices"])) for _, t in written] == [("review", 2)]
        review = Review(s, "ana", clock=lambda: CLOCK)
    assert review.docs[k].tasks == [written[0][0]]
    assert review.skipped == [
        f"packet {k}: 1 label tasks of the blind audit, because the packet has tasks "
        "that show a value"
    ]
