"""The decision procedure (SPEC §3) and receipts (SPEC §5)."""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .canonical import SPEC_VERSION, Offsets, digest, is_nfc
from .model import (
    Action,
    Decision,
    Field,
    Judgment,
    Outcome,
    PacketError,
    Part,
    Policy,
    Receipt,
    Schema,
)
from .text import (
    Token,
    brackets_around,
    canonical,
    cells,
    form_next,
    gain_word,
    header,
    holds_form,
    host,
    in_scale,
    item_scale,
    key_mentions,
    keys_at,
    loss_sign,
    normalize_ws,
    parse_value,
    qualifiers,
    quote_pattern,
    scale_word,
    scaled_value,
    sentence,
    tokens,
    unit_at,
    verbatim_equal,
)

NULL_LITERALS = {"null", "none", "nil", "n/a"}
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
    "EVIDENCE_QUOTED",
    "EVIDENCE_STATED",
    "LOW_CONFIDENCE",
    "CONFLICTING_CANDIDATES",
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
ROLES = ("value", "sign", "scale", "unit", "key", "field")
PART_ORDER = ("sign", "scale", "unit", "field", "key")  # SPEC §5 `parts`
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


@dataclass
class _Text:
    """A text that evidence items point into: the document, a reference, or an external quote."""

    text: str
    offsets: Offsets
    ref: str | None = None
    mentions: dict[tuple[str, ...], list[tuple[int, int, str]]] = field(default_factory=dict)

    def key_mentions(self, words: tuple[str, ...]) -> list[tuple[int, int, str]]:
        if words not in self.mentions:
            self.mentions[words] = key_mentions(self.text, words)
        return self.mentions[words]


@dataclass
class _Ctx:
    doc: _Text
    refs: dict[str, _Text]
    schema: Schema
    policy: Policy
    source_host: str | None
    suffixes: frozenset[str] = frozenset()  # of every unit in the table (SPEC §4.3)

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
            if any(o.role == role and o.source in ("document", "reference") for o in out):
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
    out = {tok.value} if sv is None else {tok.value, sv}
    if sv is None and scale is not None:
        out.add(tok.value.scaleb(scale))
    neg = neg_item or (prefixes is not None and brackets_around(t.text, tok, prefixes) is not None)
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
) -> tuple[_At | None, str | None]:
    """Steps 10-11 at one span: where the value is, or a failure code. ``lenient`` lets a part
    be missing (SPEC §3.1)."""
    s, e = span
    if f.type == "string":
        assert isinstance(value, str)
        if normalize_ws(value) not in normalize_ws(t.text[s:e]):
            return None, "VALUE_NOT_IN_EVIDENCE"
        return _At(item, t, span, None), None
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
    hits: list[tuple[Token, set[str]]] = []
    for k in toks:
        vals, _ = _values(t, k, neg_item, scale, signs)
        if value in vals:
            hits.append((k, set()))
    if not hits and lenient:
        for k in toks:
            need = _missing(t, k, value, neg_item, scale_item is not None, scale, signs)
            if need is not None:
                hits = [(k, need)]
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
    return None, "UNIT_NOT_IN_EVIDENCE"


def _unscaled(tok: Token, value: Decimal | str) -> bool:
    """The value is the number as written, with any sign, not its scaled value (SCALE_WORD)."""
    return tok.value is not None and isinstance(value, Decimal) and abs(tok.value) == abs(value)


def _same(a: _Item, b: _Item) -> bool:
    """Whether two items are in the same text."""
    return a.source == b.source and a.ref == b.ref


def _occurrences(t: _Text, quote: str, region: tuple[int, int]) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in quote_pattern(quote).finditer(t.text, *region)]


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
    if text_value.strip().lower() in NULL_LITERALS:
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
    checked = {i.role or "value": i for i in items if i.source in ("document", "reference")}
    outside = [i for i in items if i.source in ("external", "knowledge")]
    vitem = checked.pop("value", None)
    if vitem is None and not outside:
        raise _Reject("NO_EVIDENCE")
    canon = value if isinstance(value, str) else canonical(value)
    if vitem is None:
        p = _outside(ctx, f, value, key, outside, "key" in checked)
        p.value, p.unit = canon, unit
    else:
        p = _checked(ctx, f, value, key, vitem, checked, region_span)
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
    region_span: tuple[int, int] | None,
) -> _Passed:
    """The checked path (SPEC §3.1) and the role checks (SPEC §4.6)."""
    t = ctx.doc if vitem.source == "document" else ctx.refs[vitem.ref or ""]
    # 9. spans
    search = (0, len(ctx.doc.text)) if region_span is None else _valid(ctx.doc.offsets, region_span)
    if search is None:
        raise _Reject("SPAN_INVALID", item=vitem)
    region = search if t is ctx.doc else (0, len(t.text))
    flags: list[str] = []
    info: set[str] = set()
    if vitem.span is None:
        # 9a. a quote: the first occurrence where steps 10-11 pass, else the first occurrence
        assert vitem.text is not None
        found = _occurrences(t, vitem.text, region)
        if not found:
            raise _Reject("QUOTE_NOT_FOUND", item=vitem)
        at: _At | None = None
        for occ in found:
            at, _ = _value_at(ctx, vitem, t, f, value, occ, roles, lenient=False)
            if at is not None:
                break
        if at is None:
            at, failure = _value_at(ctx, vitem, t, f, value, found[0], roles, lenient=True)
            if at is None:
                assert failure is not None
                raise _Reject(failure, _At(vitem, t, found[0], None))
    else:
        span = _valid(t.offsets, vitem.span)
        if span is None:
            raise _Reject("SPAN_INVALID", item=vitem)
        # 10-11. value and unit at the evidence, with re-anchoring
        at, failure = _value_at(ctx, vitem, t, f, value, span, roles, lenient=False)
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
            if at is None:
                at, failure = _value_at(ctx, vitem, t, f, value, span, roles, lenient=True)
            if at is None:
                assert failure is not None
                raise _Reject(failure, _At(vitem, t, span, None))
        if vitem.text is not None and not verbatim_equal(
            vitem.text, t.text[at.span[0] : at.span[1]]
        ):
            flags.append("NON_VERBATIM_EVIDENCE")
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
    _roles(ctx, p, roles, region)
    return p


def _find(
    t: _Text, item: _Item, at: _At, region: tuple[int, int]
) -> tuple[tuple[int, int] | None, bool]:
    """Where a role item is in the value's text (SPEC §4.6), or None, and whether it is found
    there: an item with offsets whose ``text`` differs from its span is at its span, but not
    found."""
    if item.span is not None:
        span = _valid(t.offsets, item.span)
        if span is None:
            return None, False
        shown = item.text
        return span, shown is None or verbatim_equal(shown, t.text[span[0] : span[1]])
    assert item.text is not None
    found = _occurrences(t, item.text, region)
    tok = at.token
    if tok is not None:
        for a, b in found:
            if a <= tok.start and tok.end <= b:
                return (a, b), True
    pos = tok.start if tok is not None else at.span[0]
    before = [(a, b) for a, b in found if b <= pos]
    if before:
        return before[-1], True
    after = [(a, b) for a, b in found if a >= pos]
    return (after[0], True) if after else (None, False)


_CHECK_ORDER = ("field", "sign", "scale", "unit", "key")  # the unit check reads the field's


def _roles(ctx: _Ctx, p: _Passed, roles: dict[str, _Item], region: tuple[int, int]) -> None:
    """Check each role item at the value, then place the key (SPEC §4.5, §4.6)."""
    at, f = p.at, p.field
    assert at is not None
    t, tok = at.t, at.token
    pos = tok.start if tok is not None else at.span[0]
    prefixes, suffixes = ctx.schema.units.get(f.unit, ([], [])) if f.unit else ([], [])
    found: dict[str, tuple[int, int]] = {}
    passed: dict[str, bool] = {}
    row = False  # the field item is at the value's row
    for role in _CHECK_ORDER:
        item = roles.get(role)
        if item is None:
            continue
        span, located = _find(t, item, at, region) if _same(item, at.item) else (None, False)
        ok = False
        if span is not None and located:
            found[role] = span
            a, b = span
            if role == "key":
                ok = any(
                    a <= x and y <= b and k == p.key for x, y, k in t.key_mentions(f.keys or ())
                )
            elif role == "field":
                if f.aliases is not None and b <= pos:
                    named = any(a <= x and y <= b for x, y, _ in t.key_mentions(f.aliases))
                    s0, _ = sentence(t.text, pos)
                    row = named and not any(ch.isalpha() for ch in t.text[b:pos])
                    in_sentence = a >= s0 and not tokens(t.text, b, pos)
                    ok = named and (row or in_sentence)
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
                    in_scale(t.text, a, b)
                    and b <= tok.start
                    and item_scale(t.text, b, tok.start) is None
                )
            elif role == "unit":
                ok = (
                    f.unit is not None
                    and passed.get("field", False)
                    and holds_form(t.text, a, b, prefixes + suffixes)
                    and b <= tok.start
                    and not ctx.any_unit_at(t, tok)
                )
        passed[role] = ok
        byte_span = None if span is None else _bytes(t, span)
        p.parts.append(Part(role, byte_span, ok))
        if role == "field" and f.aliases is None:
            continue  # not checked: changes nothing
        if not ok:
            p.flags.append(f"{role.upper()}_CITATION_INVALID")
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
        if (
            run[-1][1] <= fa
            and not any(run[-1][1] <= x and y <= fa for x, y, _ in mentions)
            and not note  # a number after the row label on its line, such as a footnote "(1)"
            and len(cells(t.text, fb, pos, prefixes)) == n - 1
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
    if at is not None and f.keys is not None:
        pos = tok.start if tok is not None else 0
        if key not in keys_at(at.t.text, at.t.key_mentions(f.keys), pos):
            p.flags.append("KEY_NOT_AT_VALUE")
            if not key_item:
                p.missing.add("key")
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
) -> Receipt:
    """Decide every candidate and return the receipt.

    ``text`` is the document in Unicode NFC. ``schema`` and ``policy`` are dicts or ``Schema`` and
    ``Policy`` objects; ``policy=None`` uses the defaults. ``candidates`` is a list of candidate
    dicts whose evidence is a list of evidence items (SPEC §2.5). A malformed candidate gets a
    ``rejected`` decision, not an exception. ``document_id`` is copied into the receipt.
    ``judgments`` are recorded answers of a judge (SPEC §2.6); the policy's ``judge`` block says
    which apply. ``references`` are other source texts that the app supplies, and
    ``document_source`` is the URL of the document (SPEC §2.1).

    Raises ``PacketError`` when the text is not NFC, ``candidates`` is not a list, or the schema,
    policy, judgments, references or document source are invalid. Then no receipt is made.
    """
    if not isinstance(text, str) or not is_nfc(text):
        raise PacketError("document text must be a string in Unicode NFC")
    if not isinstance(schema, Schema):
        schema = Schema.from_dict(schema)
    if not isinstance(policy, Policy):
        policy = Policy() if policy is None else Policy.from_dict(policy)
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise PacketError("candidates must be a list")
    if document_source is not None and not (
        isinstance(document_source, str) and document_source.strip()
    ):
        raise PacketError("document source must be a non-blank string or null")
    refs = _references(references)
    by_cand = _judgments(judgments, candidates)
    table = frozenset(x for _, suffixes in schema.units.values() for x in suffixes)
    ctx = _Ctx(
        _Text(text, Offsets(text)),
        {rid: t for rid, (t, _) in refs.items()},
        schema,
        policy,
        None if document_source is None else host(document_source),
        suffixes=table,
    )

    results: list[tuple[str, int, object, _Passed | _Reject]] = []
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

    decisions: list[Decision] = []
    applied: list[Judgment] = []
    for sha, i, cand, p in sorted(results, key=lambda r: (r[0], r[1])):
        if isinstance(p, _Passed):
            for j in sorted(_judge(policy, p, by_cand.get(i, {})), key=lambda j: j.question):
                applied.append(Judgment(sha, j.question, j.answer, j.p))
        cid = cand.get("id") if isinstance(cand, Mapping) else None
        decisions.append(_decision(ctx, sha, cand, cid, p))

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
    )
    return Receipt(**{**draft.__dict__, "receipt_sha256": digest("receipt", draft.body())})


def _bytes(t: _Text, span: tuple[int, int]) -> tuple[int, int]:
    return t.offsets.to_bytes(span[0]), t.offsets.to_bytes(span[1])


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
        return Decision(
            _json_id(cid),
            sha,
            p.field.name,
            outcome,
            (*flags, *(c for c in INFO_ORDER if c in info)),
            p.value,
            p.unit,
            None if at is None else _bytes(at.t, at.span),
            p.key,
            p.source,
            None if at is None else at.item.ref,
            p.url,
            tuple(sorted(p.parts, key=lambda x: PART_ORDER.index(x.role))),
            tuple(m for m in MISSING_ORDER if m in p.missing),
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
        url,
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
) -> Verification:
    """Re-derive the receipt from its inputs and compare it with ``receipt``.

    ``receipt`` is the JSON object that ``Receipt.to_dict()`` returned. The other arguments are
    the inputs given to ``admit``, with the same ``judgments``, ``references`` and
    ``document_source``. The result has ``ok`` and
    ``problems``: ``(True, ())`` when every byte re-derives. A receipt from another spec version
    gives one problem and no further
    checks. Raises ``PacketError`` when ``receipt`` is not a JSON object or an input is invalid.
    """
    if not isinstance(receipt, Mapping):
        raise PacketError("receipt must be a JSON object")
    if (version := receipt.get("groundgate")) != SPEC_VERSION:
        problem = f"receipt was decided under spec {version}; this groundgate implements "
        return Verification(False, (problem + SPEC_VERSION,))
    problems = []
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if digest("receipt", body) != receipt.get("receipt_sha256"):
        problems.append("receipt_sha256 does not match the receipt body")
    doc_id = (
        receipt.get("document", {}).get("id")
        if isinstance(receipt.get("document"), Mapping)
        else None
    )
    fresh = admit(
        text,
        schema,
        candidates,
        policy,
        doc_id,
        judgments,
        references=references,
        document_source=document_source,
    ).to_dict()
    for key in (
        "document",
        "references",
        "schema_sha256",
        "policy_sha256",
        "coverage",
        "judgments",
        "summary",
    ):
        if receipt.get(key) != fresh[key]:
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
