"""A held-out 10-K set for spec 0.6 (#170): the next 20 filings of the bench/sec walk, after
every filing that bench/sec and bench/sec2 looked at. The rules of spec 0.6 came from bench/sec2
and the status set, so they are measured here, on filings that no rule was written from.

    SEC_USER_AGENT="name email" uv run python bench/sec3/sec3.py pick --count
    SEC_USER_AGENT="name email" uv run python bench/sec3/sec3.py pick   # sources.json, log
    SEC_USER_AGENT="name email" uv run python bench/sec3/sec3.py docs   # docs/, from the cache
    uv run python bench/sec3/sec3.py fields   # schema.json, descriptions.json, gold/

The download, the cache and the Item 7 cut are those of bench/sec/sec.py, and the schema is that
of bench/sec2. The contact comes from SEC_USER_AGENT only and is never written to a file. The
walk prints no text. The filings are not public-domain works, so their text stays in the cache
and docs/, out of git.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "sec"))
sys.path.insert(0, str(Path(__file__).parent.parent / "sec2"))
import sec  # bench/sec/sec.py
import sec2  # bench/sec2/sec2.py

from groundgate.extract import extract

HERE = Path(__file__).parent
FILINGS = 20
SCHEMA = sec2.SCHEMA  # the same five fields and aliases as bench/sec2 (#170)


def walk(count_only: bool) -> None:
    seen = {
        e["accession"]
        for log in (sec.HERE / "selection-log.json", sec2.HERE / "selection-log.json")
        for e in json.loads(log.read_text())
    }
    log: list[dict[str, Any]] = []
    chosen: list[dict[str, Any]] = []
    for acc, folder in sec.filings():
        if len(chosen) >= FILINGS:
            break
        if acc in seen:  # looked at by an earlier walk, or already here: one filing can be
            continue  # listed once for each filer, with one accession number
        seen.add(acc)
        entry: dict[str, Any] = {"accession": acc}
        log.append(entry)
        name = sec.primary(acc, folder)
        if name is None:
            entry["skip"] = "no document of type 10-K"
            continue
        if not name.lower().endswith((".htm", ".html")):
            entry["skip"] = "primary document is not HTML"
            continue
        url = f"{sec.EDGAR}{folder}/{name}"
        data = sec.get(url, f"{acc}.htm")
        part = sec.item7(extract(sec.CACHE / f"{acc}.htm").text)
        if part is None:
            entry["skip"] = "no Item 7 and Item 7A or 8 headings"
        elif not sec.MIN_CHARS <= len(part) <= sec.MAX_CHARS:
            entry["skip"] = f"Item 7 has {len(part)} code points"
        if "skip" in entry:
            continue
        entry["chars"] = len(part)
        chosen.append(
            {
                "id": f"sec-{acc}",
                "kind": "sec",
                "url": url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "select": {"item": "7"},
            }
        )
        print(f"sec3: {len(chosen)} filings", file=sys.stderr)
    skips: dict[str, int] = {}
    for e in log:
        if "skip" in e:
            why = re.sub(r"\d+ code points", "too short or too long", e["skip"])
            skips[why] = skips.get(why, 0) + 1
    print(f"sec3: {len(chosen)} filings from {len(log)} looked at")
    for why, c in sorted(skips.items()):
        print(f"  skipped, {why}: {c}")
    if count_only:
        return
    lock = {"retrieved": datetime.date.today().isoformat(), "sources": chosen}
    (HERE / "sources.json").write_text(json.dumps(lock, indent=2) + "\n")
    (HERE / "selection-log.json").write_text(json.dumps(log, indent=1) + "\n")
    print("wrote sources.json and selection-log.json")


def docs() -> None:
    """docs/<id>.txt: Item 7 of each pinned filing, from the cache, after a check of its
    sha256."""
    (HERE / "docs").mkdir(exist_ok=True)
    for old in (HERE / "docs").glob("*.txt"):
        old.unlink()
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        acc = src["id"][4:]
        data = sec.get(src["url"], f"{acc}.htm")
        if hashlib.sha256(data).hexdigest() != src["sha256"]:
            raise SystemExit(f"{src['id']}: the filing changed since the pick")
        part = sec.item7(extract(sec.CACHE / f"{acc}.htm").text)
        assert part is not None
        (HERE / "docs" / f"{src['id']}.txt").write_text(part, encoding="utf-8")
    print("wrote docs/")


def fields() -> None:
    """schema.json and descriptions.json, and gold/<id>.json with the fields only (no facts),
    for bench/propose.py."""
    (HERE / "schema.json").write_text(json.dumps(SCHEMA, indent=1) + "\n")
    (HERE / "descriptions.json").write_text(json.dumps(sec.FIELDS, indent=1) + "\n")
    (HERE / "gold").mkdir(exist_ok=True)
    for old in (HERE / "gold").glob("*.json"):
        old.unlink()
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        spec = {f: {"schema": SCHEMA["fields"][f], "description": d} for f, d in sec.FIELDS.items()}
        rec = {"doc": src["id"], "kind": "sec", "fields": spec}
        (HERE / "gold" / f"{src['id']}.json").write_text(json.dumps(rec, indent=1) + "\n")
    print("wrote schema.json, descriptions.json and gold/")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report counts; write nothing")
    sub.add_parser("docs")
    sub.add_parser("fields")
    args = ap.parse_args()
    if args.command == "pick":
        walk(args.count)
    elif args.command == "docs":
        docs()
    else:
        fields()


if __name__ == "__main__":
    main()
