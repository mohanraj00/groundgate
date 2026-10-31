"""The decision procedure (SPEC §3) and receipts (SPEC §5)."""

from __future__ import annotations

import bisect
import dataclasses
import heapq
import itertools
import os
import re
from array import array
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import MAX_PREC, Context, Decimal, Inexact
from fractions import Fraction
from typing import Any

from .canonical import SPEC_VERSION, Offsets, digest, is_nfc
from .fold import fold_text, mark_fold
from .model import (
    Action,
    Decision,
    EvidenceUnits,
    Field,
    Judgment,
    Outcome,
    PacketError,
    Part,
    Policy,
    Receipt,
    Relation,
    RelationResult,
    Schema,
)
from .pack import BASE, checked_copy, reading_retired, receipt_packs, schema_named
from .text import (
    HeadingIndex,
    Token,
    UnitPlaces,
    bracket_sign,
    brackets_around,
    canonical,
    cells,
    code_scale_cut,
    currency_name,
    currency_scale,
    first_token_end,
    form_next,
    gain_word,
    header,
    header_column,
    heading_rows,
    holds_form,
    host,
    item_scale,
    key_break,
    key_mentions,
    keys_at,
    loss_sign,
    normalize_ws,
    parse_value,
    qualifiers,
    quote_pattern,
    scale_between,
    scale_form,
    scale_word,
    scaled_value,
    sentence,
    sentence_index,
    tokens,
    unit_at,
    units_next,
    using,
    verbatim_equal,
    vocabulary,
)

NULL_LITERALS = frozenset(BASE["null_literals"])  # the null literals of the base pack (SPEC §4.7)
FLAG_ORDER = (  # SPEC §3.3 table order; it is part of every receipt hash
    "NON_VERBATIM_EVIDENCE",
    "QUALIFIED_VALUE",
    "SCALE_WORD",
    "PART_MISSING",
    "SIGN_CITATION_INVALID",
    "SCALE_CITATION_INVALID",
    "UNIT_CITATION_INVALID",
    "FIELD_CITATION_INVALID",
    "KEY_NOT_AT_VALUE",
    "KEY_CITATION_INVALID",
    "COLUMN_NOT_AT_VALUE",
    "MARKER_OTHER_FIELD",
    "EVIDENCE_QUOTED",
    "EVIDENCE_STATED",
    "LOW_CONFIDENCE",
    "CONFLICTING_CANDIDATES",
    "RELATION_FAILED",
    "MODEL_DOUBT",
)
INFO_ORDER = (
    "EVIDENCE_REANCHORED",
    "VALUE_DERIVED",
    "KEY_CITED",
    "ADMITTED_BY_POLICY",
    "MODEL_CLEARED",
)
QUESTIONS = ("key", "field_match")
SOURCES = ("document", "reference", "external", "knowledge")
ROLES = ("value", "sign", "scale", "unit", "key", "field", "column", "marker")
PART_ORDER = ("sign", "scale", "unit", "field", "column", "marker", "key")  # SPEC §5 `parts`
MAX_FIELD_ITEMS = 8  # the field items that a candidate can cite (SPEC §3 step 1, #300)
MISSING_ORDER = ("sign", "scale", "unit", "key")
_SCALES = (3, 5, 6, 7, 9, 12)  # the powers of ten of the scale words (SPEC §4.1)
_ACTION_RANK = {"admit": 0, "review": 1, "reject": 2}


class _Reject(Exception):
    def __init__(self, code: str, at: _At | None = None, item: _Item | None = None) -> None:
        self.code = code
        self.at = at  # where the value was looked for, when known
        self.item = item  # the deciding outside item, when known


def _span(obj: object) -> tuple[int, int] | None:
    """(start, end) from a span object, or None if malformed (SPEC §3 step 1)."""
    if not isinstance(obj, Mapping):
        return None
    s, e = obj.get("start"), obj.get("end")
    if (
        isinstance(s, bool)
        or isinstance(e, bool)
        or not isinstance(s, int)
        or not isinstance(e, int)
    ):
        return None
    return s, e


def _valid(offsets: Offsets, span: tuple[int, int]) -> tuple[int, int] | None:
    """Code-point span for a valid byte span (SPEC §2.2), else None."""
    s, e = span
    if not (0 <= s < e <= offsets.byte_length):
        return None
    cs, ce = offsets.to_char(s), offsets.to_char(e)
    return None if cs is None or ce is None else (cs, ce)


_Index = tuple["array[int]", "array[int]"]  # the starts and the ends of the occurrences, in order


@dataclass
class _Text:
    """A text that evidence items point into: the document, a reference, or an external quote."""

    text: str
    offsets: Offsets
    ref: str | None = None
    mentions: dict[tuple[str, ...], list[tuple[int, int, str]]] = field(default_factory=dict)
    rows: list[tuple[int, int]] | None = None  # reached by a heading scale, read once
    headings: HeadingIndex | None = None  # the heading units (#315), read once
    # the quotes of the candidate being checked, for the many occurrences of one value (#249)
    # and its field items (#300): cleared for each candidate, so that they are at most the value
    # quote, 8 field items and one item of each other role
    quotes: dict[tuple[str, int, int], _Index] = field(default_factory=dict)
    spans: dict[tuple[str, ...], list[tuple[int, int]]] = field(default_factory=dict)
    letters: dict[int, int] = field(default_factory=dict)  # the first letter at or after each place
    numbers: dict[int, int | None] = field(default_factory=dict)  # the first token end, likewise
    breaks: list[int] | None = None  # the places of the line breaks, read once
    tabs: list[int] | None = None  # the places of the tabs, read once
    words: dict[int, list[int]] = field(default_factory=dict)  # word starts of each answer slot
    reach: dict[tuple[int, int], int] = field(default_factory=dict)  # of each header slot
    cells: dict[int, list[tuple[int, int]]] = field(default_factory=dict)  # slots by line start
    ends: dict[tuple[str, ...], list[tuple[int, int]]] = field(default_factory=dict)  # by end
    bounds: dict[tuple[int, int, str | None], tuple[list[int], list[int]]] = field(
        default_factory=dict
    )  # the runs of letters of each answer slot (the boundary rule)

    def line(self, pos: int) -> tuple[int, int]:
        """The start and the end of the line that holds ``pos``."""
        if self.breaks is None:
            self.breaks = [m.start() for m in re.finditer("\n", self.text)]
        i = bisect.bisect_left(self.breaks, pos)
        start = self.breaks[i - 1] + 1 if i else 0
        return start, self.breaks[i] if i < len(self.breaks) else len(self.text)

    def tab_in(self, a: int, b: int) -> int:
        """The first tab in text[a:b], or -1."""
        if self.tabs is None:
            self.tabs = [m.start() for m in re.finditer("\t", self.text)]
        i = bisect.bisect_left(self.tabs, a)
        return self.tabs[i] if i < len(self.tabs) and self.tabs[i] < b else -1

    def words_before(self, slot: int, end: int, pos: int) -> int:
        """The words in text[slot:pos] of the slot text[slot:end], not the run that holds
        ``pos`` (SPEC §4.6)."""
        if slot not in self.words:
            runs = re.compile(r"\S+").finditer(self.text, slot, end)
            self.words[slot] = [m.start() for m in runs]
        n = bisect.bisect_left(self.words[slot], pos)
        return n - 1 if n and pos > slot and not self.text[pos - 1].isspace() else n

    def key_mentions(self, words: tuple[str, ...]) -> list[tuple[int, int, str]]:
        if words not in self.mentions:
            self.mentions[words] = key_mentions(self.text, words)
        return self.mentions[words]

    def named(self, words: tuple[str, ...], a: int, b: int) -> bool:
        """Whether a key mention of ``words`` lies within text[a:b]."""
        if words not in self.spans:
            self.spans[words] = sorted((x, y) for x, y, _ in self.key_mentions(words))
        found = self.spans[words]
        i = bisect.bisect_left(found, (a, -1))
        return any(
            y <= b
            for _, y in itertools.takewhile(lambda m: m[0] < b, itertools.islice(found, i, None))
        )

    def within(self, words: tuple[str, ...], a: int, b: int) -> list[tuple[int, int]]:
        """The key mentions of ``words`` that lie within text[a:b]."""
        if words not in self.spans:
            self.spans[words] = sorted((x, y) for x, y, _ in self.key_mentions(words))
        found = self.spans[words]
        i, out = bisect.bisect_left(found, (a, -1)), []
        while i < len(found) and found[i][0] < b:
            if found[i][1] <= b:
                out.append(found[i])
            i += 1
        return out

    def slot(self, pos: int) -> tuple[int, int]:
        """The slot of its line that holds ``pos``."""
        line = self.slots(pos)
        return line[bisect.bisect_right(line, (pos, len(self.text) + 1)) - 1]

    def starting(self, words: tuple[str, ...], a: int, b: int) -> list[tuple[int, int]]:
        """The key mentions of ``words`` that start at or after ``a`` and at or before ``b``."""
        self.within(words, 0, 0)  # the spans of ``words``, sorted by start
        found = self.spans[words]
        i, j = bisect.bisect_left(found, (a, -1)), bisect.bisect_right(found, (b, len(self.text)))
        return found[i:j]

    def ending(self, words: tuple[str, ...], a: int, b: int) -> list[tuple[int, int]]:
        """The key mentions of ``words`` that end at or after ``a`` and at or before ``b``."""
        if words not in self.ends:
            self.within(words, 0, 0)
            self.ends[words] = sorted((y, x) for x, y in self.spans[words])
        found = self.ends[words]
        i, j = bisect.bisect_left(found, (a, -1)), bisect.bisect_right(found, (b, len(self.text)))
        return [(x, y) for y, x in found[i:j]]

    def slots(self, pos: int) -> list[tuple[int, int]]:
        """The slots of the line that holds ``pos``: the parts between its tabs (SPEC §4.6)."""
        start, end = self.line(pos)
        if start in self.cells:
            return self.cells[start]
        if self.tabs is None:
            self.tabs = [m.start() for m in re.finditer("\t", self.text)]
        tabs = self.tabs
        i = bisect.bisect_left(tabs, start)
        out = []
        while i < len(tabs) and tabs[i] < end:  # no copy of the tabs after the line (#543)
            out.append((start, tabs[i]))
            start = tabs[i] + 1
            i += 1
        out.append((start, end))
        self.cells[self.line(pos)[0]] = out
        return out

    def letter_after(self, pos: int) -> int:
        """The first letter at or after ``pos``, or the end of the text."""
        if pos not in self.letters:
            text = self.text
            self.letters[pos] = next(
                (i for i in range(pos, len(text)) if text[i].isalpha()), len(text)
            )
        return self.letters[pos]

    def token_after(self, pos: int) -> int | None:
        """The end of the first number token at or after ``pos``, or None."""
        if pos not in self.numbers:
            self.numbers[pos] = first_token_end(self.text, pos)
        return self.numbers[pos]


def heading_scale(t: _Text, pos: int) -> bool:
    """Whether a heading scale reaches the token at ``pos`` (SPEC §4.1)."""
    if t.rows is None:
        t.rows = heading_rows(t.text)
    i = bisect.bisect_right(t.rows, (pos, len(t.text) + 1)) - 1
    return i >= 0 and t.rows[i][0] <= pos <= t.rows[i][1]


def _heading_unit(ctx: _Ctx, t: _Text, unit: str, tok: Token, a: int, b: int) -> bool:
    """Whether text[a:b] holds a heading unit that reaches the token, and the token's heading
    currency is ``unit`` (SPEC §4.3, §4.6, spec 0.10, #315)."""
    if t.headings is None:
        t.headings = HeadingIndex(t.text)
    if not t.headings.held(a, b, tok.start):
        return False
    return t.headings.currency(tok.start, unit, ctx.schema.units)


def _conflict(ctx: _Ctx, t: _Text, unit: str | None, tok: Token | None) -> bool:
    """Whether the token has a heading conflict: the field's unit is a currency unit that a
    heading unit that reaches the token does not allow (SPEC §4.3, spec 0.10, #365)."""
    if unit is None or tok is None:
        return False
    if t.headings is None:
        t.headings = HeadingIndex(t.text)
    return t.headings.conflict(tok.start, unit, ctx.schema.units)


@dataclass
class _Ctx:
    doc: _Text
    refs: dict[str, _Text]
    schema: Schema
    policy: Policy
    source_host: str | None
    suffixes: frozenset[str] = frozenset()  # of every unit in the table (SPEC §4.3)
    quoted: list[_Text] = field(default_factory=list)  # the text that holds quotes now
    aliases: tuple[str, ...] = ()  # of every field, for the label cell rule (SPEC §4.6)
    columns: tuple[str, ...] = ()  # the column words of every field (spec 0.12)
    markers: tuple[str, ...] = ()  # the marker words of every field
    competing: dict[str, tuple[str, ...]] = field(default_factory=dict)  # by field name

    def any_unit_at(self, t: _Text, tok: Token) -> bool:
        """Whether a form of any unit in the table is next to the token (SPEC §3.1)."""
        prefixes = [x for pre, _ in self.schema.units.values() for x in pre]
        return form_next(t.text, tok, prefixes, sorted(self.suffixes), self.policy.unit_window)


@dataclass(frozen=True)
class _Item:
    """One evidence item, after step 1 (SPEC §2.5)."""

    source: str
    role: str | None  # None on an outside item
    ref: str | None
    span: tuple[int, int] | None  # byte offsets as given
    text: str | None
    url: str | None


@dataclass
class _At:
    """Where the value is: the text, the span and the supporting token (None for strings)."""

    item: _Item
    t: _Text
    span: tuple[int, int]  # code points
    token: Token | None
    missing: set[str] = field(default_factory=set)
    derived: bool = False
    start: int | None = None  # a string value's first occurrence in the span (#140)
    end: int | None = None  # the end of that occurrence

    @property
    def pos(self) -> int:
        """Where the value is: its token, or a string value's first occurrence in the span."""
        if self.token is not None:
            return self.token.start
        return self.span[0] if self.start is None else self.start


@dataclass
class _Passed:
    """A candidate that passed (SPEC §3.3)."""

    field: Field
    value: str
    unit: str | None
    key: str | None  # None on a field without keys
    at: _At | None  # None on the outside path
    flags: list[str]
    info: set[str]
    source: str
    url: str | None = None
    parts: list[Part] = dataclasses.field(default_factory=list)
    missing: set[str] = dataclasses.field(default_factory=set)
    cleared: bool = False  # a recorded judgment removed KEY_NOT_AT_VALUE (step 12)
    cited: bool = False  # a key item removed KEY_NOT_AT_VALUE (KEY_CITED)


def _items(ev: object, refs: Mapping[str, _Text]) -> list[_Item]:
    """The evidence items of a candidate, or _Reject (SPEC §3 step 1)."""
    if ev is None:
        return []
    raw = [ev] if isinstance(ev, Mapping) else ev
    if not isinstance(raw, list):
        raise _Reject("CANDIDATE_INVALID")
    out: list[_Item] = []
    for it in raw:
        if not isinstance(it, Mapping) or any(v is None for v in it.values()):
            raise _Reject("CANDIDATE_INVALID")
        source = it.get("source", "document")
        role = it.get("role")
        text = it.get("text")
        if source not in SOURCES or (text is not None and not isinstance(text, str)):
            raise _Reject("CANDIDATE_INVALID")
        has = "start" in it or "end" in it
        span = _span(it) if has else None
        if has and span is None:
            raise _Reject("CANDIDATE_INVALID")
        ref, url = it.get("ref"), it.get("url")
        if (ref is not None) != (source == "reference"):
            raise _Reject("CANDIDATE_INVALID")
        if source == "reference" and (not isinstance(ref, str) or ref not in refs):
            raise _Reject("CANDIDATE_INVALID")
        if source in ("document", "reference"):
            if "url" in it or "retrieved" in it:
                raise _Reject("CANDIDATE_INVALID")
            if role is None:
                role = "value"
            if role not in ROLES or (span is None and not (text and text.strip())):
                raise _Reject("CANDIDATE_INVALID")
            same = sum(o.role == role and o.source in ("document", "reference") for o in out)
            if same >= (MAX_FIELD_ITEMS if role == "field" else 1):  # several field items (#300)
                raise _Reject("CANDIDATE_INVALID")
        else:
            if role is not None or has or not (text and text.strip()):
                raise _Reject("CANDIDATE_INVALID")
            if source == "external":
                day = it.get("retrieved")
                if not (isinstance(url, str) and url.strip()):
                    raise _Reject("CANDIDATE_INVALID")
                if not (isinstance(day, str) and day.strip()):
                    raise _Reject("CANDIDATE_INVALID")
        out.append(_Item(source, role, ref, span, text, url if source == "external" else None))
    return out


def _values(
    t: _Text, tok: Token, neg_item: bool, scale: int | None, prefixes: list[str] | None
) -> tuple[set[Decimal], bool]:
    """The token's derived values (SPEC §4.6), and whether the token is negative. ``prefixes``
    is None on a field without a unit, where brackets alone do not make a sign."""
    assert tok.value is not None
    sv = scaled_value(t.text, tok)
    if sv is not None:
        out = {tok.value, sv}
    elif scale is not None:  # a scale item scales the number as written (#242)
        out = {tok.value.scaleb(scale)}
    else:
        out = {tok.value}
    neg = neg_item or bracket_sign(t.text, tok, prefixes)
    if neg:
        out |= {-abs(v) for v in out}
    return out, neg


def _missing(
    t: _Text,
    tok: Token,
    value: Decimal,
    neg_item: bool,
    scale_item: bool,
    scale: int | None,
    prefixes: list[str] | None,
) -> set[str] | None:
    """The parts that the value needs at this token and has no item for (SPEC §3.1)."""
    assert tok.value is not None
    base, neg = _values(t, tok, neg_item, scale, prefixes)
    if not neg_item and value in {-abs(v) for v in base}:
        return {"sign"}
    if scale_item or scaled_value(t.text, tok) is not None:
        return None
    for k in _SCALES:
        times = tok.value.scaleb(k)
        if value in ({times, -abs(times)} if neg else {times}):
            return {"scale"}
        if not neg_item and value == -abs(times):
            return {"sign", "scale"}
    return None


def _value_at(
    ctx: _Ctx,
    item: _Item,
    t: _Text,
    f: Field,
    value: Decimal | str,
    span: tuple[int, int],
    roles: dict[str, _Item],
    lenient: bool,
    failed: list[Token] | None = None,
) -> tuple[_At | None, str | None]:
    """Steps 10-11 at one span: where the value is, or a failure code. ``lenient`` lets a part
    be missing (SPEC §3.1). On ``UNIT_NOT_IN_EVIDENCE``, the first token that step 10 matched
    is added to ``failed``, for the receipt's ``evidence_units`` (SPEC §5, #362)."""
    s, e = span
    if f.type == "string":
        assert isinstance(value, str)
        if normalize_ws(value) not in normalize_ws(t.text[s:e]):
            return None, "VALUE_NOT_IN_EVIDENCE"
        start, end = _string_place(t, value, span)
        return _At(item, t, span, None, start=start, end=end), None
    assert isinstance(value, Decimal)
    prefixes, suffixes = ctx.schema.units.get(f.unit, ([], [])) if f.unit else ([], [])
    signs = prefixes if f.unit is not None else None  # brackets make a sign only with a unit
    neg_item = "sign" in roles
    scale_item = roles.get("scale")
    scale = None
    if scale_item is not None:
        words = scale_item.text
        if words is None and scale_item.span is not None:  # the text at its span, in its own text
            own = ctx.doc if scale_item.source == "document" else ctx.refs[scale_item.ref or ""]
            at_span = _valid(own.offsets, scale_item.span)
            words = None if at_span is None else own.text[at_span[0] : at_span[1]]
        scale = None if words is None else item_scale(words, 0, len(words))
    toks = [k for k in tokens(t.text, s, e) if k.value is not None]

    def heading(k: Token, need: set[str]) -> set[str]:
        """The parts missing at the token, with the scale of a heading over its table."""
        if (
            scale_item is None
            and f.unit != "%"
            and "scale" not in need
            and scaled_value(t.text, k) is None
            and heading_scale(t, k.start)
        ):
            return need | {"scale"}
        return need

    hits: list[tuple[Token, set[str]]] = []
    for k in toks:
        vals, _ = _values(t, k, neg_item, scale, signs)
        if value in vals and (lenient or not heading(k, set())):
            hits.append((k, heading(k, set())))
    if not hits and lenient:
        for k in toks:
            need = _missing(t, k, value, neg_item, scale_item is not None, scale, signs)
            if need is not None:
                hits = [(k, heading(k, need))]
                break
    if not hits:
        return None, "VALUE_NOT_IN_EVIDENCE"

    def at(k: Token, need: set[str]) -> _At:
        assert k.value is not None
        plain = {k.value, scaled_value(t.text, k)}
        return _At(item, t, span, k, need, derived=not need and value not in plain)

    if f.unit is None:
        return at(*hits[0]), None
    for k, need in hits:
        if unit_at(t.text, k, prefixes, suffixes, ctx.policy.unit_window, ctx.suffixes):
            return at(k, need), None
    for k, need in hits:
        if not ctx.any_unit_at(t, k):
            if "unit" in roles:
                return at(k, need), None
            if lenient:
                a = at(k, need | {"unit"})
                a.derived = not need and value not in {k.value, scaled_value(t.text, k)}
                return a, None
    if failed is not None:
        failed.append(hits[0][0])
    return None, "UNIT_NOT_IN_EVIDENCE"


def _string_place(t: _Text, value: str, span: tuple[int, int]) -> tuple[int, int | None]:
    """Where a string value is: its first occurrence in the span, where whitespace runs match any
    whitespace run, else the start of the span with no end (#140)."""
    first = quote_pattern(value).search(t.text, *span)
    return (span[0], None) if first is None else (first.start(), first.end())


def _unscaled(tok: Token, value: Decimal | str) -> bool:
    """The value is the number as written, with any sign, not its scaled value (SCALE_WORD)."""
    return tok.value is not None and isinstance(value, Decimal) and abs(tok.value) == abs(value)


def _same(a: _Item, b: _Item) -> bool:
    """Whether two items are in the same text."""
    return a.source == b.source and a.ref == b.ref


def _occurrences(t: _Text, quote: str, region: tuple[int, int]) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in quote_pattern(quote).finditer(t.text, *region)]


def _indexed(t: _Text, quote: str, region: tuple[int, int]) -> _Index:
    """The occurrences of a quote, with their starts and their ends, each in order: the matches
    do not overlap. A quote is read and compiled once for each candidate, so field items do not
    read the text again at each occurrence of the value."""
    k = (quote, *region)
    held = t.quotes.get(k)
    if held is None:
        starts, ends = array("q"), array("q")  # 16 bytes for each occurrence
        for m in quote_pattern(quote).finditer(t.text, *region):
            starts.append(m.start())
            ends.append(m.end())
        held = t.quotes[k] = (starts, ends)
    return held


def _check(ctx: _Ctx, cand: object) -> _Passed:
    """Steps 1-11, the outside path and per-candidate flags. Raises _Reject."""
    # 1. structure
    if not isinstance(cand, Mapping):
        raise _Reject("CANDIDATE_INVALID")
    name, raw, unit = cand.get("field"), cand.get("value"), cand.get("unit")
    conf, region = cand.get("confidence"), cand.get("search_region")
    key = cand.get("key")
    if not isinstance(name, str) or isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise _Reject("CANDIDATE_INVALID")
    if (unit is not None and not isinstance(unit, str)) or (
        key is not None and not isinstance(key, str)
    ):
        raise _Reject("CANDIDATE_INVALID")
    if conf is not None and (
        isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1
    ):
        raise _Reject("CANDIDATE_INVALID")
    items = _items(cand.get("evidence"), ctx.refs)
    region_span = None
    if region is not None:
        region_span = _span(region)
        if region_span is None:
            raise _Reject("CANDIDATE_INVALID")
    # 2-6. field, value, type, range, unit
    f = ctx.schema.fields.get(name)
    if f is None:
        raise _Reject("FIELD_UNKNOWN")
    text_value = str(raw)
    if text_value.strip().lower() in vocabulary().null_literals:
        raise _Reject("NULL_STRING_LITERAL")
    value: Decimal | str
    if f.type == "string":
        if not isinstance(raw, str) or not normalize_ws(raw):
            raise _Reject("TYPE_INVALID")
        value = normalize_ws(raw)
    else:
        parsed = parse_value(text_value)
        if parsed is None or (f.type == "integer" and parsed != parsed.to_integral_value()):
            raise _Reject("TYPE_INVALID")
        value = parsed
        if (f.minimum is not None and parsed < f.minimum) or (
            f.maximum is not None and parsed > f.maximum
        ):
            raise _Reject("RANGE_INVALID")
    if unit != f.unit:
        raise _Reject("UNIT_INVALID")
    # 7. key
    if f.keys is None:
        key = None
    elif key not in f.keys:
        raise _Reject("KEY_INVALID")
    # 8. evidence
    inside = [i for i in items if i.source in ("document", "reference")]
    checked = {i.role or "value": i for i in inside if i.role != "field"}
    fields = [i for i in inside if i.role == "field"]  # in list order (#300)
    outside = [i for i in items if i.source in ("external", "knowledge")]
    vitem = checked.pop("value", None)
    if vitem is None and not outside:
        raise _Reject("NO_EVIDENCE")
    canon = value if isinstance(value, str) else canonical(value)
    if vitem is None:
        p = _outside(ctx, f, value, key, outside, "key" in checked)
        p.value, p.unit = canon, unit
    else:
        p = _checked(ctx, f, value, key, vitem, checked, fields, region_span)
        p.value, p.unit = canon, unit
    mc = ctx.policy.min_confidence
    if mc is not None and conf is not None and conf < mc:
        p.flags.append("LOW_CONFIDENCE")
    return p


def _checked(
    ctx: _Ctx,
    f: Field,
    value: Decimal | str,
    key: str | None,
    vitem: _Item,
    roles: dict[str, _Item],
    fields: list[_Item],
    region_span: tuple[int, int] | None,
) -> _Passed:
    """The checked path (SPEC §3.1) and the role checks (SPEC §4.6). ``roles`` holds the role
    items other than the field items, which are ``fields``."""
    t = ctx.doc if vitem.source == "document" else ctx.refs[vitem.ref or ""]
    for held in ctx.quoted:  # only the quotes of this candidate are held
        held.quotes.clear()
    ctx.quoted[:] = [t]
    # 9. spans
    search = (0, len(ctx.doc.text)) if region_span is None else _valid(ctx.doc.offsets, region_span)
    if search is None:
        raise _Reject("SPAN_INVALID", item=vitem)
    region = search if t is ctx.doc else (0, len(t.text))
    flags: list[str] = []
    info: set[str] = set()
    if vitem.span is None:
        # 9a. a quote: of the occurrences where a field item passes, or else of all of them
        # (#249, #300), the first where steps 10-11 pass, else the first one
        assert vitem.text is not None
        found = _occurrences(t, vitem.text, region)
        if not found:
            raise _Reject("QUOTE_NOT_FOUND", item=vitem)
        by_field = bool(fields) and f.aliases is not None
        at: _At | None = None
        first: _At | None = None  # the first occurrence where steps 10-11 pass
        named: tuple[int, int] | None = None  # the first occurrence where a field item passes
        for occ in found:  # one pass: it stops where both pass, as the first of the first kind
            strict, _ = _value_at(ctx, vitem, t, f, value, occ, roles, lenient=False)
            if by_field:
                here, _ = _value_at(ctx, vitem, t, f, value, occ, roles, lenient=True)
                if here is not None and _field_passes(ctx, t, f, here, fields, roles, region):
                    named = named or occ
                    if strict is not None:
                        at = strict
                        break
            elif strict is not None:
                at = strict
                break
            first = first or strict
        if at is None and named is None:
            at = first
        if at is None:
            occ = named or found[0]
            failed: list[Token] = []
            at, failure = _value_at(ctx, vitem, t, f, value, occ, roles, True, failed)
            if at is None:
                assert failure is not None
                raise _Reject(failure, _At(vitem, t, occ, failed[0] if failed else None))
    else:
        span = _valid(t.offsets, vitem.span)
        if span is None:
            raise _Reject("SPAN_INVALID", item=vitem)
        # 10-11. value and unit at the evidence, with re-anchoring
        at, failure = _value_at(ctx, vitem, t, f, value, span, roles, lenient=False)
        if at is None:  # the unit at a unit place where a field item passes (#249)
            near, _ = _value_at(ctx, vitem, t, f, value, span, roles, lenient=True)
            if near is not None and _unit_relief(ctx, t, f, near, fields, roles, region):
                at = near
        if at is None:
            quote = vitem.text
            if ctx.policy.reanchor and quote is not None and normalize_ws(quote):
                passing = []
                for alt in _occurrences(t, quote, region):
                    if alt != span:
                        alt_at, _ = _value_at(ctx, vitem, t, f, value, alt, roles, lenient=False)
                        if alt_at is not None:
                            passing.append(alt_at)
                if len(passing) == 1:
                    at = passing[0]
                    info.add("EVIDENCE_REANCHORED")
            failed = []
            if at is None:
                at, failure = _value_at(ctx, vitem, t, f, value, span, roles, True, failed)
            if at is None:
                assert failure is not None
                raise _Reject(failure, _At(vitem, t, span, failed[0] if failed else None))
        if vitem.text is not None and not verbatim_equal(
            vitem.text, t.text[at.span[0] : at.span[1]]
        ):
            flags.append("NON_VERBATIM_EVIDENCE")
    # the evidence is chosen as if no heading unit reached the token: then at a heading conflict
    # no unit form or unit place makes the unit present, and a unit item fails (#365)
    if "unit" not in roles and _conflict(ctx, at.t, f.unit, at.token):
        at.missing.add("unit")
    token = at.token
    if token is not None:
        if qualifiers(t.text, token) - {f.comparator}:
            flags.append("QUALIFIED_VALUE")
        if scale_word(t.text, token) and _unscaled(token, value):  # written, not scaled
            flags.append("SCALE_WORD")
    if at.missing:
        flags.append("PART_MISSING")
    if at.derived:
        info.add("VALUE_DERIVED")
    p = _Passed(f, "", None, key, at, flags, info, vitem.source, missing=set(at.missing))
    _roles(ctx, p, roles, fields, region)
    return p


def _find(
    t: _Text,
    item: _Item,
    at: _At,
    region: tuple[int, int],
    place: Callable[[int, int], bool] | None = None,
) -> tuple[tuple[int, int] | None, bool]:
    """Where a role item is in the value's text (SPEC §4.6), or None, and whether it is found
    there: an item with offsets whose ``text`` differs from its span is at its span, but not
    found. A unit item quote prefers its last occurrence at a unit place (``place``)."""
    if item.span is not None:
        span = _valid(t.offsets, item.span)
        if span is None:
            return None, False
        shown = item.text
        return span, shown is None or verbatim_equal(shown, t.text[span[0] : span[1]])
    assert item.text is not None
    starts, ends = _indexed(t, item.text, region)
    tok = at.token
    held = (tok.start, tok.end) if tok is not None else (at.start, at.end)
    if held[0] is not None and held[1] is not None:
        i = bisect.bisect_right(starts, held[0]) - 1  # the only one that can hold the value
        if i >= 0 and held[1] <= ends[i]:
            return (starts[i], ends[i]), True
    pos = at.pos
    if place is not None:  # a unit quote: also the occurrences that overlap, as in "$$$"
        every = quote_pattern(item.text).pattern
        seen = re.compile(f"(?=({every}))").finditer(t.text, *region)
        near = sorted({(m.start(1), m.end(1)) for m in seen if m.end(1) <= pos})
        placed = next(((a, b) for a, b in reversed(near) if place(a, b)), None)
        if placed is not None:
            return placed, True
    i = bisect.bisect_right(ends, pos)
    if i:
        return (starts[i - 1], ends[i - 1]), True
    i = bisect.bisect_left(starts, pos)
    return ((starts[i], ends[i]), True) if i < len(starts) else (None, False)


def _repeats(ctx: _Ctx, t: _Text, tok: Token, prefixes: list[str], suffixes: list[str]) -> bool:
    """Whether the field's unit is at the token, so that a unit item repeats it (SPEC §4.6)."""
    return unit_at(t.text, tok, prefixes, suffixes, ctx.policy.unit_window, ctx.suffixes)


_CHECK_ORDER = ("sign", "scale", "unit", "key")  # after the field items: the unit check reads them


LABEL_CELL_WORDS = 4  # the most words before the value in an answer slot (SPEC §4.6)
_NOT_SPACE = re.compile(r"\S")


def _field_ok(
    ctx: _Ctx,
    t: _Text,
    f: Field,
    span: tuple[int, int],
    pos: int,
    column: bool = False,
    marker: bool = False,
) -> tuple[bool, bool]:
    """Whether a field item at ``span`` passes for a value at ``pos``, and whether it is at the
    value's row (SPEC §4.6). With ``column``, a column item passes, so the item can be a row
    label. With ``marker``, a marker item passes, so a label cell can have numbers between."""
    a, b = span
    if f.aliases is None or b > pos or not t.named(f.aliases, a, b):
        return False, False
    if t.letter_after(b) >= pos:
        return True, True  # at the value's row
    text = t.text
    start, line_end = t.line(a)
    tab = t.tab_in(start, line_end)
    if column and tab >= 0 and b <= tab and pos < line_end:
        return True, False  # a row label: in slot 0 of the value's line (spec 0.12)
    end = t.token_after(b)  # no number token between the item and the value
    blocked = end is not None and end <= pos
    if tab < 0 or b > tab or pos <= tab:
        # no label slot, or the value is in it
        return not blocked and a >= sentence(text, pos)[0], False
    # the item is in a label slot and the value after it: only a label cell passes (#316)
    slot = tab + 1
    slot_end = t.tab_in(slot, line_end)
    slot_end = line_end if slot_end < 0 else slot_end
    if pos >= slot_end:
        return False, False  # a later slot or a later line
    if blocked and not (marker and _bounded(ctx, t, f, (slot, slot_end), pos)):
        return False, False
    left = sentence(text, pos)[0]
    names = ctx.aliases
    return (
        t.words_before(slot, slot_end, pos) <= LABEL_CELL_WORDS
        and (left <= slot or _NOT_SPACE.search(text, slot, left) is None)  # no sentence end
        and not (names and t.named(names, slot, pos))
    ), False


def _bounded(ctx: _Ctx, t: _Text, f: Field, slot: tuple[int, int], pos: int) -> bool:
    """Whether each run of letters after the first number token of the answer slot and before
    the value lies in a mention of a marker word of the schema or in a form of the field's unit
    (the boundary rule, SPEC §4.6, spec 0.12)."""
    end = t.token_after(slot[0])
    if end is None or end > pos:
        return True
    text = t.text
    if text[pos].isalpha():  # a run that the value cuts: read the slot up to the value
        return _covers(ctx, t, f, end, pos)[1][-1:] <= [pos]
    starts, needs = _covers(ctx, t, f, end, slot[1])
    k = bisect.bisect_left(starts, pos)  # the runs that start before the value
    return k == 0 or needs[k - 1] <= pos


def _covers(ctx: _Ctx, t: _Text, f: Field, end: int, stop: int) -> tuple[list[int], list[int]]:
    """The runs of letters in text[end:stop]: the start of each, and the furthest of the ends
    that the held spans of the runs up to it need. A run lies in a held span when the value
    starts at or after the span's end. Each slot and unit is read once (#543)."""
    key = (end, stop, f.unit)
    if key in t.bounds:
        return t.bounds[key]
    text = t.text
    held = t.within(ctx.markers, end, stop) if ctx.markers else []
    prefixes, suffixes = ctx.schema.units.get(f.unit, ([], [])) if f.unit else ([], [])
    for form in {x for x in prefixes + suffixes if any(ch.isalpha() for ch in x)}:
        i = text.find(form, end, stop)
        while i >= 0:
            held.append((i, i + len(form)))
            i = text.find(form, i + 1, stop)
    held.sort()
    starts: list[int] = []
    needs: list[int] = []
    ends: list[int] = []  # a heap of the ends of the held spans that start at or before the run
    k, i, need = 0, end, -1
    while i < stop:
        if not text[i].isalpha():
            i += 1
            continue
        j = i
        while j < stop and text[j].isalpha():
            j += 1
        while k < len(held) and held[k][0] <= i:
            heapq.heappush(ends, held[k][1])
            k += 1
        while ends and ends[0] < j:  # this span ends too soon for this run and each run after
            heapq.heappop(ends)
        need = max(need, ends[0] if ends else len(text) + 1)
        starts.append(i)
        needs.append(need)
        i = j
    t.bounds[key] = starts, needs
    return starts, needs


def _only(text: str, a: int, b: int, forms: Sequence[str]) -> bool:
    """Whether text[a:b] holds only whitespace other than tabs and line breaks, and ``forms``."""
    ordered = sorted(forms, key=len, reverse=True)
    while a < b:
        ch = text[a]
        if ch in "\t\n":
            return False
        if ch.isspace():
            a += 1
            continue
        form = next((x for x in ordered if x and text.startswith(x, a) and a + len(x) <= b), None)
        if form is None:
            return False
        a += len(form)
    return True


def _column_ok(ctx: _Ctx, t: _Text, f: Field, span: tuple[int, int], tok: Token) -> bool:
    """Whether a column item at ``span`` is a column item for the token: rules 1 to 5 of
    SPEC §4.6 (spec 0.12)."""
    if f.columns is None:
        return False
    a, b = span
    text = t.text
    head = t.slots(a)
    n = next((i for i, (x, y) in enumerate(head) if x <= a and b <= y), 0)
    if n == 0 or not t.within(f.columns, a, b):  # rule 1
        return False
    row = t.slots(tok.start)
    if len(row) != len(head) or not (row[n][0] <= tok.start and tok.end <= row[n][1]):
        return False  # rules 2 and 3: the same slot, and the same slot count
    prefixes, suffixes = ctx.schema.units.get(f.unit, ([], [])) if f.unit else ([], [])
    forms = prefixes + suffixes
    if not (_only(text, row[n][0], tok.start, forms) and _only(text, tok.end, row[n][1], forms)):
        return False  # rule 2: only the token, whitespace and unit forms in the slot
    h_end, v_start = head[-1][1], row[0][0]
    if h_end >= v_start or "\f" in text[b:h_end] or "\f" in text[v_start : tok.start]:
        return False  # rule 3: the header comes first, and no page break is on the two lines
    if any(t.within(f.columns, x, y) for i, (x, y) in enumerate(head) if i != n):
        return False  # rule 4
    return v_start <= _reach(ctx, t, head, n)


def _reach(ctx: _Ctx, t: _Text, head: list[tuple[int, int]], n: int) -> int:
    """The start of the first line after the header line that cannot stand between it and a
    value (rules 3 and 5 of column items), read once for each header slot."""
    key = (head[0][0], n)
    if key in t.reach:
        return t.reach[key]
    text = t.text
    pos = head[-1][1] + 1
    while pos <= len(text):
        line = t.slots(pos)
        x, y = line[0][0], line[-1][1]
        cell = line[n] if len(line) == len(head) else None
        if (
            cell is None
            or not text[x:y].strip()  # rule 3: a blank line
            or "\f" in text[x : y + 1]  # rule 3: a page break
            or (ctx.columns and t.within(ctx.columns, x, y))  # rule 5: a second header
            or (not tokens(text, *cell) and any(ch.isalpha() for ch in text[cell[0] : cell[1]]))
        ):
            break
        pos = y + 1
    t.reach[key] = pos
    return pos


def _next_to(
    text: str, m: tuple[int, int], tok: Token, prefixes: list[str], suffixes: list[str]
) -> bool:
    """Whether the mention ``m`` is next to the token, before or after it (SPEC §4.6)."""
    x, y = m
    if y <= tok.start:
        return _only(text, y, tok.start, [*prefixes, "(", ")"])
    return tok.end <= x and _only(text, tok.end, x, suffixes)


def _near(
    ctx: _Ctx, t: _Text, f: Field, words: tuple[str, ...], tok: Token
) -> list[tuple[int, int]]:
    """The mentions of ``words`` in the token's slot that are next to the token. Only the
    mentions that end in the gap before the token, or start in the gap after it, are read."""
    if not words:
        return []
    prefixes, suffixes = ctx.schema.units.get(f.unit, ([], [])) if f.unit else ([], [])
    text = t.text
    before, after = set("".join(prefixes)) | set("()"), set("".join(suffixes))
    q = tok.start  # no mention that ends before q is next to the token
    while q > 0 and text[q - 1] not in "\t\n" and (text[q - 1].isspace() or text[q - 1] in before):
        q -= 1
    r = tok.end  # no mention that starts after r is next to the token
    while r < len(text) and text[r] not in "\t\n" and (text[r].isspace() or text[r] in after):
        r += 1
    slot = t.slot(tok.start)
    near = t.ending(words, q, tok.start) + t.starting(words, tok.end, r)
    return [
        m
        for m in near
        if slot[0] <= m[0] and m[1] <= slot[1] and _next_to(text, m, tok, prefixes, suffixes)
    ]


def _marker_ok(ctx: _Ctx, t: _Text, f: Field, span: tuple[int, int], tok: Token) -> bool:
    """Whether a marker item at ``span`` is a marker item for the token (SPEC §4.6)."""
    if f.markers is None:
        return False
    a, b = span  # the mention lies in the item and in the token's slot
    return any(a <= x and y <= b for x, y in _near(ctx, t, f, f.markers, tok)) and not _near(
        ctx, t, f, ctx.competing.get(f.name, ()), tok
    )


def _relief(
    ctx: _Ctx, t: _Text, f: Field, at: _At, roles: Mapping[str, _Item], region: tuple[int, int]
) -> tuple[bool, bool]:
    """Whether the column item and the marker item pass at this place of the value."""
    tok = at.token
    out = []
    for role, check in (("column", _column_ok), ("marker", _marker_ok)):
        item = roles.get(role)
        ok = False
        if item is not None and tok is not None and _same(item, at.item):
            span, located = _find(t, item, at, region)
            ok = span is not None and located and check(ctx, t, f, span, tok)
        out.append(ok)
    return out[0], out[1]


def _unit_at_place(places: UnitPlaces, tok: Token) -> bool:
    """Whether a form of the unit is at a unit place of the value, before it (#249)."""
    return places(min(places.starts, default=places.line[0]), tok.start)


def _unit_relief(
    ctx: _Ctx,
    t: _Text,
    f: Field,
    at: _At,
    fields: list[_Item],
    roles: Mapping[str, _Item],
    region: tuple[int, int],
) -> bool:
    """Whether the unit is the only missing part at this place of the value, and is not missing
    there: a field item passes and a form of the unit is at a unit place (#249)."""
    tok = at.token
    if at.missing != {"unit"} or tok is None or f.unit is None:
        return False
    if not _field_passes(ctx, t, f, at, fields, roles, region):
        return False
    prefixes, suffixes = ctx.schema.units.get(f.unit, ([], []))
    return _unit_at_place(UnitPlaces(t.text, tok, prefixes, suffixes), tok)


def _field_passes(
    ctx: _Ctx,
    t: _Text,
    f: Field,
    at: _At,
    fields: list[_Item],
    roles: Mapping[str, _Item],
    region: tuple[int, int],
) -> bool:
    """Whether one of the field items passes at this place of the value (#249, #300)."""
    if f.aliases is None:
        return False
    column, marker = _relief(ctx, t, f, at, roles, region)
    for item in fields:
        if not _same(item, at.item):
            continue
        span, located = _find(t, item, at, region)
        if span is not None and located and _field_ok(ctx, t, f, span, at.pos, column, marker)[0]:
            return True
    return False


def _roles(
    ctx: _Ctx, p: _Passed, roles: dict[str, _Item], fields: list[_Item], region: tuple[int, int]
) -> None:
    """Check each role item at the value, then place the key (SPEC §4.5, §4.6). The field check
    passes when one of the field items passes (#300)."""
    at, f = p.at, p.field
    assert at is not None
    t, tok = at.t, at.token
    pos = at.pos
    prefixes, suffixes = ctx.schema.units.get(f.unit, ([], [])) if f.unit else ([], [])
    places = None
    if tok is not None and "unit" in roles:
        places = UnitPlaces(t.text, tok, prefixes, suffixes)
    conflict = _conflict(ctx, t, f.unit, tok)  # no unit is present at the token (#365)
    found: dict[str, tuple[int, int]] = {}
    passed: dict[str, bool] = {}
    row = False  # a passing field item is at the value's row: found["field"] is the first one
    column, marker = _relief(ctx, t, f, at, roles, region)  # before the field items read them
    in_column = False  # a passing field item holds a column word of the field (spec 0.12)
    checks: list[tuple[str, _Item]] = [(r, roles[r]) for r in ("column", "marker") if r in roles]
    checks += [("field", i) for i in fields] + [(r, roles[r]) for r in _CHECK_ORDER if r in roles]
    for role, item in checks:
        place = places if role == "unit" else None
        span, located = _find(t, item, at, region, place) if _same(item, at.item) else (None, False)
        ok = False
        if span is not None and located:
            if role != "field":
                found[role] = span
            a, b = span
            if role == "key":
                ok = any(
                    a <= x and y <= b and k == p.key for x, y, k in t.key_mentions(f.keys or ())
                )
            elif role == "field":
                ok, at_row = _field_ok(ctx, t, f, span, pos, column, marker)
                if ok and at_row and not row:
                    row = True
                    found["field"] = span
                if ok and f.columns is not None and t.within(f.columns, a, b):
                    in_column = True
            elif role == "column":
                ok = column
            elif role == "marker":
                ok = marker
            elif tok is None:
                ok = False  # a sign, scale or unit item on a string field
            elif role == "sign":
                br = brackets_around(t.text, tok, prefixes)
                if br is not None and a <= br[0] and br[1] <= b:
                    ok = True
                elif b <= tok.start and loss_sign(t.text, a, b, tok.start):
                    s0, _ = sentence(t.text, tok.start)
                    between = t.text[a : tok.start]
                    ok = (
                        a >= s0
                        and not tokens(t.text, a, tok.start)
                        and "\n" not in between
                        and "\t" not in between
                        and not gain_word(t.text, a, tok.start)
                    )
            elif role == "scale":
                ok = (
                    (
                        scale_form(t.text, a, b, f.unit, prefixes + suffixes)
                        or currency_scale(t.text, a, b)
                    )
                    and b <= tok.start
                    and not code_scale_cut(t.text, a, b)
                    and not scale_between(t.text, b, tok.start, item_scale(t.text, a, b))
                )
            elif role == "unit":
                ok = (
                    (
                        f.unit is not None
                        and holds_form(t.text, a, b, prefixes + suffixes)
                        and (
                            _repeats(ctx, t, tok, prefixes, suffixes)
                            or (
                                passed.get("field", False)
                                and b <= tok.start
                                and not ctx.any_unit_at(t, tok)
                                and places is not None
                                and places(a, b)
                            )
                        )
                    )
                    or (
                        f.unit is not None
                        and passed.get("field", False)
                        and b <= tok.start
                        and not ctx.any_unit_at(t, tok)
                        and _heading_unit(ctx, t, f.unit, tok, a, b)
                    )
                    or (
                        # a unit with no form is at every token: its name repeats it (#423)
                        f.unit is not None
                        and not prefixes
                        and not suffixes
                        and currency_name(t.text, a, b, f.unit)
                    )
                )
                ok = ok and not conflict  # a heading conflict: the item fails (#365)
        passed[role] = ok or (role == "field" and passed.get("field", False))
        byte_span = None if span is None else _bytes(t, span)
        p.parts.append(Part(role, byte_span, ok))
        if role in ("field", "column", "marker"):
            continue  # flagged once, below, or not at all
        if not ok:
            p.flags.append(f"{role.upper()}_CITATION_INVALID")
    if fields and f.aliases is not None and not passed["field"]:
        p.flags.append("FIELD_CITATION_INVALID")  # no field item passes
    if f.columns is not None and not column and not in_column:
        p.flags.append("COLUMN_NOT_AT_VALUE")  # the value is not in a column of the field
    competing = ctx.competing.get(f.name, ())
    other = f.markers is not None and tok is not None and _near(ctx, t, f, competing, tok)
    if other and tok is not None and not _near(ctx, t, f, f.markers or (), tok):
        p.flags.append("MARKER_OTHER_FIELD")  # a marker word of another field at the value
    if (
        "unit" in p.missing
        and passed.get("field")
        and tok is not None
        and f.unit is not None
        and not conflict
    ):
        # a form of the unit at a unit place of the value, as for a unit item (#249)
        if places is None:
            places = UnitPlaces(t.text, tok, prefixes, suffixes)
        if _unit_at_place(places, tok):
            p.missing.discard("unit")
            if not p.missing:
                p.flags.remove("PART_MISSING")
    if f.keys is None:
        return
    mentions = t.key_mentions(f.keys)
    held = keys_at(t.text, mentions, pos)
    ok_key = p.key in held
    if not held and passed.get("key") and passed.get("field") and row:
        a, b = found["key"]
        mine = next(x for x, y, k in mentions if a <= x and y <= b and k == p.key)
        run = header(t.text, mentions, mine)
        n = [x for x, _ in run].index(mine) + 1
        fa, fb = found["field"]
        line_end = t.text.find("\n", fb, pos)
        line_end = pos if line_end < 0 else line_end
        note = any("\t" not in t.text[fb : k.start] for k in tokens(t.text, fb, line_end))
        prior = cells(t.text, fb, pos, prefixes)
        same_line = "\n" not in t.text[fb:pos]
        if (
            run[-1][1] <= fa
            and header_column(t.text, mentions, run)
            and not key_break(t.text, run[-1][1], pos)
            and not any(run[-1][1] <= x and y <= fa for x, y, _ in mentions)
            and not note  # a number after the row label on its line, such as a footnote "(1)"
            and (not same_line or "\t" in t.text[fb:pos])
            and prior is not None
            and len(prior) == n - 1
        ):
            ok_key = p.cited = True
    if not ok_key:
        p.flags.append("KEY_NOT_AT_VALUE")
        if "key" not in roles:
            p.missing.add("key")


def _outside(
    ctx: _Ctx,
    f: Field,
    value: Decimal | str,
    key: str | None,
    items: list[_Item],
    key_item: bool,
) -> _Passed:
    """The outside path (SPEC §3.2)."""
    holding: list[tuple[_Item, _At | None]] = []
    for item in items:
        if item.source == "knowledge":
            holding.append((item, None))
            continue
        assert item.text is not None
        t = _Text(item.text, Offsets(item.text))
        at, _ = _value_at(ctx, item, t, f, value, (0, len(t.text)), {}, lenient=False)
        if at is not None:
            holding.append((item, at))
    if not holding:
        raise _Reject("VALUE_NOT_IN_EVIDENCE")
    src = ctx.policy.sources

    def action(item: _Item) -> Action:
        if item.source == "knowledge":
            return src.knowledge
        assert item.url is not None
        for entry in src.allow:
            if entry == "document-domain":
                if ctx.source_host is not None and host(item.url) == ctx.source_host:
                    return "admit"
            elif entry == "*" or item.url.startswith(entry):
                return "admit"
        return src.other

    ranked = sorted(
        enumerate(holding),
        key=lambda x: (_ACTION_RANK[action(x[1][0])], x[1][0].source != "external", x[0]),
    )
    item, at = ranked[0][1]
    act = action(item)
    if act == "reject":
        raise _Reject("SOURCE_REJECTED", item=item)
    p = _Passed(f, "", None, key, None, [], set(), item.source, url=item.url)
    tok = at.token if at is not None else None
    if at is not None and tok is not None:
        if qualifiers(at.t.text, tok) - {f.comparator}:
            p.flags.append("QUALIFIED_VALUE")
        if scale_word(at.t.text, tok) and _unscaled(tok, value):
            p.flags.append("SCALE_WORD")
    if (
        at is not None
        and f.keys is not None
        and key not in keys_at(at.t.text, at.t.key_mentions(f.keys), at.pos)
    ):
        p.flags.append("KEY_NOT_AT_VALUE")
        if not key_item:
            p.missing.add("key")
    # The deciding item is chosen as if no heading unit reached a token. Then a heading conflict
    # in its text makes the unit missing, and the action does not change. A knowledge item has
    # no text that groundgate reads, so it has no heading conflict (spec 0.11, #367).
    if at is not None and _conflict(ctx, at.t, f.unit, tok):
        p.missing.add("unit")
        p.flags.append("PART_MISSING")
    if act == "review":
        p.flags.append("EVIDENCE_QUOTED" if item.source == "external" else "EVIDENCE_STATED")
    else:
        p.info.add("ADMITTED_BY_POLICY")
    return p


@dataclass(frozen=True)
class _Judgment:
    question: str
    judge: tuple[str, str]
    answer: str | None
    p: float


def _judgments(raw: object, candidates: Sequence[object]) -> dict[int, dict[str, _Judgment]]:
    """The recorded judgments (SPEC §2.6) by candidate position and question."""
    if raw is None:
        return {}
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise PacketError("judgments must be a list")
    ids: dict[tuple[type, object], list[int]] = defaultdict(list)
    for i, cand in enumerate(candidates):
        cid = cand.get("id") if isinstance(cand, Mapping) else None
        if isinstance(cid, (str, int)) and not isinstance(cid, bool):
            ids[type(cid), cid].append(i)
    out: dict[int, dict[str, _Judgment]] = defaultdict(dict)
    for n, j in enumerate(raw):
        where = f"judgment {n}"
        if not isinstance(j, Mapping):
            raise PacketError(f"{where} must be an object")
        known = {"candidate_id", "question", "judge", "p"} | (
            {"answer"} if j.get("question") == "key" else set()
        )
        if set(j) - known:
            raise PacketError(f"{where} has unknown keys {sorted(set(j) - known)}")
        question, judge, p = j.get("question"), j.get("judge"), j.get("p")
        if question not in QUESTIONS:
            raise PacketError(f"{where}: question must be one of {list(QUESTIONS)}")
        if (
            not isinstance(judge, Mapping)
            or set(judge) != {"id", "digest"}
            or not all(isinstance(judge[k], str) and judge[k].strip() for k in judge)
        ):
            raise PacketError(f"{where}: judge must hold a non-blank id and digest")
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
            raise PacketError(f"{where}: p must be a number in [0, 1]")
        answer = j.get("answer")
        if question == "key" and ("answer" not in j or not isinstance(answer, (str, type(None)))):
            raise PacketError(f"{where}: a key judgment needs an answer, a key or null")
        cid = j.get("candidate_id")
        if isinstance(cid, bool) or not isinstance(cid, (str, int)):
            raise PacketError(f"{where}: candidate_id must be a string or an integer")
        at = ids.get((type(cid), cid), [])
        if len(at) != 1:
            raise PacketError(f"{where}: {len(at)} candidates have the id {cid!r}, not 1")
        if question in out[at[0]]:
            raise PacketError(f"{where}: the candidate has a {question} judgment already")
        out[at[0]][question] = _Judgment(question, (judge["id"], judge["digest"]), answer, float(p))
    return out


def _judge(policy: Policy, p: _Passed, js: dict[str, _Judgment]) -> list[_Judgment]:
    """Step 12: apply the recorded judgments of one candidate; return those that applied."""
    jp = policy.judge
    if jp is None:
        return []
    applied = []
    for j in js.values():
        if j.judge != (jp.id, jp.digest):
            continue
        if j.question == "key" and jp.clear_key is not None:
            applied.append(j)
            if j.p < jp.clear_key:
                continue
            if "KEY_NOT_AT_VALUE" in p.flags:
                if j.answer == p.key:
                    p.flags.remove("KEY_NOT_AT_VALUE")
                    p.cleared = True
                else:
                    p.flags.append("MODEL_DOUBT")
            elif p.cited and j.answer != p.key:  # a judge that names another key doubts a citation
                p.flags.append("MODEL_DOUBT")
        elif j.question == "field_match" and jp.doubt_field is not None:
            applied.append(j)
            if j.p < jp.doubt_field:
                p.flags.append("MODEL_DOUBT")
    return applied


def _references(raw: object) -> dict[str, tuple[_Text, str | None]]:
    """The packet's references (SPEC §2.1), or PacketError."""
    if raw is None:
        return {}
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise PacketError("references must be a list")
    out: dict[str, tuple[_Text, str | None]] = {}
    for n, r in enumerate(raw):
        where = f"reference {n}"
        if not isinstance(r, Mapping) or set(r) - {"id", "text", "source"}:
            raise PacketError(f"{where} must be an object with id, text and source")
        rid, text, source = r.get("id"), r.get("text"), r.get("source")
        if not isinstance(rid, str) or not rid.strip() or rid in out:
            raise PacketError(f"{where}: id must be a unique non-blank string")
        if not isinstance(text, str) or not text or not is_nfc(text):
            raise PacketError(f"{where}: text must be a non-empty string in Unicode NFC")
        if source is not None and not (isinstance(source, str) and source.strip()):
            raise PacketError(f"{where}: source must be a non-blank string or null")
        out[rid] = (_Text(text, Offsets(text), rid), source)
    return out


def _check_integers(value: object, path: str) -> None:
    """Reject integers without a canonical JSON form before any digest (SPEC §6)."""
    if isinstance(value, int):
        if not -(2**53 - 1) <= value <= 2**53 - 1:
            raise PacketError(f"{path}: integer is outside [-(2^53-1), 2^53-1]")
    elif isinstance(value, Mapping):
        for key, member in value.items():
            _check_integers(member, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for i, member in enumerate(value):
            _check_integers(member, f"{path}[{i}]")


def admit(
    text: str,
    schema: Schema | Mapping[str, Any],
    candidates: Sequence[object],
    policy: Policy | Mapping[str, Any] | None = None,
    document_id: str | None = None,
    judgments: Sequence[object] | None = None,
    *,
    references: Sequence[object] | None = None,
    document_source: str | None = None,
    packs: Sequence[object] = (),
) -> Receipt:
    """Decide every candidate and return the receipt.

    ``text`` is the document in Unicode NFC. ``schema`` and ``policy`` are dicts or ``Schema`` and
    ``Policy`` objects; ``policy=None`` uses the defaults. ``candidates`` is a list of candidate
    dicts whose evidence is a list of evidence items (SPEC §2.5). A malformed candidate gets a
    ``rejected`` decision unless it contains an integer outside the range in SPEC §6, which
    makes the packet invalid. ``document_id`` is copied into the receipt.
    ``judgments`` are recorded answers of a judge (SPEC §2.6); the policy's ``judge`` block says
    which apply. ``references`` are other source texts that the app supplies, and
    ``document_source`` is the URL of the document (SPEC §2.1). ``packs`` are the vocabulary
    packs that the schema names, as pack objects (SPEC §4.8).

    Raises ``PacketError`` when the text is not NFC, ``candidates`` is not a list, or the schema,
    policy, judgments, references, document source or packs are invalid. Then no receipt is made.
    """
    if not isinstance(text, str) or not is_nfc(text):
        raise PacketError("document text must be a string in Unicode NFC")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise PacketError("candidates must be a list")
    _check_integers(candidates, "candidates")
    _check_integers(document_id, "document_id")
    _check_integers(references, "references")
    _check_integers(judgments, "judgments")
    _check_integers(policy.to_dict() if isinstance(policy, Policy) else policy, "policy")
    if not isinstance(schema, Schema):
        schema = Schema.from_dict(schema, packs)
    elif packs:
        raise PacketError("give the packs to Schema.from_dict when the schema is a Schema")
    if not isinstance(policy, Policy):
        policy = Policy() if policy is None else Policy.from_dict(policy)
    if document_source is not None and not (
        isinstance(document_source, str) and document_source.strip()
    ):
        raise PacketError("document source must be a non-blank string or null")
    refs = _references(references)
    by_cand = _judgments(judgments, candidates)
    with using(schema.vocabulary):
        return _admit(text, schema, candidates, policy, document_id, refs, by_cand, document_source)


def _admit(
    text: str,
    schema: Schema,
    candidates: Sequence[object],
    policy: Policy,
    document_id: str | None,
    refs: dict[str, tuple[_Text, str | None]],
    by_cand: dict[int, dict[str, Any]],
    document_source: str | None,
) -> Receipt:
    table = frozenset(x for _, suffixes in schema.units.values() for x in suffixes)
    ctx = _Ctx(
        _Text(text, Offsets(text)),
        {rid: t for rid, (t, _) in refs.items()},
        schema,
        policy,
        None if document_source is None else host(document_source),
        suffixes=table,
        aliases=tuple(dict.fromkeys(a for f in schema.fields.values() for a in f.aliases or ())),
        columns=tuple(dict.fromkeys(c for f in schema.fields.values() for c in f.columns or ())),
        markers=tuple(dict.fromkeys(m for f in schema.fields.values() for m in f.markers or ())),
        competing=_competing(schema),
    )

    results: list[tuple[str, int, object, _Passed | _Reject]] = []
    with sentence_index():  # the texts leave the index when the candidates are checked
        for i, cand in enumerate(candidates):
            try:
                outcome: _Passed | _Reject = _check(ctx, cand)
            except _Reject as r:
                outcome = r
            results.append((digest("candidate", cand), i, cand, outcome))

    by_key: dict[tuple[str, str | None], set[tuple[str, str | None]]] = defaultdict(set)
    for *_, p in results:
        if isinstance(p, _Passed) and not p.field.multiple:
            by_key[p.field.name, p.key].add((p.value, p.unit))
    for *_, p in results:
        if isinstance(p, _Passed) and len(by_key.get((p.field.name, p.key), ())) > 1:
            p.flags.append("CONFLICTING_CANDIDATES")

    relations = _relate(schema.relations, [p for *_, p in results if isinstance(p, _Passed)])

    decisions: list[Decision] = []
    applied: list[Judgment] = []
    read = _PackMarks(schema, [text, *(t.text for t, _ in refs.values())])
    for sha, i, cand, p in sorted(results, key=lambda r: (r[0], r[1])):
        if isinstance(p, _Passed):
            for j in sorted(_judge(policy, p, by_cand.get(i, {})), key=lambda j: j.question):
                applied.append(Judgment(sha, j.question, j.answer, j.p))
        cid = cand.get("id") if isinstance(cand, Mapping) else None
        d = _decision(ctx, sha, cand, cid, p)
        decisions.append(dataclasses.replace(d, packs=read.packs(cand)) if schema.packs else d)

    live = {d.field for d in decisions if d.outcome != "rejected"}
    coverage = tuple(
        (name, "REQUIRED_FIELD_MISSING")
        for name in sorted(schema.fields)
        if schema.fields[name].required and name not in live
    )
    draft = Receipt(
        document_id,
        digest("document", {"text": text}),
        digest("schema", schema.to_dict()),
        digest("policy", policy.to_dict()),
        tuple(decisions),
        coverage,
        "",
        tuple(applied),
        document_source,
        tuple(
            (rid, digest("reference", {"text": t.text}), source)
            for rid, (t, source) in sorted(refs.items())
        ),
        relations if schema.relations else None,
        packs=schema.packs,
    )
    return Receipt(**{**draft.__dict__, "receipt_sha256": digest("receipt", draft.body())})


def _place(p: _Passed) -> Fraction:
    """One unit of the last written digit of a passed value, times the scale that the value
    takes from its token (SPEC §3.4). On the outside path, that of the canonical value."""
    tok = None if p.at is None else p.at.token
    if tok is None or tok.value is None:
        exponent = Decimal(p.value).as_tuple().exponent
        assert isinstance(exponent, int)
        return Fraction(10) ** min(exponent, 0)
    exponent = tok.value.as_tuple().exponent
    assert isinstance(exponent, int)
    place = Fraction(10) ** exponent
    if tok.value != 0:
        place *= abs(Fraction(Decimal(p.value))) / abs(Fraction(tok.value))
    return place


def _decimal(x: Fraction) -> str:
    """The canonical decimal of an exact sum of decimals (SPEC §4.1)."""
    d = x.denominator  # 2^a * 5^b, because every input is a decimal
    twos = (d & -d).bit_length() - 1
    fives = d >> twos
    b = max(0, round((fives.bit_length() - 1) / 2.321928094887362))  # log2(5)
    while 5**b < fives:
        b += 1
    while b and 5 ** (b - 1) >= fives:
        b -= 1
    assert 5**b == fives
    digits = max(twos, b)
    # Decimal(int) and scaleb do not convert the int to a string, so no digit limit applies.
    exact = Context(prec=MAX_PREC, traps=[Inexact])
    return canonical(Decimal(x.numerator * (10**digits // d)).scaleb(-digits, exact))


def _relate(relations: tuple[Relation, ...], passed: list[_Passed]) -> tuple[RelationResult, ...]:
    """Step 13: check each relation at each relation key, and flag the values of each relation
    that fails (SPEC §3.4). The values come from the candidates that passed."""
    by: dict[tuple[str, str | None], list[_Passed]] = defaultdict(list)
    for p in passed:
        by[p.field.name, p.key].append(p)
    keys_of: dict[str, set[str | None]] = defaultdict(set)
    for name, key in by:
        keys_of[name].add(key)
    out: list[RelationResult] = []
    for r in sorted(relations, key=lambda r: r.id):
        keys = sorted(keys_of.get(r.total, set()), key=lambda k: "" if k is None else k)
        for key in keys:
            values: list[tuple[Fraction, Fraction]] = []  # (value, place) of each field
            for name in r.fields:
                ps = by.get((name, key), [])
                if len({p.value for p in ps}) != 1:
                    break  # no value that passed, or two values: the relation does not apply
                values.append((Fraction(Decimal(ps[0].value)), min(_place(p) for p in ps)))
            else:
                (total, total_place), parts = values[0], values[1:]
                factors = [Fraction(f) for _, f in r.parts]
                difference = total - sum(
                    (f * v for f, (v, _) in zip(factors, parts, strict=True)), Fraction(0)
                )
                allowance = Fraction(r.tolerance) + total_place / 2
                allowance += sum(
                    (abs(f) * place / 2 for f, (_, place) in zip(factors, parts, strict=True)),
                    Fraction(0),
                )
                holds = abs(difference) <= allowance
                if not holds:
                    for name in r.fields:
                        for p in by[name, key]:
                            if "RELATION_FAILED" not in p.flags:
                                p.flags.append("RELATION_FAILED")
                out.append(
                    RelationResult(r.id, key, holds, _decimal(difference), _decimal(allowance))
                )
    return tuple(out)


def _competing(schema: Schema) -> dict[str, tuple[str, ...]]:
    """The competing words of each field with markers: the marker words of another field that
    are not marker words of this field, after whitespace normalisation and the fold (§4.6)."""
    out = {}
    for f in schema.fields.values():
        if f.markers is None:
            continue
        own = {fold_text(normalize_ws(m)) for m in f.markers}
        words = (m for g in schema.fields.values() if g is not f for m in g.markers or ())
        other = (m for m in words if fold_text(normalize_ws(m)) not in own)
        out[f.name] = tuple(dict.fromkeys(other))
    return out


def _fold(s: str) -> str:
    """A text as the pack marks compare it (SPEC §5): the four look-alikes of SPEC §4 folded,
    then casefolded, each whitespace run one space. So it never misses a word that a rule
    matches by the fold of its letters (#356)."""
    return mark_fold(s)


def _strings(obj: object) -> list[str]:
    """Each string in a candidate, keys included, and each number and boolean as text."""
    out: list[str] = []
    stack = [obj]
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, Mapping):
            stack.extend(k for k in x if isinstance(k, str))
            stack.extend(x.values())
        elif isinstance(x, (list, tuple)):
            stack.extend(x)
        elif isinstance(x, (bool, int, float)):
            out.append(str(x))  # step 3 reads str(value): a null literal can be "0" or "true"
    return out


class _PackMarks:
    """The packs that a decision read (SPEC §5): each pack that adds a word that occurs in the
    document, in a reference or in the candidate. A pack can be named when its word did not
    change the outcome. That error is safe: a report then marks one value too many."""

    def __init__(self, schema: Schema, texts: list[str]) -> None:
        self.marks = schema.marks
        self.fields = schema.fields
        folded = "\n".join(_fold(t) for t in texts)
        self.found = {pid for pid, words in self.marks if any(w in folded for w in words)}

    def packs(self, cand: object) -> tuple[str, ...]:
        folded = "\n".join(_fold(s) for s in _strings(cand))
        more = {
            pid
            for pid, words in self.marks
            if pid not in self.found and any(w in folded for w in words)
        }
        name = cand.get("field") if isinstance(cand, Mapping) else None
        field = self.fields.get(name) if isinstance(name, str) else None
        if field is not None and field.template is not None:
            more.add(field.template.split("/", 1)[0])  # the kind pack gave the template
        return tuple(sorted(self.found | more))


def _bytes(t: _Text, span: tuple[int, int]) -> tuple[int, int]:
    return t.offsets.to_bytes(span[0]), t.offsets.to_bytes(span[1])


_UNIT_CODES = frozenset({"UNIT_NOT_IN_EVIDENCE", "UNIT_CITATION_INVALID"})


def _evidence_units(
    ctx: _Ctx, at: _At | None, codes: tuple[str, ...], missing: tuple[str, ...]
) -> EvidenceUnits | None:
    """The units that groundgate finds for the token when the unit check does not pass, or None
    (SPEC §5, spec 0.10, #362). A report only: it never changes the outcome or the codes."""
    if at is None or at.token is None or not (_UNIT_CODES & set(codes) or "unit" in missing):
        return None
    t, tok, units = at.t, at.token, ctx.schema.units
    near, per = units_next(t.text, tok, units, ctx.policy.unit_window)
    if t.headings is None:
        t.headings = HeadingIndex(t.text)
    headers, statements, currency = t.headings.report(tok.start, units)
    return EvidenceUnits(_bytes(t, (tok.start, tok.end)), near, per, headers, statements, currency)


def _decision(ctx: _Ctx, sha: str, cand: object, cid: object, p: _Passed | _Reject) -> Decision:
    if isinstance(p, _Passed):
        flags = [c for c in FLAG_ORDER if c in p.flags]
        info = (
            p.info
            | ({"KEY_CITED"} if p.cited else set())
            | ({"MODEL_CLEARED"} if p.cleared else set())
        )
        outcome: Outcome = "needs_verification" if flags else "admitted"
        at = p.at
        codes = (*flags, *(c for c in INFO_ORDER if c in info))
        missing = tuple(m for m in MISSING_ORDER if m in p.missing)
        return Decision(
            _json_id(cid),
            sha,
            p.field.name,
            outcome,
            codes,
            p.value,
            p.unit,
            None if at is None else _bytes(at.t, at.span),
            p.key,
            p.source,
            None if at is None else at.item.ref,
            p.url,
            tuple(sorted(p.parts, key=lambda x: PART_ORDER.index(x.role))),
            missing,
            evidence_units=_evidence_units(ctx, at, codes, missing),
        )
    # rejected: report what is known about the candidate
    field_name: str | None = None
    value: str | None = None
    unit: str | None = None
    span: tuple[int, int] | None = None
    key: str | None = None
    source = ref = url = None
    if isinstance(cand, Mapping):
        if isinstance(cand.get("field"), str):
            field_name = cand["field"]
        if isinstance(cand.get("unit"), str):
            unit = cand["unit"]
        f = ctx.schema.fields.get(field_name or "")
        if f is not None and f.keys is not None and isinstance(cand.get("key"), str):
            key = cand["key"]
        raw = cand.get("value")
        if f is not None and isinstance(raw, (str, int)) and not isinstance(raw, bool):
            if f.type == "string" and isinstance(raw, str) and normalize_ws(raw):
                value = normalize_ws(raw)
            elif f.type != "string" and (parsed := parse_value(str(raw))) is not None:
                value = canonical(parsed)
    if p.at is not None:
        span, source, ref = _bytes(p.at.t, p.at.span), p.at.item.source, p.at.item.ref
    else:
        if p.item is not None:
            source, ref, url = p.item.source, p.item.ref, p.item.url
        if isinstance(cand, Mapping):
            cited = _cited(ctx, cand.get("evidence"))
            if cited is not None:  # the value item names the text of its span
                span = cited[0]
                if source is None:
                    source, ref = cited[1], cited[2]
    return Decision(
        _json_id(cid), sha, field_name, "rejected", (p.code,), value, unit, span, key, source, ref,
        url, evidence_units=_evidence_units(ctx, p.at, (p.code,), ()),
    )  # fmt: skip


def _cited(ctx: _Ctx, ev: object) -> tuple[tuple[int, int] | None, str, str | None] | None:
    """The value item's span when its offsets are valid in its text (else None), with the item's
    source and ref; None when the evidence has no value item (SPEC §5)."""
    try:
        items = _items(ev, ctx.refs)
    except _Reject:
        return None
    for it in items:
        if it.role == "value":
            t = ctx.doc if it.source == "document" else ctx.refs[it.ref or ""]
            valid = it.span is not None and _valid(t.offsets, it.span) is not None
            return (it.span if valid else None), it.source, it.ref
    return None


def _json_id(cid: object) -> object:
    return (
        cid if cid is None or (isinstance(cid, (str, int)) and not isinstance(cid, bool)) else None
    )


@dataclass(frozen=True)
class Verification:
    ok: bool
    problems: tuple[str, ...]


def verify(
    receipt: Mapping[str, Any],
    text: str,
    schema: Schema | Mapping[str, Any],
    candidates: Sequence[object],
    policy: Policy | Mapping[str, Any] | None = None,
    judgments: Sequence[object] | None = None,
    *,
    references: Sequence[object] | None = None,
    document_source: str | None = None,
    packs: Sequence[object] = (),
    pack_dir: str | os.PathLike[str] | None = None,
) -> Verification:
    """Re-derive the receipt from its inputs and compare it with ``receipt``.

    ``receipt`` is the JSON object that ``Receipt.to_dict()`` returned. The other arguments are
    the inputs given to ``admit``, with the same ``judgments``, ``references``,
    ``document_source`` and ``packs``. The result has ``ok`` and
    ``problems``: ``(True, ())`` when every byte re-derives. A receipt from another spec version
    gives one problem and no further
    checks. Raises ``PacketError`` when ``receipt`` is not a JSON object or an input is invalid.

    ``verify`` finds each pack that the receipt names by its id, version and digest: a built-in
    pack, then a pack in ``packs``, then a pack file in the folder ``pack_dir``. The folder is
    untrusted. ``verify`` reads only its ``.json`` files, follows no link, and uses a file only
    when its computed digest is the digest in the receipt. A pack that is not found, or a pack
    with another digest, gives a problem and no further checks (docs/design/packs.md §11).
    ``verify`` also reads a retired built-in version, which ``admit`` refuses.
    """
    if not isinstance(receipt, Mapping):
        raise PacketError("receipt must be a JSON object")
    _check_integers(receipt, "receipt")
    if (version := receipt.get("groundgate")) != SPEC_VERSION:
        problem = f"receipt was decided under spec {version}; this groundgate implements "
        return Verification(False, (problem + SPEC_VERSION,))
    problems = []
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if digest("receipt", body) != receipt.get("receipt_sha256"):
        problems.append("receipt_sha256 does not match the receipt body")
    if isinstance(schema, Schema):
        if pack_dir is not None:
            raise PacketError("give the schema as a dict when you give a pack folder")
        given: list[dict[str, Any]] = list(schema.given)
    else:
        if isinstance(packs, (str, bytes, dict)) or not isinstance(packs, Sequence):
            raise PacketError("packs must be a list of pack objects")
        given = [checked_copy(p) for p in packs]
    found, pack_problems = receipt_packs(receipt.get("packs"), given, pack_dir)
    if pack_problems:
        return Verification(False, (*problems, *pack_problems))
    if found and isinstance(schema, Mapping):
        keep = schema_named(schema.get("packs"), [*given, *found])
        found = [p for p in found if (p["id"], p["version"]) in keep]
    doc_id = (
        receipt.get("document", {}).get("id")
        if isinstance(receipt.get("document"), Mapping)
        else None
    )
    with reading_retired():
        fresh = admit(
            text,
            schema,
            candidates,
            policy,
            doc_id,
            judgments,
            references=references,
            document_source=document_source,
            packs=[*packs, *found],
        ).to_dict()
    for key in (
        "document",
        "references",
        "packs",
        "schema_sha256",
        "policy_sha256",
        "coverage",
        "judgments",
        "relations",
        "summary",
    ):
        if receipt.get(key) != fresh.get(key):
            problems.append(f"{key} differs from the re-derived receipt")
    theirs, ours = receipt.get("decisions"), fresh["decisions"]
    if not isinstance(theirs, list) or len(theirs) != len(ours):
        problems.append("decision count differs from the re-derived receipt")
    else:
        for a, b in zip(theirs, ours, strict=True):
            if a != b:
                problems.append(f"decision for candidate {b['candidate_sha256']} differs")
    if not problems and receipt.get("receipt_sha256") != fresh["receipt_sha256"]:
        problems.append("receipt_sha256 differs from the re-derived receipt")  # pragma: no cover
    return Verification(not problems, tuple(problems))
