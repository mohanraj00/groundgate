from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from groundgate.text import canonical, parse_value, qualifiers, tokens, verbatim_equal


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
