"""Text rules (SPEC §4): number tokens, qualifiers, units, whitespace. Offsets are code points."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_TOKEN = re.compile(r"[-\u2212]?\d[\d,]*(?:\.\d+)?")
# ungrouped, grouped in threes ("200,000"), or grouped the Indian way: the last three digits,
# then pairs ("2,00,000")
_VALID = re.compile(r"^[-\u2212]?(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3}|\d+)(?:\.\d+)?$")
_SENTENCE_END = re.compile(r"\.\s|;\s|•|\n[ \t\r]*\n")
_ABBREVIATIONS = [
    "a.m.",
    "p.m.",
    "approx.",
    "ca.",
    "cf.",
    "e.g.",
    "i.e.",
    "etc.",
    "vs.",
    "viz.",
    "no.",
    "nos.",
    "p.",
    "pp.",
    "para.",
    "fig.",
    "figs.",
    "vol.",
    "rs.",
    "u.s.",
    "u.k.",
    "dr.",
    "mr.",
    "mrs.",
    "ms.",
    "jr.",
    "sr.",
    "st.",
    "inc.",
    "co.",
    "corp.",
    "ltd.",
    "est.",
    "min.",
    "max.",
    "hr.",
    "hrs.",
    "mo.",
    "mos.",
    "yr.",
    "yrs.",
    "wk.",
    "wks.",
    "wt.",
    "oz.",
    "lb.",
    "lbs.",
]
# a listed abbreviation that ends at a dot, as a whole word ("Rs." but not the end of "Mrs.")
_ABBREVIATION_END = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r")\Z", re.I
)
_ABBREVIATION_MAX = max(len(a) for a in _ABBREVIATIONS)
_BLANK_LINE = re.compile(r"\n[ \t\r]*\n")
_WS_RUN = re.compile(r"\s*")
_CONTINUES = "$€£₹"
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
        whole = _TOKEN.match(text, s)
        if whole and s + len(whole.group().removesuffix(",")) > end:
            continue  # the number runs past the region: never read a prefix of it
        out.append(Token(s, e, _to_decimal(tok)))
    return out


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


def _ends_sentence(text: str, m: re.Match[str]) -> bool:
    """A "." that ends a listed abbreviation is not a sentence end when the next character is a
    lowercase letter, a digit or a currency sign and no blank line comes first (SPEC §4.2)."""
    if not m.group().startswith("."):
        return True
    dot = m.start()
    if not _ABBREVIATION_END.search(text, max(0, dot + 1 - _ABBREVIATION_MAX), dot + 1):
        return True
    gap = _WS_RUN.match(text, dot + 1)  # in place: no copy of the rest of the text
    assert gap is not None
    nxt = gap.end()
    if _BLANK_LINE.search(gap.group()) or nxt == len(text):
        return True
    # only a plain continuation joins; an uppercase letter or punctuation may start a sentence
    ch = text[nxt]
    return not (ch.islower() or "0" <= ch <= "9" or ch in _CONTINUES)


def sentence(text: str, pos: int, qualifiers: bool = False) -> tuple[int, int]:
    """The sentence around ``pos`` (SPEC §4.2). Only the qualifier window (``qualifiers``) reads
    on past an abbreviation dot: there a join can only add a flag, while key scope and the unit
    search must never reach into the next sentence."""
    left = 0
    for m in _SENTENCE_END.finditer(text, 0, pos):
        if not qualifiers or _ends_sentence(text, m):
            left = m.end()
    right = len(text)
    for m in _SENTENCE_END.finditer(text, pos):
        if not qualifiers or _ends_sentence(text, m):
            right = m.start()
            break
    return left, right


# ------------------------------------------------------------------ qualifiers

_BEFORE = {
    "approx": [
        "approximately",
        "approx",
        "about",
        "around",
        "nearly",
        "roughly",
        "generally",
        "~",
        "≈",
    ],
    "gt": ["more than", "greater than", "above", "over", "exceed", "exceeds", "exceeding", ">"],
    "lt": ["less than", "fewer than", "below", "under", "<"],
    "ge": ["at least", "minimum of", "no less than", "≥"],
    "le": ["up to", "maximum of", "at most", "no more than", "≤"],
    "range": ["between"],
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
_INVERT = {"gt": "le", "le": "gt", "lt": "ge", "ge": "lt"}
_NEGATION_END = re.compile(r"\b(?:not|cannot|can['\u2019]t)\s+(?:be\s+)?$", re.I)
_RANGE_NEXT = re.compile(r"^\s*(?:through|thru|to|-|\u2013)\s*\S{0,4}?(?=[-\u2212]?\d)", re.I)
# one unit or scale word may stand before a word connector: "30 mg to 45", "$1 million to $2"
_UNIT_WORD = r"(?:[^\s\d]{1,12}\s+(?=(?:through|thru|to|and)\b))?"
_RANGE_PREV = re.compile(rf"\s*{_UNIT_WORD}(?:through|thru|to|-|\u2013)\s*\S{{0,4}}?", re.I)
_AND_NEXT = re.compile(r"^\s*and\s*\S{0,4}?(?=[-\u2212]?\d)", re.I)
_AND_PREV = re.compile(rf"\s*{_UNIT_WORD}and\s*\S{{0,4}}?", re.I)
_BETWEEN_END = re.compile(r"\bbetween\s*\S{0,4}?$", re.I)
_CHANGE = (
    "increase|increases|increased|increasing|decrease|decreases|decreased|decreasing|"
    "raise|raises|raised|raising|reduce|reduces|reduced|reducing|reduction|reductions|"
    "lowers|lowered|lowering|rise|rises|rose|risen|rising|fall|falls|fell|fallen|falling|"
    "drop|drops|dropped|dropping|grow|grows|grew|grown|growing|"
    "change|changes|changed|changing|decline|declines|declined|declining|"
    "adjust|adjusts|adjusted|adjusting|adjustment|adjustments|"
    "revise|revises|revised|revising|revision|revisions"
)
_DETERMINER = "the|a|an|its|their|this|that|these|those"
_NOT_BETWEEN = (
    "about|above|across|after|among|at|before|below|between|by|during|for|from|in|into|on|over|"
    "per|since|through|to|under|until|with|within|range|ranges|ranged|ranging|vary|varies|"
    "varied|varying"
)
_PLAIN = rf"\s+(?!(?:{_NOT_BETWEEN})\b)[^\W\d_](?:[^\W\d_]|['\u2019-](?=[^\W\d_]))*"
# at most six words between the change word and "from", the first of them a determiner or
# "in", "of" or "to" and then a determiner: "reducing the fee from", "an increase in the fee from"
_CHANGE_GAP = (
    rf"(?:\s+(?:in|of|to)\s+(?:{_DETERMINER})(?:{_PLAIN}){{0,4}}"
    rf"|\s+(?:{_DETERMINER})(?:{_PLAIN}){{0,5}})?"
)
# "increased from X to Y": Y is the new value, not a range end
_CHANGE_FROM = re.compile(rf"\b(?:{_CHANGE}){_CHANGE_GAP}\s+from\s+\S{{0,4}}?$", re.I)


def qualifiers(text: str, tok: Token) -> set[str]:
    """Comparators that apply to the value at ``tok`` (SPEC §4.2)."""
    s0, s1 = sentence(text, tok.start, qualifiers=True)
    nearby = tokens(text, s0, s1)
    prev_end = max([t.end for t in nearby if t.end <= tok.start] + [s0, tok.start - _WINDOW])
    next_start = min([t.start for t in nearby if t.start >= tok.end] + [s1, tok.end + _WINDOW])
    before, after = text[prev_end : tok.start], text[tok.end : next_start]
    found = _before_qualifiers(text, s0, prev_end, tok.start)
    found |= {c for c, rx in _AFTER_RE.items() if rx.search(after)}
    rest = _strip_unit_suffix(text[tok.end : s1])
    prev = [t for t in nearby if t.end <= tok.start and t.end >= prev_end]
    between_before = bool(_BETWEEN_END.search(before.rstrip()))
    if (
        _RANGE_NEXT.match(rest)
        or (between_before and _AND_NEXT.match(rest))
        or (
            prev
            and _RANGE_PREV.fullmatch(before)
            and not _CHANGE_FROM.search(text[s0 : prev[-1].start])
        )
        or (
            prev
            and _AND_PREV.fullmatch(before)
            and _BETWEEN_END.search(text[max(s0, prev[-1].start - 20) : prev[-1].start].rstrip())
        )
    ):
        found.add("range")
    return found


def _before_qualifiers(text: str, s0: int, start: int, end: int) -> set[str]:
    """Comparators of the qualifiers in text[start:end]: the longest of overlapping matches,
    inverted by a negation directly before it in the same sentence."""
    window = text[start:end]
    hits = [(m.start(), m.end(), c) for c, rx in _BEFORE_RE.items() for m in rx.finditer(window)]
    found = set()
    for a, b, c in hits:
        if any(a2 <= a and b <= b2 and (a2, b2) != (a, b) for a2, b2, _ in hits):
            continue  # "more than" inside "no more than"
        if c in _INVERT and _NEGATION_END.search(text[s0 : start + a]):
            c = _INVERT[c]
        found.add(c)
    return found


def _strip_unit_suffix(rest: str) -> str:
    # "30 mg to 45 mg": skip a short unit word before the range connector.
    m = re.match(r"^\s*[^\s\d]{1,12}(?=\s+(?:through|thru|to|and)\b)", rest)
    return rest[m.end() :] if m else rest


_SCALE = re.compile(r"^\s{0,2}(thousand|million|billion|trillion|lakh|crore)\b", re.I)


_SCALE_EXP = {"thousand": 3, "million": 6, "billion": 9, "trillion": 12, "lakh": 5, "crore": 7}


def scale_word(text: str, tok: Token) -> bool:
    return bool(_SCALE.match(text[tok.end : tok.end + 12]))


def scaled_value(text: str, tok: Token) -> Decimal | None:
    """The token's value times its scale word, or None (SPEC §4.1)."""
    m = _SCALE.match(text[tok.end : tok.end + 12])
    if m is None or tok.value is None:
        return None
    return tok.value.scaleb(_SCALE_EXP[m.group(1).lower()])


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


_PER_UNIT = re.compile(
    r"\s*(?:/|per\b)\s*(?:\d+(?:\.\d+)?\s*)?"
    r"(?:kg|kilograms?|lbs?|pounds?|m2|m\u00b2|m\^2|square\s+met(?:er|re)s?"
    r"|mL|dL|L|lit(?:er|re)s?)(?![A-Za-z])",
    re.I,
)


def unit_at(
    text: str,
    tok: Token,
    prefixes: list[str],
    suffixes: list[str],
    window: int,
    table: frozenset[str] = frozenset(),
) -> bool:
    """Whether a unit surface form is at ``tok`` (SPEC §4.3). ``table`` holds the suffixes of
    every unit in the table; the first of them after the number decides."""
    if not prefixes and not suffixes:
        return True
    head = text[: tok.start].rstrip()
    for p in prefixes:
        if head.endswith(p):
            before = head[: len(head) - len(p)]
            if not (p[0].isalnum() and before and before[-1].isalnum()):
                return True
    if not suffixes:
        return False
    candidates = table | set(suffixes)
    _, s1 = sentence(text, tok.start)
    region = text[tok.end : min(s1, tok.end + window + max(len(s) for s in candidates))]
    first: tuple[int, int, str] | None = None  # the earliest suffix match, longest at a tie
    for suffix in sorted(candidates):
        pat = re.escape(suffix)
        if suffix[-1].isalnum():
            pat += r"(?![A-Za-z0-9])"
        if suffix[0].isalnum():
            pat = r"(?<![A-Za-z0-9])" + pat
        m = re.search(pat, region)
        if m and (first is None or (m.start(), -m.end()) < (first[0], -first[1])):
            first = (m.start(), m.end(), suffix)
    if first is None or first[0] > window or first[2] not in suffixes:
        return False  # "10 mcg (maximum 500 mg)": mcg comes first, so mg is not at 10
    # "10 mg/kg", "250 mg/5 mL": a per-unit is not the unit
    return not _PER_UNIT.match(text, tok.end + first[1])


# ------------------------------------------------------------------------ keys

_NOT_ALNUM_BEFORE, _NOT_ALNUM_AFTER = r"(?<![^\W_])", r"(?![^\W_])"


def key_mentions(text: str, keys: tuple[str, ...]) -> list[tuple[int, int, str]]:
    """(start, end, key) for each mention of a key, the longer of overlapping ones (SPEC §4.5)."""
    hits = []
    for key in keys:
        body = r"\s+".join(re.escape(w) for w in normalize_ws(key).split(" "))
        rx = re.compile(_NOT_ALNUM_BEFORE + body + _NOT_ALNUM_AFTER, re.I)
        hits += [(m.start(), m.end(), key) for m in rx.finditer(text)]
    return [
        (a, b, k)
        for a, b, k in hits
        if not any(a2 <= a and b <= b2 and (a2, b2) != (a, b) for a2, b2, _ in hits)
    ]


def keys_at(text: str, mentions: list[tuple[int, int, str]], pos: int) -> set[str]:
    """The keys a value at ``pos`` belongs to: those its sentence mentions, else the nearest
    mention before it (SPEC §4.5)."""
    s0, s1 = sentence(text, pos)
    inside = {k for a, b, k in mentions if s0 <= a and b <= s1}
    if inside:
        return inside
    before = [(b, k) for _, b, k in mentions if b <= pos]
    return {max(before)[1]} if before else set()
