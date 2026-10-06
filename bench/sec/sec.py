"""The 10-K demo of the calibration tool (#112): Item 7 of 10-K filings from the EDGAR full index
of 2026 Q1, taken in a fixed order.

    SEC_USER_AGENT="name email" uv run python bench/sec/sec.py pick --count
    SEC_USER_AGENT="name email" uv run python bench/sec/sec.py pick   # sources.json, log
    SEC_USER_AGENT="name email" uv run python bench/sec/sec.py docs   # docs/, from the cache
    uv run python bench/sec/sec.py fields   # schema.json, descriptions.json, gold/
    uv run --group langextract python bench/propose.py --set bench/sec --provider claude-cli \
        --model claude-haiku-4-5-20251001 --label "Claude Haiku 4.5" --buffer 4000
    uv run --group langextract python bench/sec/sec.py cands Claude_Haiku_4.5/4000

EDGAR asks every client to name itself with a contact in the User-Agent. The contact comes from
SEC_USER_AGENT only, and it is never written to a file. The walk reads only the Item headings
and the length of each filing, and prints no text. The filings are not public-domain works, so
their text stays in the cache and docs/, out of git; sources.json pins each one by sha256.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from groundgate.extract import extract

HERE = Path(__file__).parent
BENCH = HERE.parent
CACHE = HERE / ".cache"
EDGAR = "https://www.sec.gov/Archives/"
INDEX = EDGAR + "edgar/full-index/2026/QTR1/form.idx"
FILINGS = 40
MIN_CHARS, MAX_CHARS = 5_000, 150_000
START = re.compile(r"^[ \t]*item[ \t]+7\.", re.I | re.M)
END = re.compile(r"^[ \t]*item[ \t]+(?:7a|8)\.", re.I | re.M)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
HREF = re.compile(r'href="([^"]+)"', re.I)
KEYS = ["2025", "2024", "2023"]
FIELDS = {
    "revenue": "Total revenue or net sales for the fiscal year.",
    "net_income": "Net income for the fiscal year.",
    "operating_income": "Operating income (income from operations) for the fiscal year.",
    "cash_and_equivalents": "Cash and cash equivalents at the end of the fiscal year.",
    "total_debt": "Total debt at the end of the fiscal year.",
}
SCHEMA = {
    "fields": {f: {"type": "number", "unit": "USD", "multiple": True, "keys": KEYS} for f in FIELDS}
}


def get(url: str, name: str) -> bytes:
    """Download into the cache, at most about 5 requests a second. A 404 raises HTTPError; any
    other failure is retried and then stops the walk."""
    path = CACHE / name
    if path.exists():
        return path.read_bytes()
    agent = os.environ.get("SEC_USER_AGENT")
    if not agent:
        raise SystemExit('set SEC_USER_AGENT to "name email", as EDGAR asks')
    err: Exception | None = None
    for wait in (0.2, 10, 30, 90):
        time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": agent})
            with urllib.request.urlopen(req, timeout=60) as r:
                data: bytes = r.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            err = e
        except OSError as e:
            err = e
    raise SystemExit(f"{url}: {err}")


def filings() -> list[tuple[str, str]]:
    """(accession, filing folder) of each 10-K in the index, in the order of sha256 of the
    accession number."""
    text = get(INDEX, "form-2026-QTR1.idx").decode("latin-1")
    out = []
    for line in text.splitlines():
        if not line.startswith("10-K "):
            continue
        path = line.split()[-1]  # edgar/data/<cik>/<accession>.txt
        cik, acc = path.split("/")[2], path.split("/")[3][:-4]
        out.append((acc, f"edgar/data/{cik}/{acc.replace('-', '')}"))
    return sorted(out, key=lambda x: hashlib.sha256(x[0].encode()).hexdigest())


def primary(acc: str, folder: str) -> str | None:
    """The file name of the document of type 10-K in the filing index, or None."""
    page = get(f"{EDGAR}{folder}/{acc}-index.htm", f"{acc}-index.htm").decode("utf-8", "replace")
    for row in ROW.findall(page):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in CELL.findall(row)]
        if len(cells) >= 4 and cells[3] == "10-K":
            m = HREF.search(row)
            if m:
                return m.group(1).split("/")[-1].split("?")[0]
    return None


def item7(text: str) -> str | None:
    """Item 7: the longest text from an "Item 7." heading to the next "Item 7A." or "Item 8."
    heading. The table of contents gives a short pair."""
    best = None
    for s in START.finditer(text):
        e = END.search(text, s.end())
        if e and (best is None or e.start() - s.start() > len(best)):
            best = text[s.start() : e.start()]
    return best


def walk(count_only: bool) -> None:
    log: list[dict[str, Any]] = []
    chosen: list[dict[str, Any]] = []
    for acc, folder in filings():
        if len(chosen) >= FILINGS:
            break
        entry: dict[str, Any] = {"accession": acc}
        log.append(entry)
        name = primary(acc, folder)
        if name is None:
            entry["skip"] = "no document of type 10-K"
            continue
        if not name.lower().endswith((".htm", ".html")):
            entry["skip"] = "primary document is not HTML"
            continue
        url = f"{EDGAR}{folder}/{name}"
        data = get(url, f"{acc}.htm")
        part = item7(extract(CACHE / f"{acc}.htm").text)
        if part is None:
            entry["skip"] = "no Item 7 and Item 7A or 8 headings"
        elif not MIN_CHARS <= len(part) <= MAX_CHARS:
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
        print(f"sec: {len(chosen)} filings", file=sys.stderr)
    skips: dict[str, int] = {}
    for e in log:
        if "skip" in e:
            why = re.sub(r"\d+ code points", "too short or too long", e["skip"])
            skips[why] = skips.get(why, 0) + 1
    print(f"sec: {len(chosen)} filings from {len(log)} looked at")
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
    sha256. The cache and docs/ stay out of git."""
    (HERE / "docs").mkdir(exist_ok=True)
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        acc = src["id"][4:]
        data = get(src["url"], f"{acc}.htm")
        if hashlib.sha256(data).hexdigest() != src["sha256"]:
            raise SystemExit(f"{src['id']}: the filing changed since the pick")
        part = item7(extract(CACHE / f"{acc}.htm").text)
        assert part is not None
        (HERE / "docs" / f"{src['id']}.txt").write_text(part, encoding="utf-8")
    print("wrote docs/")


def fields() -> None:
    """The inputs that stay the same for every filing: schema.json and descriptions.json for the
    calibration tool, and gold/<id>.json with the fields only (no facts), for bench/propose.py."""
    (HERE / "schema.json").write_text(json.dumps(SCHEMA, indent=1) + "\n")
    (HERE / "descriptions.json").write_text(json.dumps(FIELDS, indent=1) + "\n")
    (HERE / "gold").mkdir(exist_ok=True)
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        spec = {f: {"schema": SCHEMA["fields"][f], "description": d} for f, d in FIELDS.items()}
        rec = {"doc": src["id"], "kind": "sec", "fields": spec}
        (HERE / "gold" / f"{src['id']}.json").write_text(json.dumps(rec, indent=1) + "\n")
    print("wrote schema.json, descriptions.json and gold/")


def cands(run: str) -> None:
    """cands/<id>.json: the candidates of one extraction run, in the spec 0.3 format, for the
    calibration tool. A filing that the run has not reached yet gets no file."""
    from groundgate.adapters.langextract import to_candidates

    out = HERE / "cands"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.json"):  # never mix the candidates of two runs
        old.unlink()
    n = 0
    for path in sorted((HERE / "runs").glob(f"{run}/*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        doc = rec["document"]["document_id"]
        (out / f"{doc}.json").write_text(json.dumps(to_candidates(rec["document"])) + "\n")
        n += 1
    print(f"wrote cands/ for {n} filings")


KINDS = {  # the field-doubt thresholds that other kinds chose (#106, #110)
    "FDA labels": BENCH / "judges" / "fields" / "report.json",
    "NTSB reports": BENCH / "judges" / "aviation" / "report.json",
}


def results(check: bool) -> None:
    """results.json: the demo's numbers, from the calibration tool's files and the other kinds'
    reports, with how the other kinds' thresholds do on the 10-K test part. RESULTS.md is
    rendered from results.json only."""
    field = json.loads((HERE / "work-field" / "report.json").read_text())["judges"]["jev"]
    keys = json.loads((HERE / "work-key" / "items.json").read_text())
    docs = json.loads((HERE / "sources.json").read_text())["sources"]
    test = field["test"]
    kinds = {"10-K filings (this demo)": field["by_ceiling"]}
    for kind, path in KINDS.items():
        kinds[kind] = json.loads(path.read_text())["engines"]["jev"]["by_ceiling"]
    travel = []
    for kind, by_ceiling in kinds.items():
        for c, v in by_ceiling.items():
            t = v["threshold"]
            row: dict[str, Any] = {"from": kind, "ceiling": c, "threshold": t}
            if t is not None:
                got = test["by_threshold"][str(t)]
                row |= {"wrong_caught": got["wrong_caught"], "right_doubted": got["right_doubted"]}
            travel.append(row)
    res = {
        "filings": len(docs),
        "field_items": field["calibration"]["items"] + test["items"],
        "key_items": len(keys),
        "test": {"wrong": test["wrong"], "right": test["right"]},
        "travel": travel,
    }
    md = [
        "# 10-K demo of the calibration tool",
        "",
        "Generated by `bench/sec/sec.py results` from [results.json](results.json), which it "
        "builds from `work-field/report.json`, `work-key/items.json` and the field-judge reports "
        "of the other kinds. [README.md](README.md) says how the numbers were made.",
        "",
        "## Items",
        "",
        "| Filings | Field items (admitted values) | Key items (`KEY_NOT_AT_VALUE`) |",
        "|---:|---:|---:|",
        f"| {res['filings']} | {res['field_items']} | {res['key_items']} |",
        "",
        "## Field doubt on the 10-K test part",
        "",
        f"The test part has {res['test']['wrong']} wrong and {res['test']['right']} right values.",
        "",
        "| Threshold from | Ceiling | Threshold | Wrong caught | Right doubted |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in travel:
        if r["threshold"] is None:
            md.append(f"| {r['from']} | {r['ceiling']} | none | | |")
        else:
            md.append(
                f"| {r['from']} | {r['ceiling']} | {r['threshold']} | {r['wrong_caught']} "
                f"| {r['right_doubted']} |"
            )
    out = {
        HERE / "results.json": json.dumps(res, indent=1) + "\n",
        HERE / "RESULTS.md": "\n".join(md) + "\n",
    }
    if check:
        stale = [p.name for p, body in out.items() if not p.exists() or p.read_text() != body]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run sec.py results")
        print("results.json and RESULTS.md are up to date")
        return
    for path, body in out.items():
        path.write_text(body)
    print("wrote results.json and RESULTS.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report counts; write nothing")
    sub.add_parser("docs")
    sub.add_parser("fields")
    p = sub.add_parser("results")
    p.add_argument("--check", action="store_true", help="fail if RESULTS.md differs")
    p = sub.add_parser("cands")
    p.add_argument("run", help='a run folder, for example "Claude_Haiku_4.5/4000"')
    args = ap.parse_args()
    if args.cmd == "pick":
        walk(args.count)
    elif args.cmd == "docs":
        docs()
    elif args.cmd == "fields":
        fields()
    elif args.cmd == "results":
        results(args.check)
    else:
        cands(args.run)


if __name__ == "__main__":
    main()
