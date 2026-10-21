"""The measures of the review step (docs/design/review.md §10).

``measures`` reads each answer log of a store, resolves each packet with ``resolve`` and gives
these measures for each item kind, and for each field in that kind:

- ``answers``: the number of answers. Each measure uses the latest answer of each reviewer to
  each task (§6.1 rule 1).
- ``ms_median``: the median time for each item, from ``ms``.
- ``one_key``: the answers given with one key, from ``keys``, and ``answers``.
- ``agreement``: the pairs that agree, and the pairs. A pair is an answer and a blind label of
  another reviewer on the same task, and two blind labels on one task make one pair. A blind
  label is an answer to an audit task with ``reason_seen`` false (§10 point 1). Two answers
  agree under §6.1 rule 4. An ``unsure`` answer, and a correction that does not count, are in
  no pair.
- ``escapes``: the audit slots that resolve to a value other than the admitted value, or to
  ``not_in_document``, and the audit slots that an answer settles (§6.1 rule 7).

The kinds ``text`` and ``span`` also give ``span_moved``, the ``adjust_span`` answers and
``answers``, and ``span_move_median``, the median of the characters that the two ends of a
counted ``adjust_span`` answer move from the nearest choice. The measures never put two kinds
in one number.

The answer logs and the store objects are untrusted input. A packet whose receipt does not
match its inputs, or whose answers break their tasks, is left out, and ``skipped`` names it.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..model import PacketError
from .resolve import Seen, resolve
from .tasks import DEFAULT_POLICY, check_policy, checked_packet

__all__ = ["Measured", "lines", "measures"]

_SPANS = frozenset({"text", "span"})
_SETTLES = frozenset({"admitted", "confirmed", "chosen", "corrected", "not_in_document"})


@dataclass
class _Tally:
    ms: list[int] = field(default_factory=list)
    one_key: int = 0
    agree: int = 0
    pairs: int = 0
    escapes: int = 0
    audited: int = 0
    moved: int = 0
    moves: list[int] = field(default_factory=list)

    def out(self, item: str) -> dict[str, Any]:
        n = len(self.ms)
        found: dict[str, Any] = {
            "answers": n,
            "ms_median": _median(self.ms),
            "one_key": [self.one_key, n],
            "agreement": [self.agree, self.pairs],
            "escapes": [self.escapes, self.audited],
        }
        if item in _SPANS:
            found["span_moved"] = [self.moved, n]
            found["span_move_median"] = _median(self.moves)
        return found


@dataclass(frozen=True)
class Measured:
    """The result of ``measures``. ``kinds`` maps each item kind to its measures, and its
    member ``fields`` maps each field to the same measures. ``packets`` is the number of
    packets measured. ``skipped`` has one line for each packet that is left out. With a split,
    ``other_split`` counts the packets of a document in another split, and ``no_split`` the
    packets of a document that the ``splits`` log does not name."""

    kinds: dict[str, dict[str, Any]]
    packets: int
    skipped: tuple[str, ...] = ()
    other_split: int = 0
    no_split: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kinds": self.kinds,
            "packets": self.packets,
            "skipped": list(self.skipped),
            "other_split": self.other_split,
            "no_split": self.no_split,
        }


def _median(values: Sequence[int]) -> int | float | None:
    if not values:
        return None
    m = statistics.median(values)
    return int(m) if m == int(m) else m


def _printable(value: object) -> str:
    text = value if isinstance(value, str) else repr(value)
    text = "".join(c if c.isprintable() else f"\\u{ord(c):04x}" for c in text)
    return text if len(text) <= 200 else text[:197] + "..."


def _document(store: Any, packet: Any) -> str:
    """The document key of a packet for the ``splits`` log: the source key of its reading, or
    the text key when there is no reading (store.md §10)."""
    from ..store import key
    from ..store.packets import load_reading

    if packet.reading is not None:
        return str(load_reading(store, packet.reading)["source"])
    return key("text@1", packet.text.encode("utf-8"))


def _logs(store: Any) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], list[str]]:
    """The answer logs of the store by packet and reviewer name, and a line for each log that
    is left out. The name in the first record must give the digest of the log name."""
    from ..store import StoreError, reviewer_key

    names, _ = store.log_names()
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    skipped: list[str] = []
    for log in names:
        if log[0] != "answers":
            continue
        try:
            records = store.read(log)
        except StoreError as exc:
            skipped.append(f"answer log {log[1]} {log[2]}: {_printable(str(exc))}")
            continue
        if not records:
            continue
        name = records[0].get("reviewer")
        if not isinstance(name, str) or reviewer_key(name) != log[2]:
            skipped.append(f"answer log {log[1]} {log[2]}: the reviewer is not the log name")
            continue
        out.setdefault(log[1], {})[name] = records
    return out, skipped


def measures(
    store: Any,
    policy: Mapping[str, Any] | None = None,
    *,
    set_name: str | None = None,
    split: str | None = None,
) -> Measured:
    """The measures of §10 over each answer log of ``store``, a ``FolderStore``. ``policy``
    sets ``agree`` and ``leads`` for the resolution of each packet; without it, the default
    policy of ``review tasks`` applies. With ``set_name`` and ``split``, only the packets of a
    document in that split of the set count. The result counts the packets of the other
    documents, and the split check comes before the receipt check."""
    from ..store import StoreError
    from ..store.packets import load_packet
    from ..store.splits import read_split

    checked = check_policy(DEFAULT_POLICY if policy is None else policy)
    if (set_name is None) != (split is None):
        raise ValueError("give the set and the split together")
    splits = read_split(store, set_name) if set_name is not None else None
    logs, skipped = _logs(store)
    tallies: dict[str, _Tally] = {}
    by_field: dict[str, dict[str, _Tally]] = {}
    packets = other_split = no_split = 0
    for pk in sorted(logs):
        seen: list[Seen] = []
        try:
            if splits is not None:
                named = splits.get(_document(store, load_packet(store, pk)))
                if named != split:
                    other_split += named is not None
                    no_split += named is None
                    continue
            packet, schema, layout, problems = checked_packet(store, pk)
            if problems or schema is None:
                skipped.append(f"packet {pk}: the receipt does not match its inputs")
                continue
            resolution, _ = resolve(pk, packet, schema, checked, logs[pk], layout=layout,
                                    seen=seen)  # fmt: skip
        except (PacketError, StoreError, ValueError) as exc:  # untrusted input: name it
            skipped.append(f"packet {pk}: {_printable(str(exc))}")
            continue
        packets += 1
        _count(seen, resolution, packet.receipt["decisions"], tallies, by_field)
    kinds = {}
    for item in sorted(tallies):
        found = tallies[item].out(item)
        found["fields"] = {f: t.out(item) for f, t in sorted(by_field[item].items())}
        kinds[item] = found
    return Measured(kinds, packets, tuple(skipped), other_split, no_split)


def _count(
    seen: Sequence[Seen],
    resolution: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
    tallies: dict[str, _Tally],
    by_field: dict[str, dict[str, _Tally]],
) -> None:
    """Add the answers and the audit slots of one packet to the tallies."""
    latest: dict[str, dict[str, Seen]] = {}  # task key -> reviewer -> latest answer
    for s in seen:
        latest.setdefault(s.task_key, {})[s.reviewer] = s
    for answers in latest.values():
        blind = [
            s for s in answers.values()
            if s.task["mode"] == "audit" and s.record["reason_seen"] is False
            and s.answer.target is not None
        ]  # fmt: skip
        for s in answers.values():
            item, name = s.task["item"], s.task["slot"]["field"]
            for t in (tallies.setdefault(item, _Tally()),
                      by_field.setdefault(item, {}).setdefault(name, _Tally())):  # fmt: skip
                t.ms.append(s.record["ms"])
                t.one_key += s.record["keys"] == 1
                if s.answer.target is not None:
                    for b in blind:  # two blind labels make one pair, not two
                        if b.reviewer != s.reviewer and (s not in blind or s.reviewer < b.reviewer):
                            t.pairs += 1
                            t.agree += b.answer.target == s.answer.target
                if item in _SPANS and s.answer.verdict == "adjust_span":
                    t.moved += 1
                    move = _move(s)
                    if move is not None:
                        t.moves.append(move)
    for slot in resolution["slots"]:
        tk = slot["task"]
        answers = latest.get(tk, {}) if tk is not None else {}
        if not answers:
            continue
        task = next(iter(answers.values())).task
        if task["mode"] != "audit" or slot["status"] not in _SETTLES:
            continue
        if all(s.answer.target is None for s in answers.values()):
            continue  # only unsure answers: no one checked the value
        admitted = decisions[task["choices"][0]["decision"]]
        escape = slot["status"] == "not_in_document" or (
            slot["value"], slot["unit"]) != (admitted["value"], admitted.get("unit"))  # fmt: skip
        item = task["item"]
        for t in (tallies[item], by_field[item][slot["field"]]):
            t.audited += 1
            t.escapes += escape


def _move(s: Seen) -> int | None:
    """The characters that the two ends of a counted ``adjust_span`` answer move from the
    nearest choice, or None when the answer does not count."""
    target = s.answer.target
    if target is None:
        return None
    _, _, start, end = target
    if type(start) is not int or type(end) is not int:
        return None
    moves = [
        abs(start - c["evidence"]["start"]) + abs(end - c["evidence"]["end"])
        for c in s.task["choices"]
        if isinstance(c.get("evidence"), Mapping)
    ]
    return min(moves) if moves else None


def _ratio(pair: Sequence[int]) -> str:
    return f"{pair[0]} of {pair[1]}"


def lines(measured: Measured) -> list[str]:
    """One line for each kind, then one line for each field of that kind. A field name comes
    from the schema, so each control character shows as an escape."""

    def line(name: str, m: Mapping[str, Any]) -> str:
        ms = "none" if m["ms_median"] is None else f"{m['ms_median']} ms"
        parts = [
            f"answers {m['answers']}",
            f"median time {ms}",
            f"one key {_ratio(m['one_key'])}",
            f"agreement with blind labels {_ratio(m['agreement'])}",
            f"escapes {_ratio(m['escapes'])} audit slots",
        ]
        if "span_moved" in m:
            move = m["span_move_median"]
            parts.append(f"span moved {_ratio(m['span_moved'])}")
            parts.append("median move " + ("none" if move is None else f"{move} characters"))
        return _printable(name) + ": " + ", ".join(parts)

    out = [f"packets: {measured.packets}"]
    if measured.other_split or measured.no_split:
        out[0] += (
            f", left out: {measured.other_split} in another split, {measured.no_split} not in "
            "the splits log"
        )
    for item, m in measured.kinds.items():
        out.append(line(item, m))
        for f, fm in m["fields"].items():
            out.append("  " + line(f"{item} {f}", fm))
    return out
