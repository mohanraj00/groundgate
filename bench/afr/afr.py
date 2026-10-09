"""A held-out set for spec 0.7 (#229, planned on #164): the principal statements of 20 FY2025
agency financial reports, as PDF text. The rule of #164 came from bench/sec3, the
status set and the vectors, so it is measured here, on documents that no rule came from.

    uv run python bench/afr/afr.py pick     # .cache/, sources.json, selection-log.json
    uv run python bench/afr/afr.py docs     # docs/, from the cache
    uv run python bench/afr/afr.py fields   # schema.json, descriptions.json

agencies.json lists the CFO Act agencies in the order of 31 U.S.C. 901(b), each with the URL of
its FY2025 report on its own site, or null when it has none. pick takes them in that order. It
downloads each report into .cache, takes the pages of pages.json, and stops at 20 reports. A site
that refuses the download: save the PDF from a browser as .cache/<id>.pdf, and run pick again.
pick prints counts and reasons, never text. The reports are works of the US government, so docs/
and the runs are in git. The PDFs stay in .cache.

The cut is the principal statements, from the balance sheet to the statement of budgetary
resources. I chose the pages by hand from the page headers and the statement titles, and never
from the values. pages.json has the first and the last page of each report, or the reason for a
skip. pick checks that the first page has a "Total assets" line, the last page has a "Total
budgetary resources" line, and the cut has at most 8 pages.

Two title rules came first, and both chose wrong pages. The titles are also in the summary at the
front, in the tables of contents and in the notes. The first rule (the first line that is only a
balance sheet title) gave 12 reports, and the second (the first line that starts with the title,
3 to 8 pages) gave 19 reports with 9 right cuts. The maintainer approved the hand choice before
the docs, the runs and the labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from fetch import download  # noqa: E402  (bench/fetch.py)

REPORTS = 20
MAX_PAGES = 8
YEARS = ["2025", "2024"]
FIRST = re.compile(r"total\s+assets\b", re.I)
LAST = re.compile(r"total\s+budgetary\s+resources\b", re.I)
# the fields of #164, fixed before any document was read
FIELDS = {
    "total_assets": ("total assets", "Total assets at the end of the fiscal year."),
    "total_liabilities": ("total liabilities", "Total liabilities at the end of the fiscal year."),
    "total_net_position": ("total net position", "Total net position at the fiscal year end."),
    "net_cost_of_operations": ("net cost of operations", "Net cost of operations for the year."),
    "total_budgetary_resources": ("total budgetary resources", "Total budgetary resources."),
}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def check(pdf: Path, first: int, last: int) -> str:
    """Why the pages of pages.json are not a cut, or ""."""
    from groundgate.extract import extract

    if not 1 <= first <= last or last - first + 1 > MAX_PAGES:
        return f"pages {first} to {last}: not 1 to {MAX_PAGES} pages"
    for page, line in ((first, FIRST), (last, LAST)):
        text = extract(pdf, pages=[page]).text
        if not any(line.match(t.strip()) for t in text.split("\n")):
            return f"page {page} has no line that starts with {line.pattern!r}"
    return ""


def pick() -> None:
    (HERE / ".cache").mkdir(exist_ok=True)
    chosen_pages = _read(HERE / "pages.json")
    log: list[dict[str, Any]] = []
    chosen: list[dict[str, Any]] = []
    failed = []
    for agency in _read(HERE / "agencies.json"):
        if len(chosen) >= REPORTS:
            break
        entry: dict[str, Any] = {"id": agency["id"], "agency": agency["agency"]}
        log.append(entry)
        if agency["url"] is None:
            entry["skip"] = "no FY2025 report on the agency's site"
            continue
        if isinstance(chosen_pages.get(agency["id"]), str):
            entry["skip"] = chosen_pages[agency["id"]]
            continue
        path = HERE / ".cache" / f"{agency['id']}.pdf"
        try:
            data = download(agency["url"], path)
        except OSError as e:
            failed.append(agency["id"])
            entry["skip"] = f"download failed: {type(e).__name__}"
            continue
        if not data.startswith(b"%PDF"):
            path.unlink()
            failed.append(agency["id"])
            entry["skip"] = "the download is not a PDF"
            continue
        first, last = chosen_pages[agency["id"]]
        why = check(path, first, last)
        if why:
            raise SystemExit(f"{agency['id']}: {why}")
        pages = list(range(first, last + 1))
        sha = hashlib.sha256(data).hexdigest()
        entry["pages"] = pages
        chosen.append({**agency, "sha256": sha, "select": {"pages": pages}, "kind": "afr"})
    if failed:
        raise SystemExit(
            f"download failed for {', '.join(failed)}: save each PDF from a browser as "
            ".cache/<id>.pdf and run pick again. Nothing was written."
        )
    _dump(HERE / "sources.json", {"sources": chosen})
    _dump(HERE / "selection-log.json", log)
    print(f"afr: {len(chosen)} reports from {len(log)} agencies looked at")
    for e in log:
        if "skip" in e:
            print(f"  skip {e['id']}: {e['skip']}")


def docs() -> None:
    """docs/<id>.txt: the cut pages of each pinned report, after a check of its digest."""
    from groundgate.extract import extract

    out = HERE / "docs"
    out.mkdir(exist_ok=True)
    for src in _read(HERE / "sources.json")["sources"]:
        path = HERE / ".cache" / f"{src['id']}.pdf"
        data = download(src["url"], path)
        if hashlib.sha256(data).hexdigest() != src["sha256"]:
            raise SystemExit(f"{src['id']}: the report changed since the pick")
        text = extract(path, pages=src["select"]["pages"]).text
        (out / f"{src['id']}.txt").write_text(text, encoding="utf-8")
    print(f"wrote {len(_read(HERE / 'sources.json')['sources'])} documents")


def fields() -> None:
    schema = {
        "fields": {
            name: {
                "type": "number",
                "unit": "USD",
                "multiple": True,
                "keys": YEARS,
                "aliases": [alias],
            }
            for name, (alias, _) in FIELDS.items()
        }
    }
    _dump(HERE / "schema.json", schema)
    _dump(HERE / "descriptions.json", {name: d for name, (_, d) in FIELDS.items()})
    print("wrote schema.json, descriptions.json")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pick", "docs", "fields"):
        sub.add_parser(name)
    args = ap.parse_args()
    {"pick": pick, "docs": docs, "fields": fields}[args.cmd]()


if __name__ == "__main__":
    main()
