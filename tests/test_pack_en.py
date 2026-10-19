"""The base vocabulary pack ``en`` 1.0.0 (SPEC §4.7, #333).

The proof of stage 1 of docs/design/packs.md §10.3: the patterns that the core builds from the
pack match the same text as the patterns that the code held before. The old patterns below are
the patterns of groundgate before #333, kept for this proof.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from groundgate import text
from groundgate.admit import NULL_LITERALS
from groundgate.pack import BASE, pack_digest

REPO = Path(__file__).parent.parent
SPEC = REPO / "SPEC.md"


# --------------------------------------------------------------- the old patterns (before #333)

_OLD_ABBREVIATIONS = (  # noqa: SIM905
    "a.m. p.m. approx. ca. cf. e.g. i.e. etc. vs. viz. no. nos. p. pp. para. fig. figs. vol. rs. "
    "u.s. u.k. dr. mr. mrs. ms. jr. sr. st. inc. co. corp. ltd. est. min. max. hr. hrs. mo. mos. "
    "yr. yrs. wk. wks. wt. oz. lb. lbs."
).split()
_OLD_CONTINUES = "$€£₹"
_OLD_BEFORE = {
    "approx": ["approximately", "approx", "about", "around", "nearly", "roughly", "generally", "~",
               "≈"],
    "gt": ["more than", "greater than", "above", "over", "exceed", "exceeds", "exceeding", ">"],
    "lt": ["less than", "fewer than", "below", "under", "<"],
    "ge": ["at least", "minimum of", "no less than", "≥"],
    "le": ["up to", "maximum of", "at most", "no more than", "≤"],
    "range": ["between"],
}  # fmt: skip
_OLD_AFTER = {
    "ge": ["or more", "or greater", "or older", "or higher", "or above"],
    "le": ["or less", "or fewer", "or younger", "or lower", "or below"],
}
_OLD_UNIT_WORD = r"(?:[^\s\d]{1,12}\s+(?=(?:through|thru|to|and)\b))?"
_OLD_CHANGE = (
    "increase|increases|increased|increasing|decrease|decreases|decreased|decreasing|"
    "raise|raises|raised|raising|reduce|reduces|reduced|reducing|reduction|reductions|"
    "lowers|lowered|lowering|rise|rises|rose|risen|rising|fall|falls|fell|fallen|falling|"
    "drop|drops|dropped|dropping|grow|grows|grew|grown|growing|"
    "change|changes|changed|changing|decline|declines|declined|declining|"
    "adjust|adjusts|adjusted|adjusting|adjustment|adjustments|"
    "revise|revises|revised|revising|revision|revisions"
)
_OLD_DETERMINER = "the|a|an|its|their|this|that|these|those"
_OLD_NOT_BETWEEN = (
    "about|above|across|after|among|at|before|below|between|by|during|for|from|in|into|on|over|"
    "per|since|through|to|under|until|with|within|range|ranges|ranged|ranging|vary|varies|"
    "varied|varying"
)
_OLD_PLAIN = rf"\s+(?!(?:{_OLD_NOT_BETWEEN})\b)[^\W\d_](?:[^\W\d_]|['\u2019-](?=[^\W\d_]))*"
_OLD_CHANGE_GAP = (
    rf"(?:\s+(?:in|of|to)\s+(?:{_OLD_DETERMINER})(?:{_OLD_PLAIN}){{0,4}}"
    rf"|\s+(?:{_OLD_DETERMINER})(?:{_OLD_PLAIN}){{0,5}})?"
)
_OLD_CURRENCY_FORM = (
    "["
    + re.escape(_OLD_CONTINUES)
    + r"](k|K|m|M|bn|Bn|BN|'000|\u2019000|000(?![,.][0-9]))(?![^\W_])"
)
_OLD_CURRENCY_NAMES = {
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
_OLD_PLURALS = ("dollars", "euros", "pounds", "rupees")


def _old_name_pattern(name: str) -> str:
    words = [re.escape(w[:-1]) + "s?" if w in _OLD_PLURALS else re.escape(w) for w in name.split()]
    return r"[^\S\n]+".join(words)


_OLD_CURRENCY = {
    "USD": (["US$", "$"], ["USD", "dollars"]),
    "EUR": (["€"], ["EUR", "euros"]),
    "GBP": (["£"], ["GBP"]),
    "INR": (["₹", "Rs.", "Rs"], ["INR", "rupees"]),
    "%": ([], ["%", "percent"]),
}


def _old_units() -> dict[str, tuple[list[str], list[str]]]:
    table = {k: (list(p), list(s)) for k, (p, s) in _OLD_CURRENCY.items()}
    for code in ["mg", "mcg", "g", "kg", "mL", "L"]:
        table[code] = ([], [code])
    for code in ["hours", "days", "weeks", "months", "years", "minutes"]:
        single = code[:-1]
        table[code] = ([], [code, single, f"-{single}"])
    return table


def _old_strip_unit_suffix(rest: str) -> str:
    m = re.match(r"^\s*[^\s\d]{1,12}(?=\s+(?:through|thru|to|and)\b)", rest)
    return rest[m.end() :] if m else rest


OLD = {
    "_ABBREVIATION_END": re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(a) for a in _OLD_ABBREVIATIONS) + r")\Z", re.I
    ),
    "_NEGATION_END": re.compile(r"\b(?:not|cannot|can['\u2019]t)\s+(?:be\s+)?$", re.I),
    "_RANGE_NEXT": re.compile(r"^\s*(?:through|thru|to|-|\u2013)\s*\S{0,4}?(?=[-\u2212]?\d)", re.I),
    "_RANGE_PREV": re.compile(
        rf"\s*{_OLD_UNIT_WORD}(?:through|thru|to|-|\u2013)\s*\S{{0,4}}?", re.I
    ),
    "_AND_NEXT": re.compile(r"^\s*and\s*\S{0,4}?(?=[-\u2212]?\d)", re.I),
    "_AND_PREV": re.compile(rf"\s*{_OLD_UNIT_WORD}and\s*\S{{0,4}}?", re.I),
    "_BETWEEN_END": re.compile(r"\bbetween\s*\S{0,4}?$", re.I),
    "_BETWEEN": re.compile(r"(?<![^\W_])between\s", re.I),
    "_CHANGE_FROM": re.compile(rf"\b(?:{_OLD_CHANGE}){_OLD_CHANGE_GAP}\s+from\s+\S{{0,4}}?$", re.I),
    "_SCALE": re.compile(r"^\s{0,2}(thousand|million|billion|trillion|lakh|crore)\b", re.I),
    "_SCALE_SUFFIX": re.compile(r"(k|K|m|M|bn|Bn|BN)(?![^\W_])"),
    "_CURRENCY_SCALE": re.compile(_OLD_CURRENCY_FORM),
    "_PER_UNIT": re.compile(
        r"\s*(?:/|per\b)\s*(?:\d+(?:\.\d+)?\s*)?"
        r"(?:kg|kilograms?|lbs?|pounds?|m2|m²|m\^2|square\s+met(?:er|re)s?"
        r"|mL|dL|L|lit(?:er|re)s?)(?![A-Za-z])",
        re.I,
    ),
    "_GAIN": re.compile(
        r"(?<![^\W_])(?:income|gain|gains|profit|profits|earnings)(?![^\W_])", re.I
    ),
    "_ITEM_SCALE": re.compile(
        r"(?<![^\W_])(?i:(thousand|million|billion|trillion|lakh|crore)s?)(?![^\W_])|"
        + _OLD_CURRENCY_FORM
    ),
    "_IN_SCALE": re.compile(
        r"(?<![^\W_])in\s+(?:thousand|million|billion|trillion|lakh|crore)s?(?![^\W_])", re.I
    ),
    "_NEGATION": re.compile(r"(?<![^\W_])(?:no|not|without)\s+\Z", re.I),
    "_STATEMENT": re.compile(
        r"(?<![^\W_])(?i:in)[^\S\n]+"
        r"(?:(?i:thousand|million|billion|trillion|lakh|crore)s?[^\S\n]+(?i:of)[^\S\n]+)?(?:"
        + "|".join(
            f"(?P<{code}>(?i:{'|'.join(_old_name_pattern(n) for n in names)})|{code})"
            for code, (names, _) in _OLD_CURRENCY_NAMES.items()
        )
        + r")(?![^\W_])"
    ),
}
# each pattern is compared where the core uses it: searched in a whole text, matched at a
# number's end, searched in a text that ends at a probe point, or fully matched between numbers
FIND = ["_BETWEEN", "_GAIN", "_ITEM_SCALE", "_IN_SCALE", "_CURRENCY_SCALE", "_SCALE_SUFFIX",
        "_PER_UNIT", "_STATEMENT"]  # fmt: skip
AT_END = ["_SCALE_SUFFIX", "_PER_UNIT"]
BETWEEN_NUMBERS = ["_RANGE_PREV", "_AND_PREV"]


# --------------------------------------------------------------------------------- the texts


def _strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _texts() -> list[tuple[str, str]]:
    """Every conformance string, and every bench document text in the repository."""
    out = []
    for path in sorted((REPO / "conformance").glob("*/*.json")):
        strings = [s for s in _strings(json.loads(path.read_text(encoding="utf-8"))) if s]
        out.append((str(path.relative_to(REPO)), "\n\n".join(strings)))
    for path in sorted((REPO / "bench").rglob("*")):
        if path.suffix in (".txt", ".html") and "runs" not in path.parts and path.is_file():
            out.append((str(path.relative_to(REPO)), path.read_text(encoding="utf-8")))
    return out


def _spans(m: re.Match[str] | None) -> object:
    return None if m is None else (m.span(), m.groups())


def _probes(s: str, toks: list[text.Token]) -> dict[str, list[int]]:
    """The points where the core reads each pattern that ends at the end of its text: a
    negation before a qualifier word or a loss word, `between` or a change phrase before a
    number, and an abbreviation before a dot."""
    starts = {t.start for t in toks}
    qualifier_starts = {m.start() for rx in text._BEFORE_RE.values() for m in rx.finditer(s)}
    loss_starts = {m.start() for m in text._LOSS.finditer(s)}
    before_number = starts | {
        len(s[max(0, p - 200) : p].rstrip()) + max(0, p - 200) for p in starts
    }
    return {
        "_NEGATION_END": sorted(qualifier_starts),
        "_BETWEEN_END": sorted(before_number),
        "_CHANGE_FROM": sorted(starts),
        "_NEGATION": sorted(loss_starts),
        "_ABBREVIATION_END": sorted(m.end() for m in re.finditer(r"\.", s)),
    }


TEXTS = _texts()


@pytest.mark.parametrize(("name", "s"), TEXTS, ids=[name for name, _ in TEXTS])
def test_the_pack_patterns_match_as_the_old_patterns(name: str, s: str) -> None:
    """Part 1 of the proof: every match of every moved pattern stays the same."""
    toks = text.tokens(s)
    for key in FIND:
        new, old = getattr(text, key), OLD[key]
        assert [_spans(m) for m in new.finditer(s)] == [_spans(m) for m in old.finditer(s)], key
    ends = sorted({t.end for t in toks})
    for e in ends:
        assert _spans(text._SCALE.match(s[e : e + 12])) == _spans(
            OLD["_SCALE"].match(s[e : e + 12])
        )
        for key in AT_END:
            assert _spans(getattr(text, key).match(s, e)) == _spans(OLD[key].match(s, e)), key
        rest = s[e : e + 300]
        new_rest, old_rest = text._strip_unit_suffix(rest), _old_strip_unit_suffix(rest)
        assert new_rest == old_rest
        for key in ("_RANGE_NEXT", "_AND_NEXT"):
            assert _spans(getattr(text, key).match(rest)) == _spans(OLD[key].match(rest)), key
    for p in (i for i, ch in enumerate(s) if ch in _OLD_CONTINUES):
        new_m, old_m = text._CURRENCY_SCALE.match(s, p), OLD["_CURRENCY_SCALE"].match(s, p)
        assert _spans(new_m) == _spans(old_m), ("_CURRENCY_SCALE", p)
    for key, points in _probes(s, toks).items():
        for p in points:
            lo = max(0, p - 200)
            new_m, old_m = getattr(text, key).search(s, lo, p), OLD[key].search(s, lo, p)
            assert _spans(new_m) == _spans(old_m), (key, p)
    for a, b in itertools.pairwise(toks):
        if a.end <= b.start:
            for key in BETWEEN_NUMBERS:
                new_m, old_m = (
                    getattr(text, key).fullmatch(s, a.end, b.start),
                    OLD[key].fullmatch(s, a.end, b.start),
                )
                assert _spans(new_m) == _spans(old_m), (key, a.end)


def test_the_pack_tables_are_the_old_tables() -> None:
    assert text.builtin_units() == _old_units()
    assert list(text.builtin_units()) == list(_old_units())
    assert set(NULL_LITERALS) == {"null", "none", "nil", "n/a"}
    assert text._CONTINUES == _OLD_CONTINUES
    assert text._ABBREVIATIONS == _OLD_ABBREVIATIONS
    assert text._BEFORE == _OLD_BEFORE and text._AFTER == _OLD_AFTER
    assert text._SCALE_EXP == {
        "thousand": 3, "million": 6, "billion": 9, "trillion": 12, "lakh": 5, "crore": 7,
    }  # fmt: skip
    assert text._SUFFIX_EXP == {"k": 3, "m": 6, "bn": 9, "'000": 3, "\u2019000": 3, "000": 3}
    assert {c: s for c, (_, s) in text.CURRENCY_NAMES.items()} == {
        c: s for c, (_, s) in _OLD_CURRENCY_NAMES.items()
    }


def test_the_spec_gives_the_digest_of_the_base_pack() -> None:
    """SPEC §4.7 names the base pack and its digest, and the core loads a pack with that digest."""
    found = re.search(
        r"`(sha256:[0-9a-f]{64})`", SPEC.read_text(encoding="utf-8").split("### 4.7")[1]
    )
    assert found is not None
    assert pack_digest(BASE) == found.group(1)
    assert (BASE["groundgate_pack"], BASE["type"], BASE["id"], BASE["version"]) == (
        1, "vocabulary", "en", "1.0.0",
    )  # fmt: skip


def test_the_base_pack_holds_no_loss_word() -> None:
    """The loss words stay in the code until the `finance` pack takes them (#336)."""
    assert "loss" not in BASE.get("sign", {})


def test_key_scope_and_the_unit_search_end_a_sentence_at_every_dot() -> None:
    """Part 6 of the proof: only the qualifier window reads the abbreviations. The key scope and
    the unit search use ``sentence`` without ``qualifiers``, and there every dot ends a sentence."""
    for abbreviation in text._ABBREVIATIONS:
        s = f"A fee {abbreviation} 25 applies."
        dot = s.index(abbreviation) + len(abbreviation) - 1
        pos = s.index("25")
        assert text.sentence(s, pos)[0] == dot + 2, abbreviation
        assert text.sentence(s, pos, qualifiers=True)[0] == 0, abbreviation
        with text.sentence_index():
            assert text.sentence(s, pos)[0] == dot + 2, abbreviation
