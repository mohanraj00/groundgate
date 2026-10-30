"""The review views of ``store rebuild`` (store.md §7.4)."""

from __future__ import annotations

import json
from pathlib import Path

from test_review_serve import answer, store_with_tasks

from groundgate.canonical import jcs
from groundgate.review.resolve import write_resolution
from groundgate.review.serve import Review
from groundgate.review.tasks import DEFAULT_POLICY
from groundgate.review.views import latest_view, queue_view
from groundgate.store import FolderStore, key, reviewer_key
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
    names = ["review-queue.json", "latest-resolutions.json"]
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
        found = json.loads(queue_view(store))
        ana = Review(store, "ana").queue()["tasks"]
    (queue,) = found["queues"]
    assert len(queue["tasks"]) == 2
    assert [t["task"] for t in ana] == [tasks["revenue"]]  # ana answered net income
