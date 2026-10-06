"""The fields set for the field question of #67: doses in sections 2 and 3 of FDA labels that no
other set used, each labeled by a person with the set-2 fields that the text states as that dose.

    uv run python bench/fields/fields.py pick --count   # how many doses the walk finds
    uv run python bench/fields/fields.py pick           # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/fields     # download, verify, write docs/
    uv run python bench/fields/fields.py items          # write items.json from docs/
    uv run python bench/fields/fields.py label          # label them in the terminal

This is the pick of the keys-set tool (bench/keys/keys.py) with its own documents. The pick looks
only at counts and prints no text, and the label tool never shows what spec 0.3 or a model reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent / "keys")]

import keys  # noqa: E402  (bench/keys/keys.py)

PER_SET, PER_DOC, MAX_RANK = 150, 6, 2000
# the four set-2 FDA fields in mg, as set 2 writes them for a label without keys
FIELDS: dict[str, dict[str, Any]] = {
    "starting_dose": {
        "schema": {"type": "number", "unit": "mg", "comparator": "eq", "minimum": "0"},
        "description": "Usual recommended starting dose for adults. If the label gives a range, "
        "its lower bound. For the first indication in section 2.",
    },
    "max_daily_dose": {
        "schema": {"type": "number", "unit": "mg", "comparator": "le", "minimum": "0"},
        "description": "Maximum recommended daily dose for adults. Doses that were only studied "
        "or used are not a recommendation. For the first indication in section 2.",
    },
    "hepatic_starting_dose": {
        "schema": {"type": "number", "unit": "mg", "comparator": "eq", "minimum": "0"},
        "description": "Recommended starting dose for adults with hepatic impairment, when the "
        "label gives a number.",
    },
    "strengths": {
        "schema": {
            "type": "number",
            "unit": "mg",
            "comparator": "eq",
            "minimum": "0",
            "multiple": True,
        },
        "description": "Every tablet or capsule strength listed in section 3 (one extraction per "
        "strength).",
    },
}


def excluded() -> set[str]:
    """Drugs used by v0.1, set 2, the pattern, dots, keys, tables or relations set."""
    used = set()
    for name in ("keys", "tables", "relations"):
        sources = json.loads((HERE.parent / name / "sources.json").read_text())["sources"]
        used |= {s["id"].removeprefix("fda-") for s in sources}
    return keys_excluded() | used


def label() -> None:
    """Label each dose in turn with the fields that the text states as that dose."""
    items = json.loads((HERE / "items.json").read_text())
    path = HERE / "labels.json"
    labels: dict[str, list[str] | None] = json.loads(path.read_text()) if path.exists() else {}
    texts: dict[str, str] = {}
    names = list(FIELDS)
    print("For each marked dose: which of these fields does the text state as that dose?")
    print("Type a number, or several numbers with commas (1,2) when the dose is each of those")
    print("fields. Type 0 when it is none of them, and ? when you can't tell.")
    print("Type m to see more of the text before the dose, with its heading.\n")
    j = next((n for n, it in enumerate(items) if it["id"] not in labels), len(items))
    while j < len(items):
        it = items[j]
        if it["doc"] not in texts:
            texts[it["doc"]] = (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8")
        done = sum(x["id"] in labels for x in items)
        print(f"\n{'=' * 72}\n[{j + 1}/{len(items)}, {done} labeled] {it['doc']}\n")
        print(keys.context(texts[it["doc"]], it["span"]))
        print()
        for n, f in enumerate(names, 1):
            print(f"  {n}  {FIELDS[f]['description']}")
        print("  0  none of them")
        print("  ?  not sure")
        was = ""
        if it["id"] in labels:
            now = labels[it["id"]]
            was = f" (now: {'not sure' if now is None else ', '.join(now) or 'none'})"
        ans = input(f"Fields{was}: numbers, 0, ?, m more text, b back, q quit: ").strip().lower()
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
        else:
            try:
                picked = sorted({int(x) for x in ans.split(",") if x.strip()})
            except ValueError:
                continue
            if not picked or not all(0 <= n <= len(names) for n in picked):
                continue
            if 0 in picked and len(picked) > 1:
                continue
            labels[it["id"]] = [names[n - 1] for n in picked if n]
        path.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
        j += 1
    done = sum(x["id"] in labels for x in items)
    print(f"\n{done} of {len(items)} labeled, saved in bench/fields/labels.json")


keys_excluded = keys.excluded
keys.HERE, keys.NAME, keys.TITLE = HERE, "fields", "Fields set: the field question"
keys.MAX_RANK, keys.PER_SET, keys.PER_DOC = MAX_RANK, PER_SET, PER_DOC
keys.NEED_KEYS = False
keys.excluded = excluded
keys.EXCLUDED_WHY = "used in v0.1, set 2, the pattern, dots, keys, tables or relations set"


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report dose counts; write nothing")
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
