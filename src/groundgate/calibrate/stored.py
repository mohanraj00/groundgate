"""Calibrate labels in a store (docs/design/review.md §11, store.md §10).

``put_items`` writes one packet for each document and one blind task for each item, and gives
the map that ``tasks.json`` keeps: item id to packet and task. ``labels`` reads the answer log
of one reviewer for each packet, checks each record against its packet as ``review resolve``
does, and gives the labels in the form of ``labels.json``, with the head of each log. With
``heads``, it reads each log only up to that head, so a later answer cannot change the labels
that a judge was scored on.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from groundgate.canonical import digest, jcs
from groundgate.model import PacketError, Schema

__all__ = ["dump", "labels", "put_items"]


def dump(labels: Mapping[str, Any]) -> str:
    """The text of ``labels.json`` as the label page writes it."""
    return json.dumps(dict(sorted(labels.items())), indent=1) + "\n"


def put_items(
    store: Any,
    doc: str,
    text: str,
    schema: Mapping[str, Any],
    cands: Sequence[Any],
    items: Sequence[Mapping[str, Any]],
    question: str,
) -> dict[str, dict[str, str]]:
    """Write the packet of document ``doc`` and the task of each of its items. The receipt of
    the packet decides the same candidates as the sample, so each item is one decision."""
    from groundgate.review.labels import label_task
    from groundgate.store import check_bytes
    from groundgate.store.packets import admit_packet

    pk, receipt = admit_packet(store, text, dict(schema), list(cands), None, doc)
    decided = receipt.to_dict()
    index = {d["candidate_sha256"]: i for i, d in enumerate(decided["decisions"])}
    parsed = Schema.from_dict(dict(schema))
    out: dict[str, dict[str, str]] = {}
    for it in items:
        n = int(it["id"].rsplit(":", 1)[1])
        task = label_task(pk, decided, text, parsed, index[digest("candidate", cands[n])],
                          question, raw_schema=schema)  # fmt: skip
        data = jcs(task).encode("utf-8")
        check_bytes("task@1", data)
        out[it["id"]] = {"packet": pk, "task": store.put("task@1", data)}
    return out


def _records(store: Any, pk: str, reviewer: str, head: str | None) -> list[dict[str, Any]]:
    """The records of the answer log of ``reviewer`` up to ``head``. A head of None is a log
    that had no record."""
    from groundgate.store import reviewer_key

    records: list[dict[str, Any]] = store.read(("answers", pk, reviewer_key(reviewer)))
    if head is None:
        return []
    for n, r in enumerate(records):
        if r["entry_sha256"] == head:
            return records[: n + 1]
    raise SystemExit(f"the answer log of {pk} has no record {head}; the store changed")


def labels(
    store_dir: Path,
    tasks: Mapping[str, Mapping[str, str]],
    items: Sequence[Mapping[str, Any]],
    reviewer: str,
    heads: Mapping[str, str | None] | None = None,
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """The labels of ``reviewer`` for each item that has one, and the head of each answer log.
    An answer that breaks its task stops with the reviewer and the sequence of the record."""
    from groundgate.review.labels import NO_LABEL, label_of, label_tasks
    from groundgate.review.resolve import AnswerError, _check
    from groundgate.review.tasks import checked_packet
    from groundgate.store import FolderStore, StoreError, reviewer_key

    last: dict[str, object] = {}
    found: dict[str, str | None] = {}
    try:
        with FolderStore(store_dir) as store:
            for pk in sorted({t["packet"] for t in tasks.values()}):
                packet, schema, layout, problems = checked_packet(store, pk)
                if problems or schema is None:
                    raise SystemExit(f"the packet {pk} does not match its receipt")
                own = label_tasks(pk, packet.receipt, packet.text, schema, layout=layout,
                                  raw_schema=packet.schema)  # fmt: skip
                if heads is None:
                    records = store.read(("answers", pk, reviewer_key(reviewer)))
                else:
                    records = _records(store, pk, reviewer, heads.get(pk))
                ids = [c.get("id") for c in packet.candidates if isinstance(c, Mapping)]
                for r in records:
                    if not isinstance(r.get("task"), str) or r["task"] not in own:
                        continue  # a review answer: review resolve checks it
                    c = _check(reviewer, r, {}, schema, ids, labels=own)
                    value = label_of(c.task, r)
                    if value is not NO_LABEL:
                        last[c.task_key] = value
                found[pk] = records[-1]["entry_sha256"] if records else None
    except AnswerError as exc:
        raise SystemExit(f"{store_dir}: {exc}") from exc
    except (StoreError, PacketError, ValueError, OSError) as exc:
        raise SystemExit(f"{store_dir}: {exc}") from exc
    out: dict[str, Any] = {}
    for it in items:
        tk = tasks[it["id"]]["task"]
        if tk not in last:
            continue
        value = last[tk]
        out[it["id"]] = [k for k in it["keys"] if k in value] if isinstance(value, list) else value
    return dict(sorted(out.items())), found
