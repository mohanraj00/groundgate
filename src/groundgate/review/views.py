"""The review views of ``groundgate store rebuild`` (store.md §7.4).

Each view gives one result for each review policy: each ``review-policy@1`` object of the
store, and the default policy of ``review tasks``. The results are sorted by policy key, so the
bytes depend only on the objects and logs.
"""

from __future__ import annotations

import json
from typing import Any

from ..canonical import jcs
from .tasks import DEFAULT_POLICY, check_policy

__all__ = ["policies", "queue_view"]


def policies(store: Any) -> list[tuple[str, dict[str, Any]]]:
    """Each policy of the views as (key, checked policy), sorted by key: each
    ``review-policy@1`` object of the store that passes the policy check, and the default
    policy. An object that the store cannot read or that fails the check is left out."""
    from ..store import StoreError, key

    found = {key("review-policy@1", jcs(DEFAULT_POLICY).encode("utf-8")): dict(DEFAULT_POLICY)}
    keys, _ = store.object_keys()
    for k in keys:
        try:
            data = store.object_bytes(k)
        except StoreError:
            continue
        if key("review-policy@1", data) != k:
            continue
        try:
            found[k] = check_policy(json.loads(data))
        except (ValueError, RecursionError):  # deep nesting fits in a store object
            continue
    return sorted(found.items())


def queue_view(store: Any) -> bytes:
    """The view ``review-queue@1``: for each policy, the open tasks for all reviewers. An open
    task is a task whose slot no answer settles under the policy. ``answered`` names each
    reviewer that gave an answer to the task, so the queue of one reviewer is the tasks that do
    not name it. A packet that ``review serve`` leaves out, and a log that it cannot read, are
    left out here too."""
    from .serve import Review

    review = Review(store, "store rebuild", DEFAULT_POLICY)
    logs = {pk: review._logs(pk) for pk in review.docs}
    queues = []
    for pkey, policy in policies(store):
        items = []
        for pk, doc in review.docs.items():
            settled = review.settled(pk, logs[pk], policy)
            for tk in doc.tasks:
                if tk in settled:
                    continue
                names = sorted(
                    n for n, rs in logs[pk].items() if any(r.get("task") == tk for r in rs)
                )
                items.append((review.place(pk, tk), names))
        tasks = [
            {"task": tk, "packet": pk, "document": d, "page": page, "answered": names}
            for (d, pk, _, tk, page), names in sorted(items)
        ]
        queues.append({"policy": pkey, "tasks": tasks})
    return jcs({"format": "review-queue@1", "queues": queues}).encode("utf-8")
