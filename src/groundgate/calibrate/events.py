"""Calibration events from an outside approver (SPEC §4.19, #642).

An approver outside groundgate sees the exported facts (SPEC §5.1, §5.2) and approves, rejects
or corrects each one. ``check_event`` checks one event of format 1. ``add`` writes new events
to the ``events`` log of their profile digest, through the ``append`` operation of the store
contract. ``suggest`` reads the events of one profile version and proposes drafts: a review
share for each field, a changed-value test for each rejection and correction, and a new term
from a correction. A person or a policy accepts or refuses each draft.

An event is a suggestion only. The approver saw the proposed value, so no event is a label, and
the measure (``measure.py``) and the audit (``audit.py``) never read the events log.
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from groundgate.canonical import digest, jcs
from groundgate.model import PacketError
from groundgate.pack import _no_twice
from groundgate.profile import check_profile, load_profile
from groundgate.store import CHAIN, Store, StoreError

from .audit import _day, _digest
from .measure import MeasureError, _read_bytes

__all__ = [
    "EventError",
    "add",
    "check_event",
    "counted",
    "fact_sha256",
    "read_events",
    "suggest",
]

FORMAT = 1
DRAFTS_FORMAT = 1
MAX_EVENT = 64 << 10  # bytes of one event as canonical JSON
MAX_LABEL = 64  # characters of a proposed term
DECISIONS = ("approve", "reject", "correct")
ACTORS = ("person", "program")
_EVENT = frozenset(
    {"groundgate_calibration_event", "decision", "profile", "packet_sha256", "receipt_sha256",
     "fact_sha256", "field", "key", "value", "corrected", "actor", "origin", "date"}
)  # fmt: skip


class EventError(MeasureError):
    """An event, an events file or an events log is not valid."""


def fact_sha256(fact: Mapping[str, Any]) -> str:
    """The ``fact_sha256`` of an event: the digest of kind ``fact`` over the fact object of an
    export, as it is (SPEC §4.19)."""
    return digest("fact", dict(fact))


def _text(v: object, limit: int) -> bool:
    return (
        isinstance(v, str)
        and 0 < len(v) <= limit
        and bool(v.strip())
        and unicodedata.is_normalized("NFC", v)
    )


def _scalars(v: str) -> bool:
    """True if ``v`` holds only Unicode scalar values: no lone surrogate."""
    return not any("\ud800" <= ch <= "\udfff" for ch in v)


def check_event(obj: object) -> dict[str, Any]:
    """An event of format 1 (SPEC §4.19), or ``EventError``. The format is closed, so an audit
    label or a review answer is not an event."""
    if not isinstance(obj, dict) or set(obj) != _EVENT:
        raise EventError("an event must be an object with the members of format 1 only")
    fmt, decision = obj["groundgate_calibration_event"], obj["decision"]
    corrected, origin = obj["corrected"], obj["origin"]
    ok = (
        isinstance(fmt, int)
        and not isinstance(fmt, bool)
        and fmt == FORMAT
        and decision in DECISIONS
        and all(_digest(obj[m]) for m in ("profile", "packet_sha256", "receipt_sha256"))
        and _digest(obj["fact_sha256"])
        and isinstance(obj["field"], str)
        and bool(obj["field"])
        and (obj["key"] is None or (isinstance(obj["key"], str) and bool(obj["key"])))
        and isinstance(obj["value"], str)
        and (
            (isinstance(corrected, str) and corrected != obj["value"])
            if decision == "correct"
            else corrected is None
        )
        and obj["actor"] in ACTORS
        and isinstance(origin, dict)
        and set(origin) == {"system", "id"}
        and _text(origin["system"], 128)
        and _text(origin["id"], 256)
        and _day(obj["date"])
    )
    if not ok:
        raise EventError("an event has a member with a wrong form")
    if not all(_scalars(v) for v in (*obj.values(), *origin.values()) if isinstance(v, str)):
        # A lone surrogate has no UTF-8 form, so a later write of the drafts would fail.
        raise EventError("an event has a string with a lone surrogate")
    try:
        size = len(jcs(obj).encode("utf-8"))
    except (PacketError, TypeError, ValueError, RecursionError) as exc:
        raise EventError(f"an event has no canonical JSON form: {exc}") from None
    if size > MAX_EVENT:
        raise EventError(f"an event is more than {MAX_EVENT} bytes as canonical JSON")
    return dict(obj)


def _origin(event: Mapping[str, Any]) -> tuple[str, str]:
    return event["origin"]["system"], event["origin"]["id"]


def counted(profile: str, records: Iterable[object]) -> list[dict[str, Any]]:
    """The events of the events log of ``profile`` that count, in log order (SPEC §4.19).
    ``records`` are the records of the log, with or without the chain members of the store. A
    record that is not an event of ``profile`` raises ``EventError``. A later event with the
    origin of an earlier one is a copy, and it does not count."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for n, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise EventError(f"the events log of {profile}: record {n} is not an event")
        body = {m: v for m, v in record.items() if m not in CHAIN}
        try:
            event = check_event(body)
        except EventError as exc:
            raise EventError(f"the events log of {profile}: record {n}: {exc}") from None
        if event["profile"] != profile:
            raise EventError(f"the events log of {profile}: record {n} is of another profile")
        if _origin(event) not in seen:
            seen.add(_origin(event))
            out.append(event)
    return out


def read_events(store: Store, profile: str) -> list[dict[str, Any]]:
    """The events of ``profile`` that count, from its events log in ``store``."""
    try:
        return counted(profile, store.read(("events", profile)))
    except (StoreError, ValueError) as exc:
        if isinstance(exc, EventError):
            raise
        raise EventError(f"the events log of {profile}: {exc}") from None


def read_file(path: Path) -> list[dict[str, Any]]:
    """The events of an events file: one JSON event on each line, in file order. An empty
    line is not permitted."""
    try:
        text = _read_bytes(path).decode("utf-8")
    except UnicodeDecodeError:
        raise EventError(f"{path} is not UTF-8") from None
    if text and not text.endswith("\n"):
        raise EventError(f"{path}: the last line has no line break")
    out = []
    for n, line in enumerate(text.split("\n")[:-1], 1):
        try:
            obj = json.loads(line, object_pairs_hook=_no_twice, parse_constant=_no_constant)
        except (ValueError, RecursionError, PacketError) as exc:
            raise EventError(f"{path}: line {n} is not JSON: {exc}") from None
        try:
            out.append(check_event(obj))
        except EventError as exc:
            raise EventError(f"{path}: line {n}: {exc}") from None
    return out


def _no_constant(value: str) -> Any:
    raise ValueError(f"{value} is not a JSON number")


def add(store: Store, events: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """Append each event that is not a copy to the events log of its profile. Return the count
    of the new events and the count of the copies. ``add`` checks all events before it writes
    one. With a store that can take the lock of a log, as the folder store can, ``add`` takes it
    before it reads the log, so no other writer can add the same origin between the read and
    the append. With another store, a copy can get into the log, and the reader does not count
    it."""
    checked = [check_event(e) for e in events]
    by_profile: dict[str, list[dict[str, Any]]] = {}
    for e in checked:
        by_profile.setdefault(e["profile"], []).append(e)
    new = copies = 0
    for profile in sorted(by_profile):
        log = ("events", profile)
        take = getattr(store, "take", None)  # the folder store has it; the contract has not
        if take is not None:
            take(log)
        seen = {_origin(e) for e in read_events(store, profile)}
        for e in by_profile[profile]:
            if _origin(e) in seen:
                copies += 1
                continue
            seen.add(_origin(e))
            store.append(log, e)
            new += 1
    return new, copies


# ------------------------------------------------------------------------------ the drafts


def _share(wrong: int, total: int) -> str:
    """``wrong / total`` rounded up to two decimals, as ``0.67``."""
    hundredths = (100 * wrong + total - 1) // total
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def _is_word(ch: str) -> bool:
    return ch.isalnum()


def _found(line: str, value: str) -> int:
    """The position of the first occurrence of ``value`` in ``line`` with no letter or digit
    just before or after it, or -1."""
    start = line.find(value)
    while start >= 0:
        end = start + len(value)
        before = start > 0 and _is_word(line[start - 1])
        after = end < len(line) and _is_word(line[end])
        if not before and not after:
            return start
        start = line.find(value, start + 1)
    return -1


def _label(head: str) -> str | None:
    """The words before a value on its line, as a term: with no punctuation or space at the
    end, with a letter, and at most MAX_LABEL characters. Else ``None``."""
    end = len(head)
    while end > 0 and not (_is_word(head[end - 1]) or head[end - 1] == ")"):
        end -= 1
    label = " ".join(head[:end].split())
    if not label or len(label) > MAX_LABEL or not any(ch.isalpha() for ch in label):
        return None
    return label


def _term(text: str, value: str) -> tuple[str, int] | None:
    """The term and the line number (from 1) of the one line of ``text`` that holds ``value``,
    or ``None`` when no line or more than one line holds it."""
    if not value.strip():
        return None
    hits = []
    for n, line in enumerate(text.split("\n"), 1):
        at = _found(line, value)
        if at >= 0:
            hits.append((n, line[:at]))
    if len(hits) != 1:
        return None
    label = _label(hits[0][1])
    return None if label is None else (label, hits[0][0])


def suggest(store: Store, profile_obj: Mapping[str, Any]) -> dict[str, Any]:
    """The drafts from the events of one profile version (docs/calibrate.md). The drafts change
    nothing: a person or a policy accepts or refuses each one."""
    from groundgate.store.packets import load_packet

    profile = check_profile(profile_obj)
    events = read_events(store, profile.sha256)
    slots: dict[tuple[str, str], dict[str, int]] = {}
    for e in events:
        slot = (e["field"], "" if e["key"] is None else "\0" + e["key"])
        counts = slots.setdefault(slot, {"approve": 0, "reject": 0, "correct": 0})
        counts[e["decision"]] += 1
    drafts: list[dict[str, Any]] = []
    for (name, key), c in sorted(slots.items()):
        total, wrong = sum(c.values()), c["reject"] + c["correct"]
        drafts.append({
            "draft": "review_share", "field": name, "key": key[1:] if key else None,
            "approved": c["approve"], "rejected": c["reject"], "corrected": c["correct"],
            "share": _share(wrong, total),
        })  # fmt: skip
    for e in events:
        if e["decision"] == "approve":
            continue
        drafts.append({
            "draft": "value_test", "field": e["field"], "key": e["key"],
            "packet": e["packet_sha256"], "refuse": e["value"], "admit": e["corrected"],
            "origin": e["origin"],
        })  # fmt: skip
    missing: set[str] = set()
    terms: set[tuple[str, str]] = set()
    texts: dict[str, str] = {}
    for e in events:
        if e["decision"] != "correct":
            continue
        packet = e["packet_sha256"]
        if packet not in texts:
            try:
                texts[packet] = load_packet(store, packet).text
            except (StoreError, PacketError, ValueError):
                missing.add(packet)
                texts[packet] = ""
                continue
        found = _term(texts[packet], e["corrected"])
        spec = profile.schema.fields.get(e["field"])
        if found is None or spec is None:
            continue
        label, line = found
        known = {e["field"].casefold(), *(a.casefold() for a in spec.aliases or ())}
        if label.casefold() in known or (e["field"], label.casefold()) in terms:
            continue
        terms.add((e["field"], label.casefold()))
        drafts.append({
            "draft": "term", "field": e["field"], "alias": label, "packet": packet,
            "line": line, "origin": e["origin"],
        })  # fmt: skip
    return {
        "groundgate_profile_drafts": DRAFTS_FORMAT,
        "profile": profile.entry(),
        "events": len(events),
        "drafts": drafts,
        "missing_packets": sorted(missing),
    }


def add_parser(sub: Any) -> None:
    p = sub.add_parser("events", help="calibration events of an outside approver (SPEC 4.19)")
    steps = p.add_subparsers(dest="events_step", required=True)
    a = steps.add_parser("add", help="add the events of an events file to the store")
    a.add_argument("--events", type=Path, required=True, help="one JSON event on each line")
    s = steps.add_parser("suggest", help="propose draft changes of a profile from its events")
    s.add_argument("--profile", type=Path, required=True, help="the profile file")
    s.add_argument("--out", type=Path, help="write the drafts here instead of stdout")
    for step in (a, s):
        step.add_argument("--store", type=Path, metavar="DIR", required=True, help="the store")


def main(args: argparse.Namespace) -> None:
    from groundgate.store import FolderStore

    try:
        with FolderStore(args.store) as store:
            if args.events_step == "add":
                new, copies = add(store, read_file(args.events))
                print(f"added {new} events; {copies} copies were not added")
                return
            drafts = suggest(store, load_profile(args.profile))
        text = json.dumps(drafts, indent=1, ensure_ascii=False) + "\n"
        if args.out is None:
            print(text, end="")
        else:
            with open(args.out, "x", encoding="utf-8") as f:  # "x": never write over a file
                f.write(text)
    except (MeasureError, PacketError, StoreError, OSError) as e:
        raise SystemExit(f"calibrate events: {e}") from None
