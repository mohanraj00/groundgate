"""Steps 14 and 15: the records of a record field and the checks across a document set
(SPEC §4.12, §4.13, #613). The steps read only the decisions of the member fields. They never
read the text."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .model import CheckResult, Outcome, RecordLine, Schema

RECORD_CODES = (  # SPEC §4.12 order; it is part of every receipt hash
    "RECORD_MEMBER_MISSING",
    "RECORD_MEMBER_CONFLICT",
    "RECORD_SOURCE_MIXED",
    "SET_REPLACES_NOTHING",
    "SET_DUPLICATE",
    "SET_CONFLICT",
)
_CODE_OF = {"replace": "SET_REPLACES_NOTHING", "unique": "SET_DUPLICATE", "agree": "SET_CONFLICT"}


@dataclass(frozen=True)
class Value:
    """A decision of a member field that passed (SPEC §3.3)."""

    member: str
    value: str  # the canonical value
    text: object  # the document, a reference, or the decision itself on the outside path
    source: str
    ref: str | None
    doubtful: bool  # the decision is needs_verification


@dataclass
class _Record:
    field: str
    id: str
    values: list[Value]
    codes: set[str]
    members: dict[str, str | None]
    source: str | None = None
    ref: str | None = None
    position: int | None = None  # the position of its text in the document set
    replaced: bool = False


def decide(
    schema: Schema,
    ids: Sequence[tuple[str, str]],
    values: Mapping[tuple[str, str], Sequence[Value]],
    positions: Mapping[str, int],
) -> tuple[tuple[RecordLine, ...], tuple[CheckResult, ...]]:
    """The record lines, sorted by field and record, and the check results, sorted by id.

    ``ids`` holds each (record field, record id) that a decision names. ``values`` holds the
    decisions that passed of each record. ``positions`` maps a reference id to its position in
    the document set; the document has the position 0."""
    records: dict[tuple[str, str], _Record] = {}
    for fid, rid in sorted(set(ids)):
        rf = schema.records[fid]
        got = list(values.get((fid, rid), ()))
        by: dict[str, set[str]] = defaultdict(set)
        for v in got:
            by[v.member].add(v.value)
        r = _Record(fid, rid, got, set(), {})
        for member in rf.members:
            seen = by.get(member, set())
            r.members[member] = next(iter(seen)) if len(seen) == 1 else None
            if not seen and schema.fields[rf.member(member)].required:
                r.codes.add("RECORD_MEMBER_MISSING")
            if len(seen) > 1:
                r.codes.add("RECORD_MEMBER_CONFLICT")
        texts = {id(v) if v.source in ("external", "knowledge") else v.text for v in got}
        if len(texts) > 1:
            r.codes.add("RECORD_SOURCE_MIXED")
        elif got:
            r.source, r.ref = got[0].source, got[0].ref
            if r.source == "document":
                r.position = 0
            elif r.source == "reference" and r.ref is not None:
                r.position = positions.get(r.ref)
        records[fid, rid] = r

    found: dict[str, set[str]] = {c.id: set() for c in schema.checks}
    ordered = sorted(schema.checks, key=lambda c: (c.check != "replace", c.id))
    for c in ordered:  # each replace check runs first (SPEC §4.13)
        live = [
            r
            for r in records.values()
            if r.field == c.field
            and "RECORD_MEMBER_MISSING" not in r.codes
            and r.position is not None
            and r.members[c.member] is not None
            and (c.check == "replace" or not r.replaced)
        ]
        groups: dict[str | None, list[_Record]] = defaultdict(list)
        for r in live:
            groups[r.members[c.member]].append(r)
        for group in groups.values():
            low = min(r.position or 0 for r in group)
            high = max(r.position or 0 for r in group)
            if c.check == "replace":
                hit = [r for r in group if r.position == low and low > 0]
                for r in group:
                    r.replaced = r.replaced or (r.position or 0) < high
            elif c.check == "unique":
                hit = group if len(group) > 1 else []
            else:
                hit = group if low < high and _differ(group, c.compare) else []
            for r in hit:
                r.codes.add(_CODE_OF[c.check])
                found[c.id].add(r.id)

    lines = []
    for r in records.values():
        outcome: Outcome = "admitted"
        if "RECORD_MEMBER_MISSING" in r.codes:
            outcome = "rejected"
        elif r.codes or any(v.doubtful for v in r.values):
            outcome = "needs_verification"
        lines.append(
            RecordLine(
                r.field,
                r.id,
                outcome,
                tuple(code for code in RECORD_CODES if code in r.codes),
                r.source,
                r.ref,
                r.replaced,
                tuple(r.members.items()),
            )
        )
    checks = tuple(CheckResult(cid, tuple(sorted(found[cid]))) for cid in sorted(found))
    return tuple(lines), checks


def _differ(group: list[_Record], compare: tuple[str, ...]) -> bool:
    """A ``compare`` member has two different values that are not null in the group."""
    return any(len({r.members[m] for r in group} - {None}) > 1 for m in compare)
