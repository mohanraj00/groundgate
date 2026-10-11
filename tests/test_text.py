from __future__ import annotations

import re
import time
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from groundgate.text import (
    _SENTENCE_END,
    _label_line_in,
    canonical,
    first_token_end,
    key_mentions,
    keys_at,
    parse_value,
    qualifiers,
    sentence,
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


def test_a_long_line_of_spaces_takes_linear_time() -> None:
    mentions = key_mentions("Hypertension", ("Hypertension",))
    text = "Hypertension\n\n" + " " * 200_000 + "\nThe dose is 5 mg."
    t0 = time.perf_counter()
    assert keys_at(text, mentions, text.index("5 mg")) == {"Hypertension"}
    assert time.perf_counter() - t0 < 1


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
