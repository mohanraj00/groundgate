"""The bullets set for the letter rule of label lines (#86, #93): every dose in FDA labels that no
other set used whose sentence mentions no key, after an earlier key mention, where every label
line between them holds no letter. Each dose is labeled by a person with the keys it belongs to.

    uv run python bench/bullets/bullets.py pick --count     # how many doses the walk finds
    uv run python bench/bullets/bullets.py pick             # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/bullets        # download, verify, write docs/
    uv run python bench/bullets/bullets.py items            # write items.json from docs/
    uv run python bench/bullets/bullets.py label            # label them in the terminal
    uv run python bench/bullets/bullets.py score            # RESULTS.md: spec 0.2 and 0.3
    uv run python bench/bullets/bullets.py score --check    # fail if the committed files differ

This is the keys-set tool (bench/keys/keys.py) with its own documents and its own items. The pick
looks only at counts and prints no text, and the label tool never shows which keys a spec puts
at a dose.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent / "keys")]

import keys  # noqa: E402  (bench/keys/keys.py)

# the whole ranking and every dose: such doses are rare, so the set holds all of them
MAX_RANK = PER_SET = PER_DOC = 10**6
# SPEC 0.3 §4.5, written out here so the pick does not run the rule it measures: a label line
# has a blank line or the start of the text before it and a blank line after it, at most 12
# words, and no "." or ";" followed by whitespace, its own line break included
LABEL_MAX_WORDS = 12
INNER_END = re.compile(r"[.;]\s")
LINE_SPACE = " \t\r"


def label_lines(text: str, start: int, end: int) -> list[str]:
    """The label lines that lie wholly in text[start:end]."""
    lines = text[start:end].split("\n")
    blank = [not line.strip(LINE_SPACE) for line in lines]
    out = []
    for i, line in enumerate(lines[:-2]):
        before = (i >= 2 and blank[i - 1]) or (i == 0 and start == 0)
        body = line.strip(LINE_SPACE)
        if (
            before
            and blank[i + 1]
            and body
            and len(body.split()) <= LABEL_MAX_WORDS
            and not INNER_END.search(body + "\n")
        ):
            out.append(body)
    return out


def bullet_doses_in(text: str, label_keys: list[str]) -> list[tuple[int, int]]:
    """The doses whose sentence mentions no key, after an earlier key mention, where there is a
    label line between them and none of them holds a letter."""
    from groundgate.text import key_mentions, sentence

    mentions = key_mentions(text, tuple(label_keys))
    out = []
    for a, b in keys.doses_in(text):
        s0, s1 = sentence(text, a)
        if any(s0 <= x and y <= s1 for x, y, _ in mentions):
            continue
        before = [y for _, y, _ in mentions if y <= a]
        if not before:
            continue
        lines = label_lines(text, max(before), s0)
        if lines and not any(c.isalpha() for line in lines for c in line):
            out.append((a, b))
    return out


def excluded() -> set[str]:
    """Drugs used by v0.1, set 2 or the pattern, dots, keys or tables set."""
    used = []
    for name in ("keys", "tables"):
        used += json.loads((HERE.parent / name / "sources.json").read_text())["sources"]
    return keys_excluded() | {s["id"].removeprefix("fda-") for s in used}


keys_excluded = keys.excluded
keys.HERE, keys.NAME, keys.TITLE = HERE, "bullets", "Bullets set: the letter rule for label lines"
keys.MAX_RANK, keys.PER_SET, keys.PER_DOC = MAX_RANK, PER_SET, PER_DOC
keys.items_in = bullet_doses_in
keys.excluded = excluded
keys.EXCLUDED_WHY = "used in v0.1, set 2, the pattern, dots, keys or tables set"
keys.SPEC02 = [
    *("uv", "run", "--isolated", "--no-project", "--quiet", "--python", "3.12"),
    *("--with", "groundgate[pdf]==0.2.0", "python", str(HERE / "bullets.py"), "read"),
]

if __name__ == "__main__":
    keys.main()
