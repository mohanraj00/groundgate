"""A held-out set for spec 0.7 (#229, planned on #164): the principal statements of 20 FY2025
agency financial reports, as PDF text. The rules of #164 and #152 came from bench/sec3, the
status set and the vectors, so they are measured here, on documents that no rule came from.

    uv run python bench/afr/afr.py pick     # .cache/, sources.json, selection-log.json
    uv run python bench/afr/afr.py docs     # docs/, from the cache
    uv run python bench/afr/afr.py fields   # schema.json, descriptions.json

agencies.json lists the CFO Act agencies in the order of 31 U.S.C. 901(b), each with the URL of
its FY2025 report on its own site, or null when it has none. pick takes them in that order. It
downloads each report into .cache, finds the cut, and stops at 20 reports with a cut. A site that
refuses the download: save the PDF from a browser as .cache/<id>.pdf, and run pick again. pick
prints counts and reasons, never text. The reports are works of the US government, so docs/ and
the runs are in git. The PDFs stay in .cache.

The cut: from the first page with a line "Balance Sheet" to the first page after it with a line
"Statement of Budgetary Resources", at most 8 pages. A line may also say "Consolidated" or
"Combined" before the title, and "Sheets" or "Statements".
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
_PREFIX = r"(?:(?:consolidated|combined)\s+)?"
BALANCE = re.compile(_PREFIX + r"balance\s+sheets?", re.I)
BUDGET = re.compile(_PREFIX + r"statements?\s+of\s+budgetary\s+resources", re.I)
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


def cut(pdf: Path) -> tuple[list[int] | None, str]:
    """The pages of the cut, or None and the reason."""
    from groundgate.extract import extract

    got = extract(pdf)

    def page(line_start: int) -> int | None:
        return got.layout.page_at(len(got.text[:line_start].encode("utf-8")))

    first = last = None
    pos = 0
    for line in got.text.split("\n"):
        title = line.strip()
        if first is None and BALANCE.fullmatch(title):
            first = page(pos)
        elif first is not None and BUDGET.fullmatch(title):
            p = page(pos)
            if p is not None and p >= first:
                last = p
                break
        pos += len(line) + 1
    if first is None:
        return None, "no line with the balance sheet title"
    if last is None:
        return None, "no line with the budgetary resources title after the balance sheet"
    if last - first + 1 > MAX_PAGES:
        return None, f"the cut has {last - first + 1} pages, more than {MAX_PAGES}"
    return list(range(first, last + 1)), ""


def pick() -> None:
    (HERE / ".cache").mkdir(exist_ok=True)
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
        pages, why = cut(path)
        if pages is None:
            entry["skip"] = why
            continue
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
