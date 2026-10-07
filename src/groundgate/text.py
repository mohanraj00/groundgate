"""Text rules (SPEC §4): number tokens, qualifiers, units, whitespace. Offsets are code points."""

from __future__ import annotations

import re
import unicodedata
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
_CONTINUES = "$€£₹"
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
    end = len(text) if end is None else end
    out = []
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


# a table sentence (SPEC §4.5): 3 or more line breaks and mentions of 2 or more keys
_TABLE_BREAKS, _TABLE_KEYS = 3, 2


def _own_keys(text: str, mentions: list[tuple[int, int, str]], pos: int) -> set[str] | None:
    """The keys that the value's own text names: in a table sentence those of its line (maybe
    none), else those of its sentence, or None when the sentence names no key (SPEC §4.5)."""
    s0, s1 = sentence(text, pos)
    inside = {k for a, b, k in mentions if s0 <= a and b <= s1}
    if len(inside) >= _TABLE_KEYS and text.count("\n", s0, s1) >= _TABLE_BREAKS:
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
    stands between them (SPEC §4.5)."""
    s0, _ = sentence(text, pos)
    named = _own_keys(text, mentions, pos)
    if named is not None:
        return named
    before = [(b, k) for _, b, k in mentions if b <= pos]
    if not before:
        return set()
    end, key = max(before)
    return set() if _label_line_in(text, end, s0) else {key}


# -------------------------------------------------------------- evidence items

_LOSS = re.compile(r"(?<![^\W_])(?:loss|losses|deficit|deficits)(?![^\W_])", re.I)
_GAIN = re.compile(r"(?<![^\W_])(?:income|gain|gains|profit|profits|earnings)(?![^\W_])", re.I)
_ITEM_SCALE = re.compile(
    r"(?<![^\W_])(thousand|million|billion|trillion|lakh|crore)s?(?![^\W_])", re.I
)
_LONE_DASH = re.compile("(?<!\\S)[-\u2013\u2014](?!\\S)")
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


def in_scale(text: str, start: int, end: int) -> bool:
    """Whether text[start:end] holds "in" and a scale word, such as "in thousands" (SPEC §4.6)."""
    return bool(_IN_SCALE.search(text, start, end))


def item_scale(text: str, start: int, end: int) -> int | None:
    """The power of ten of the first scale word in text[start:end], also with a final "s"."""
    m = _ITEM_SCALE.search(text, start, end)
    return None if m is None else _SCALE_EXP[m.group(1).lower()]


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


def cells(text: str, start: int, end: int, prefixes: list[str]) -> list[int]:
    """The starts of the table cells in text[start:end] (SPEC §4.5, the column rule): number
    tokens, lone dashes, and a unit prefix that stands alone with no number after it."""
    toks = tokens(text, start, end)
    starts = [t.start for t in toks]
    starts += [
        m.start() for m in _LONE_DASH.finditer(text) if start <= m.start() and m.end() <= end
    ]
    numbers = {t.start for t in toks}
    for p in prefixes:
        for m in re.finditer(re.escape(p), text[start:end]):
            a, b = start + m.start(), start + m.end()
            if (a > 0 and not text[a - 1].isspace()) or (b < len(text) and not text[b].isspace()):
                continue
            rest = len(text[b:end]) - len(text[b:end].lstrip())
            nxt = b + rest
            if nxt >= end or nxt in numbers or text[nxt] == "(":
                continue
            starts.append(a)
    return sorted(starts)


def header(text: str, mentions: list[tuple[int, int, str]], at: int) -> list[tuple[int, int]]:
    """The run of key mentions that holds the mention starting at ``at``, where only whitespace
    stands between two mentions of the run (SPEC §4.5)."""
    spans = sorted((a, b) for a, b, _ in mentions)
    i = next(n for n, (a, _) in enumerate(spans) if a == at)
    lo = hi = i
    while lo > 0 and not text[spans[lo - 1][1] : spans[lo][0]].strip():
        lo -= 1
    while hi + 1 < len(spans) and not text[spans[hi][1] : spans[hi + 1][0]].strip():
        hi += 1
    return spans[lo : hi + 1]


def host(url: str) -> str | None:
    """The host of a URL (SPEC §2.4), or None when it has no "://"."""
    if "://" not in url:
        return None
    rest = url.split("://", 1)[1]
    rest = re.split(r"[/\\?#]", rest, maxsplit=1)[0]
    rest = rest.rsplit("@", 1)[-1]
    return rest.split(":", 1)[0].lower()
