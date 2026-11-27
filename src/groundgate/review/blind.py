"""The label tasks of the blind audit (SPEC §4.18, docs/design/review.md §5.5).

A label task asks for the value of one field and key of a document of the blind audit pick. It
is a ``task@1`` with the mode ``audit`` and a slot with no decision. It has no choice, no code
and no place, so it is the same with and without an admitted value, and the existence of the
task tells nothing of the decisions. No other task has the mode ``audit`` and no decision.

A label task takes ``correct``, ``not_in_document`` and ``unsure``. Its answer is a label
(§6.1 rule 9): it settles no slot and changes no decision or receipt. ``calibrate audit labels``
makes the ``groundgate_audit_label`` records of the answers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..canonical import jcs
from ..model import Schema
from .tasks import _PARTS, Slot, _question, _stored_tasks, checked_packet

__all__ = ["VERDICTS", "blind_task", "blind_tasks", "is_label_task", "write_blind_tasks"]

VERDICTS = frozenset({"correct", "not_in_document", "unsure"})


def is_label_task(task: Mapping[str, Any]) -> bool:
    """True for a label task of the blind audit: the mode ``audit`` and no decision."""
    slot = task.get("slot")
    return task.get("mode") == "audit" and isinstance(slot, Mapping) and slot.get("decisions") == []


def blind_task(packet_key: str, schema: Schema, field: str, key: str | None) -> dict[str, Any]:
    """The label task of ``field`` and ``key`` of the packet ``packet_key``."""
    f = schema.fields[field]
    if f.type in ("number", "integer"):
        item, template = "number", "number@1"
    elif f.options is not None:
        item, template = "closed_set", "closed_set@1"
    else:
        item, template = "text", "text@1"
    question, named = _question(item, Slot(field, key, ()), f.unit, [])
    task: dict[str, Any] = {
        "format": "task@1",
        "packet": packet_key,
        "slot": {"field": field, "key": key, "decisions": []},
        "item": item,
        "mode": "audit",
        "template": template,
        "question": question,
        "parts": [p for p in _PARTS[template] if p in named],
        "codes": [],
        "choices": [],
        "places": [],
    }
    if f.options is not None:
        task["options"] = list(f.options)
    return task


def blind_tasks(packet_key: str, schema: Schema) -> dict[str, tuple[Slot, dict[str, Any]]]:
    """The label task of each field and each key of the schema, by store key, with its slot.
    A record field has none. The order is the code point order of the field and the key, as
    the tasks of SPEC §4.18."""
    from ..store import key as store_key

    out: dict[str, tuple[Slot, dict[str, Any]]] = {}
    for name in sorted(schema.fields):
        f = schema.fields[name]
        if f.record is not None:
            continue
        for k in [None] if f.keys is None else sorted(f.keys):
            task = blind_task(packet_key, schema, name, k)
            out[store_key("task@1", jcs(task).encode("utf-8"))] = (Slot(name, k, ()), task)
    return out


def write_blind_tasks(store: Any, packet_key: str) -> list[tuple[str, dict[str, Any]]]:
    """Get the packet from ``store``, decide it again, and write its label tasks. Return each
    task key with its task. Raise ``ValueError`` before a write when the receipt does not match
    its inputs, or when the store has a task of the packet with another mode than ``audit``
    and a label task is new: the blind tasks come first (SPEC §4.20)."""
    from ..store import MAX_BYTES, check_bytes

    _, schema, _, problems = checked_packet(store, packet_key)
    if problems or schema is None:
        raise ValueError("the receipt does not match its inputs: " + "; ".join(problems))
    tasks = blind_tasks(packet_key, schema)
    stored = _stored_tasks(store, packet_key)
    if set(stored.values()) - {"audit"} and set(tasks) - set(stored):
        raise ValueError(
            "the store has review tasks of this packet: the blind tasks of a packet come "
            "before its review tasks"
        )
    limit = getattr(store, "max_bytes", MAX_BYTES)
    encoded = []
    for _, task in tasks.values():  # each check of put, before any write
        data = jcs(task).encode("utf-8")
        if len(data) > limit:
            raise ValueError("a task@1 object is larger than max_bytes")
        check_bytes("task@1", data)
        encoded.append((data, task))
    return [(store.put("task@1", data), task) for data, task in encoded]
