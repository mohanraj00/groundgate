"""The resolution of one packet (docs/design/review.md §5.4, §6).

``resolve`` is a pure function of the packet, the review policy, the tasks and the answer logs.
It reads no clock and calls no model, so the same inputs give the same bytes. It runs ``admit``
one time for each ``correct`` or ``adjust_span`` answer (§6.2). ``write_resolution`` gets the
packet and the answer logs from a store, decides the packet again with ``verify``, keeps each
correction as a packet in the store, and writes the ``resolution@1`` object.

The answer logs are untrusted input. An answer that breaks its task stops the resolution with
``AnswerError``, which names the reviewer and the sequence of the record (§6.3 point 5).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..canonical import digest, jcs
from ..codes import INFO
from ..model import PacketError, Schema
from ..read.layout import Layout
from .tasks import DEFAULT_POLICY, Slot, check_policy, checked_packet, make_tasks, slots

__all__ = [
    "AnswerError",
    "Resolved",
    "Seen",
    "lines",
    "resolve",
    "write_resolution",
]

# Each slot that a rule of §5.2 can select gets a task. The receipt sets the mode of each task,
# so this policy gives the task of each slot under any policy (§6.3 point 1).
EVERY_TASK: dict[str, Any] = {
    **DEFAULT_POLICY,
    "audit": {"rate": "1", "seed": ""},
    "rejected": True,
}

CORRECTIONS = frozenset({"correct", "adjust_span"})
VERDICTS = frozenset({"confirm", "choose", "not_in_document", "unsure"}) | CORRECTIONS
_MEMBERS = frozenset(
    {
        "format", "task", "reviewer", "verdict", "decision", "candidate", "codes_kept",
        "statements", "nodes", "reason_seen", "keys", "ms", "time",
        "sequence", "previous", "entry_sha256",
    }
)  # fmt: skip
# The members of an answer before the store adds the chain members (review serve checks this).
ANSWER_MEMBERS = _MEMBERS - {"sequence", "previous", "entry_sha256"}
_REASONS = {
    "not_in_document": "a reviewer says that the document does not give it",
    "rejected": "the gate rejected each candidate, and the review policy makes no task",
    "open": "no answer settles the task yet",
    "disputed": "the reviewers do not agree",
}

# The correction call: the candidates and the judgments in, the receipt and its store key out.
Correct = Callable[[list[Any], list[Any] | None], tuple[dict[str, Any], str]]


class AnswerError(ValueError):
    """An answer breaks its task (§6.3 point 5). ``reviewer`` and ``sequence`` name the record."""

    def __init__(self, reviewer: str, sequence: object, message: str) -> None:
        self.reviewer = reviewer
        self.sequence = sequence
        self.reason = _escape(message)  # the message without the reviewer and the sequence
        # The message can quote an error of admit about the candidate: escape it too.
        super().__init__(
            f"answer {_printable(sequence)} of the reviewer {_printable(reviewer)}: "
            + _escape(message)
        )


def _escape(text: str) -> str:
    """``text`` with each control character as an escape."""
    return "".join(c if c.isprintable() else f"\\u{ord(c):04x}" for c in text)


def _printable(value: object) -> str:
    """A value from the store as text with no control character, for a message."""
    text = _escape(value if isinstance(value, str) else repr(value))
    return text if len(text) <= 200 else text[:197] + "..."


@dataclass(frozen=True)
class _Correction:
    receipt: str  # the store key of the correction receipt
    decision: dict[str, Any]  # the decision of the person's candidate
    counts: bool  # §6.2 rules 1 to 3


@dataclass(frozen=True)
class _Answer:
    reviewer: str
    verdict: str
    target: tuple[Any, ...] | None  # None: no answer (unsure, or a correction that does not count)
    keeps: bool  # an audit answer that keeps the admitted value: unsure, or a confirm
    decision: int | None = None
    correction: _Correction | None = None


@dataclass(frozen=True)
class _Checked:
    """A record that passed each check of its task. A correction has not run ``admit`` yet."""

    name: str
    sequence: object
    task_key: str
    slot: Slot
    task: dict[str, Any]
    answer: _Answer | None  # None for a correction
    verdict: str = ""
    candidate: Mapping[str, Any] | None = None
    kept: tuple[str, ...] = ()
    memo: tuple[str, str] = ("", "")


@dataclass(frozen=True)
class Seen:
    """One answer record that ``resolve`` checked and read: the reviewer, the record, the key
    and the task of the record, and what the answer counts as under §6.1."""

    reviewer: str
    record: Mapping[str, Any]
    task_key: str
    task: dict[str, Any]
    answer: _Answer


def _store_key(kind: str, value: Any) -> str:
    from ..store import key

    return key(kind, jcs(value).encode("utf-8"))


def _key(slot_key: object, field: Any) -> str | None:
    """The key of a slot as ``slots`` gives it: null for a field without keys."""
    return slot_key if isinstance(slot_key, str) and field.keys is not None else None


def resolve(
    packet_key: str,
    packet: Any,
    schema: Schema,
    policy: Mapping[str, Any],
    logs: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    layout: Layout | None = None,
    correct: Correct | None = None,
    seen: list[Seen] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The ``resolution@1`` object of the packet, and each task that it names by key.

    ``packet`` is a ``groundgate.store.packets.Packet`` whose receipt matches its inputs, and
    ``schema`` is its schema. ``logs`` maps each reviewer name to the records of its answer
    log, in log order. ``correct`` runs ``admit`` for a correction and gives the receipt and
    its store key. Without it, ``resolve`` runs ``admit`` and keeps nothing. If ``seen`` is a
    list, ``resolve`` adds a ``Seen`` for each record, in code point order of the reviewer
    name and then in log order (``review measures`` reads them).
    """
    policy = check_policy(policy)
    receipt = packet.receipt
    decisions = receipt["decisions"]
    run = correct or _admit_only(packet)
    texts = {"references": packet.references, "layout": layout}
    every = make_tasks(packet_key, receipt, packet.text, schema, EVERY_TASK, **texts)
    made = {
        _store_key("task@1", t)
        for t in make_tasks(packet_key, receipt, packet.text, schema, policy, **texts)
    }
    by_slot: dict[tuple[str, str | None, tuple[int, ...]], tuple[str, dict[str, Any]]] = {}
    by_key: dict[str, tuple[Slot, dict[str, Any]]] = {}
    all_slots = slots(receipt, schema)
    for t in every:
        s = t["slot"]
        by_slot[s["field"], s["key"], tuple(s["decisions"])] = (_store_key("task@1", t), t)
    for slot in all_slots:
        found = by_slot.get((slot.field, slot.key, slot.decisions))
        if found is not None:
            by_key[found[0]] = (slot, found[1])

    ids = [c.get("id") for c in packet.candidates if isinstance(c, Mapping)]
    latest: dict[str, dict[str, _Answer]] = {}  # task key -> reviewer -> latest answer
    answered: set[str] = set()
    heads = []
    cache: dict[tuple[str, str], _Correction] = {}
    checked = []
    for name in sorted(logs):  # check each record before the first call to admit
        records = logs[name]
        checked += [(r, _check(name, r, by_key, schema, ids)) for r in records]
        if records:
            heads.append({"reviewer": name, "head": records[-1]["entry_sha256"]})
    for record, c in checked:
        answer = c.answer or _read(c, schema, packet, decisions, run, cache)
        answered.add(c.task_key)
        latest.setdefault(c.task_key, {})[c.name] = answer
        if seen is not None:
            seen.append(Seen(c.name, record, c.task_key, c.task, answer))

    out_slots = []
    named: dict[str, dict[str, Any]] = {}
    packet_receipt = _store_key("receipt@1", receipt)
    for slot in all_slots:
        found = by_slot.get((slot.field, slot.key, slot.decisions))
        tkey: str | None = None
        task: dict[str, Any] | None = None
        if found is not None and (found[0] in made or found[0] in answered):
            tkey, task = found
            named[tkey] = task
        answers = latest.get(tkey, {}) if tkey is not None else {}
        status, source = _settle(slot, decisions, task, answers, policy)
        value: dict[str, Any] = {"value": None, "unit": None, "evidence": None}
        rkey = packet_receipt
        if isinstance(source, _Correction):
            value = _value(source.decision)
            rkey = source.receipt
        elif isinstance(source, int):
            value = _value(decisions[source])
        out_slots.append(
            {"field": slot.field, "key": slot.key, "decisions": list(slot.decisions),
             "status": status, **value, "receipt": rkey, "task": tkey,
             "statements": None, "nodes": None}
        )  # fmt: skip
    resolution = {
        "format": "resolution@1",
        "packet": packet_key,
        "policy": _store_key("review-policy@1", policy),
        "answers": heads,
        "slots": out_slots,
    }
    return resolution, named


def _value(d: Mapping[str, Any]) -> dict[str, Any]:
    evidence = d.get("evidence")
    return {
        "value": d["value"],
        "unit": d.get("unit"),
        "evidence": None
        if evidence is None
        else {"start": evidence["start"], "end": evidence["end"]},
    }


def _settle(
    slot: Slot,
    decisions: Sequence[Mapping[str, Any]],
    task: Mapping[str, Any] | None,
    answers: Mapping[str, _Answer],
    policy: Mapping[str, Any],
) -> tuple[str, int | _Correction | None]:
    """The status of a slot, and the source of its value: a decision index of the packet, a
    correction, or None (§6.1)."""
    passed = [i for i in slot.decisions if decisions[i]["outcome"] != "rejected"]
    if task is None:
        if not passed:
            return "rejected", None
        return "admitted", passed[0]
    audit = task["mode"] == "audit"
    if audit and all(a.keeps for a in answers.values()):  # rule 7
        return "admitted", passed[0]
    counted = {r: a for r, a in answers.items() if a.target is not None}  # rule 2, §6.3 point 7
    targets = {a.target for a in counted.values()}
    if not targets:
        return "open", None
    if len(targets) == 1:
        if len(counted) < policy["agree"]:  # rule 5
            return "open", None
        (target,) = targets
    else:  # rule 6
        leads = {counted[r].target for r in policy["leads"] if r in counted}
        if len(leads) != 1:
            return "disputed", None
        (target,) = leads
    first = next(a for r, a in sorted(counted.items()) if a.target == target)  # §6.3 point 6
    if first.verdict in CORRECTIONS:
        return "corrected", first.correction
    if first.verdict == "not_in_document":
        return "not_in_document", None
    if audit:  # §6.3 point 3
        return "admitted", first.decision
    return ("confirmed" if len(task["choices"]) == 1 else "chosen"), first.decision


def _check(
    name: str,
    record: Mapping[str, Any],
    by_key: Mapping[str, tuple[Slot, dict[str, Any]]],
    schema: Schema,
    ids: Sequence[object],
    members: frozenset[str] = _MEMBERS,
) -> _Checked:
    """Check one record of the answer log of ``name`` against its task. Read each answer that
    is not a correction. ``members`` are the members that the record must have."""
    sequence = record.get("sequence") if isinstance(record, Mapping) else None

    def fail(message: str) -> AnswerError:
        return AnswerError(name, sequence, message)

    if not isinstance(record, Mapping) or set(record) != members:
        raise fail("the record does not have the members of answer@1")
    if record["format"] != "answer@1":
        raise fail("the record format is not answer@1")
    if record["reviewer"] != name:
        raise fail("the record names another reviewer than its log")
    task_key = record["task"]
    if not isinstance(task_key, str) or task_key not in by_key:
        raise fail("the task is not a task of a slot of this packet")
    slot, task = by_key[task_key]
    verdict = record["verdict"]
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        raise fail("the verdict is not an answer@1 verdict")
    if record["statements"] is not None or record["nodes"] is not None:
        raise fail("statements and nodes must be null in format 1")
    kept = record["codes_kept"]
    if not isinstance(kept, list) or not all(isinstance(c, str) for c in kept):
        raise fail("codes_kept is not a list of codes")
    if len(set(kept)) != len(kept):
        raise fail("codes_kept names a code two times")
    if kept and verdict not in CORRECTIONS:
        raise fail("only a correction keeps codes")
    for name_ in ("keys", "ms"):
        if type(record[name_]) is not int or record[name_] < 0:
            raise fail(f"{name_} is not an integer of 0 or more")
    if not isinstance(record["reason_seen"], bool) or not isinstance(record["time"], str):
        raise fail("reason_seen or time has the wrong type")
    choices = [c["decision"] for c in task["choices"]]
    decision = record["decision"]
    if verdict == "choose":
        if type(decision) is not int or decision not in choices:
            raise fail("the decision is not a choice of the task")
    elif decision is not None:
        raise fail(f"a {verdict} answer has no decision")
    if verdict not in CORRECTIONS and record["candidate"] is not None:
        raise fail(f"a {verdict} answer has no candidate")
    found = slot, task
    if verdict == "unsure":
        return _Checked(name, sequence, task_key, *found, _Answer(name, verdict, None, True))
    if verdict == "not_in_document":
        target = ("not_in_document",)
        return _Checked(name, sequence, task_key, *found, _Answer(name, verdict, target, False))
    if verdict == "confirm":
        if len(choices) != 1:  # rule 3
            raise fail("confirm needs a task with exactly one choice")
        decision = choices[0]
        verdict = "choose"
    if verdict == "choose":
        one = len(choices) == 1
        answer = _Answer(name, verdict, ("choose", decision), one, decision)
        return _Checked(name, sequence, task_key, *found, answer)

    candidate = record["candidate"]
    if not isinstance(candidate, Mapping):
        raise fail(f"a {verdict} answer needs a candidate")
    cid = candidate.get("id")
    if not isinstance(cid, str) or not cid.strip():
        raise fail("the candidate id is not a string")
    if cid in ids:  # #410: the correction call to admit would be invalid
        raise fail("the candidate id is the id of a candidate of the packet")
    proposer = candidate.get("proposer")
    if not isinstance(proposer, str) or not proposer.startswith("person:"):
        raise fail("the candidate proposer does not start with person:")
    field = schema.fields[slot.field]
    if candidate.get("field") != slot.field or _key(candidate.get("key"), field) != slot.key:
        raise fail("the candidate is for another field or key than the slot")
    if field.keys is None and candidate.get("key") is not None:
        raise fail("the candidate has a key, and the field has no keys")
    try:
        memo = (task_key, jcs(candidate))
    except (TypeError, ValueError, RecursionError) as exc:
        raise fail(f"the candidate has no canonical JSON form: {exc}") from exc
    return _Checked(name, sequence, task_key, *found, None, verdict, candidate, tuple(kept), memo)


def _read(
    c: _Checked,
    schema: Schema,
    packet: Any,
    decisions: Sequence[Mapping[str, Any]],
    run: Correct,
    cache: dict[tuple[str, str], _Correction],
) -> _Answer:
    """Run ``admit`` for a checked correction (§6.2), and read its decision."""
    slot, task, verdict, kept = c.slot, c.task, c.verdict, c.kept
    assert c.candidate is not None

    def fail(message: str) -> AnswerError:
        return AnswerError(c.name, c.sequence, message)

    field = schema.fields[slot.field]
    if c.memo not in cache:
        cache[c.memo] = _correct(slot, c.candidate, packet, decisions, run, fail)
    correction = cache[c.memo]
    found = correction.decision
    if found["outcome"] != "rejected" and (
        found.get("field") != slot.field or _key(found.get("key"), field) != slot.key
    ):
        raise fail("the gate gives the candidate another field or key than the slot")
    counts = correction.counts and (
        found["outcome"] == "admitted" or set(found["codes"]) - set(INFO) <= set(kept)
    )
    target: tuple[Any, ...] | None = None
    if counts:
        if task["item"] == "number":  # rule 4
            target = (verdict, found["value"], found.get("unit"), slot.key)
        else:
            span = found.get("evidence") or {}
            target = (verdict, found.get("ref"), span.get("start"), span.get("end"))
    return _Answer(c.name, verdict, target, False, None, correction)


def _correct(
    slot: Slot,
    candidate: Mapping[str, Any],
    packet: Any,
    decisions: Sequence[Mapping[str, Any]],
    run: Correct,
    fail: Callable[[str], AnswerError],
) -> _Correction:
    """Run ``admit`` for a correction (§6.2): the candidates of the packet without those of the
    slot and with the person's candidate, and the judgments without those of the removed
    candidates."""
    removed = {decisions[i]["candidate_sha256"] for i in slot.decisions}
    kept, gone = [], set()
    for c in packet.candidates:
        if digest("candidate", c) in removed:
            if isinstance(c, Mapping) and type(c.get("id")) in (str, int):
                gone.add(c["id"])
        else:
            kept.append(c)
    judgments = packet.judgments
    if judgments is not None:
        judgments = [
            j for j in judgments
            if not (isinstance(j, Mapping) and type(j.get("candidate_id")) in (str, int)
                    and j["candidate_id"] in gone)
        ]  # fmt: skip
    try:
        receipt, rkey = run([*kept, dict(candidate)], judgments)
    except PacketError as exc:
        raise fail(f"the correction call to admit is invalid: {exc}") from exc
    mine = [d for d in receipt["decisions"] if d["candidate_id"] == candidate["id"]]
    if len(mine) != 1:
        raise fail("the correction receipt has no one decision for the candidate")
    d = mine[0]
    return _Correction(rkey, d, d["outcome"] != "rejected")


def _admit_only(packet: Any) -> Correct:
    from ..admit import admit

    def run(candidates: list[Any], judgments: list[Any] | None) -> tuple[dict[str, Any], str]:
        receipt = admit(
            packet.text,
            packet.schema,
            candidates,
            packet.policy,
            packet.receipt["document"]["id"],
            judgments,
            references=packet.references,
            document_source=packet.document_source,
            packs=packet.packs,
        ).to_dict()
        return receipt, _store_key("receipt@1", receipt)

    return run


# The store


@dataclass(frozen=True)
class Resolved:
    """The result of ``write_resolution``. ``problems`` is not empty when the receipt of the
    packet does not match its inputs: then ``key`` and ``resolution`` are None, and the store
    has no new object."""

    key: str | None
    resolution: dict[str, Any] | None
    problems: tuple[str, ...] = ()


def write_resolution(
    store: Any,
    packet_key: str,
    policy: Mapping[str, Any] | None = None,
    reviewers: Sequence[str] = (),
) -> Resolved:
    """Get the packet ``packet_key`` and the answer log of each reviewer in ``reviewers`` from
    ``store``, decide the packet again, and resolve it. Check each answer before the first
    correction runs. Only after the resolution succeeds, keep each correction as a packet in the
    store, and write the review policy, each task that the resolution names and the
    ``resolution@1`` object. An answer that breaks its task writes nothing. Without
    ``policy``, the default policy of ``review tasks`` applies.
    A log with no record adds nothing."""
    from ..store import reviewer_key
    from ..store.packets import admit_packet

    checked = check_policy(DEFAULT_POLICY if policy is None else policy)
    for name in reviewers:
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                "a reviewer name must be a string with a character that is not a space"
            )
    packet, schema, layout, problems = checked_packet(store, packet_key)
    if problems or schema is None:
        return Resolved(None, None, problems)
    logs = {
        name: store.read(("answers", packet_key, reviewer_key(name))) for name in set(reviewers)
    }

    pure = _admit_only(packet)
    corrections: list[tuple[list[Any], list[Any] | None, str]] = []

    def run(candidates: list[Any], judgments: list[Any] | None) -> tuple[dict[str, Any], str]:
        receipt, rkey = pure(candidates, judgments)
        corrections.append((candidates, judgments, rkey))
        return receipt, rkey

    resolution, tasks = resolve(
        packet_key, packet, schema, checked, logs, layout=layout, correct=run
    )
    for candidates, judgments, rkey in corrections:  # only after the resolution succeeds
        _, receipt = admit_packet(
            store,
            packet.text,
            packet.schema,
            candidates,
            packet.policy,
            packet.receipt["document"]["id"],
            judgments,
            references=packet.references,
            document_source=packet.document_source,
            packs=packet.packs,
            reading=packet.reading,
        )
        if _store_key("receipt@1", receipt.to_dict()) != rkey:
            raise PacketError("a correction gave another receipt in the store")
    for task in tasks.values():
        store.put("task@1", jcs(task).encode("utf-8"))
    store.put("review-policy@1", jcs(checked).encode("utf-8"))
    k = store.put("resolution@1", jcs(resolution).encode("utf-8"))
    return Resolved(k, resolution)


def lines(resolution: Mapping[str, Any]) -> list[str]:
    """One line for each slot: the final value, or the reason that there is none. A line can
    quote a value or a key from the document, so each control character shows as an escape."""
    seen: dict[tuple[str, str | None], int] = {}
    for s in resolution["slots"]:
        seen[s["field"], s["key"]] = seen.get((s["field"], s["key"]), 0) + 1
    out = []
    for s in resolution["slots"]:
        name = s["field"] if s["key"] is None else f"{s['field']} [{s['key']}]"
        if seen[s["field"], s["key"]] > 1:
            name += " #" + ",".join(str(i) for i in s["decisions"])
        if s["value"] is None:
            out.append(f"{name}: no value ({s['status']}: {_REASONS[s['status']]})")
        else:
            unit = "" if s["unit"] is None else f" {s['unit']}"
            out.append(f"{name}: {s['value']}{unit} ({s['status']})")
    return ["".join(c if c.isprintable() else f"\\u{ord(c):04x}" for c in line) for line in out]
