"""The review views of ``store rebuild`` (store.md §7.4)."""

from __future__ import annotations

import json
from pathlib import Path

from test_review_serve import answer, store_with_tasks

from groundgate.canonical import jcs
from groundgate.review.serve import Review
from groundgate.review.tasks import DEFAULT_POLICY
from groundgate.review.views import queue_view
from groundgate.store import key, reviewer_key
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


def test_a_rebuild_after_a_delete_gives_the_same_queue_bytes(tmp_path: Path) -> None:
    store, _, tasks = store_with_tasks(tmp_path / "store")
    with store:
        Review(store, "ben").answer(answer(tasks["net_income"], "confirm"))
        store.put("review-policy@1", jcs(AGREE_2).encode("utf-8"))
        rebuild(store)
        view = tmp_path / "store" / "views" / "review-queue.json"
        first = view.read_bytes()
        view.unlink()
        rebuild(store)
    assert view.read_bytes() == first


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
