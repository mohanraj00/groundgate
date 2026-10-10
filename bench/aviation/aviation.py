"""The aviation set for the field question of #67 on a second document kind: NTSB aviation
reports that no other set used, with each number in hours or feet labeled by a person with the
set-2 fields that the text states as that number.

    uv run python bench/aviation/aviation.py pick --count   # how many reports the walk finds
    uv run python bench/aviation/aviation.py pick           # sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/aviation       # download, verify, write docs/
    uv run python bench/aviation/aviation.py items          # write items.json from docs/
    uv run python bench/aviation/aviation.py web            # label at http://127.0.0.1:8772

Since #230, groundgate writes a PDF table as rows with tabs, so its PDF text differs from the
committed text. Run pick, fetch.py, items and web on the 0.7.0 wheel, which writes it:

    uv run --isolated --no-project --no-sources --python 3.12 --with 'groundgate[pdf]==0.7.0' \
        python bench/aviation/aviation.py items

The pick is the set-2 NTSB rule (bench/pick.py) from the first report id after set 2. It looks
only at the first words and the page count, and prints no text. The label tool never shows what
spec 0.3 or a model reads.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import re
import sys
import urllib.error
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
BENCH = HERE.parent
sys.path[:0] = [str(BENCH), str(BENCH / "fields")]

import pick  # noqa: E402  (bench/pick.py)

ITEMS = 150  # reports are taken in id order until their numbers reach this count
FIRST_ID = 192732  # the first report id after set 2
NTSB_FIELDS = (
    "pilot_total_hours",
    "pilot_make_model_hours",
    "pilot_last_90_days_hours",
    "airframe_total_hours",
    "airport_elevation",
    "runway_length",
)
# a number in hours or feet, with the set-2 unit suffixes
UNIT_AFTER = re.compile(r"(?:\s*(?:hours|hour|Hrs|hrs|ft|feet)|-(?:ft|foot))(?![A-Za-z])")
PAGE = re.compile(r"Page \d+ of \d+")


def set2_fields() -> dict[str, dict[str, Any]]:
    """The six fields as set 2 writes them for an NTSB report, and its unit table."""
    g = json.loads((BENCH / "set2" / "gold" / "ntsb-192719.json").read_text())
    return {f: g["fields"][f] for f in NTSB_FIELDS}


FIELDS = set2_fields()


def numbers_in(text: str) -> list[tuple[int, int]]:
    """(start, end) of each number token that a unit of hours or feet follows."""
    from groundgate.text import tokens

    return [(t.start, t.end) for t in tokens(text) if UNIT_AFTER.match(text, t.end)]


def walk(count_only: bool) -> None:
    pick.CACHE = HERE / ".cache"
    pick.CACHE.mkdir(exist_ok=True)
    from groundgate.extract import extract

    log: list[dict[str, Any]] = []
    chosen: list[dict[str, Any]] = []
    total = 0
    for rid in range(FIRST_ID, FIRST_ID + 300):
        if total >= ITEMS:
            break
        entry: dict[str, Any] = {"kind": "ntsb", "id": rid}
        log.append(entry)
        try:
            data = pick.get(pick.NTSB.format(rid), f"ntsb-{rid}.pdf")
        except urllib.error.HTTPError:
            entry["skip"] = "no report (404)"
            continue
        except SystemExit as e:
            # pick.get retries every failure but a 404 for about two minutes; a 500 that stays
            # is the server's answer for a report it can't make, not a slow server
            if "HTTP Error 500" not in str(e):
                raise
            entry["skip"] = "no report (500 after retries)"
            continue
        if not data.startswith(b"%PDF"):
            entry["skip"] = "not a PDF"
            continue
        doc = extract(pick.CACHE / f"ntsb-{rid}.pdf")
        pages = len(doc.layout.pages) if doc.layout else 0
        if not doc.text.lstrip().startswith("Aviation Investigation Final Report"):
            entry["skip"] = "not a final report"
        elif pages > pick.NTSB_MAX_PAGES:
            entry["skip"] = f"{pages} pages"
        elif not numbers_in(doc.text):
            entry["skip"] = "no number in hours or feet"
        if "skip" in entry:
            continue
        entry["numbers"] = len(numbers_in(doc.text))
        total += entry["numbers"]
        print(f"ntsb: {len(chosen) + 1} reports, {total} numbers", file=sys.stderr)
        chosen.append(
            {
                "id": f"ntsb-{rid}",
                "kind": "ntsb",
                "groups": ["aviation"],
                "url": pick.NTSB.format(rid),
                "sha256": hashlib.sha256(data).hexdigest(),
                "select": {},
            }
        )
    skips: dict[str, int] = {}
    for e in log:
        if "skip" in e:
            skips[e["skip"]] = skips.get(e["skip"], 0) + 1
    print(f"ntsb: {len(chosen)} reports, {total} numbers")
    for why, c in sorted(skips.items()):
        print(f"  skipped, {why}: {c}")
    if count_only:
        return
    lock = {"retrieved": datetime.date.today().isoformat(), "sources": chosen}
    (HERE / "sources.json").write_text(json.dumps(lock, indent=2) + "\n")
    (HERE / "selection-log.json").write_text(json.dumps(log, indent=1) + "\n")
    print("wrote bench/aviation/sources.json and selection-log.json")


def items() -> None:
    """items.json: every number in hours or feet of each report, with its PDF page, from the
    "Page n of m" line at the foot of each page."""
    out: list[dict[str, Any]] = []
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        text = (HERE / "docs" / f"{src['id']}.txt").read_text(encoding="utf-8")
        for a, b in numbers_in(text):
            page = 1 + len(PAGE.findall(text, 0, a))
            out.append({"id": f"{src['id']}:{a}", "doc": src["id"], "span": [a, b], "page": page})
    (HERE / "items.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote items.json: {len(out)} numbers in {len({it['doc'] for it in out})} reports")


def render(doc: str, its: list[dict[str, Any]]) -> str:
    """The report text with its line breaks, and a <mark> around each number."""
    text = (HERE / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
    out, at = [], 0
    for it in sorted(its, key=lambda x: x["span"][0]):
        a, b = it["span"]
        out += [html.escape(text[at:a]), f'<mark id="{html.escape(it["id"])}">']
        out += [html.escape(text[a:b]), "</mark>"]
        at = b
    out.append(html.escape(text[at:]))
    return '<div style="white-space: pre-wrap">' + "".join(out) + "</div>"


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report counts; write nothing")
    sub.add_parser("items")
    sub.add_parser("web")
    args = ap.parse_args()
    if args.cmd == "pick":
        walk(args.count)
    elif args.cmd == "items":
        items()
    else:
        import web  # bench/fields/web.py

        web.serve(FIELDS, HERE, render, 8772, lambda doc: HERE / ".cache" / f"{doc}.pdf")


if __name__ == "__main__":
    main()
