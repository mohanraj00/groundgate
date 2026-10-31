"""The review views of ``store rebuild`` (store.md §7.4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_review_measures import EVERY
from test_review_measures import store as measures_store
from test_review_serve import answer, store_with_tasks

from groundgate.canonical import jcs
from groundgate.review.measures import measures
from groundgate.review.resolve import write_resolution
from groundgate.review.serve import Review
from groundgate.review.tasks import DEFAULT_POLICY
from groundgate.review.views import latest_view, measures_view, queue_view
from groundgate.store import FolderStore, key, reviewer_key, set_key
from groundgate.store.maintain import rebuild

AGREE_2 = {**DEFAULT_POLICY, "agree": 2}


def test_the_queue_view_gives_the_open_tasks_for_each_policy(tmp_path: Path) -> None:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    with store:
        Review(store, "ben").answer(answer(tasks["net_income"], "not_in_document"))
        Review(store, "cy").answer(answer(tasks["revenue"], "unsure"))
        two = store.put("review-policy@1", jcs(AGREE_2).encode("utf-8"))
        store.put("review-policy@1", b"{}")  # fails the policy check
        found = json.loads(queue_view(store))
        ana = Review(store, "ana", AGREE_2).queue()["tasks"]
    default = key("review-policy@1", jcs(DEFAULT_POLICY).encode("utf-8"))
    queues = {q["policy"]: q["tasks"] for q in found["queues"]}
    assert found["format"] == "review-queue@1"
    assert [q["policy"] for q in found["queues"]] == sorted([default, two])
    # one answer settles net income under agree 1; an unsure answer settles nothing
    assert queues[default] == [
        {"task": tasks["revenue"], "packet": k, "document": "", "page": None, "answered": ["cy"]}
    ]
    # under agree 2, both stay open; the queue of ana is the same tasks in the same order
    assert [t["task"] for t in queues[two]] == [t["task"] for t in ana]
    answered = {t["task"]: t["answered"] for t in queues[two]}
    assert answered == {tasks["net_income"]: ["ben"], tasks["revenue"]: ["cy"]}


def test_a_rebuild_after_a_delete_gives_the_same_view_bytes(tmp_path: Path) -> None:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    names = ["review-queue.json", "latest-resolutions.json", "review-measures.json"]
    views = tmp_path / "store" / "views"
    with store:
        Review(store, "ben").answer(answer(tasks["net_income"], "confirm"))
        write_resolution(store, k, AGREE_2, ["ben"])
        rebuild(store)
        first = [(views / n).read_bytes() for n in names]
        for n in names:
            (views / n).unlink()
        rebuild(store)
    assert [(views / n).read_bytes() for n in names] == first


def test_the_latest_view_gives_each_resolution_that_read_the_current_heads(
    tmp_path: Path,
) -> None:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    default = key("review-policy@1", jcs(DEFAULT_POLICY).encode("utf-8"))
    two = key("review-policy@1", jcs(AGREE_2).encode("utf-8"))
    with store:
        assert json.loads(latest_view(store)) == {
            "format": "latest-resolutions@1",
            "resolutions": [],
            "stale": [],
        }
        Review(store, "ben").answer(answer(tasks["net_income"], "not_in_document"))
        first = write_resolution(store, k, None, ["ben"]).key
        assert json.loads(latest_view(store))["resolutions"] == [
            {"packet": k, "policy": default, "resolution": first}
        ]
        # a new log that no resolution read: the packet is stale
        Review(store, "cy").answer(answer(tasks["revenue"], "unsure"))
        assert json.loads(latest_view(store)) == {
            "format": "latest-resolutions@1",
            "resolutions": [],
            "stale": [k],
        }
        # a resolution of one log of two is not current either
        write_resolution(store, k, None, ["cy"])
        assert json.loads(latest_view(store))["stale"] == [k]
        # two current resolutions with two policies: one row for each policy
        a = write_resolution(store, k, None, ["ben", "cy"]).key
        b = write_resolution(store, k, AGREE_2, ["ben", "cy"]).key
        store.put("resolution@1", b'{"packet":1}')  # not a resolution
        no_policy = {"answers": [], "packet": k, "policy": "not-a-key"}
        store.put("resolution@1", jcs(no_policy).encode("utf-8"))
        found = json.loads(latest_view(store))
    assert found == {
        "format": "latest-resolutions@1",
        "resolutions": sorted(
            [
                {"packet": k, "policy": default, "resolution": a},
                {"packet": k, "policy": two, "resolution": b},
            ],
            key=lambda row: row["policy"],
        ),
        "stale": [],
    }


def test_a_log_that_the_store_cannot_read_makes_the_packet_stale(tmp_path: Path) -> None:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    with store:
        Review(store, "ben").answer(answer(tasks["net_income"], "not_in_document"))
        write_resolution(store, k, None, ["ben"])
    (log,) = (tmp_path / "store" / "logs" / "answers").rglob("*.jsonl")
    with log.open("a", encoding="utf-8") as f:
        f.write('{"torn": ')
    with FolderStore(tmp_path / "store") as store:
        found = json.loads(latest_view(store))
    assert found["resolutions"] == [] and found["stale"] == [k]


def test_a_bad_answer_record_does_not_stop_the_queue_view(tmp_path: Path) -> None:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    with store:
        Review(store, "ana").answer(answer(tasks["net_income"], "unsure"))
        bad = {"reviewer": "ana", "task": [], "verdict": "unsure"}
        store.append(("answers", k, reviewer_key("ana")), bad)
        bad = {"reviewer": "ana", "task": tasks["revenue"], "verdict": []}
        store.append(("answers", k, reviewer_key("ana")), bad)
        found = json.loads(queue_view(store))
        ana = Review(store, "ana").queue()["tasks"]
    (queue,) = found["queues"]
    answered = {t["task"]: t["answered"] for t in queue["tasks"]}
    assert answered == {tasks["net_income"]: ["ana"], tasks["revenue"]: []}
    assert [t["task"] for t in ana] == [tasks["revenue"]]  # ana answered net income


def test_the_measures_view_gives_each_policy_and_each_split(tmp_path: Path) -> None:
    store, keys = measures_store(tmp_path)
    every = store.put("review-policy@1", jcs(EVERY).encode("utf-8"))
    default = key("review-policy@1", jcs(DEFAULT_POLICY).encode("utf-8"))
    log = ("splits", set_key("set-a"))
    store.append(log, {"set": "set-a", "document": "sha256:" + "1" * 64, "split": "held-out"})
    store.append(log, {"set": "set-a", "document": "sha256:" + "2" * 64, "split": "development"})
    bad = ("splits", set_key("set-b"))
    store.append(bad, {"set": "set-a", "document": "sha256:" + "3" * 64, "split": "x"})
    store.append(("answers", keys["text"], reviewer_key("ben")), {"reviewer": "ben", "task": []})
    found = json.loads(measures_view(store))
    assert found["format"] == "review-measures@1"
    scopes = [(None, None), ("set-a", "development"), ("set-a", "held-out")]  # set-b names set-a
    policies = sorted([(default, DEFAULT_POLICY), (every, EVERY)])
    assert [(r["policy"], r["set"], r["split"]) for r in found["results"]] == [
        (p, s, t) for p, _ in policies for s, t in scopes
    ]
    for row, (policy, set_name, split) in zip(
        found["results"], [(p, s, t) for _, p in policies for s, t in scopes], strict=True
    ):
        m = measures(store, policy, set_name=set_name, split=split)
        assert row["kinds"] == m.kinds and row["packets"] == m.packets
        assert (row["other_split"], row["no_split"]) == (m.other_split, m.no_split)
        assert row["skipped"] == len(m.skipped)
    every_all = found["results"][[p for p, _ in policies].index(every) * 3]
    assert every_all["packets"] == 2 and every_all["skipped"] == 1  # ben's bad record
    assert found["results"][1]["packets"] == 0 and found["results"][1]["no_split"] == 3


def test_a_symlink_answer_log_makes_the_packet_stale(tmp_path: Path) -> None:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    with store:
        write_resolution(store, k, None, [])
        Review(store, "ben").answer(answer(tasks["net_income"], "not_in_document"))
        assert json.loads(latest_view(store))["stale"] == [k]
    (log,) = (tmp_path / "store" / "logs" / "answers").rglob("*.jsonl")
    log.rename(tmp_path / "moved.jsonl")
    log.symlink_to(tmp_path / "moved.jsonl")
    with FolderStore(tmp_path / "store") as store:
        found = json.loads(latest_view(store))
    # the log is not listed, but the old resolution with no answers is still not current
    assert found["resolutions"] == [] and found["stale"] == [k]


def test_an_answers_folder_that_is_a_symlink_makes_each_packet_stale(tmp_path: Path) -> None:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    with store:
        write_resolution(store, k, None, [])
        Review(store, "ben").answer(answer(tasks["net_income"], "not_in_document"))
    folder = tmp_path / "store" / "logs" / "answers"
    folder.rename(tmp_path / "moved")
    folder.symlink_to(tmp_path / "moved")
    with FolderStore(tmp_path / "store") as store:
        found = json.loads(latest_view(store))
    assert found["resolutions"] == [] and found["stale"] == [k]


def test_an_answer_during_the_build_makes_the_packet_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    with store:
        Review(store, "ben").answer(answer(tasks["net_income"], "not_in_document"))
        write_resolution(store, k, None, ["ben"])
        review = Review(store, "ben")
        keys = store.object_keys

        def late() -> Any:  # the answer comes after the first read of the heads
            review.answer(answer(tasks["revenue"], "unsure"))
            return keys()

        monkeypatch.setattr(store, "object_keys", late)
        found = json.loads(latest_view(store))
    assert found["resolutions"] == [] and found["stale"] == [k]


def test_an_answers_folder_that_turns_into_a_symlink_makes_each_packet_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, k, _ = store_with_tasks(tmp_path / "store")
    folder = tmp_path / "store" / "logs" / "answers"
    with store:
        write_resolution(store, k, None, [])
        assert json.loads(latest_view(store))["resolutions"] != []
        folder.mkdir(parents=True, exist_ok=True)
        keys = store.object_keys

        def late() -> Any:  # the folder turns into a symlink after the first read
            if not folder.is_symlink():
                folder.rename(tmp_path / "moved")
                folder.symlink_to(tmp_path / "moved")
            return keys()

        monkeypatch.setattr(store, "object_keys", late)
        found = json.loads(latest_view(store))
    assert found["resolutions"] == [] and found["stale"] == [k]


def test_a_log_that_turns_unreadable_during_the_build_makes_the_packet_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, k, tasks = store_with_tasks(tmp_path / "store")
    with store:
        write_resolution(store, k, None, [])
        review = Review(store, "ben")
        keys = store.object_keys

        def late() -> Any:  # a first log, with a torn line, after the first read
            if not list((tmp_path / "store" / "logs").rglob("*.jsonl")):
                review.answer(answer(tasks["revenue"], "unsure"))
                (log,) = (tmp_path / "store" / "logs" / "answers").rglob("*.jsonl")
                with log.open("a", encoding="utf-8") as f:
                    f.write('{"torn": ')
            return keys()

        monkeypatch.setattr(store, "object_keys", late)
        found = json.loads(latest_view(store))
    assert found["resolutions"] == [] and found["stale"] == [k]


def test_a_splits_log_that_changes_during_the_build_gives_no_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = measures_store(tmp_path)
    log = ("splits", set_key("set-a"))
    document = "sha256:" + "1" * 64
    store.append(log, {"set": "set-a", "document": document, "split": "development"})
    keys = store.object_keys

    def late() -> Any:  # a second split for the document, after the scopes are known
        if len(store.read(log)) == 1:
            store.append(log, {"set": "set-a", "document": document, "split": "held-out"})
        return keys()

    monkeypatch.setattr(store, "object_keys", late)
    found = json.loads(measures_view(store))
    assert [(r["set"], r["split"]) for r in found["results"]] == [(None, None)]
