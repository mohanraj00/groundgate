"""Calibrate labels as review answers (docs/design/review.md §5.3, §11; store.md §10).

A calibrate item is one decision of a packet. ``label_task`` makes its blind ``task@1``: the
template is ``calibrate_field@1`` or ``calibrate_key@1``, the mode is ``audit``, and the task
holds no code. A key task holds no choice, so the page does not show the key of the candidate.
``label_tasks`` gives each task that a packet can have, so the server and ``resolve`` accept
only a task that comes from the packet.

A label is an ``answer@2`` record. ``label_of`` reads it:

- ``calibrate_field@1``: ``confirm`` is true, ``wrong`` is false, ``unsure`` is null.
- ``calibrate_key@1``: ``confirm`` gives ``field_keys``, the keys that the value gives (an empty
  list for none), and ``unsure`` is null.

``labels_view`` is the view ``views/calibrate-labels.json`` of ``store rebuild``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..canonical import jcs
from ..model import PacketError, Schema
from ..read.layout import Layout
from ..text import normalize_ws
from .tasks import Slot, _long, _number, _places, _span, _string, _texts

__all__ = ["QUESTIONS", "TEMPLATES", "label_of", "label_task", "label_tasks", "labels_view"]

TEMPLATES = {"field": "calibrate_field@1", "key": "calibrate_key@1"}
QUESTIONS = {template: question for question, template in TEMPLATES.items()}
_PARTS = {"number": ["amount", "scale", "sign", "unit"], "text": ["text"], "span": ["start", "end"]}
NO_LABEL = object()  # a record that gives no label


def label_task(
    packet_key: str,
    receipt: Mapping[str, Any],
    text: str,
    schema: Schema,
    decision: int,
    question: str,
    *,
    references: Sequence[Any] | None = None,
    layout: Layout | None = None,
) -> dict[str, Any]:
    """The blind ``task@1`` of the calibrate item for decision ``decision`` of the receipt.
    Raise ``PacketError`` when the decision cannot be an item of ``question``."""
    if question not in TEMPLATES:
        raise ValueError(f"{question!r} is not a calibrate question: use field or key")
    d = receipt["decisions"][decision]
    name = d.get("field")
    if not isinstance(name, str) or name not in schema.fields:
        raise PacketError(f"decision {decision} is for no field of the schema")
    field = schema.fields[name]
    span = _span(d.get("evidence"))
    if not isinstance(d.get("value"), str) or span is None or d.get("ref") is not None:
        raise PacketError(f"decision {decision} has no value in the document")
    if question == "key" and field.keys is None:
        raise PacketError(f"the field {name} has no keys")
    # the predicate of questions.sample: a task is only for a decision that the sample takes
    if question == "key" and "KEY_NOT_AT_VALUE" not in (d.get("codes") or ()):
        raise PacketError(f"decision {decision} has no KEY_NOT_AT_VALUE: it is not a key item")
    if question == "field" and d.get("outcome") != "admitted":
        raise PacketError(f"decision {decision} is not admitted: it is not a field item")
    texts = _texts(text, references)
    if field.type in ("number", "integer"):
        item = "number"
        shown = _number(d["value"], d.get("unit"), span, texts[None])
    else:
        item = "span" if _long(d, texts) else "text"
        shown = _string(d["value"], item)
    key = d.get("key") if isinstance(d.get("key"), str) and field.keys is not None else None
    words = normalize_ws(name.replace("_", " "))
    # the description in the packet schema, as the label page and the judge prompt show it
    means = f" The field means: {field.description}" if field.description else ""
    if question == "field":
        asked = f"Is {shown} the {words}?{means}"
        parts = [*_PARTS[item], "field"]
        choices = [
            {"decision": decision, "value": d["value"], "unit": d.get("unit"), "shown": shown,
             "evidence": {"start": span[0], "end": span[1]}}
        ]  # fmt: skip
    else:
        asked = f"Which keys of the {words} does the marked value give? It can give none.{means}"
        parts = ["field", "key"]
        choices = []
    return {
        "format": "task@1",
        "packet": packet_key,
        "slot": {"field": name, "key": key, "decisions": [decision]},
        "item": item,
        "mode": "audit",
        "template": TEMPLATES[question],
        "question": asked,
        "parts": parts,
        "codes": [],
        "choices": choices,
        "places": _places([d], layout),
    }


def label_tasks(
    packet_key: str,
    receipt: Mapping[str, Any],
    text: str,
    schema: Schema,
    *,
    references: Sequence[Any] | None = None,
    layout: Layout | None = None,
) -> dict[str, tuple[Slot, dict[str, Any]]]:
    """Each calibrate task that the packet can have, by store key, with its slot."""
    from ..store import key

    out: dict[str, tuple[Slot, dict[str, Any]]] = {}
    for i in range(len(receipt["decisions"])):
        for question in TEMPLATES:
            try:
                task = label_task(packet_key, receipt, text, schema, i, question,
                                  references=references, layout=layout)  # fmt: skip
            except PacketError:
                continue
            s = task["slot"]
            out[key("task@1", jcs(task).encode("utf-8"))] = (Slot(s["field"], s["key"], (i,)), task)
    return out


def label_of(task: Mapping[str, Any], record: Mapping[str, Any]) -> object:
    """The label that an answer record gives to a calibrate task, or ``NO_LABEL``. The record
    must have passed the checks of ``resolve`` when the label is scored."""
    question = QUESTIONS.get(task.get("template"))  # type: ignore[arg-type]
    verdict = record.get("verdict")
    if question is None:
        return NO_LABEL
    if verdict == "unsure":
        return None
    if question == "field":
        return {"confirm": True, "wrong": False}.get(verdict, NO_LABEL)  # type: ignore[arg-type]
    keys = record.get("field_keys")
    if verdict == "confirm" and isinstance(keys, list) and all(isinstance(k, str) for k in keys):
        return list(keys)
    return NO_LABEL


def labels_view(store: Any) -> bytes:
    """The view ``calibrate-labels@1``: for each calibrate task and each reviewer, the label of
    the last answer. A task that its packet does not give, a log that the store cannot read, a
    record that names another reviewer than its log or fails the check of ``resolve``, or a
    record that gives no label, is left out."""
    import json

    from ..store import StoreError, key

    tasks: dict[str, dict[str, Any]] = {}
    keys, _ = store.object_keys()
    for k in keys:
        try:
            data = store.object_bytes(k)
        except StoreError:
            continue
        if key("task@1", data) != k:
            continue
        try:
            task = json.loads(data)
        except (ValueError, RecursionError):  # deep nesting fits in a store object
            continue
        if isinstance(task, dict) and task.get("template") in QUESTIONS:
            tasks[k] = task
    tasks, packets = _from_packets(store, tasks)
    last: dict[tuple[str, str], object] = {}
    names, _ = store.log_names()
    for log in names:
        if log[0] != "answers" or log[1] not in packets:
            continue
        try:
            records = store.read(log)
        except StoreError:
            continue
        for r in records:
            found = _record_label(r, log[2], packets[log[1]])
            if found is not NO_LABEL:
                last[r["task"], r["reviewer"]] = found
    rows = [{"task": t, "reviewer": n, "label": v} for (t, n), v in sorted(last.items())]
    return jcs({"format": "calibrate-labels@1", "labels": rows}).encode("utf-8")


def _record_label(record: Any, log_reviewer: str, packet: _Packet) -> object:
    """The label of one record of an answer log, or ``NO_LABEL``. The record must name the
    reviewer of its log and pass the check of ``resolve`` against its packet. A record that
    fails is left out."""
    from ..store import reviewer_key
    from .resolve import AnswerError, _check

    schema, ids, own = packet
    if not isinstance(record, Mapping):
        return NO_LABEL
    name, tk = record.get("reviewer"), record.get("task")
    if not isinstance(name, str) or not isinstance(tk, str) or tk not in own:
        return NO_LABEL  # a review answer, or a task that the packet does not give
    if reviewer_key(name) != log_reviewer:
        return NO_LABEL
    try:
        c = _check(name, record, {}, schema, ids, labels=own)
    except (AnswerError, KeyError, TypeError, ValueError):
        return NO_LABEL
    return label_of(c.task, record)


_Packet = tuple[Schema, list[object], dict[str, tuple[Slot, dict[str, Any]]]]


def _from_packets(
    store: Any, tasks: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, _Packet]]:
    """The tasks that their packet gives with the same bytes, and for each such packet its
    schema, its candidate ids and its calibrate tasks. A task object is untrusted local data,
    so a task with a bad packet member, or a packet that the store cannot read or that
    ``verify`` refuses, is left out."""
    from ..store import StoreError
    from .tasks import checked_packet

    seen: set[str] = set()
    packets: dict[str, _Packet] = {}
    out: dict[str, Any] = {}
    for k, task in tasks.items():
        pk = task.get("packet")
        if not isinstance(pk, str):
            continue
        if pk not in seen:
            seen.add(pk)
            try:
                packet, schema, layout, problems = checked_packet(store, pk)
                if not problems and schema is not None:
                    own = label_tasks(pk, packet.receipt, packet.text, schema, layout=layout)
                    ids = [c.get("id") for c in packet.candidates if isinstance(c, Mapping)]
                    packets[pk] = (schema, ids, own)
            except (StoreError, PacketError, ValueError, KeyError, TypeError):
                pass
        if pk in packets and k in packets[pk][2]:
            out[k] = task
    return out, packets
