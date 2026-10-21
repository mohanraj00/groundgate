from __future__ import annotations

import re
import time
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

import groundgate as gg
from groundgate.text import (
    _MIXED_HEADERS,
    _SENTENCE_END,
    HeadingIndex,
    _label_line_in,
    _mixed_header_lines,
    canonical,
    currency_name,
    first_token_end,
    heading_units,
    in_scale,
    item_scale,
    key_mentions,
    keys_at,
    parse_value,
    qualifiers,
    scale_form,
    sentence,
    sentence_index,
    token_scale,
    tokens,
    verbatim_equal,
)


def _values(text: str) -> list[Decimal | None]:
    return [t.value for t in tokens(text)]


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("$7,000 ($8,000)", [Decimal(7000), Decimal(8000)]),
        ("$252,0000", [None]),
        ("1.73 m2", [Decimal("1.73")]),
        ("ages 50, 60, and 70.", [Decimal(50), Decimal(60), Decimal(70)]),
        ("mean change -0.7 kg; range 5-10", [Decimal("-0.7"), Decimal(5), Decimal(10)]),
        ("\N{MINUS SIGN}3 degrees", [Decimal(-3)]),
        ("2x500 mg, n=338, m2", [Decimal(2), Decimal(338)]),
        ("version 1.2.3", [Decimal("1.2")]),
    ],
)
def test_tokens(text: str, values: list[Decimal | None]) -> None:
    assert _values(text) == values


def test_region_never_reads_a_prefix() -> None:
    text = "code 12345 and 12,500"
    assert [t.value for t in tokens(text, 5, 8)] == []
    assert [t.value for t in tokens(text, 15, 17)] == []
    assert [t.value for t in tokens(text, 5, 10)] == [Decimal(12345)]
    split = "Altimeter 29.97 inches"  # a chunk boundary cut the number after "29."
    assert tokens(split, 10, 13) == []
    assert [t.value for t in tokens(split, 10, 15)] == [Decimal("29.97")]
    assert [t.value for t in tokens("fees of 1,500, then", 8, 13)] == [Decimal(1500)]


@given(st.integers(min_value=-(10**12), max_value=10**12))
def test_grouped_integers_round_trip(n: int) -> None:
    assert parse_value(f"{n:,}") == n
    assert parse_value(str(n)) == n


@given(st.decimals(allow_nan=False, allow_infinity=False, places=4))
def test_canonical_is_stable(d: Decimal) -> None:
    c = canonical(d)
    assert parse_value(c) == d
    assert canonical(Decimal(c)) == c


@pytest.mark.parametrize(
    ("raw", "ok"),
    [
        ("7000", True),
        (" 7,000 ", True),
        ("7,00", False),
        ("7000 mg", False),
        ("", False),
        ("1e5", False),
    ],
)
def test_parse_value(raw: str, ok: bool) -> None:
    assert (parse_value(raw) is not None) is ok


@pytest.mark.parametrize(
    ("text", "target", "expected"),
    [
        ("approximately 7 to 8 hours", "7", {"approx", "range"}),
        ("approximately 7 to 8 hours", "8", {"range"}),
        ("between 30 and 60 mL", "30", {"range"}),
        ("between 30 and 60 mL", "60", {"range"}),
        ("Tablets: 250 mg and 500 mg.", "500", set()),
        ("more than $126,000 but less than $146,000", "146,000", {"lt"}),
        ("$165,000 or more", "165,000", {"ge"}),
        ("up to a maximum of 2,000 mg", "2,000", {"le"}),
        ("age 50 or older", "50", {"ge"}),
        ("The fee is 40. More than 9 apply.", "40", set()),
        ("more than $242,000 (up from $236,000 for 2025)", "236,000", set()),
        ("from 7 to 8 hours", "7", {"range"}),
        ("ages from 50 through 70", "50", {"range"}),
        ("ages from 50 through 70", "70", {"range"}),
        ("The promotion is over.\nFee: $500.", "500", set()),
    ],
)
def test_qualifiers(text: str, target: str, expected: set[str]) -> None:
    tok = next(t for t in tokens(text) if text[t.start : t.end] == target)
    assert qualifiers(text, tok) == expected


def test_verbatim_equal() -> None:
    assert verbatim_equal("mar-\nried  couple", "married couple")
    assert not verbatim_equal("2,000 mg", "2000 mg")


# the first form of the label-line rule, kept as the reference for the linear scan
_LABEL_LINE_REGEX = re.compile(r"(?:\A|\n[ \t\r]*\n)[ \t\r]*([^\n]*?)[ \t\r]*(?=\n[ \t\r]*\n)")


def _label_line_by_regex(text: str, start: int, end: int) -> bool:
    for m in _LABEL_LINE_REGEX.finditer(text, start, end):
        line = m.group(1)
        if line and len(line.split()) <= 12 and not re.search(r"[.;]\s", line + "\n"):
            return True
    return False


@given(
    st.text(alphabet=" \t\r\nab.;", max_size=40),
    st.integers(min_value=0, max_value=40),
    st.integers(min_value=0, max_value=40),
)
def test_the_label_line_scan_agrees_with_the_regex(text: str, a: int, b: int) -> None:
    start, end = min(a, b, len(text)), min(max(a, b), len(text))
    assert _label_line_in(text, start, end) == _label_line_by_regex(text, start, end)


def test_a_line_of_spaces_is_blank_for_a_label_line() -> None:
    # #348: the statement pattern of #341 used the same name as the label-line strip set
    s = "The fee is 25. More text here.\n\nLabel\n \nThe fee is 25.\n"
    assert _label_line_in(s, 0, len(s))
    t = s.replace(" \n", "\n")
    assert _label_line_in(t, 0, len(t))


def test_a_long_line_of_spaces_takes_linear_time() -> None:
    mentions = key_mentions("Hypertension", ("Hypertension",))
    text = "Hypertension\n" + " " * 200_000 + "\nThe dose is 5 mg."
    t0 = time.perf_counter()
    assert keys_at(text, mentions, text.index("5 mg")) == {"Hypertension"}
    assert time.perf_counter() - t0 < 1


def test_repeated_key_lines_scale_with_many_values() -> None:
    """Four times the header lines and value lookups must not cost quadratic work."""

    def time_for(lines: int, values: int) -> float:
        text = "2024\n" * lines + "Cash $100\n" * values
        # Build source offsets directly; key matching is outside this regression's scope.
        mentions = [(i * 5, i * 5 + 4, "2024") for i in range(lines)]
        best = float("inf")
        for _ in range(2):
            started = time.perf_counter()
            with sentence_index():
                for i in range(values):
                    # Different header occurrences prevent a per-position memo from hiding scans.
                    assert not _mixed_header_lines(text, mentions, mentions[-1 - i][0])
            best = min(best, time.perf_counter() - started)
        return best

    small = time_for(1000, 32)
    large = time_for(4000, 128)
    assert large < 8 * small, (small, large)


def test_mixed_header_index_keeps_key_sets_separate_and_expires() -> None:
    text = "Year\t2025\tChange\n2024\nCash\t$100"
    both = [(5, 9, "2025"), (17, 21, "2024")]
    one = both[1:]
    assert _MIXED_HEADERS.get() is None
    with sentence_index():
        assert _mixed_header_lines(text, both, 17)
        assert not _mixed_header_lines(text, one, 17)
        outer = _MIXED_HEADERS.get()
        assert outer is not None and len(outer) == 2
        with sentence_index():
            assert _MIXED_HEADERS.get() == {}
            assert _mixed_header_lines(text, both, 17)
        assert _MIXED_HEADERS.get() is outer
    assert _MIXED_HEADERS.get() is None


def test_two_blank_lines_break_a_prose_heading() -> None:
    text = "Hypertension\n\n" + " " * 200_000 + "\nThe dose is 5 mg."
    mentions = key_mentions(text, ("Hypertension",))
    assert keys_at(text, mentions, text.index("5 mg")) == set()


_PIECES = st.lists(
    st.sampled_from(["1", "0", ",", ".", "-", "\u2212", "a", " ", "\n", "\t", ";", "\u2022"]),
    max_size=30,
).map("".join)


@given(_PIECES, st.data())
def test_first_token_end_agrees_with_tokens(text: str, data: st.DataObject) -> None:
    """``tokens(text, start, end)`` is empty exactly when the first token from ``start`` is
    missing or ends after ``end`` (#249)."""
    start = data.draw(st.integers(0, len(text)))
    end = data.draw(st.integers(start, len(text)))
    first = first_token_end(text, start)
    assert bool(tokens(text, start, end)) == (first is not None and first <= end)


@given(_PIECES, st.data())
def test_sentence_agrees_with_a_scan(text: str, data: st.DataObject) -> None:
    """The sentence ends read once give the same sentence as a scan from each place (#249)."""
    pos = data.draw(st.integers(0, len(text)))
    end = _SENTENCE_END
    left = max((m.end() for m in end.finditer(text, 0, pos)), default=0)
    right = next((m.start() for m in end.finditer(text, pos)), len(text))
    assert sentence(text, pos) == (left, right)
    with sentence_index():
        assert sentence(text, pos) == (left, right)


def test_heading_units_read_each_line_once() -> None:
    """A table with a currency header on every row stays linear (#315): four times the rows take
    less than eight times as long."""

    def time_for(rows: int) -> float:
        text = "(in Australian dollars)\n" + "\t$m\n" * rows
        best = float("inf")
        for _ in range(2):
            began = time.perf_counter()
            found = heading_units(text)
            best = min(best, time.perf_counter() - began)
            assert len(found) == rows + 1
        return best

    assert time_for(20000) < 8 * time_for(5000)


def test_heading_index_checks_each_kind_once() -> None:
    """With a currency header on every row, the check at a token reads each kind of heading unit
    once, not each unit that reaches it (#315): four times the rows and the checks take less
    than eight times as long."""
    units = {"USD": (["US$", "$"], ["USD", "dollars"])}

    def time_for(rows: int) -> float:
        head = "(in Australian dollars)\n"
        text = head + "".join(f"Revenue\t{k + 1}\t$m\n" for k in range(rows))
        index = HeadingIndex(text)
        places = [text.index(f"\t{k + 1}\t") + 1 for k in range(0, rows, 4)]
        best = float("inf")
        for _ in range(2):
            began = time.perf_counter()
            for pos in places:
                assert index.held(1, 22, pos)
                assert index.currency(pos, "AUD", units)
            best = min(best, time.perf_counter() - began)
        return best

    assert time_for(20000) < 8 * time_for(5000)


def test_heading_conflict_reads_only_currency_units() -> None:
    """A heading conflict needs a currency unit: a code of the currency table, or a unit with a
    prefix that ends with a currency sign (SPEC §4.3, #365). `%`, and a schema unit with a sign
    that §4.1 does not list, have none. JPY is a code of the currency table since spec 0.11
    (#368), so it is a currency unit with any prefix."""
    units = {
        "USD": (["US$", "$"], ["USD", "dollars"]),
        "AUD": ([], []),
        "CAD2": (["C$"], []),
        "%": ([], ["%"]),
        "JPY": (["\u00a5"], []),
        "YEN2": (["\u00a5"], []),
    }
    text = "(in Australian dollars)\nRevenue\t5\n"
    index = HeadingIndex(text)
    pos = text.index("5")
    assert index.conflict(pos, "USD", units)
    assert index.conflict(pos, "CAD2", units)
    assert not index.conflict(pos, "AUD", units)
    assert not index.conflict(pos, "%", units)
    assert index.conflict(pos, "JPY", units)
    assert not index.conflict(pos, "YEN2", units)
    assert not index.conflict(text.index("Australian"), "USD", units)  # its own line


def test_heading_conflict_of_two_statements_and_unknown_headers() -> None:
    """Two statements that do not agree give a conflict for each currency. An unknown header
    allows no code and gives no conflict (SPEC §4.3, #365)."""
    units = {"USD": (["US$", "$"], ["USD", "dollars"])}
    text = "Group in Australian dollars, parent in New Zealand dollars\nRevenue\t5\n"
    pos = text.index("5")
    index = HeadingIndex(text)
    assert index.conflict(pos, "AUD", units)
    assert index.conflict(pos, "NZD", units)
    text = "\tHK$'000\nRevenue\t5\n"
    assert not HeadingIndex(text).conflict(text.index("5"), "USD", units)


def test_the_outside_path_reads_the_heading_conflict() -> None:
    """An external item still holds a value under a statement of another currency, and the
    decision lists the unit as missing (SPEC §3.2, spec 0.11, #367)."""
    item = {
        "source": "external",
        "url": "https://example.org/a",
        "retrieved": "2026-10-01",
        "text": "Presented in Australian dollars\n\t2025\nRevenue\t$5,200\n",
    }
    receipt = gg.admit(
        "x",
        {"fields": {"usd": {"unit": "USD"}}},
        [{"id": "c1", "field": "usd", "value": "5200", "unit": "USD", "evidence": [item]}],
        {"sources": {"external": {"allow": ["*"], "other": "review"}, "knowledge": "review"}},
    )
    (d,) = receipt.decisions
    assert (d.outcome, list(d.codes), list(d.missing)) == (
        "needs_verification",
        ["PART_MISSING", "ADMITTED_BY_POLICY"],
        ["unit"],
    )


def test_heading_index_held_skips_units_that_reach_nothing() -> None:
    """An item span that holds many headers that reach nothing does not read them one by one
    (#315): four times the headers and the checks take less than eight times as long."""

    def time_for(rows: int) -> float:
        text = "£m\n" * rows + "No table here.\nRevenue\t5\n"
        index = HeadingIndex(text)
        pos = text.index("\t5") + 1
        best = float("inf")
        for _ in range(2):
            began = time.perf_counter()
            for _ in range(rows // 4):
                assert not index.held(0, pos, pos)
            best = min(best, time.perf_counter() - began)
        return best

    assert time_for(40000) < 8 * time_for(10000)


def test_a_long_s_in_a_scale_word_gives_a_receipt() -> None:
    """The input of #350: re.I matched "thou\u017fand" with "thousand", and the lookup then raised
    KeyError. The fold of the long s is "s" (#356), so the word is a scale word."""
    s = "The fee is 5 thou\u017fand."  # U+017F LATIN SMALL LETTER LONG S
    receipt = gg.admit(
        s,
        {"fields": {"fee": {"type": "integer"}}},
        [{"id": "a", "field": "fee", "value": "5", "evidence": {"text": "5 thou\u017fand"}}],
    )
    assert [(d.outcome, d.codes) for d in receipt.decisions] == [
        ("needs_verification", ("SCALE_WORD",))
    ]


FOLDED = [
    ("thou\u017fand", 3),
    ("THOU\u017fAND", 3),
    ("b\u0130llion", 9),
    ("b\u0131llion", 9),
    ("m\u0131ll\u0131on", 6),
    ("tr\u0130ll\u0131on", 12),
    ("la\u212ah", 5),
]


@pytest.mark.parametrize(("word", "power"), FOLDED)
def test_the_look_alike_letters_fold_in_a_scale_word(word: str, power: int) -> None:
    """The fold of the long s, the dotless i, the dotted capital I and the Kelvin sign is an
    ASCII letter (SPEC §4, #356). The final "s" of "(in thousands)" folds too."""
    for s in (f"5 {word} (in {word}s)", f"5 {word} (in {word}\u017f)"):
        assert token_scale(s, tokens(s)[0]) == power
        assert item_scale(s, 0, len(s)) == power
        assert in_scale(s, 0, len(s))


@pytest.mark.parametrize("word", ["thous\u00e1nd", "m\u00edllion", "thou\u00dfand"])
def test_other_letters_are_no_scale_word(word: str) -> None:
    """A letter whose fold is not the letter of the word does not match it."""
    s = f"5 {word} (in {word}s)"
    assert token_scale(s, tokens(s)[0]) is None
    assert item_scale(s, 0, len(s)) is None
    assert not in_scale(s, 0, len(s))


@pytest.mark.parametrize(("word", "power"), [("THOUSAND", 3), ("Million", 6), ("LAKH", 5)])
def test_capitals_still_make_a_scale_word(word: str, power: int) -> None:
    s = f"5 {word} (in {word}S)"
    assert token_scale(s, tokens(s)[0]) == power
    assert item_scale(s, 0, len(s)) == power
    assert in_scale(s, 0, len(s))


@pytest.mark.parametrize("abbreviation", ["U.S.", "u.s.", "U.\N{LATIN SMALL LETTER LONG S}."])
def test_an_abbreviation_matches_by_the_fold(abbreviation: str) -> None:
    """SPEC §4.2 reads an abbreviation letter by letter by the fold (#356)."""
    s = f"The fee is in {abbreviation} dollars and is 5."
    assert sentence(s, len(s) - 2, qualifiers=True) == (0, len(s))


EUR_FORMS = ["€", "EUR", "euros"]
USD_FORMS = ["$", "US$", "USD", "dollars"]


@pytest.mark.parametrize(
    ("text", "unit", "forms"),
    [
        ("(in thousands)", None, []),
        ("(in € million)", "EUR", EUR_FORMS),
        ("(In €million, unless otherwise stated)", "EUR", EUR_FORMS),
        ("in EUR thousands", "EUR", EUR_FORMS),
        ("in euro millions", "EUR", EUR_FORMS),
        ("(MILLIONS OF CANADIAN DOLLARS)", "CAD", []),
        ("thousands of USD", "USD", USD_FORMS),
        ("billions of U.S. dollars", "USD", USD_FORMS),
        ("DKK million", "DKK", []),
        ("Danish krone millions", "DKK", []),
        ("$ millions", "USD", USD_FORMS),
        ("EUR million (per share data in EUR)", "EUR", EUR_FORMS),
    ],
)
def test_a_scale_form(text: str, unit: str | None, forms: list[str]) -> None:
    """The three scale forms of SPEC §4.6 (spec 0.11, #423)."""
    assert scale_form(text, 0, len(text), unit, forms)


@pytest.mark.parametrize(
    ("text", "unit", "forms"),
    [
        ("(in € million)", None, []),
        ("(in $ million)", "EUR", EUR_FORMS),
        ("(thousands of customers)", "USD", USD_FORMS),
        ("(thousands of dollars)", "USD", USD_FORMS),
        ("(millions of US dollars)", "CAD", []),
        ("millions of cad", "CAD", []),
        ("EUR million", "DKK", []),
        ("tCO2e per EUR million", "EUR", EUR_FORMS),
        ("tCO2e PER\nEUR million", "EUR", EUR_FORMS),
        ("tCO2e/EUR million", "EUR", EUR_FORMS),
        ("tCO2e / EUR million", "EUR", EUR_FORMS),
        ("EURmillion", "EUR", EUR_FORMS),
        ("millions", "CAD", []),
        ("in Canadian dollars", "CAD", []),
    ],
)
def test_no_scale_form(text: str, unit: str | None, forms: list[str]) -> None:
    """Texts that hold no scale form for the field's unit (SPEC §4.6, spec 0.11, #423)."""
    assert not scale_form(text, 0, len(text), unit, forms)


def test_per_before_the_item_stops_form_3() -> None:
    """The "per" stands before the item, outside it: the form still does not count."""
    text = "Carbon intensity (tCO2e per EUR million of net sales)"
    a = text.index("EUR")
    assert not scale_form(text, a, a + len("EUR million"), "EUR", EUR_FORMS)
    assert scale_form("Super EUR million", 6, 17, "EUR", EUR_FORMS)


@pytest.mark.parametrize(
    ("text", "unit", "held"),
    [
        ("Canadian dollars", "CAD", True),
        ("canadian DOLLAR", "CAD", True),
        ("in CAD", "CAD", True),
        ("in cad", "CAD", False),
        ("US dollars", "CAD", False),
        ("CADS", "CAD", False),
        ("Danish kroner", "DKK", True),
        ("kroner", "DKK", False),
        ("Canadian dollars", "XYZ", False),
    ],
)
def test_a_currency_name(text: str, unit: str, held: bool) -> None:
    """A unit item can hold a currency name or the code of a unit with no form (spec 0.11,
    #423). The code matches in capitals only, and a name as a whole word."""
    assert currency_name(text, 0, len(text), unit) is held


@pytest.mark.parametrize(
    "text",
    [
        "tCO2e/US$ million",
        "tCO2e per US$ million",
        "tCO2e/US dollars million",
        "tCO2e/U.S. dollars million",
        "tCO2e /\tUnited  States dollars millions",
    ],
)
def test_the_longest_form_reads_per_and_slash(text: str) -> None:
    """Form 3 reads the longest currency form that ends at the scale word, so a "$" or
    "dollars" inside a longer form after "/" or "per" does not count (spec 0.11, #423)."""
    assert not scale_form(text, 0, len(text), "USD", USD_FORMS)
    a = text.rindex("$") if "$" in text else text.rindex("dollars")
    assert not scale_form(text, a, len(text), "USD", USD_FORMS)


@pytest.mark.parametrize("text", ["\tUS$ million", "Amounts in US dollars million", "MUS$ million"])
def test_a_longest_form_with_no_per_counts(text: str) -> None:
    assert scale_form(text, 0, len(text), "USD", USD_FORMS)
