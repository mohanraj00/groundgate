"""The tables set for the table-sentence rule (#87, #90): doses in table sentences of FDA labels
that no other set used, each labeled by a person with the keys it belongs to. A table sentence
is a sentence (SPEC §4.2) with 3 or more line breaks that mentions 2 or more of the label's keys.

    uv run python bench/tables/tables.py pick --count     # how many doses the walk finds
    uv run python bench/tables/tables.py pick             # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/tables       # download, verify, write docs/
    uv run python bench/tables/tables.py items            # write items.json from docs/
    uv run python bench/tables/tables.py label            # label them in the terminal
    uv run python bench/tables/tables.py score            # RESULTS.md: spec 0.2 and 0.3
    uv run python bench/tables/tables.py score --check    # fail if the committed files differ

This is the keys-set tool (bench/keys/keys.py) with its own documents and its own items. The pick
looks only at counts and prints no text, and the label tool never shows which keys a spec puts
at a dose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent / "keys")]

import keys  # noqa: E402  (bench/keys/keys.py)

TABLE_BREAKS, TABLE_KEYS = 3, 2
# the whole ranking and every dose: table sentences with two keys are rare, so the set holds all
# of them, not a sample
MAX_RANK = PER_SET = PER_DOC = 10**6


def table_doses_in(text: str, label_keys: list[str]) -> list[tuple[int, int]]:
    """The doses that lie in a table sentence: a sentence with TABLE_BREAKS or more line breaks
    that mentions TABLE_KEYS or more of the label's keys."""
    from groundgate.text import key_mentions, sentence

    mentions = key_mentions(text, tuple(label_keys))
    out = []
    for a, b in keys.doses_in(text):
        s0, s1 = sentence(text, a)
        named = {k for x, y, k in mentions if s0 <= x and y <= s1}
        if text.count("\n", s0, s1) >= TABLE_BREAKS and len(named) >= TABLE_KEYS:
            out.append((a, b))
    return out


def excluded() -> set[str]:
    """Drugs used by v0.1, set 2, the pattern set, the dots set or the keys set."""
    used = json.loads((HERE.parent / "keys" / "sources.json").read_text())["sources"]
    return keys_excluded() | {s["id"].removeprefix("fda-") for s in used}


keys_excluded = keys.excluded
keys.HERE, keys.NAME, keys.TITLE = HERE, "tables", "Tables set: the table-sentence rule"
keys.MAX_RANK, keys.PER_SET, keys.PER_DOC = MAX_RANK, PER_SET, PER_DOC
keys.items_in = table_doses_in
keys.excluded = excluded
keys.EXCLUDED_WHY = "used in v0.1, set 2, the pattern, dots or keys set"
keys.SPEC02 = [
    *("uv", "run", "--isolated", "--no-project", "--quiet", "--python", "3.12"),
    *("--with", "groundgate[pdf]==0.2.0", "python", str(HERE / "tables.py"), "read"),
]

if __name__ == "__main__":
    keys.main()
