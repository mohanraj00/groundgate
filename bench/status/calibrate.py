"""The key clear on the status set with a local judge (#175): groundgate-calibrate on the amounts
that spec 0.6 flags KEY_NOT_AT_VALUE in the roles run of bench/evidence.

    uv run python bench/status/calibrate.py inputs     # calibrate/candidates, calibrate/schema.json
    uv run groundgate-calibrate sample --work bench/status/calibrate/work --docs bench/status/docs \
        --candidates bench/status/calibrate/candidates --schema bench/status/calibrate/schema.json \
        --question key --context "The text is from an IRS publication."
    uv run groundgate-calibrate split --work bench/status/calibrate/work
    uv run python bench/status/calibrate.py labels     # the labels of #128, and links.json
    uv run python bench/status/web.py --work bench/status/calibrate/work      # the other items
    GROUNDGATE_CHAT_URL=http://127.0.0.1:11434/v1 GROUNDGATE_CHAT_MODEL=qwen2.5:7b \
    GROUNDGATE_CHAT_VERSION=845dbda0ea48 \
        uv run groundgate-calibrate ask --work bench/status/calibrate/work --judge chat
    uv run groundgate-calibrate report --work bench/status/calibrate/work [--check]

An item that is an amount of the status set gets its label from labels.json, which a person gave
blind (#128): the filing statuses that the amount belongs to, or None for not sure. That is the
answer that the key question asks for. A person labels every other item on the PDF page of
bench/status/web.py, which is blind too and never shows the split.

I ran split after the labels. The split is sha256 of the document name, so the order does not
change it: split.json is the same when split runs first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OUT = HERE / "calibrate"
WORK = OUT / "work"
sys.path.insert(0, str(HERE.parent / "evidence"))


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def inputs() -> None:
    """The candidates of the roles run, by the adapter of bench/evidence, and the set's schema
    with the field description of its gold files."""
    import measure  # bench/evidence/measure.py

    (OUT / "candidates").mkdir(parents=True, exist_ok=True)
    schemas = set()
    for doc, _, schema, cands in measure._packets("status"):
        schemas.add(json.dumps(schema, sort_keys=True))
        _dump(
            OUT / "candidates" / f"{doc}.json", [{"id": f"c{i}", **c} for i, c in enumerate(cands)]
        )
    if len(schemas) != 1:
        raise SystemExit("the documents of the set have different schemas")
    schema = json.loads(schemas.pop())
    golds = {
        g["fields"]["amount"]["description"] for g in map(_read, (HERE / "gold").glob("*.json"))
    }
    if len(golds) != 1:
        raise SystemExit("the gold files have different descriptions")
    schema["fields"]["amount"]["description"] = golds.pop()
    _dump(OUT / "schema.json", schema)
    print(f"wrote {len(list((OUT / 'candidates').glob('*.json')))} candidate files and the schema")


def labels() -> None:
    """W/labels.json for each item that is an amount of the set: same document, same first code
    point of the number. It never changes a label that is there. Also W/links.json: the PDF of
    each document."""
    status = {}
    given = _read(HERE / "labels.json")
    for it in _read(HERE / "items.json"):
        if it["id"] in given:
            label = given[it["id"]]
            status[it["doc"], it["span"][0]] = None if label is None else list(label)
    path = WORK / "labels.json"
    have = _read(path) if path.exists() else {}
    items = _read(WORK / "items.json")
    added = 0
    for it in items:
        key = (it["doc"], it["mark"][0])
        if key in status and it["id"] not in have:
            have[it["id"]] = status[key]
            added += 1
    _dump(path, dict(sorted(have.items())))
    # the label page links each document to its PDF, because the text lost the tables' shape
    links = {s["id"]: s["url"] for s in _read(HERE / "sources.json")["sources"]}
    _dump(WORK / "links.json", {it["doc"]: links[it["doc"]] for it in items})
    left = sum(it["id"] not in have for it in items)
    print(f"{added} labels from the status set; {left} of {len(items)} items need a label")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("inputs", "labels"))
    args = ap.parse_args()
    inputs() if args.command == "inputs" else labels()


if __name__ == "__main__":
    main()
