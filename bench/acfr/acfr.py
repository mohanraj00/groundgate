"""A held-out set for the #242 rule: the government-wide statements of 10 FY2025 state annual
comprehensive financial reports (ACFR), as PDF text. The rule of #242 came from bench/afr, so it
is measured here, on documents that no rule came from. The plan is on #242.

    uv run python bench/acfr/acfr.py pick     # .cache/, sources.json, selection-log.json
    uv run python bench/acfr/acfr.py docs     # docs/, from the cache, with the extract of #230
    uv run python bench/acfr/acfr.py fields   # schema.json, descriptions.json

states.json lists the states in alphabetical order after Alaska, each with the URL of its FY2025
ACFR on its own site. Alabama and Alaska are the development text of #230, so they are not in
the set. pick takes the states in that order. It downloads each report into .cache, takes the
pages of pages.json, and stops at 10 reports. A site that refuses the download: save the PDF
from a browser as .cache/<id>.pdf, and run pick again. pick prints counts and reasons, never
text. The PDFs, docs/ and the runs stay out of git.

The cut is the statement of net position and the statement of activities. I chose the pages by
hand from the statement titles, and never from the values. pages.json has the first and the last
page of each report, or the reason for a skip. pick checks that the first page has a "Total
assets" line, the last page has the words "change in net position" or "changes in net
position", and the cut has at most 8 pages.
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

REPORTS = 10
MAX_PAGES = 8
FIRST = re.compile(r"total\s+assets\b", re.I)
LAST = re.compile(r"changes?\s+in\s+net\s+position", re.I)
# the fields of #242, fixed before any document was read
FIELDS = {
    "total_assets": (
        "total assets",
        "Total assets of the primary government (its Total column) at the fiscal year end.",
    ),
    "total_liabilities": (
        "total liabilities",
        "Total liabilities of the primary government (its Total column) at the fiscal year end.",
    ),
    "total_net_position": (
        "total net position",
        "Total net position of the primary government (its Total column) at the fiscal year end.",
    ),
    "change_in_net_position": (
        "change in net position",
        "Change in net position of the primary government (its Total column) for the year.",
    ),
}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _extract(pdf: Path, pages: list[int]) -> str:
    """The text of the pages, as groundgate writes it since #230: a table as rows with tabs."""
    from groundgate.extract import extract
    from groundgate.extract import pdf as pdf_path

    if not hasattr(pdf_path, "CELL_BREAK"):
        raise SystemExit("this set reads the text of #230: run it with the extract of #230")
    return extract(pdf, pages=pages).text


def check(pdf: Path, first: int, last: int) -> str:
    """Why the pages of pages.json are not a cut, or ""."""
    if not 1 <= first <= last or last - first + 1 > MAX_PAGES:
        return f"pages {first} to {last}: not 1 to {MAX_PAGES} pages"
    if not any(FIRST.match(t.strip()) for t in _extract(pdf, [first]).split("\n")):
        return f"page {first} has no line that starts with {FIRST.pattern!r}"
    if not LAST.search(_extract(pdf, [last])):
        return f"page {last} has no {LAST.pattern!r}"
    return ""


def pick() -> None:
    (HERE / ".cache").mkdir(exist_ok=True)
    chosen_pages = _read(HERE / "pages.json")
    log: list[dict[str, Any]] = []
    chosen: list[dict[str, Any]] = []
    failed = []
    for state in _read(HERE / "states.json"):
        if len(chosen) >= REPORTS:
            break
        entry: dict[str, Any] = {"id": state["id"], "state": state["state"]}
        log.append(entry)
        if isinstance(chosen_pages.get(state["id"]), str):
            entry["skip"] = chosen_pages[state["id"]]
            continue
        path = HERE / ".cache" / f"{state['id']}.pdf"
        if state["url"] is None or state["id"] not in chosen_pages:
            failed.append(state["id"])
            entry["skip"] = "no URL or no pages yet"
            continue
        try:
            data = download(state["url"], path)
        except OSError as e:
            failed.append(state["id"])
            entry["skip"] = f"download failed: {type(e).__name__}"
            continue
        if not data.startswith(b"%PDF"):
            path.unlink()
            failed.append(state["id"])
            entry["skip"] = "the download is not a PDF"
            continue
        first, last = chosen_pages[state["id"]]
        why = check(path, first, last)
        if why:
            raise SystemExit(f"{state['id']}: {why}")
        pages = list(range(first, last + 1))
        sha = hashlib.sha256(data).hexdigest()
        entry["pages"] = pages
        chosen.append({**state, "sha256": sha, "select": {"pages": pages}, "kind": "acfr"})
    if failed:
        raise SystemExit(
            f"no report yet for {', '.join(failed)}: save each PDF from a browser as "
            ".cache/<id>.pdf, give its URL and pages, and run pick again. Nothing was written."
        )
    _dump(HERE / "sources.json", {"sources": chosen})
    _dump(HERE / "selection-log.json", log)
    print(f"acfr: {len(chosen)} reports from {len(log)} states looked at")
    for e in log:
        if "skip" in e:
            print(f"  skip {e['id']}: {e['skip']}")


def docs() -> None:
    """docs/<id>.txt: the cut pages of each pinned report, after a check of its digest."""
    out = HERE / "docs"
    out.mkdir(exist_ok=True)
    srcs = _read(HERE / "sources.json")["sources"]
    for src in srcs:
        path = HERE / ".cache" / f"{src['id']}.pdf"
        data = download(src["url"], path)
        if hashlib.sha256(data).hexdigest() != src["sha256"]:
            raise SystemExit(f"{src['id']}: the report changed since the pick")
        text = _extract(path, src["select"]["pages"])
        (out / f"{src['id']}.txt").write_text(text, encoding="utf-8")
    print(f"wrote {len(srcs)} documents")


def fields() -> None:
    schema = {
        "fields": {
            name: {"type": "number", "unit": "USD", "aliases": [alias], "description": d}
            for name, (alias, d) in FIELDS.items()
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
