"""Text rules (SPEC §4): number tokens, qualifiers, units, whitespace. Offsets are code points."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_TOKEN = re.compile(r"[-\u2212]?\d[\d,]*(?:\.\d+)?")
_VALID = re.compile(r"^[-\u2212]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
_SENTENCE_END = re.compile(r"\. |; |•|\n[ \t]*\n")
_WS = re.compile(r"\s+")
_HYPHEN_BREAK = re.compile(r"-\n\s*")
_WINDOW = 40


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    value: Decimal | None  # None when the digit grouping is invalid


def _to_decimal(tok: str) -> Decimal | None:
    if not _VALID.match(tok):
        return None
    try:
        return Decimal(tok.replace(",", "").replace("\u2212", "-"))
    except InvalidOperation:  # pragma: no cover - the regex admits only valid decimals
        return None


def tokens(text: str, start: int = 0, end: int | None = None) -> list[Token]:
    """Number tokens whose characters lie within text[start:end] (SPEC §4.1)."""
    end = len(text) if end is None else end
    out = []
    for m in _TOKEN.finditer(text, start, end):
        s, tok = m.start(), m.group()
        if tok[0] in "-\u2212" and s > 0 and text[s - 1].isalnum():
            s, tok = s + 1, tok[1:]
        if s > 0 and (text[s - 1].isalnum() or text[s - 1] in ".,"):
            continue
        if tok.endswith(","):
            tok = tok[:-1]
        e = s + len(tok)
        if e == end and _continues(text, e):
            continue  # the number runs past the region: never read a prefix of it
        out.append(Token(s, e, _to_decimal(tok)))
    return out


def _continues(text: str, i: int) -> bool:
    if i >= len(text):
        return False
    if text[i].isdigit():
        return True
    return text[i] in ".," and i + 1 < len(text) and text[i + 1].isdigit()


def parse_value(raw: str) -> Decimal | None:
    """Parse a candidate value: a single number token and nothing else."""
    raw = raw.strip()
    found = tokens(raw)
    if len(found) != 1 or found[0].start != 0 or found[0].end != len(raw):
        return None
    return found[0].value


def canonical(value: Decimal) -> str:
    """Canonical decimal string (SPEC §4.1)."""
    if value == 0:
        return "0"
    s = format(value, "f")  # exact; normalize() would round to the context precision
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def verbatim_equal(a: str, b: str) -> bool:
    return normalize_ws(_HYPHEN_BREAK.sub("", a)) == normalize_ws(_HYPHEN_BREAK.sub("", b))


def quote_pattern(quote: str) -> re.Pattern[str]:
    """Regex for a quote where each whitespace run matches any whitespace run."""
    parts = normalize_ws(quote).split(" ")
    return re.compile(r"\s+".join(re.escape(p) for p in parts))


def sentence(text: str, pos: int) -> tuple[int, int]:
    left = 0
    for m in _SENTENCE_END.finditer(text, 0, pos):
        left = m.end()
    nxt = _SENTENCE_END.search(text, pos)
    return left, (nxt.start() if nxt else len(text))


# ------------------------------------------------------------------ qualifiers

_BEFORE = {
    "approx": ["approximately", "about", "around", "nearly", "roughly", "generally", "~", "≈"],
    "gt": ["more than", "greater than", "above", "over", "exceeds", "exceeding", ">"],
    "lt": ["less than", "fewer than", "below", "under", "<"],
    "ge": ["at least", "minimum of", "no less than", "≥"],
    "le": ["up to", "maximum of", "at most", "no more than", "≤"],
    "range": ["between", "from"],
}
_AFTER = {
    "ge": ["or more", "or greater", "or older", "or higher", "or above"],
    "le": ["or less", "or fewer", "or younger", "or lower", "or below"],
}


def _phrase(p: str) -> str:
    body = r"\s+".join(re.escape(w) for w in p.split())
    return body if not p[0].isalnum() else rf"\b{body}\b"


_BEFORE_RE = {c: re.compile("|".join(_phrase(p) for p in ps), re.I) for c, ps in _BEFORE.items()}
_AFTER_RE = {c: re.compile("|".join(_phrase(p) for p in ps), re.I) for c, ps in _AFTER.items()}
_RANGE_NEXT = re.compile(r"^\s*(?:to|-|\u2013)\s*\S{0,4}?(?=[-\u2212]?\d)", re.I)
_RANGE_PREV = re.compile(r"\s*(?:to|-|\u2013)\s*\S{0,4}?", re.I)
_AND_NEXT = re.compile(r"^\s*and\s*\S{0,4}?(?=[-\u2212]?\d)", re.I)
_AND_PREV = re.compile(r"\s*and\s*\S{0,4}?", re.I)
_BETWEEN_END = re.compile(r"\bbetween\s*\S{0,4}?$", re.I)


def qualifiers(text: str, tok: Token) -> set[str]:
    """Comparators that apply to the value at ``tok`` (SPEC §4.2)."""
    s0, s1 = sentence(text, tok.start)
    nearby = tokens(text, s0, s1)
    prev_end = max([t.end for t in nearby if t.end <= tok.start] + [s0, tok.start - _WINDOW])
    next_start = min([t.start for t in nearby if t.start >= tok.end] + [s1, tok.end + _WINDOW])
    before, after = text[prev_end : tok.start], text[tok.end : next_start]
    found = {c for c, rx in _BEFORE_RE.items() if rx.search(before)}
    found |= {c for c, rx in _AFTER_RE.items() if rx.search(after)}
    rest = _strip_unit_suffix(text[tok.end : s1])
    prev = [t for t in nearby if t.end <= tok.start and t.end >= prev_end]
    between_before = bool(_BETWEEN_END.search(before.rstrip()))
    if (
        _RANGE_NEXT.match(rest)
        or (between_before and _AND_NEXT.match(rest))
        or (prev and _RANGE_PREV.fullmatch(before))
        or (
            prev
            and _AND_PREV.fullmatch(before)
            and _BETWEEN_END.search(text[max(s0, prev[-1].start - 20) : prev[-1].start].rstrip())
        )
    ):
        found.add("range")
    return found


def _strip_unit_suffix(rest: str) -> str:
    # "30 mg to 45 mg": skip a short unit word before the range connector.
    m = re.match(r"^\s*[^\s\d]{1,12}(?=\s+(?:to|and)\b)", rest)
    return rest[m.end() :] if m else rest


_SCALE = re.compile(r"^\s{0,2}(thousand|million|billion|trillion|lakh|crore)\b", re.I)


def scale_word(text: str, tok: Token) -> bool:
    return bool(_SCALE.match(text[tok.end : tok.end + 12]))


# ----------------------------------------------------------------------- units

_CURRENCY = {
    "USD": (["US$", "$"], ["USD", "dollars"]),
    "EUR": (["€"], ["EUR", "euros"]),
    "GBP": (["£"], ["GBP"]),
    "INR": (["₹", "Rs.", "Rs"], ["INR", "rupees"]),
    "%": ([], ["%", "percent"]),
}
_TIME = ["hours", "days", "weeks", "months", "years", "minutes"]
_SELF = ["mg", "mcg", "g", "kg", "mL", "L"]


def builtin_units() -> dict[str, tuple[list[str], list[str]]]:
    table = {k: (list(p), list(s)) for k, (p, s) in _CURRENCY.items()}
    for code in _SELF:
        table[code] = ([], [code])
    for code in _TIME:
        single = code[:-1]
        table[code] = ([], [code, single, f"-{single}"])
    return table


def unit_at(text: str, tok: Token, prefixes: list[str], suffixes: list[str], window: int) -> bool:
    """Whether a unit surface form is at ``tok`` (SPEC §4.3)."""
    if not prefixes and not suffixes:
        return True
    head = text[: tok.start].rstrip()
    for p in prefixes:
        if head.endswith(p):
            before = head[: len(head) - len(p)]
            if not (p[0].isalnum() and before and before[-1].isalnum()):
                return True
    _, s1 = sentence(text, tok.start)
    region = text[tok.end : min(s1, tok.end + window + max((len(s) for s in suffixes), default=0))]
    for suffix in suffixes:
        pat = re.escape(suffix)
        if suffix[-1].isalnum():
            pat += r"(?![A-Za-z0-9])"
        if suffix[0].isalnum():
            pat = r"(?<![A-Za-z0-9])" + pat
        m = re.search(pat, region)
        if m and m.start() <= window:
            return True
    return False
