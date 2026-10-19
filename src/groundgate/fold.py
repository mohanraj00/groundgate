"""The case rule of SPEC §4 (spec 0.10, #356): two letters match when they have the same fold.

Every rule that matches case-insensitively builds its pattern here, with no ``re.I``. A lookup
after a match folds the found text with the same function, so it always finds the listed word.
"""

from __future__ import annotations

import functools
import re

# The four look-alike letters and their folds: the long s (U+017F), the dotless i (U+0131), the
# dotted capital I (U+0130) and the Kelvin sign (U+212A).
LOOK_ALIKE = {"\u017f": "s", "\u0131": "i", "\u0130": "i", "\u212a": "k"}


def fold(ch: str) -> str:
    """The fold of one character: a look-alike gives its ASCII letter. Each other character gives
    its Unicode lowercase mapping when that is one code point, else itself."""
    ch = LOOK_ALIKE.get(ch, ch)
    low = ch.lower()
    return low if len(low) == 1 else ch


def fold_text(text: str) -> str:
    """The text with each character folded. It has as many code points as the text."""
    return "".join(map(fold, text))


@functools.cache
def _non_ascii_folds() -> dict[str, str]:
    """Each fold with the characters that have it, for a fold that more than one character has.
    One pass over all code points, the first time a word holds a cased non-ASCII letter."""
    out: dict[str, list[str]] = {}
    for i in range(0x110000):
        c = chr(i)
        f = fold(c)
        if f != c:
            out.setdefault(f, [f]).append(c)
    return {f: "".join(cs) for f, cs in out.items()}


@functools.cache
def same_fold(ch: str) -> str:
    """Each character with the fold of ``ch``. A character with no case has only itself."""
    f = fold(ch)
    if ch not in LOOK_ALIKE and ch.lower() == ch == ch.upper():
        return ch
    if "a" <= f <= "z":
        return f + f.upper() + "".join(k for k, v in LOOK_ALIKE.items() if v == f)
    return _non_ascii_folds().get(f, f)


def folded_word(word: str) -> str:
    """The regex body of a word that matches by the fold of each letter: a class for each
    letter with case, and each other character escaped."""
    out = []
    for ch in word:
        members = same_fold(ch)
        if len(members) == 1:
            out.append(re.escape(ch))
        else:
            out.append("[" + "".join(re.escape(m) for m in members) + "]")
    return "".join(out)


def mark_fold(text: str) -> str:
    """A text as the receipt list ``packs`` compares it (SPEC §5): the four look-alikes folded,
    then casefolded, each whitespace run as one space. It joins each pair that ``fold`` joins."""
    return " ".join("".join(LOOK_ALIKE.get(c, c) for c in text).casefold().split())
