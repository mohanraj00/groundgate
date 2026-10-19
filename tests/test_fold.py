"""The case rule of SPEC §4 (#356): the fold of each letter."""

from __future__ import annotations

import re

import pytest

from groundgate.fold import LOOK_ALIKE, fold, fold_text, folded_word, mark_fold

ALL = [chr(i) for i in range(0x110000) if not 0xD800 <= i <= 0xDFFF]


def test_the_look_alikes_fold_to_ascii() -> None:
    assert fold_text("ſıİK") == "siik"
    assert fold_text("ABC xyz 5") == "abc xyz 5"


def test_a_letter_with_a_lowercase_of_two_code_points_folds_to_itself() -> None:
    # "İ".lower() is two code points, but İ is a look-alike. "ẞ".lower() is "ß".
    assert fold("ẞ") == "ß"
    assert fold("ß") == "ß"
    assert all(len(fold(c)) == 1 for c in ALL)


def test_each_fold_pair_is_a_re_i_pair() -> None:
    """The rule is a subset of re.I: each letter matches its fold under re.I."""
    for c in ALL:
        f = fold(c)
        if f != c:
            assert re.fullmatch(re.escape(c), f, re.I), hex(ord(c))


def test_mark_fold_joins_each_pair_that_fold_joins() -> None:
    """The receipt list packs (SPEC §5) never sees a new word where the fold sees the base word."""
    for c in ALL:
        assert mark_fold(c) == mark_fold(fold(c)), hex(ord(c))


@pytest.mark.parametrize("word", ["thousand", "U.S.", "Net loss", "State Income"])
def test_a_folded_word_matches_each_spelling_with_the_same_fold(word: str) -> None:
    rx = re.compile(folded_word(word))
    swaps = {c: lk for lk, c in LOOK_ALIKE.items() if c != "i"} | {"i": "\u0131", "I": "\u0130"}
    for spelling in (word, word.upper(), word.lower(), "".join(swaps.get(c, c) for c in word)):
        assert rx.fullmatch(spelling), spelling
    assert rx.fullmatch(word + "x") is None


def test_a_letter_with_no_case_matches_only_itself() -> None:
    assert folded_word("5 $") == re.escape("5 $")
    assert set(LOOK_ALIKE.values()) == {"s", "i", "k"}
