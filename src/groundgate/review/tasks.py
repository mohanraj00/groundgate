"""The tasks of one packet (docs/design/review.md §5.2, §6.3 point 2, §7).

``make_tasks`` is a pure function of a packet and a review policy. It gives a ``task@1`` object
for each slot that the four rules of §5.2 select. ``write_tasks`` gets the packet from a store,
decides it again with ``verify``, and writes the tasks to the store. It writes no task for a
packet whose receipt does not match its inputs.

A task holds no review policy. The receipt sets the mode of each slot, so the same packet always
gives the same bytes for a slot, and a new policy keeps the answers to its tasks (§6.3 point 1).
A task holds offsets, pages and boxes, and no document text other than the values that its
question and choices quote.
"""

from __future__ import annotations

import bisect
import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from ..canonical import digest, jcs
from ..model import PacketError, Schema
from ..read.layout import Layout
from ..text import canonical, normalize_ws, quote_pattern, tokens

__all__ = [
    "DEFAULT_POLICY",
    "Slot",
    "audit_hash",
    "audit_picked",
    "check_policy",
    "make_tasks",
    "slots",
    "write_tasks",
]

DEFAULT_POLICY: dict[str, Any] = {
    "format": "review-policy@1",
    "audit": {"rate": "0", "seed": ""},
    "agree": 1,
    "leads": [],
    "rejected": False,
}

AUDIT_PREFIX = "groundgate-audit/1:"
MISSING = "REQUIRED_FIELD_MISSING"
SPAN_CHARS = 300  # a string value longer than this is a span (§7)
_RATE = re.compile(r"0|1|0\.[0-9]{0,17}[1-9]")
_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")  # the line breaks of str.splitlines
_SCALES = {
    0: "not scaled",
    3: "in thousands",
    6: "in millions",
    9: "in billions",
    12: "in trillions",
}
_ENDS = 8  # the words of a span that its question quotes at each end
_PARTS = {
    "number@1": ("amount", "scale", "sign", "unit", "field", "key"),
    "text@1": ("text", "field", "key"),
    "span@1": ("start", "end", "field", "key"),
}


# The review policy (§5.1)


def check_policy(policy: object) -> dict[str, Any]:
    """``policy`` as a ``review-policy@1`` object, or ``ValueError``. The object must give each
    member, as the schema ``review-policy@1.schema.json`` says."""
    if not isinstance(policy, dict):
        raise ValueError("the review policy is not a JSON object")
    names = ["agree", "audit", "format", "leads", "rejected"]
    if sorted(policy) != names:
        raise ValueError(f"the review policy must have exactly the members {', '.join(names)}")
    if policy["format"] != "review-policy@1":
        raise ValueError("the review policy format must be review-policy@1")
    audit = policy["audit"]
    if not isinstance(audit, dict) or sorted(audit) != ["rate", "seed"]:
        raise ValueError("the review policy member audit must have exactly rate and seed")
    if not isinstance(audit["rate"], str) or not _RATE.fullmatch(audit["rate"]):
        raise ValueError(
            'the audit rate must be a decimal string from 0 to 1, such as "0.02", with at most '
            "18 digits after the point and no last 0 after the point"
        )
    if not isinstance(audit["seed"], str):
        raise ValueError("the audit seed must be a string")
    agree = policy["agree"]
    if isinstance(agree, bool) or not isinstance(agree, int) or agree < 1:
        raise ValueError("the review policy member agree must be an integer of 1 or more")
    leads = policy["leads"]
    if (
        not isinstance(leads, list)
        or not all(isinstance(name, str) and name.strip() for name in leads)
        or len(set(leads)) != len(leads)
    ):
        raise ValueError("the review policy member leads must be a list of different names")
    if not isinstance(policy["rejected"], bool):
        raise ValueError("the review policy member rejected must be true or false")
    return policy


# The audit pick (§6.3 point 2)


def audit_hash(seed: str, packet: str, field: str, key: str | None, decision: int | None) -> int:
    """H: the first 8 bytes, big-endian, of SHA-256 over ``groundgate-audit/1:`` and the
    canonical JSON of ``[seed, packet, field, key, decision]``."""
    data = (AUDIT_PREFIX + jcs([seed, packet, field, key, decision])).encode("utf-8")
    return int.from_bytes(hashlib.sha256(data).digest()[:8], "big")


def audit_picked(h: int, rate: str) -> bool:
    """True when H / 2^64 < ``rate``, in integer arithmetic: with ``rate`` = n / 10^d, when
    H * 10^d < n * 2^64."""
    if not _RATE.fullmatch(rate):
        raise ValueError(f"{rate!r} is not an audit rate")
    whole, _, digits = rate.partition(".")
    return bool(h * 10 ** len(digits) < int(whole + digits) * 2**64)


# Slots (§4)


@dataclass(frozen=True)
class Slot:
    """One thing that a person decides: a field and a key, or one decision of a ``multiple``
    field. ``decisions`` holds the index in the receipt of each decision of the slot, in receipt
    order. ``missing`` is true when the receipt gives ``REQUIRED_FIELD_MISSING`` for the field."""

    field: str
    key: str | None
    decisions: tuple[int, ...]
    missing: bool = False

    def order(self) -> tuple[str, int, str, int]:
        """The order of §5.4: the field, then the key with null first, then the first
        decision."""
        first = self.decisions[0] if self.decisions else -1
        return (self.field, self.key is not None, self.key or "", first)


def slots(receipt: Mapping[str, Any], schema: Schema) -> list[Slot]:
    """The slots of a receipt, in the order of §5.4. A decision for a field that the schema does
    not have is in no slot. A coverage entry is the slot of its field with a null key."""
    found: dict[tuple[str, str | None, int | None], list[int]] = {}
    for i, d in enumerate(receipt["decisions"]):
        field = d.get("field")
        if not isinstance(field, str) or field not in schema.fields:
            continue
        key = d.get("key")
        if not isinstance(key, str) or schema.fields[field].keys is None:
            key = None
        multiple = schema.fields[field].multiple
        found.setdefault((field, key, i if multiple else None), []).append(i)
    missing = {
        c["field"] for c in receipt["coverage"] if c.get("code") == MISSING and c["field"]
    } & set(schema.fields)
    single = {f for f in missing if not schema.fields[f].multiple}
    out = [Slot(f, k, tuple(ds), f in single and k is None) for (f, k, _), ds in found.items()]
    out += [Slot(f, None, (), True) for f in missing - {s.field for s in out if s.missing}]
    return sorted(out, key=Slot.order)


# The tasks (§5.2)


def make_tasks(
    packet_key: str,
    receipt: Mapping[str, Any],
    text: str,
    schema: Schema,
    policy: Mapping[str, Any],
    *,
    references: Sequence[Any] | None = None,
    layout: Layout | None = None,
) -> list[dict[str, Any]]:
    """The ``task@1`` objects of the packet, in slot order. ``receipt`` must match the other
    inputs: ``write_tasks`` checks that with ``verify`` first."""
    policy = check_policy(policy)
    decisions = receipt["decisions"]
    texts = _texts(text, references)
    tasks = []
    for slot in slots(receipt, schema):
        ds = [decisions[i] for i in slot.decisions]
        passed = [i for i, d in zip(slot.decisions, ds, strict=True) if d["outcome"] != "rejected"]
        audit = len(passed) == 1 and decisions[passed[0]]["outcome"] == "admitted"
        if any(d["outcome"] == "needs_verification" for d in ds) or slot.missing:
            pass  # rules 1 and 2
        elif ds and not passed:  # rule 4
            if not policy["rejected"]:
                continue
        elif audit:  # rule 3
            multiple = schema.fields[slot.field].multiple
            h = audit_hash(
                policy["audit"]["seed"],
                packet_key,
                slot.field,
                slot.key,
                slot.decisions[0] if multiple else None,
            )
            if not audit_picked(h, policy["audit"]["rate"]):
                continue
        else:
            continue
        tasks.append(_task(packet_key, slot, decisions, passed, audit, schema, texts, layout))
    return tasks


def _task(
    packet_key: str,
    slot: Slot,
    decisions: Sequence[Mapping[str, Any]],
    passed: list[int],
    audit: bool,
    schema: Schema,
    texts: Mapping[str | None, _Source],
    layout: Layout | None,
) -> dict[str, Any]:
    field = schema.fields[slot.field]
    values = [decisions[i]["value"] for i in passed]
    for v in values:
        if not isinstance(v, str):
            raise PacketError(f"a passed decision of the field {slot.field} has no value")
    if field.type in ("number", "integer"):
        item, template = "number", "number@1"
    elif any(_long(decisions[i], texts) for i in passed):
        item, template = "span", "span@1"
    else:
        item, template = "text", "text@1"
    choices = []
    for i in passed:
        d = decisions[i]
        span = _span(d.get("evidence"))
        if item == "number":
            shown = _number(d["value"], d.get("unit"), span, texts.get(d.get("ref")))
        else:
            shown = _string(d["value"], item)
        choices.append(
            {"decision": i, "value": d["value"], "unit": d.get("unit"), "shown": shown,
             "evidence": None if span is None else {"start": span[0], "end": span[1]}}
        )  # fmt: skip
    question, named = _question(item, slot, field.unit, [c["shown"] for c in choices])
    codes: list[str] = [MISSING] if slot.missing else []
    for i in slot.decisions:
        codes += [c for c in decisions[i]["codes"] if c not in codes]
    return {
        "format": "task@1",
        "packet": packet_key,
        "slot": {"field": slot.field, "key": slot.key, "decisions": list(slot.decisions)},
        "item": item,
        "mode": "audit" if audit else "review",
        "template": template,
        "question": question,
        "parts": [p for p in _PARTS[template] if p in named],
        "codes": codes,
        "choices": choices,
        "places": _places([decisions[i] for i in slot.decisions], layout),
    }


def _question(item: str, slot: Slot, unit: str | None, shown: list[str]) -> tuple[str, set[str]]:
    """The question of the template for ``item``, and the parts that it names."""
    words = normalize_ws(slot.field.replace("_", " "))
    subject = words if slot.key is None else f"{words} for {normalize_ws(slot.key)}"
    named = {"field"} if slot.key is None else {"field", "key"}
    if item == "number":
        if not shown:
            if unit is None:
                return f"What is {subject}?", named
            return f"What is {subject}, in {unit}?", named | {"unit"}
        named |= {"amount", "scale", "sign", "unit"}
        if len(shown) == 1:
            return f"Is {subject} {shown[0]}?", named
        return f"Which amount is {subject}?", named
    if item == "text":
        if not shown:
            return f"What is the {subject}?", named
        named.add("text")
        if len(shown) == 1:
            return f"Is {shown[0]} the {subject}?", named
        return f"Which text is the {subject}?", named
    if not shown:
        return f"Where do the start and the end of the {subject} occur?", named
    named |= {"start", "end"}
    if len(shown) == 1:
        return f"Is the {subject} the text {shown[0]}?", named
    return f"Which text is the {subject}?", named


def _number(value: str, unit: object, span: tuple[int, int] | None, text: _Source | None) -> str:
    """The value with each part named: the amount in full, the unit, and the number as written
    with its scale and its sign. For example "4,200,000 USD (written 4,200, in thousands,
    positive)"."""
    try:
        amount = Decimal(value)
    except InvalidOperation:
        amount = Decimal("NaN")
    if not amount.is_finite():
        raise PacketError(f"the value {value!r} is not a number")
    full = format(amount, ",f")
    sign = "negative" if amount < 0 else "zero" if amount == 0 else "positive"
    unit_text = unit if isinstance(unit, str) else "with no unit"
    written = None if span is None or text is None else _written(amount, span, text)
    if written is None:
        return f"{full} {unit_text} (written form not found, {sign})"
    token, scale = written
    return f"{full} {unit_text} (written {token}, {_SCALES[scale]}, {sign})"


def _long(decision: Mapping[str, Any], texts: Mapping[str | None, _Source]) -> bool:
    """A string value is long (§7) when it has more than 300 characters, or when its first
    occurrence in its evidence span has a line break. The receipt gives the value with each
    whitespace run as one space, so the line break comes from the text."""
    value = decision["value"]
    if len(value) > SPAN_CHARS:
        return True
    source = texts.get(decision.get("ref"))
    span = _span(decision.get("evidence"))
    chars = None if source is None or span is None else source.chars(span)
    if source is None or chars is None or not value.strip():
        return False
    found = quote_pattern(value).search(source.text, *chars)
    return found is not None and bool(_BREAKS.intersection(found.group()))


class _Source:
    """A text and its UTF-8 bytes, encoded one time. ``chars`` turns a byte span into a span in
    code points without a new decode of the text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.data = text.encode("utf-8")
        # the byte offset after each character of more than one byte, and the sum of the extra
        # bytes up to that offset
        self._ends: list[int] = []
        self._extra: list[int] = []
        if len(self.data) != len(text):
            at = extra = 0
            for ch in text:
                size = len(ch.encode("utf-8"))
                at += size
                if size > 1:
                    extra += size - 1
                    self._ends.append(at)
                    self._extra.append(extra)

    def _char(self, offset: int) -> int | None:
        if offset < len(self.data) and 0x80 <= self.data[offset] < 0xC0:
            return None  # inside a character
        n = bisect.bisect_right(self._ends, offset)
        return offset - (self._extra[n - 1] if n else 0)

    def chars(self, span: tuple[int, int]) -> tuple[int, int] | None:
        """The UTF-8 byte span ``span`` in code points, or None when it is not a span of the
        text."""
        if not 0 <= span[0] <= span[1] <= len(self.data):
            return None
        start, end = self._char(span[0]), self._char(span[1])
        return None if start is None or end is None else (start, end)


def _times_ten(digits: str, power: int) -> str:
    """The canonical decimal ``digits`` times 10^``power``, as a canonical decimal, by a move of
    the point. This is exact, and its time is linear in the digits."""
    whole, _, frac = digits.partition(".")
    frac += "0" * power
    whole = (whole + frac[:power]).lstrip("0") or "0"
    frac = frac[power:].rstrip("0")
    return f"{whole}.{frac}" if frac else whole


def _written(amount: Decimal, span: tuple[int, int], source: _Source) -> tuple[str, int] | None:
    """The first number token in ``span`` of the text that gives ``amount`` with a scale of 1,
    a thousand, a million, a billion or a trillion, and the power of ten of that scale."""
    chars = source.chars(span)
    if chars is None:
        return None
    want = canonical(amount.copy_abs())  # abs() rounds to 28 digits
    for tok in tokens(source.text, *chars):
        if tok.value is None:
            continue
        digits = canonical(tok.value.copy_abs())
        for power in _SCALES:
            if _times_ten(digits, power) == want:
                return source.text[tok.start : tok.end], power
    return None


def _string(value: str, item: str) -> str:
    """A text value in quotes. A span shows its first and its last words, and its length."""
    if item == "text":
        return f'"{value}"'
    words = value.split()
    head = " ".join(words[:_ENDS])
    tail = " ".join(words[-_ENDS:])
    return f'from "{head}" to "{tail}" ({len(value)} characters)'


def _span(evidence: object) -> tuple[int, int] | None:
    if not isinstance(evidence, Mapping):
        return None
    start, end = evidence.get("start"), evidence.get("end")
    if type(start) is not int or type(end) is not int:
        return None
    return start, end


def _texts(text: str, references: Sequence[Any] | None) -> dict[str | None, _Source]:
    """The document text under ``None``, and the text of each reference under its id."""
    out: dict[str | None, _Source] = {None: _Source(text)}
    for ref in references or ():
        if isinstance(ref, Mapping) and isinstance(ref.get("id"), str):
            body = ref.get("text")
            if isinstance(body, str):
                out[ref["id"]] = _Source(body)
    return out


def _places(ds: Sequence[Mapping[str, Any]], layout: Layout | None) -> list[dict[str, Any]]:
    """Each document span of the slot, in offset order: the value span of each decision and
    the span of each role item. A span in a reference is not a place in the document."""
    spans: set[tuple[int, int]] = set()
    for d in ds:
        if d.get("ref") is not None:
            continue
        found = [_span(d.get("evidence"))]
        found += [_span(p) for p in d.get("parts") or () if isinstance(p, Mapping)]
        spans.update(s for s in found if s is not None)
    places = []
    for start, end in sorted(spans):
        page, box = None, None
        if layout is not None:
            page = layout.page_at(start)
            boxes = [b for b in layout.locate(start, end) if b.page == page]
            if any(not math.isfinite(v) for b in boxes for v in (b.x0, b.top, b.x1, b.bottom)):
                raise PacketError(f"the layout has a box that is not a finite number at {start}")
            if boxes:
                box = [
                    min(b.x0 for b in boxes),
                    min(b.top for b in boxes),
                    max(b.x1 for b in boxes),
                    max(b.bottom for b in boxes),
                ]
        places.append({"start": start, "end": end, "page": page, "box": box})
    return places


# The store


@dataclass(frozen=True)
class Written:
    """The result of ``write_tasks``. ``problems`` is not empty when the receipt of the packet
    does not match its inputs: then ``tasks`` is empty and the store has no new object."""

    tasks: list[tuple[str, dict[str, Any]]]
    problems: tuple[str, ...] = ()


def write_tasks(store: Any, packet_key: str, policy: Mapping[str, Any] | None = None) -> Written:
    """Get the packet ``packet_key`` from ``store``, decide it again, and write a ``task@1``
    object for each task. Return each task key with its task, in slot order. Without
    ``policy``, the default policy gives no audit and no task for a rejected slot."""
    from ..admit import verify
    from ..store.packets import load_packet

    checked = check_policy(DEFAULT_POLICY if policy is None else policy)
    packet = load_packet(store, packet_key, layout=True)
    result = verify(packet.receipt, packet.text, packet.schema, packet.candidates,
                    **packet.inputs())  # fmt: skip
    if not result.ok:
        return Written([], tuple(result.problems))
    layout = None
    if packet.layout is not None:
        layout = Layout.from_dict(packet.layout)
        if layout.document_sha256 != digest("document", {"text": packet.text}):
            raise PacketError("the layout was extracted from a different document")
    schema = Schema.from_dict(packet.schema, packet.packs)
    tasks = make_tasks(
        packet_key,
        packet.receipt,
        packet.text,
        schema,
        checked,
        references=packet.references,
        layout=layout,
    )
    encoded = [(jcs(t).encode("utf-8"), t) for t in tasks]  # each task, before any write
    return Written([(store.put("task@1", data), t) for data, t in encoded])
