"""The review views of ``groundgate store rebuild`` (store.md §7.4).

Each view gives one result for each review policy: each ``review-policy@1`` object of the
store, and the default policy of ``review tasks``. The results are sorted by policy key, so the
bytes depend only on the objects and logs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..canonical import jcs
from .tasks import DEFAULT_POLICY, check_policy

_KEY = re.compile(r"sha256:[0-9a-f]{64}")
_ANSWERS = re.compile(r"logs/answers/([0-9a-f]{64})[/ ]")
_RESOLUTION = frozenset({"format", "packet", "policy", "answers", "slots"})

__all__ = ["latest_view", "measures_view", "policies", "queue_view"]


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


def _heads(obj: Any) -> dict[str, str] | None:
    """The reviewer key and head of each log that a ``resolution@1`` object read, or None if
    its members do not match the format: the five members, the format name, the packet and
    policy keys, each head and a list of slots."""
    from ..store import reviewer_key

    if not (
        isinstance(obj, dict)
        and set(obj) == _RESOLUTION
        and obj["format"] == "resolution@1"
        and all(isinstance(obj[m], str) and _KEY.fullmatch(obj[m]) for m in ("packet", "policy"))
        and isinstance(obj["answers"], list)
        and isinstance(obj["slots"], list)
    ):
        return None
    out = {}
    for a in obj["answers"]:
        if not (
            isinstance(a, dict)
            and set(a) == {"reviewer", "head"}
            and isinstance(a["reviewer"], str)
            and a["reviewer"].strip()
            and isinstance(a["head"], str)
            and _KEY.fullmatch(a["head"])
        ):
            return None
        try:
            out[reviewer_key(a["reviewer"])] = a["head"]
        except UnicodeEncodeError:
            return None
    return out


def latest_view(store: Any) -> bytes:
    """The view ``latest-resolutions@1``. A stored ``resolution@1`` object is current if its
    ``answers`` heads are the current heads of all the answer logs of its packet: the same logs,
    and the same last entry of each log. The view has one row for each current resolution,
    sorted by packet, policy and resolution. ``stale`` lists each packet with an answer log
    and no current resolution. A packet with a log that the store cannot read has no current
    resolution, and so does a packet folder of the answer logs with an entry that is not a log.
    An object whose members do not match ``resolution@1`` is left out."""
    from ..store import StoreError, key

    heads: dict[str, dict[str, str] | None] = {}  # packet -> reviewer key -> head, or None
    names, problems = store.log_names()
    for log in names:
        if log[0] != "answers":
            continue
        found = heads.setdefault(log[1], {})
        if found is None:
            continue
        try:
            records = store.read(log)
        except StoreError:
            heads[log[1]] = None
            continue
        if records:
            found[log[2]] = records[-1]["entry_sha256"]
    for problem in problems:  # a symlink or other entry under the packet folder of a log
        m = _ANSWERS.match(problem)
        if m:
            heads["sha256:" + m.group(1)] = None
    rows = set()
    keys, _ = store.object_keys()
    for k in keys:
        try:
            data = store.object_bytes(k)
        except StoreError:
            continue
        if key("resolution@1", data) != k:
            continue
        try:
            obj = json.loads(data)
        except (ValueError, RecursionError):  # deep nesting fits in a store object
            continue
        read = _heads(obj)
        if read is not None and heads.get(obj["packet"], {}) == read:
            rows.add((obj["packet"], obj["policy"], k))
    current = {pk for pk, _, _ in rows}
    out = {
        "format": "latest-resolutions@1",
        "resolutions": [{"packet": p, "policy": q, "resolution": r} for p, q, r in sorted(rows)],
        "stale": sorted(pk for pk in heads if pk not in current),
    }
    return jcs(out).encode("utf-8")


def measures_view(store: Any) -> bytes:
    """The view ``review-measures@1``: the result of ``review measures`` for each policy and
    each scope. The scopes are all packets (``set`` and ``split`` null), and each split of each
    ``splits`` log. The results are sorted by policy, set and split, with null first.
    ``skipped`` is the number of skipped lines, because their text can change when only a
    message changes. A splits log that the store cannot read, or that ``read_split`` refuses,
    gives no scope."""
    from ..store import StoreError
    from ..store.splits import split_view
    from .measures import measures

    scopes: list[tuple[str | None, str | None]] = [(None, None)]
    names, _ = store.log_names()
    sets = []
    for log in names:
        if log[0] != "splits":
            continue
        try:
            records = store.read(log)
            found = split_view(records, log[1])
        except (StoreError, ValueError):
            continue
        if records:
            sets.append((records[0]["set"], sorted(set(found.values()))))
    for name, splits in sorted(sets):
        scopes += [(name, split) for split in splits]
    results = []
    for pkey, policy in policies(store):
        for set_name, split in scopes:
            m = measures(store, policy, set_name=set_name, split=split)
            results.append(
                {"policy": pkey, "set": set_name, "split": split, "kinds": m.kinds,
                 "packets": m.packets, "skipped": len(m.skipped),
                 "other_split": m.other_split, "no_split": m.no_split}
            )  # fmt: skip
    return jcs({"format": "review-measures@1", "results": results}).encode("utf-8")
