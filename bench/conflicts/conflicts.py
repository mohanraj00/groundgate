"""The conflicts set for the conflict question of #67: FDA labels that no other set used, each
labeled by a person with the dose that the text states as each of three set-2 fields.

    uv run python bench/conflicts/conflicts.py pick --count   # how many labels the walk finds
    uv run python bench/conflicts/conflicts.py pick           # sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/conflicts        # download, verify, write docs/
    uv run python bench/conflicts/conflicts.py items          # write items.json from docs/
    uv run python bench/conflicts/conflicts.py web            # label at http://127.0.0.1:8771

This is the pick of the keys-set tool (bench/keys/keys.py) with its own documents. The pick looks
only at counts and prints no text. The label tool marks every dose and never shows what spec 0.3
or a model reads.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent / "keys"), str(HERE.parent / "fields")]

import keys  # noqa: E402  (bench/keys/keys.py)
from fields import FIELDS as ALL_FIELDS  # noqa: E402  (bench/fields/fields.py)

LABELS, MAX_DOSES, MAX_RANK = 40, 30, 3000
# the set-2 fields that take one value; a conflict is two values for one of them
FIELDS = {f: d for f, d in ALL_FIELDS.items() if not d["schema"].get("multiple")}
# what joins a number to the dose after it, as in "20 to 30 mg" or "5, 10 or 20 mg"
# a unit joined by a hyphen, as in "a 5-mg dose"
HYPHEN_UNIT = re.compile(r"-(?:mg|mcg)(?![A-Za-z])")
JOIN = re.compile(r"\s*(?:,\s*(?:or|and)?|or|and|to|-|\u2013|\u2014)\s*")


def doses_in(text: str) -> list[tuple[int, int]]:
    """The doses of the keys set, a number with a hyphen before its unit, and each number that
    JOIN links to a dose after it: the lower end of a range is a dose too."""
    from groundgate.text import tokens

    toks = [t for t in tokens(text) if t.value is not None]
    dose = {(a, b) for a, b in keys.doses_in(text)}
    dose |= {(t.start, t.end) for t in toks if HYPHEN_UNIT.match(text, t.end)}
    for t, after in reversed(list(itertools.pairwise(toks))):
        m = JOIN.match(text, t.end)
        if (after.start, after.end) in dose and m and m.end() == after.start:
            dose.add((t.start, t.end))
    return sorted(dose)


def excluded() -> set[str]:
    """Drugs used by v0.1, set 2, the pattern, dots, keys, tables, relations or fields set."""
    used = set()
    for name in ("keys", "tables", "relations", "fields"):
        sources = json.loads((HERE.parent / name / "sources.json").read_text())["sources"]
        used |= {s["id"].removeprefix("fda-") for s in sources}
    return keys_excluded() | used


def items() -> None:
    """items.json: every dose of each label, as code point offsets in docs/<id>.txt."""
    out: list[dict[str, Any]] = []
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        text = (HERE / "docs" / f"{src['id']}.txt").read_text(encoding="utf-8")
        for a, b in doses_in(text):
            out.append({"id": f"{src['id']}:{a}", "doc": src["id"], "span": [a, b]})
    (HERE / "items.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote items.json: {len(out)} doses in {len({it['doc'] for it in out})} labels")


keys_excluded = keys.excluded
keys.HERE, keys.NAME, keys.TITLE = HERE, "conflicts", "Conflicts set: the conflict question"
# one "dose" for each label in the pick's count, so PER_SET counts labels
keys.MAX_RANK, keys.PER_SET, keys.PER_DOC = MAX_RANK, LABELS, 1
keys.NEED_KEYS, keys.MAX_DOSES = False, MAX_DOSES
keys.excluded = excluded
keys.EXCLUDED_WHY = "used in v0.1, set 2, the pattern, dots, keys, tables, relations or fields set"


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report label counts; write nothing")
    sub.add_parser("items")
    sub.add_parser("web")
    args = ap.parse_args()
    if args.cmd == "pick":
        keys.pick(args.count)
    elif args.cmd == "items":
        items()
    else:
        import labeler  # bench/conflicts/labeler.py

        labeler.serve()


if __name__ == "__main__":
    main()
