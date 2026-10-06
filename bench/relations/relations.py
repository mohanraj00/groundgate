"""The relations set for the relation question of #67: values in sections 2 and 3 of FDA labels
that no other set used, for which spec 0.3 finds a qualifier, each labeled by a person with the
relation that the text states.

    uv run python bench/relations/relations.py pick --count   # how many values the walk finds
    uv run python bench/relations/relations.py pick           # write sources.json, selection-log
    uv run python bench/fetch.py --set bench/relations        # download, verify, write docs/
    uv run python bench/relations/relations.py items          # write items.json from docs/
    uv run python bench/relations/relations.py label          # label them in the terminal

This is the pick of the keys-set tool (bench/keys/keys.py) with its own documents and its own
items. The pick looks only at counts and prints no text, and the label tool never shows what
spec 0.3 or a model reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent / "keys")]

import keys  # noqa: E402  (bench/keys/keys.py)

PER_SET, PER_DOC, MAX_RANK = 150, 6, 1200
# what a person can answer: the relation, not sure (None), or not a fact
RELATIONS = {
    "eq": "exactly this value",
    "le": "at most this value (up to, no more than, maximum)",
    "lt": "less than this value (below, under)",
    "ge": "at least this value (minimum, no less than)",
    "gt": "more than this value (over, above, exceeds)",
    "approx": "about this value (approximately, around)",
    "range": "one end of a range (from ... to, between ... and)",
}
NOT_A_FACT = "x"


def qualified_values_in(text: str, label_keys: list[str]) -> list[tuple[int, int]]:
    """(start, end) of each number token with a value for which spec 0.3 finds a qualifier."""
    from groundgate.text import qualifiers, tokens

    return [(t.start, t.end) for t in tokens(text) if t.value is not None and qualifiers(text, t)]


def excluded() -> set[str]:
    """Drugs used by v0.1, set 2, the pattern set, the dots set, the keys set or the tables set."""
    used = set()
    for name in ("keys", "tables"):
        sources = json.loads((HERE.parent / name / "sources.json").read_text())["sources"]
        used |= {s["id"].removeprefix("fda-") for s in sources}
    return keys_excluded() | used


def label() -> None:
    """Label each value in turn with the relation that the text states for it."""
    items = json.loads((HERE / "items.json").read_text())
    path = HERE / "labels.json"
    labels: dict[str, str | None] = json.loads(path.read_text()) if path.exists() else {}
    texts: dict[str, str] = {}
    names = list(RELATIONS)
    print("For each marked value: what does the text say about it?")
    print("Type the number of the relation. Type x when the value is not a fact, such as a")
    print("section number, and ? when you can't tell.")
    print("Type m to see more of the text before the value, with its heading.\n")
    j = next((n for n, it in enumerate(items) if it["id"] not in labels), len(items))
    while j < len(items):
        it = items[j]
        if it["doc"] not in texts:
            texts[it["doc"]] = (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8")
        done = sum(x["id"] in labels for x in items)
        print(f"\n{'=' * 72}\n[{j + 1}/{len(items)}, {done} labeled] {it['doc']}\n")
        print(keys.context(texts[it["doc"]], it["span"]))
        print()
        for n, r in enumerate(names, 1):
            print(f"  {n}  {RELATIONS[r]}")
        print("  x  not a fact")
        print("  ?  not sure")
        was = ""
        if it["id"] in labels:
            now = labels[it["id"]]
            was = f" (now: {'not sure' if now is None else now})"
        ans = input(f"Relation{was}: 1 to {len(names)}, x, ?, m more text, b back, q quit: ")
        ans = ans.strip().lower()
        if ans == "q":
            break
        if ans == "m":
            print(f"\n{keys.context(texts[it['doc']], it['span'], before=2500)}")
            continue
        if ans == "b":
            j = max(0, j - 1)
            continue
        if ans == "?":
            labels[it["id"]] = None
        elif ans == NOT_A_FACT:
            labels[it["id"]] = NOT_A_FACT
        elif ans.isdigit() and 1 <= int(ans) <= len(names):
            labels[it["id"]] = names[int(ans) - 1]
        else:
            continue
        path.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
        j += 1
    done = sum(x["id"] in labels for x in items)
    print(f"\n{done} of {len(items)} labeled, saved in bench/relations/labels.json")


keys_excluded = keys.excluded
keys.HERE, keys.NAME, keys.TITLE = HERE, "relations", "Relations set: the relation question"
keys.MAX_RANK, keys.PER_SET, keys.PER_DOC = MAX_RANK, PER_SET, PER_DOC
keys.NEED_KEYS = False
keys.items_in = qualified_values_in
keys.excluded = excluded
keys.EXCLUDED_WHY = "used in v0.1, set 2, the pattern, dots, keys or tables set"


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report value counts; write nothing")
    sub.add_parser("items")
    sub.add_parser("label")
    args = ap.parse_args()
    if args.cmd == "pick":
        keys.pick(args.count)
    elif args.cmd == "items":
        keys.find_items()
    else:
        label()


if __name__ == "__main__":
    main()
