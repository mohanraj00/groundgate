"""Text rules (SPEC §4): number tokens, qualifiers, units, whitespace. Offsets are code points."""

from __future__ import annotations

import bisect
import contextlib
import itertools
import re
import unicodedata
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_TOKEN = re.compile(r"[-\u2212]?[0-9][0-9,]*(?:\.[0-9]+)?")
# ungrouped, grouped in threes ("200,000"), or grouped the Indian way: the last three digits,
# then pairs ("2,00,000")
_VALID = re.compile(
    r"^[-\u2212]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3}|[0-9]+)(?:\.[0-9]+)?$"
)
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
_CONTINUES = "$€£₹"  # the currency signs (SPEC §4.1, §4.2)
# "No." before a code such as "DEA-1086": a word that holds a digit or starts with two capitals
_CODE = re.compile(r"\S*?\d|[A-Z]{2}")
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


def _letter_or_number(ch: str) -> bool:
    """A Unicode letter or number: general category L or N (SPEC §4.1)."""
    return unicodedata.category(ch)[0] in "LN"


def _number_char(ch: str) -> bool:
    """A Unicode number character: general category N (SPEC §4.1)."""
    return unicodedata.category(ch)[0] == "N"


def _other_number_char(ch: str) -> bool:
    """A number character that is not an ASCII digit."""
    return _number_char(ch) and not "0" <= ch <= "9"


def _other_digits_follow(text: str, i: int) -> bool:
    """Whether a number character other than 0 to 9 comes at ``i``, or after a "." or "," at
    ``i``: the ASCII digits before it start a number in other digits, as in "2" + DEVANAGARI
    ZERO."""
    if i < len(text) and _other_number_char(text[i]):
        return True
    return i + 1 < len(text) and text[i] in ".," and _other_number_char(text[i + 1])


def tokens(text: str, start: int = 0, end: int | None = None) -> list[Token]:
    """Number tokens whose characters lie within text[start:end] (SPEC §4.1)."""
    return list(_tokens(text, start, len(text) if end is None else end))


def first_token_end(text: str, start: int) -> int | None:
    """The end of the first number token at or after ``start``, or None. ``tokens(text, start,
    end)`` is empty exactly when this is None or after ``end``: a token found before ``end`` is
    the same token when the text reads on."""
    return next((t.end for t in _tokens(text, start, len(text))), None)


def _tokens(text: str, start: int, end: int) -> Iterator[Token]:
    for m in _TOKEN.finditer(text, start, end):
        s, tok = m.start(), m.group()
        if tok[0] in "-\u2212" and s > 0 and _letter_or_number(text[s - 1]):
            s, tok = s + 1, tok[1:]
        if s > 0 and (_letter_or_number(text[s - 1]) or text[s - 1] in ".,"):
            continue
        if _other_digits_follow(text, m.end()):
            continue
        if tok.endswith(","):
            tok = tok[:-1]
        e = s + len(tok)
        if tok == "000" and _scale_zeros(text, s):
            continue  # the 000 of a currency scale, as in "£000", is no token (#313)
        whole = _TOKEN.match(text, s)
        if whole and s + len(whole.group().removesuffix(",")) > end:
            continue  # the number runs past the region: never read a prefix of it
        yield Token(s, e, _to_decimal(tok))


def _scale_zeros(text: str, s: int) -> bool:
    """Whether the 000 at ``s`` is the 000 of a currency scale (SPEC §4.1, #313)."""
    sign = s - 1
    if sign > 0 and text[sign] in "'\u2019":
        sign -= 1
    return sign >= 0 and text[sign] in _CONTINUES and _CURRENCY_SCALE.match(text, sign) is not None


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
    lowercase letter, a digit or a currency sign and no blank line comes first. "U.S." never
    ends one, and "No." or "Nos." does not before a code (SPEC §4.2)."""
    if not m.group().startswith("."):
        return True
    dot = m.start()
    abbreviation = _ABBREVIATION_END.search(text, max(0, dot + 1 - _ABBREVIATION_MAX), dot + 1)
    if not abbreviation:
        return True
    gap = _WS_RUN.match(text, dot + 1)  # in place: no copy of the rest of the text
    assert gap is not None
    nxt = gap.end()
    if _BLANK_LINE.search(gap.group()) or nxt == len(text):
        return True
    word = abbreviation.group().lower()
    if word == "u.s." or (word in ("no.", "nos.") and _CODE.match(text, nxt)):
        return False
    # only a plain continuation joins; an uppercase letter or punctuation may start a sentence
    ch = text[nxt]
    return not (ch.islower() or "0" <= ch <= "9" or ch in _CONTINUES)


# the sentence ends of each text, read once while an index is open (``sentence_index``), and
# kept only while it is open
_SENTENCES: ContextVar[dict[int, tuple[str, list[int], list[int]]] | None] = ContextVar(
    "sentences", default=None
)
# Mention lists belong to _Text and remain fixed for one admission. Hold their identities and
# classifications only while the same admission context is open.
_MIXED_HEADERS: ContextVar[
    dict[tuple[int, int], tuple[str, list[tuple[int, int, str]], set[int]]] | None
] = ContextVar("mixed_headers", default=None)


@contextlib.contextmanager
def sentence_index() -> Iterator[None]:
    """Read sentence ends and mixed header blocks once, until the block ends."""
    token = _SENTENCES.set({})
    headers = _MIXED_HEADERS.set({})
    try:
        yield
    finally:
        _MIXED_HEADERS.reset(headers)
        _SENTENCES.reset(token)


def _sentence_ends(text: str) -> tuple[list[int], list[int]] | None:
    """The starts and the ends of the sentence ends in a text, in order, or None when no index
    is open. The pattern looks at nothing outside a match, so a match is the same match in any
    part of the text that holds it."""
    index = _SENTENCES.get()
    if index is None:
        return None
    held = index.get(id(text))
    if held is None or held[0] is not text:
        found = [m.span() for m in _SENTENCE_END.finditer(text)]
        held = index[id(text)] = (text, [a for a, _ in found], [b for _, b in found])
    return held[1], held[2]


def sentence(text: str, pos: int, qualifiers: bool = False) -> tuple[int, int]:
    """The sentence around ``pos`` (SPEC §4.2). Only the qualifier window (``qualifiers``) reads
    on past an abbreviation dot: there a join can only add a flag, while key scope and the unit
    search must never reach into the next sentence."""
    left = 0
    index = None if qualifiers else _sentence_ends(text)
    if index is None:
        for m in _SENTENCE_END.finditer(text, 0, pos):
            if not qualifiers or _ends_sentence(text, m):
                left = m.end()
    else:
        starts, ends = index
        i = bisect.bisect_right(ends, pos)
        left = ends[i - 1] if i else 0
        if i == len(ends) or starts[i] >= pos:  # no sentence end holds pos: the next one ends it
            return left, starts[i] if i < len(starts) else len(text)
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
_BETWEEN = re.compile(r"(?<![^\W_])between\s", re.I)
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
        or (_AND_NEXT.match(rest) and _between_words_before(text, tok.start))
        or (
            prev
            and _RANGE_PREV.fullmatch(before)
            and not _CHANGE_FROM.search(text[s0 : prev[-1].start])
        )
        or (
            prev
            and _AND_PREV.fullmatch(before)
            and (
                _BETWEEN_END.search(text[max(s0, prev[-1].start - 20) : prev[-1].start].rstrip())
                or _between_words_before(text, prev[-1].start)
            )
        )
    ):
        found.add("range")
    return found


def _between_words_before(text: str, start: int) -> bool:
    """Whether a `between` of the sentence stands before the number at ``start`` with only
    whitespace and at most six words between them (SPEC §4.2). A word is a run of letters and
    combining marks that starts with a letter. Each `between` is tried."""
    s0, _ = sentence(text, start)
    for m in _BETWEEN.finditer(text, s0, start):
        words = text[m.end() - 1 : start].split()
        if len(words) <= 6 and text[start - 1].isspace() and all(map(_word, words)):
            return True
    return False


def _word(w: str) -> bool:
    return unicodedata.category(w[0]).startswith("L") and all(
        unicodedata.category(ch)[0] in "LM" for ch in w
    )


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


# a scale suffix or a currency scale (SPEC §4.1, spec 0.10): the power of ten of each form
_SUFFIX_EXP = {"k": 3, "m": 6, "bn": 9, "'000": 3, "\u2019000": 3, "000": 3}
_SCALE_SUFFIX = re.compile(r"(k|K|m|M|bn|Bn|BN)(?![^\W_])")
# a bare 000 also stops before a "," or a "." and a digit, as in "£000,000" (#313)
_CURRENCY_FORM = (
    "[" + re.escape(_CONTINUES) + r"](k|K|m|M|bn|Bn|BN|'000|\u2019000|000(?![,.][0-9]))(?![^\W_])"
)
_CURRENCY_SCALE = re.compile(_CURRENCY_FORM)


def token_scale(text: str, tok: Token) -> int | None:
    """The power of ten of the token's scale (SPEC §4.1): a scale word after it, or a scale
    suffix directly after it when a currency sign stands directly before it. Else None."""
    m = _SCALE.match(text[tok.end : tok.end + 12])
    if m is not None:
        return _SCALE_EXP[m.group(1).lower()]
    if tok.start > 0 and text[tok.start - 1] in _CONTINUES:
        s = _SCALE_SUFFIX.match(text, tok.end)
        if s is not None:
            return _SUFFIX_EXP[s.group(1).lower()]
    return None


def scale_word(text: str, tok: Token) -> bool:
    """Whether a scale word or a scale suffix follows the token (SPEC §4.1, SCALE_WORD)."""
    return token_scale(text, tok) is not None


def scaled_value(text: str, tok: Token) -> Decimal | None:
    """The token's value times its scale, or None (SPEC §4.1)."""
    k = token_scale(text, tok)
    if k is None or tok.value is None:
        return None
    return tok.value.scaleb(k)


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
# the dashes that match each other in a key or an alias (SPEC §4.5, spec 0.10): not the minus
# sign, which is the sign of a number, and not the em dash
KEY_DASHES = "-\u2010\u2011\u2012\u2013"
_DASH = "[" + re.escape(KEY_DASHES) + "]"
_DASH_BREAK = _DASH + r"(?:[ \r]*\n[ \r]*)?"  # a dash, then one line break


def _key_pattern(key: str) -> str:
    """The regex body of a key: each whitespace run matches any whitespace run, each dash any
    dash, and a dash between two letters also a dash and one line break (SPEC §4.5)."""
    words = normalize_ws(key)
    out: list[str] = []
    for i, ch in enumerate(words):
        if ch == " ":
            out.append(r"\s+")
        elif ch in KEY_DASHES:
            between = 0 < i < len(words) - 1 and words[i - 1].isalpha() and words[i + 1].isalpha()
            out.append(_DASH_BREAK if between else _DASH)
        else:
            out.append(re.escape(ch))
    return "".join(out)


def key_mentions(text: str, keys: tuple[str, ...]) -> list[tuple[int, int, str]]:
    """(start, end, key) for each mention of a key, the longer of overlapping ones (SPEC §4.5)."""
    hits = []
    for key in keys:
        rx = re.compile(_NOT_ALNUM_BEFORE + _key_pattern(key) + _NOT_ALNUM_AFTER, re.I)
        hits += [(m.start(), m.end(), key) for m in rx.finditer(text)]
    return [
        (a, b, k)
        for a, b, k in hits
        if not any(a2 <= a and b <= b2 and (a2, b2) != (a, b) for a2, b2, _ in hits)
    ]


# a label line (SPEC §4.5): a line of its own, after a blank line or the start of the text and
# before a blank line, that holds at most 12 words, no sentence end and no final "." or ";"
_LABEL_MAX_WORDS = 12
_INNER_END = re.compile(r"[.;]\s")
_LINE_SPACE = " \t\r"


def _label_line_in(text: str, start: int, end: int) -> bool:
    """Whether a label line lies wholly in text[start:end]. A plain scan of the lines, so the
    time is linear in the length of the region."""
    lines = text[start:end].split("\n")
    blank = [not line.strip(_LINE_SPACE) for line in lines]
    # a line needs a full blank line before it (or the start of the text) and a full blank line
    # after it, so it is never the first piece of the region, which may start inside a line
    for i, line in enumerate(lines[:-2]):
        before = (i >= 2 and blank[i - 1]) or (i == 0 and start == 0)
        if not before or not blank[i + 1]:
            continue
        body = line.strip(_LINE_SPACE)
        # the line break counts as whitespace, so a final "." or ";" is a sentence end too
        if body and len(body.split()) <= _LABEL_MAX_WORDS and not _INNER_END.search(body + "\n"):
            return True
    return False


# A table sentence has several keys and enough lines, or a separate recognized header.
_TABLE_BREAKS, _TABLE_KEYS = 3, 2
_KEY_BREAK = re.compile(r"\n[ \t\r]*\n[ \t\r]*\n")


def _separate_header(text: str, mentions: list[tuple[int, int, str]], start: int, pos: int) -> bool:
    """Recognize a separate header line, key-only stream or mixed tabbed header block."""
    last = text.rfind("\n", 0, pos) + 1
    before = max(((a, b, k) for a, b, k in mentions if start <= a < b <= last), default=None)
    if before and _header_key(text, mentions, before[0]):
        return True  # separate key-only lines also form a header in a short table
    mentions = sorted(mentions)
    i = 0
    while i < len(mentions) and mentions[i][0] < start:
        i += 1
    left = start
    while left < last:
        right = text.find("\n", left, last)
        right = last if right < 0 else right
        cursor = left
        keys: set[str] = set()
        clean = True
        while i < len(mentions) and mentions[i][0] < right:
            a, b, k = mentions[i]
            if b > right or text[cursor:a].strip():
                clean = False
            cursor = b
            keys.add(k)
            i += 1
        if len(keys) >= _TABLE_KEYS and (
            "\t" in text[left:right] or (clean and not text[cursor:right].strip())
        ):
            return True
        left = right + 1
    return False


def _own_keys(text: str, mentions: list[tuple[int, int, str]], pos: int) -> set[str] | None:
    """The keys that the value's own text names: in a table sentence those of its line (maybe
    none), else those of its sentence, or None when the sentence names no key (SPEC §4.5)."""
    s0, s1 = sentence(text, pos)
    inside = {k for a, b, k in mentions if s0 <= a and b <= s1}
    if (len(inside) >= _TABLE_KEYS and text.count("\n", s0, s1) >= _TABLE_BREAKS) or (
        inside and _separate_header(text, mentions, s0, pos)
    ):
        # a table sentence: only the value's own line decides
        nl = text.rfind("\n", s0, pos)
        l0 = nl + 1 if nl >= 0 else s0
        l1 = text.find("\n", pos, s1)
        l1 = s1 if l1 < 0 else l1
        return {k for a, b, k in mentions if l0 <= a and b <= l1}
    return inside or None


def keys_at(text: str, mentions: list[tuple[int, int, str]], pos: int) -> set[str]:
    """The keys a value at ``pos`` belongs to: those its sentence mentions, or in a table
    sentence those its line mentions, else the nearest mention before it, unless a label line
    stands between them and the value is not in a one-column table under it (SPEC §4.5)."""
    s0, _ = sentence(text, pos)
    named = _own_keys(text, mentions, pos)
    if named is not None:
        return named
    before = [(b, k) for _, b, k in mentions if b <= pos]
    if not before:
        return set()
    end, key = max(before)
    at = next(a for a, b, k in mentions if b == end and k == key)
    if key_break(text, end, pos) or _header_key(text, mentions, at):
        return set()
    if _label_line_in(text, end, s0) and not _one_column(text, end, pos):
        return set()
    return {key}


def _mixed_header_blocks(text: str, mentions: list[tuple[int, int, str]]) -> set[int]:
    """Classify every connected header block once; return its qualifying key-line starts."""
    ordered = sorted(mentions)
    i = 0
    mixed: set[int] = set()
    block_lines: list[int] = []
    block_keys: set[str] = set()
    block_tabbed = False
    blanks = 0

    def finish() -> None:
        nonlocal block_tabbed
        if len(block_lines) >= 2 and len(block_keys) >= _TABLE_KEYS and block_tabbed:
            mixed.update(block_lines)
        block_lines.clear()
        block_keys.clear()
        block_tabbed = False

    left = 0
    while left <= len(text):
        right = text.find("\n", left)
        right = len(text) if right < 0 else right
        while i < len(ordered) and ordered[i][0] < left:
            i += 1
        first = i
        while i < len(ordered) and ordered[i][0] < right:
            i += 1
        spans = [(a, b, k) for a, b, k in ordered[first:i] if b <= right]
        if not text[left:right].strip(" \t\r"):
            blanks += 1
            if blanks >= 2:
                finish()
        else:
            blanks = 0
            tabbed = "\t" in text[left:right]
            clean = bool(spans)
            cursor = left
            for a, b, _ in spans:
                if not tabbed and text[cursor:a].strip():
                    clean = False
                cursor = max(cursor, b)
            if not tabbed and text[cursor:right].strip():
                clean = False
            # A data value ends the header block, even when its row also names a key.
            j = 0
            if clean:
                for token in tokens(text, left, right):
                    while j < len(spans) and spans[j][1] <= token.start:
                        j += 1
                    if j == len(spans) or not (
                        spans[j][0] <= token.start < token.end <= spans[j][1]
                    ):
                        clean = False
                        break
            if clean:
                block_lines.append(left)
                block_keys.update(k for _, _, k in spans)
                block_tabbed = block_tabbed or tabbed
            else:
                finish()
        if right == len(text):
            break
        left = right + 1
    finish()
    return mixed


def _mixed_header_lines(text: str, mentions: list[tuple[int, int, str]], at: int) -> bool:
    """Read mixed-header classification once per text/key set in the admission context."""
    index = _MIXED_HEADERS.get()
    if index is None:
        mixed = _mixed_header_blocks(text, mentions)
    else:
        key = id(text), id(mentions)
        held = index.get(key)
        if held is None or held[0] is not text or held[1] is not mentions:
            held = index[key] = (text, mentions, _mixed_header_blocks(text, mentions))
        mixed = held[2]
    return _line(text, at)[0] in mixed


def _header_key(text: str, mentions: list[tuple[int, int, str]], at: int) -> bool:
    """A key in a tabbed or whitespace-only header cannot act as a prose heading."""
    if _mixed_header_lines(text, mentions, at):
        return True
    la, lb = _line(text, at)
    if "\t" in text[la:lb] and len({k for a, b, k in mentions if la <= a < b <= lb}) >= _TABLE_KEYS:
        return True
    run = header(text, mentions, at)
    starts = {a for a, _ in run}
    if len({k for a, _, k in mentions if a in starts}) < _TABLE_KEYS:
        return False
    a, b = run[0][0], run[-1][1]
    left = text.rfind("\n", 0, a) + 1
    right = text.find("\n", b)
    right = len(text) if right < 0 else right
    return "\t" in text[left:right] or (not text[left:a].strip() and not text[b:right].strip())


def key_break(text: str, start: int, end: int) -> bool:
    """Two adjacent blank lines isolate a block from earlier keys and column evidence."""
    return _KEY_BREAK.search(text, start, end) is not None


def _one_column(text: str, end: int, pos: int) -> bool:
    """Whether a key mention that ends at ``end`` reaches a value at ``pos`` across a label line:
    no page break between them, a tab before the value on its line, and at most one number token
    after the first tab of each line after the mention's line, as in a table with one number
    column under a title (SPEC §4.5, #250)."""
    if "\f" in text[end:pos]:
        return False
    line = text.rfind("\n", 0, pos) + 1
    if "\t" not in text[line:pos]:
        return False
    a = text.find("\n", end) + 1
    while 0 < a <= line:
        b = text.find("\n", a)
        b = len(text) if b < 0 else b
        tab = text.find("\t", a, b)
        if tab >= 0 and len(tokens(text, tab, b)) > 1:
            return False
        a = b + 1
    return True


# -------------------------------------------------------------- evidence items

_LOSS = re.compile(r"(?<![^\W_])(?:loss|losses|deficit|deficits)(?![^\W_])", re.I)
_GAIN = re.compile(r"(?<![^\W_])(?:income|gain|gains|profit|profits|earnings)(?![^\W_])", re.I)
_ITEM_SCALE = re.compile(
    r"(?<![^\W_])(?i:(thousand|million|billion|trillion|lakh|crore)s?)(?![^\W_])|" + _CURRENCY_FORM
)
_LONE_DASH = re.compile("(?<!\\S)[-\u2013\u2014](?!\\S)")
_NOT_SPACE = re.compile(r"\S")
_EMPTY_TAB = re.compile(r"(?<=\t)[ \r]*(?=\t|\n|\Z)")
_NEXT_SLOT = re.compile(r"[ \r]*\t[ \r]*(?:[-\u2013\u2014][ \r]*)?(?=\t|\n|\Z)")
_IN_SCALE = re.compile(
    r"(?<![^\W_])in\s+(?:thousand|million|billion|trillion|lakh|crore)s?(?![^\W_])", re.I
)
_NEGATION = re.compile(r"(?<![^\W_])(?:no|not|without)\s+\Z", re.I)
_WORD = re.compile(r"[^\W\d_]+")
_LOSS_REACH = 4  # words between a loss word and the value (SPEC §4.6)


def form_next(text: str, tok: Token, prefixes: list[str], suffixes: list[str], window: int) -> bool:
    """Whether a unit form is next to the token (SPEC §3.1): a prefix ends at its start, or a
    suffix starts within ``window`` code points after it in its sentence. A per-unit counts."""
    head = text[: tok.start].rstrip()
    for p in prefixes:
        if head.endswith(p):
            before = head[: len(head) - len(p)]
            if not (p[0].isalnum() and before and before[-1].isalnum()):
                return True
    _, s1 = sentence(text, tok.start)
    region = text[tok.end : min(s1, tok.end + window + max((len(x) for x in suffixes), default=0))]
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


def brackets_around(text: str, tok: Token, prefixes: list[str]) -> tuple[int, int] | None:
    """The span from "(" to ")" when brackets enclose the token, with only whitespace and unit
    prefixes between "(" and the token and only whitespace between the token and ")" (SPEC
    §4.6), else None."""
    i = tok.start
    longest = sorted(prefixes, key=len, reverse=True)  # "US$" before "$"
    while True:
        j = len(text[:i].rstrip())
        for p in longest:
            if text.endswith(p, 0, j):
                i = j - len(p)
                break
        else:
            i = j
            break
    if i == 0 or text[i - 1] != "(":
        return None
    k = tok.end
    while k < len(text) and text[k].isspace():
        k += 1
    if k == len(text) or text[k] != ")":
        return None
    return i - 1, k + 1


def loss_sign(text: str, start: int, end: int, at: int) -> bool:
    """Whether text[start:end] holds a loss word with no negation directly before it and at most
    four words between it and ``at`` (SPEC §4.6)."""
    for m in _LOSS.finditer(text, start, end):
        if _NEGATION.search(text, 0, m.start()):
            continue
        if len(_WORD.findall(text, m.end(), at)) <= _LOSS_REACH:
            return True
    return False


def gain_word(text: str, start: int, end: int) -> bool:
    return bool(_GAIN.search(text, start, end))


def heading_rows(text: str) -> list[tuple[int, int]]:
    """The spans of the table rows that a heading scale reaches (SPEC §4.1), in order and
    merged, in one pass: a line with no tab that holds "in" and a scale word, or any line that
    holds a currency scale, then any blank lines, then the lines with tabs up to the first line
    with no tab."""
    out: list[tuple[int, int]] = []
    state = None  # "heading" after a heading line, "table" in its rows
    start = 0
    for line in text.split("\n"):
        end = start + len(line)
        if "\t" in line:
            if state == "table":
                out[-1] = (out[-1][0], end)
            elif state == "heading":
                out.append((start, end))
            if state is not None:
                state = "table"
        elif not line.strip():
            if state == "table":
                state = None
        else:
            state = "heading" if in_scale(line, 0, len(line)) else None
        if _CURRENCY_SCALE.search(line):  # a currency scale, with or without a tab (spec 0.10)
            state = "heading"
        start = end + 1
    return out


# The currency names of a currency statement and the sign that each currency shares (SPEC
# §4.3, spec 0.10, #315). A name also matches in the singular, and the code matches in capitals.
CURRENCY_NAMES: dict[str, tuple[tuple[str, ...], str | None]] = {
    "USD": (("US dollars", "U.S. dollars", "United States dollars"), "$"),
    "AUD": (("Australian dollars",), "$"),
    "CAD": (("Canadian dollars",), "$"),
    "HKD": (("Hong Kong dollars",), "$"),
    "NZD": (("New Zealand dollars",), "$"),
    "SGD": (("Singapore dollars",), "$"),
    "EUR": (("euros",), "\u20ac"),
    "GBP": (("pounds sterling", "sterling"), "\u00a3"),
    "INR": (("Indian rupees",), "\u20b9"),
    "LKR": (("Sri Lankan rupees",), None),
}
_PLURALS = ("dollars", "euros", "pounds", "rupees")


def _name_pattern(name: str) -> str:
    words = [re.escape(w[:-1]) + "s?" if w in _PLURALS else re.escape(w) for w in name.split()]
    return _LINE_SPACE.join(words)


_LINE_SPACE = r"[^\S\n]+"  # a whitespace run that stays on its line: a statement is on one line
_STATEMENT = re.compile(
    r"(?<![^\W_])(?i:in)[^\S\n]+"
    r"(?:(?i:thousand|million|billion|trillion|lakh|crore)s?[^\S\n]+(?i:of)[^\S\n]+)?(?:"
    + "|".join(
        f"(?P<{code}>(?i:{'|'.join(_name_pattern(n) for n in names)})|{code})"
        for code, (names, _) in CURRENCY_NAMES.items()
    )
    + r")(?![^\W_])"
)


@dataclass(frozen=True)
class HeadingUnit:
    """A currency header or a currency statement, and the rows that it reaches (SPEC §4.3)."""

    start: int
    end: int
    code: str | None  # a statement's currency; None for a header
    form: str  # a header's sign with the letters directly before it; "" for a statement
    reach: tuple[int, int] | None  # the first and the last code point of the rows it reaches

    def reaches(self, pos: int) -> bool:
        return self.reach is not None and self.reach[0] <= pos <= self.reach[1]


def heading_units(text: str) -> list[HeadingUnit]:
    """The heading units of the text (SPEC §4.3, spec 0.10, #315). Each one reaches the rows that
    a heading scale on its line reaches (SPEC §4.1): after its line and any blank lines, the lines
    with a tab up to the first line with no tab."""
    lines: list[tuple[int, int]] = []
    start = 0
    for line in text.split("\n"):
        lines.append((start, start + len(line)))
        start += len(line) + 1
    starts = [a for a, _ in lines]
    n = len(lines)
    tab = ["\t" in text[a:b] for a, b in lines]
    blank = [not tab[i] and not text[slice(*lines[i])].strip() for i in range(n)]
    # one pass from the end, so that each line is read once: the end of the run of lines with a
    # tab from each line, and the first line after each line that is not blank
    run_end = [0] * n
    after = [n] * (n + 1)
    for i in range(n - 1, -1, -1):
        run_end[i] = (run_end[i + 1] if i + 1 < n and tab[i + 1] else lines[i][1]) if tab[i] else 0
        after[i] = i + 1 if i + 1 < n and not blank[i + 1] else after[i + 1]

    def rows(i: int) -> tuple[int, int] | None:
        j = after[i]
        return (lines[j][0], run_end[j]) if j < n and tab[j] else None

    out: list[HeadingUnit] = []
    for m in _CURRENCY_SCALE.finditer(text):
        a = m.start()
        while a > 0 and unicodedata.category(text[a - 1]).startswith("L"):
            a -= 1
        i = bisect.bisect_right(starts, m.start()) - 1
        out.append(HeadingUnit(a, m.end(), None, text[a : m.start() + 1], rows(i)))
    for m in _STATEMENT.finditer(text):
        i = bisect.bisect_right(starts, m.start()) - 1
        if "\t" in text[slice(*lines[i])]:
            continue  # a statement is on a line with no tab
        code = next(c for c in CURRENCY_NAMES if m.group(c) is not None)
        out.append(HeadingUnit(m.start(), m.end(), code, "", rows(i)))
    return out


Units = dict[str, tuple[list[str], list[str]]]


def heading_allows(code: str | None, form: str, units: Units) -> set[str] | None:
    """The unit codes that a heading unit allows, or None for an unknown header (SPEC §4.3)."""
    if code is not None:
        return {code}
    have = {c for c, (prefixes, _) in units.items() if form in prefixes}
    if len(form) == 1:
        return have | {c for c, (_, sign) in CURRENCY_NAMES.items() if sign == form}
    return have or None


class HeadingIndex:
    """The heading units of a text, for a check at a token in time that does not grow with the
    number of heading units (#315). Units with the same code and form act the same, so each such
    kind keeps the merged spans of the rows that its units reach."""

    def __init__(self, text: str) -> None:
        found = heading_units(text)
        self.lines = [0] + [m.end() for m in re.finditer("\n", text)]
        self.units = sorted(found, key=lambda h: h.start)
        self.starts = [h.start for h in self.units]
        spans: dict[tuple[str | None, str], list[tuple[int, int]]] = {}
        for h in found:
            if h.reach is not None:
                spans.setdefault((h.code, h.form), []).append(h.reach)
        self.reach: dict[tuple[str | None, str], tuple[list[int], list[int]]] = {}
        for kind, got in spans.items():
            merged: list[list[int]] = []
            for x, y in sorted(got):
                if merged and x <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], y)
                else:
                    merged.append([x, y])
            self.reach[kind] = ([x for x, _ in merged], [y for _, y in merged])

    def reaches(self, kind: tuple[str | None, str], pos: int) -> bool:
        if kind not in self.reach:
            return False
        lo, hi = self.reach[kind]
        i = bisect.bisect_right(lo, pos) - 1
        return i >= 0 and pos <= hi[i]

    def held(self, a: int, b: int, pos: int) -> bool:
        """Whether text[a:b] holds a heading unit that reaches ``pos``. The units that reach a
        token are the last ones before its line, in a row: the heading line of its table and the
        rows above it in the table. So a unit that does not reach the token ends the search, and
        units that reach nothing are never read one by one."""
        line = self.lines[bisect.bisect_right(self.lines, pos) - 1]
        j = bisect.bisect_left(self.starts, min(b, line)) - 1
        while j >= 0 and self.starts[j] >= a:
            h = self.units[j]
            if not h.reaches(pos):
                return False
            if h.end <= b:
                return True
            j -= 1  # this unit runs past the item: try the one before it
        return False

    def currency(self, pos: int, unit: str, units: Units) -> bool:
        """Whether the heading currency of the token at ``pos`` is ``unit`` (SPEC §4.3): each
        heading unit that reaches it and is not unknown allows the unit, and a statement or a
        header whose form is a prefix of the unit settles it. groundgate never chooses between
        two currencies. An unknown header changes nothing, so only the kinds that the currency
        table and the unit table name are read."""
        prefixes = units.get(unit, ([], []))[0]
        forms = set(_CONTINUES) | {x for pre, _ in units.values() for x in pre}
        kinds = [(c, "") for c in CURRENCY_NAMES] + [(None, f) for f in sorted(forms)]
        settled = False
        for code, form in kinds:
            if not self.reaches((code, form), pos):
                continue
            allowed = heading_allows(code, form, units)
            if allowed is not None and unit not in allowed:
                return False
            settled = settled or code is not None or form in prefixes
        return settled


def in_scale(text: str, start: int, end: int) -> bool:
    """Whether text[start:end] holds "in" and a scale word, such as "in thousands" (SPEC §4.6)."""
    return bool(_IN_SCALE.search(text, start, end))


def currency_scale(text: str, start: int, end: int) -> bool:
    """Whether text[start:end] holds a currency scale, such as "£m" (SPEC §4.1)."""
    return bool(_CURRENCY_SCALE.search(text, start, end))


def item_scale(text: str, start: int, end: int) -> int | None:
    """The power of ten of the first scale word in text[start:end], also with a final "s", or
    of the first currency scale, whichever comes first."""
    m = _ITEM_SCALE.search(text, start, end)
    if m is None:
        return None
    if m.group(1) is not None:
        return _SCALE_EXP[m.group(1).lower()]
    return _SUFFIX_EXP[m.group(2).lower()]


def scale_between(text: str, start: int, end: int, power: int | None) -> bool:
    """Whether text[start:end] holds a scale word, also with a final "s", or a currency scale
    whose power of ten is not ``power`` (SPEC §4.6)."""
    for m in _ITEM_SCALE.finditer(text, start, end):
        if m.group(1) is not None or _SUFFIX_EXP[m.group(2).lower()] != power:
            return True
    return False


def holds_form(text: str, start: int, end: int, forms: list[str]) -> bool:
    """Whether text[start:end] holds one of the unit forms as a whole: a form that starts or ends
    with a letter or digit has no letter or digit next to it there (SPEC §4.6)."""
    for form in forms:
        pat = re.escape(form)
        if form[0].isalnum():
            pat = _NOT_ALNUM_BEFORE + pat
        if form[-1].isalnum():
            pat += _NOT_ALNUM_AFTER
        if re.compile(pat).search(text, start, end):
            return True
    return False


def _form_spans(text: str, start: int, end: int, forms: list[str]) -> list[tuple[int, int]]:
    """The spans of the unit forms as a whole in text[start:end], as holds_form finds them, also
    the ones that overlap."""
    out = []
    for form in forms:
        pat = re.escape(form)
        if form[0].isalnum():
            pat = _NOT_ALNUM_BEFORE + pat
        if form[-1].isalnum():
            pat += _NOT_ALNUM_AFTER
        # a lookahead finds every start, also where two occurrences overlap, as in "$$$"
        found = re.compile(f"(?=({pat}))").finditer(text, start, end)
        out += [(m.start(1), m.end(1)) for m in found if m.end(1) <= end]
    return out


def _line(text: str, pos: int) -> tuple[int, int]:
    """The line that holds the position: from after the line break before it to the next one."""
    end = text.find("\n", pos)
    return text.rfind("\n", 0, pos) + 1, len(text) if end < 0 else end


def _blank(line: str) -> bool:
    """A blank line holds only spaces, tabs or carriage returns (SPEC §4.2)."""
    return not line.strip(" \t\r")


def _table_line(text: str, start: int, end: int) -> bool:
    """A line of a table (SPEC §4.6, unit places): not blank, with a tab or no number token."""
    line = text[start:end]
    return not _blank(line) and ("\t" in line or not tokens(text, start, end))


def _row_cells(
    text: str, start: int, end: int, prefixes: list[str]
) -> list[tuple[int, int]] | None:
    """The cells of a line after its first tab, as (start, end), or None if a slot is ambiguous
    (SPEC §4.5, rule 6). A line whose slots hold only unit prefixes has no cells."""
    tab = text.find("\t", start, end)
    if tab < 0:
        return []
    spans = cell_spans(text, tab + 1, end, prefixes)
    # One tab slot can hold a number cell, a dash, an empty slot, or a lone unit prefix.
    # Prefix-only slots immediately before a number retain the existing numeric columns.
    cursor = 0
    left = tab + 1
    while left <= end:
        right = text.find("\t", left, end)
        right = end if right < 0 else right
        count = 0
        while cursor < len(spans) and spans[cursor][0] <= right:
            if spans[cursor][1] > right:
                return None
            count += 1
            cursor += 1
        body = text[left:right].strip(" \r")
        if count > 1 or (count == 0 and body and body not in prefixes):
            return None
        if right == end:
            return spans
        left = right + 1
    return spans


class UnitPlaces:
    """The unit places of one value (SPEC §4.6): ``places(start, end)`` says whether a unit item
    at text[start:end], which ends at or before the token, holds a form of the unit on the
    value's line, in a caption that reaches its table, or in its column. The table above the
    value is read once, so each item costs only its own line."""

    def __init__(self, text: str, tok: Token, prefixes: list[str], suffixes: list[str]) -> None:
        self.text, self.tok, self.prefixes, self.suffixes = text, tok, prefixes, suffixes
        self.line = _line(text, tok.start)
        va, vb = self.line
        self.table: set[int] = set()  # starts of the table lines directly above the value's line
        self.caption: set[int] = set()  # starts of the lines that can hold a caption
        br = brackets_around(text, tok, prefixes)
        # a prefix before the brackets ends between the whitespace before "(" and the "("
        self.bracket = (-1, -1) if br is None else (len(text[: br[0]].rstrip()), br[0])
        self.n = -1
        self.rows: dict[int, list[tuple[int, int]]] = {}
        self.ends: dict[int, int] = {}  # the end of each table and caption line, by its start
        self.starts: list[int] = []
        if "\t" not in text[va:vb]:
            return
        mine = _row_cells(text, va, vb, prefixes) or []
        self.n = next((i for i, (c, _) in enumerate(mine) if c == tok.start), -1)
        pos = va
        while pos > 0:
            a, b = _line(text, pos - 1)
            if not _table_line(text, a, b):
                break
            self.table.add(a)
            self.ends[a] = b
            pos = a
        self.caption = {a for a in self.table if "\t" not in text[a : self.ends[a]]}
        while pos > 0:  # blank lines, then the caption above the table
            a, b = _line(text, pos - 1)
            if not _blank(text[a:b]):
                if "\t" not in text[a:b] and not tokens(text, a, b):
                    self.caption.add(a)
                    self.ends[a] = b
                break
            pos = a
        self.starts = sorted(self.ends)

    def __call__(self, start: int, end: int) -> bool:
        """Whether the item at text[start:end] holds a form of the unit at a unit place."""
        forms = [(a, b, True) for a, b in _form_spans(self.text, start, end, self.prefixes)]
        forms += [(a, b, False) for a, b in _form_spans(self.text, start, end, self.suffixes)]
        return any(self._at(a, b, prefix) for a, b, prefix in forms)

    def _at(self, start: int, end: int, prefix: bool) -> bool:
        """Whether the form at text[start:end] is at a unit place: the place of the form, not of
        the item that holds it."""
        text = self.text
        lo, paren = self.bracket
        if start >= self.line[0] or (prefix and lo <= end <= paren):
            return True
        # the line of the form, from the lines read once above: none is a form on another line
        i = bisect.bisect_right(self.starts, start) - 1
        if i < 0:
            return False
        la = self.starts[i]
        lb = self.ends[la]
        if end > lb:
            return False
        if la in self.caption:
            return True
        if la not in self.table or self.n < 0:
            return False
        if la not in self.rows:  # each row is read once, also for many items on it
            self.rows[la] = _row_cells(text, la, lb, self.prefixes) or []
        row = self.rows[la]
        if self.n >= len(row):
            return False
        c, ce = row[self.n]
        if not text[c:ce].strip(" \r"):  # a blank source slot has no unit to repeat
            return False
        if prefix:  # only whitespace between, found at the first character that is not one
            return end <= c and _NOT_SPACE.search(text, end, c) is None
        return start >= ce and _NOT_SPACE.search(text, ce, start) is None


def _no_number_at(text: str, pos: int) -> bool:
    """Whether the first character at or after pos that is not whitespace is neither the start
    of a number token nor "(" (SPEC §4.5, rule 5). The text may end first."""
    found = _NOT_SPACE.search(text, pos)
    if found is None:
        return True
    at = found.start()
    return text[at] != "(" and all(t.start != at for t in tokens(text, *_line(text, at)))


def _slot_before_cell(text: str, a: int, b: int) -> bool:
    """Whether the prefix at text[a:b] fills its tab slot and the next slot is empty or holds a
    lone dash. That next slot holds the cell of the column (SPEC §4.5, rule 5)."""
    left = a
    while left > 0 and text[left - 1] in " \r":  # no copy of the text before the prefix
        left -= 1
    return left > 0 and text[left - 1] == "\t" and _NEXT_SLOT.match(text, b) is not None


def cell_spans(text: str, start: int, end: int, prefixes: list[str]) -> list[tuple[int, int]]:
    """The table cells in text[start:end] (SPEC §4.5, the column rule), as (start, end): number
    tokens, lone dashes, and a unit prefix that stands alone with no number after it, also where
    two occurrences of a prefix overlap; blank tab slots count too. One position is one cell.
    A prefix that fills its tab slot before an empty slot or a lone dash is not a cell (SPEC
    §4.5, rule 5). An empty unit cell ends where the longest prefix that makes it ends, and a
    cell that is both a number token and an empty cell ends at the later end of the two."""
    toks = tokens(text, start, end)
    numbers = {t.start for t in toks}
    spans = {t.start: t.end for t in toks}
    # one character past the end, so that the lookahead reads the text as it stands
    for m in _LONE_DASH.finditer(text, start, min(len(text), end + 1)):
        if m.end() <= end:
            spans.setdefault(m.start(), m.end())
    empty: dict[int, int] = {}
    past: bool | None = None  # whether a cell can end at the end of the range, read once
    for p in prefixes:
        nxt = -1  # the first non-space at or after the end of the last occurrence
        for m in re.finditer(f"(?=({re.escape(p)}))", text[start:end]):  # overlaps count
            a, b = start + m.start(1), start + m.end(1)
            if (a > 0 and not text[a - 1].isspace()) or (b < len(text) and not text[b].isspace()):
                continue
            if b > nxt:  # the ends grow, so each run of whitespace is read once
                found = _NOT_SPACE.search(text, b, end)
                nxt = end if found is None else found.start()
            if nxt >= end:  # the next character is past the range, such as on the next line
                if past is None:
                    past = _no_number_at(text, end)
                if not past:
                    continue
            elif nxt in numbers or text[nxt] == "(" or _slot_before_cell(text, a, b):
                continue
            empty[a] = max(b, empty.get(a, b))
    for a, b in empty.items():  # a prefix that is also a number token is one cell
        spans[a] = max(b, spans.get(a, b))
    for match in _EMPTY_TAB.finditer(text, start, end):
        a, b = match.span()
        # A bounded regex sees end as end-of-text. The real next character must also end
        # the slot; a range that stops at a number must not invent an empty cell there.
        if b == len(text) or text[b] in "\t\n":
            spans.setdefault(a, b)
    return sorted(spans.items())


def cells(text: str, start: int, end: int, prefixes: list[str]) -> list[int] | None:
    """Cell starts, or None if a crossed tab row has ambiguous slots (SPEC §4.5)."""
    la = text.rfind("\n", 0, start) + 1
    while la <= end:
        lb = text.find("\n", la)
        lb = len(text) if lb < 0 else lb
        if "\t" in text[la:lb] and _row_cells(text, la, lb, prefixes) is None:
            return None
        if lb >= end:
            break
        la = lb + 1
    return [a for a, _ in cell_spans(text, start, end, prefixes)]


def header_column(
    text: str, mentions: list[tuple[int, int, str]], run: list[tuple[int, int]]
) -> bool:
    """A tabbed header has one key per consecutive slot, on one physical line."""
    first = run[0][0]
    if _mixed_header_lines(text, mentions, first):
        return False
    la, lb = _line(text, first)
    last_end = _line(text, run[-1][1] - 1)[1]
    if "\t" not in text[la:last_end]:
        return True  # the existing stream with no tabbed header cells
    if run[-1][1] > lb:
        return False  # mixed line and tab boundaries do not define one ordinal sequence
    if any(text[left[1] : right[0]].count("\t") != 1 for left, right in itertools.pairwise(run)):
        return False  # neither skipped slots nor merged key slots may be compressed
    tab = text.find("\t", la, lb)
    first_keys = [(a, b) for a, b, _ in mentions if la <= a < b <= tab]
    begins_with_key = (
        len(first_keys) == 1
        and not text[la : first_keys[0][0]].strip()
        and not text[first_keys[0][1] : tab].strip()
    )
    if first_keys and not begins_with_key:
        return False  # a decorated or merged key slot is not a disposable row label
    start = la if begins_with_key else tab + 1
    return first >= start and not text[start:first].strip(" \r")


def header(text: str, mentions: list[tuple[int, int, str]], at: int) -> list[tuple[int, int]]:
    """The run holding the mention at ``at``: only whitespace and no key break between mentions
    (SPEC §4.5)."""
    spans = sorted((a, b) for a, b, _ in mentions)
    i = next(n for n, (a, _) in enumerate(spans) if a == at)
    lo = hi = i
    while (
        lo > 0
        and not text[spans[lo - 1][1] : spans[lo][0]].strip()
        and not key_break(text, spans[lo - 1][1], spans[lo][0])
    ):
        lo -= 1
    while (
        hi + 1 < len(spans)
        and not text[spans[hi][1] : spans[hi + 1][0]].strip()
        and not key_break(text, spans[hi][1], spans[hi + 1][0])
    ):
        hi += 1
    return spans[lo : hi + 1]


def host(url: str) -> str | None:
    """The host of a URL (SPEC §2.4), or None when it has no "://"."""
    if "://" not in url:
        return None
    rest = url.split("://", 1)[1]
    rest = re.split(r"[/\\?#]", rest, maxsplit=1)[0]
    rest = rest.rsplit("@", 1)[-1]
    if rest.startswith("["):  # an IPv6 literal keeps its brackets and its colons
        end = rest.find("]")
        return (rest if end < 0 else rest[: end + 1]).lower()
    return rest.split(":", 1)[0].lower()
