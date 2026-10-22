"""The diagnosis of #246 and #247 on a new set: which rows the PDF extract of #230 puts in a
table, and where their cells are. The plan is on #247, made before anyone read the set.

    uv run python bench/pdfrows/pdfrows.py pick     # .cache/, sources.json, selection-log.json
    uv run python bench/pdfrows/pdfrows.py rows     # rows.json
    uv run python bench/pdfrows/pdfrows.py web      # blind labels, port 8783
    uv run python bench/pdfrows/pdfrows.py results [--check]

The set is the statement of net position and the statement of activities of the FY2025 ACFRs of
10 more states, in alphabetical order after Missouri, the last state of bench/acfr2. pick follows
the rules of bench/acfr2/acfr2.py: states.json gives each state's URL (null when the state has no
FY2025 ACFR PDF on a state site), pages.json the pages, chosen by hand from the statement titles,
never from the values. The PDFs stay out of git, and no model runs on this set.

rows reads each page with the extract of the groundgate that runs it and lists three kinds of
rows from the tables of the extract (pdf._plan). A script never decides which kind a row is.

1. above: each row that the walk up from a table's first table row takes as a column heading,
   with its gap to the row below in line heights, its top as a fraction of the page height, its
   word height against the median word height of the table rows, and whether the same text
   stands on another page of the report at a top within REPEAT points.
2. join: each pair of table rows of one table with one or more rows between them that are not
   table rows, with their gap in line heights and the number of rows between.
3. short: each table row with fewer number cells than the widest table row on its page, with
   whether it is also short in its own table, and whether the number columns of the widest rows
   give one column to each of its number cells. A page can split one statement into two tables,
   as when the rows of general revenues have only the columns of net revenue.
   When there are more than SAMPLE such rows, a seeded random sample of SAMPLE is labeled.

rows.json holds the boxes and the features, never the text of a row.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import random
import statistics
import sys
import threading
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "acfr2"))
import acfr2  # noqa: E402  (bench/acfr2/acfr2.py: the cut and its check)
import localweb  # noqa: E402  (bench/localweb.py)
from fetch import download  # noqa: E402  (bench/fetch.py)

REPORTS = 10
REPEAT = 2.0  # points: the same text this close to the same top on another page is a repeat
SAMPLE = 100
SEED = 247
PORT = 8783
ANSWERS = {
    "above": ("column heading", "caption", "running head or page number", "other"),
    "join": ("same table", "not the same table", "not sure"),
    "short": ("in its columns", "a blank cell before a number", "not part of this table"),
}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


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
        why = acfr2.check(path, first, last)
        if why:
            raise SystemExit(f"{state['id']}: {why}")
        pages = list(range(first, last + 1))
        sha = hashlib.sha256(data).hexdigest()
        entry["pages"] = pages
        chosen.append({**state, "sha256": sha, "select": {"pages": pages}, "kind": "pdfrows"})
    if failed:
        raise SystemExit(
            f"no report yet for {', '.join(failed)}: save each PDF from a browser as "
            ".cache/<id>.pdf, give its URL and pages, and run pick again. Nothing was written."
        )
    _dump(HERE / "sources.json", {"sources": chosen})
    _dump(HERE / "selection-log.json", log)
    print(f"pdfrows: {len(chosen)} reports from {len(log)} states looked at")
    for e in log:
        if "skip" in e:
            print(f"  skip {e['id']}: {e['skip']}")


def _pdf(src: dict[str, Any]) -> Path:
    path = HERE / ".cache" / f"{src['id']}.pdf"
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != src["sha256"]:
        raise SystemExit(f"{src['id']}: {path} is not the pinned PDF; run pick")
    return path


def _union(boxes: list[Any]) -> list[float]:
    return [
        min(b.x0 for b in boxes),
        min(b.top for b in boxes),
        max(b.x1 for b in boxes),
        max(b.bottom for b in boxes),
    ]


def _pages(
    pdf_path: Path, pages: list[int] | None
) -> tuple[list[dict[str, Any]], dict[int, float]]:
    """For each page (all of them when pages is None): its blocks and the tables of the extract,
    and each page's height. The extract runs as groundgate runs it; this only records what _plan
    gives."""
    try:
        from groundgate.read import pdf, read
    except ImportError:  # a wheel before 0.9 names it extract
        from groundgate.extract import extract as read
        from groundgate.extract import pdf  # type: ignore[no-redef]

    seen: list[dict[str, Any]] = []
    tables = pdf._tables

    def record(blocks: list[Any]) -> Any:
        rows, span, plan = pdf._plan(blocks)
        seen.append({"blocks": blocks, "rows": rows, "span": span, "plan": plan})
        return tables(blocks)

    pdf._tables = record
    try:
        got = read(pdf_path, pages=pages)
    finally:
        pdf._tables = tables
    assert got.layout is not None
    return seen, {p.number: p.height for p in got.layout.pages}


def rows_of(doc: str, pdf_path: Path, pages: list[int]) -> list[dict[str, Any]]:
    """The rows of the three kinds on these pages of a PDF."""
    try:
        from groundgate.read import pdf
    except ImportError:  # a wheel before 0.9 names it extract
        from groundgate.extract import pdf  # type: ignore[no-redef]

    seen, heights = _pages(pdf_path, pages)
    out: list[dict[str, Any]] = []
    tops: dict[str, list[tuple[int, float]]] = collections.defaultdict(list)
    # the text and top of every row on every page of the report, for the repeat feature
    for pg in _pages(pdf_path, None)[0]:
        for row in pg["rows"]:
            words = [w for bi, li in row for w in pg["blocks"][bi][li]]
            text = " ".join(t for t, _ in words)
            tops[text].append((words[0][1].page, min(b.top for _, b in words)))
    for pg in seen:
        blocks, rows, span, plan = pg["blocks"], pg["rows"], pg["span"], pg["plan"]

        def boxes(r: int, blocks: Any = blocks, rows: Any = rows) -> list[Any]:
            return [b for bi, li in rows[r] for _, b in blocks[bi][li]]

        def cells(r: int, blocks: Any = blocks, rows: Any = rows) -> list[Any]:
            return [c for bi, li in rows[r] for c in pdf._cells(blocks[bi][li])]

        for first, group in plan:
            median = statistics.median(b.bottom - b.top for r in group for b in boxes(r))
            page = boxes(group[0])[0].page
            for r in range(first, group[0]):
                if not pdf._side_by_side(rows[r], span):
                    continue
                bx = boxes(r)
                text = " ".join(t for bi, li in rows[r] for t, _ in blocks[bi][li])
                height = statistics.median(b.bottom - b.top for b in bx)
                top = min(b.top for b in bx)
                below = min(b.top for b in boxes(r + 1))
                repeat = any(p != page and abs(t - top) <= REPEAT for p, t in tops[text])
                out.append(
                    {
                        "kind": "above",
                        "doc": doc,
                        "page": page,
                        "boxes": [_union(bx)],
                        "gap": round((below - max(b.bottom for b in bx)) / height, 2),
                        "top": round(top / heights[page], 3),
                        "height": round(height / median, 2),
                        "repeat": repeat,
                    }
                )
            for a, b in itertools.pairwise(group):
                if b - a == 1:
                    continue
                ba, bb = boxes(a), boxes(b)
                height = statistics.median(x.bottom - x.top for x in ba)
                gap = min(x.top for x in bb) - max(x.bottom for x in ba)
                out.append(
                    {
                        "kind": "join",
                        "doc": doc,
                        "page": page,
                        "boxes": [_union(ba), _union(bb)],
                        "gap": round(gap / height, 2),
                        "between": b - a - 1,
                    }
                )
        numbers = {
            r: [_union([x for _, x in c]) for c in cells(r) if pdf._number_cell(c)]
            for _, group in plan
            for r in group
        }
        if not numbers:
            continue
        widest = max(len(v) for v in numbers.values())
        full = [r for r, v in numbers.items() if len(v) == widest]
        columns = [
            (min(numbers[r][k][0] for r in full), max(numbers[r][k][2] for r in full))
            for k in range(widest)
        ]
        for _, group in plan:
            own = max(len(numbers[r]) for r in group)
            for r in group:
                if len(numbers[r]) == widest:
                    continue
                hits = [
                    [k for k, (x0, x1) in enumerate(columns) if c[0] < x1 and c[2] > x0]
                    for c in numbers[r]
                ]
                fits = all(len(h) == 1 for h in hits) and len({h[0] for h in hits}) == len(hits)
                out.append(
                    {
                        "kind": "short",
                        "doc": doc,
                        "page": boxes(r)[0].page,
                        "boxes": [_union(boxes(r))],
                        "cells": len(numbers[r]),
                        "columns": widest,
                        "short in its table": len(numbers[r]) < own,
                        "fits": fits,
                    }
                )
    for item in out:
        raw = json.dumps(["pdfrows", item["kind"], item["doc"], item["page"], item["boxes"]])
        item["id"] = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return out


def rows() -> None:
    out = []
    for src in _read(HERE / "sources.json")["sources"]:
        out += rows_of(src["id"], _pdf(src), src["select"]["pages"])
    short = sorted(r["id"] for r in out if r["kind"] == "short")
    chosen = set(short)
    if len(short) > SAMPLE:
        chosen = set(random.Random(SEED).sample(short, SAMPLE))
    for r in out:
        r["labeled"] = r["kind"] != "short" or r["id"] in chosen
    _dump(HERE / "rows.json", out)
    print(", ".join(f"{k}: {n}" for k, n in collections.Counter(r["kind"] for r in out).items()))


def labels() -> dict[str, Any]:
    path = HERE / "labels.json"
    return _read(path) if path.exists() else {}


def serve(port: int) -> None:
    srcs = {s["id"]: s for s in _read(HERE / "sources.json")["sources"]}
    items = [
        {k: r[k] for k in ("id", "kind", "doc", "page", "boxes")}
        for r in _read(HERE / "rows.json")
        if r["labeled"]
    ]
    kinds = {it["id"]: it["kind"] for it in items}
    path = HERE / "labels.json"
    page = (HERE / "web.html").read_bytes()
    lock = threading.Lock()

    class Handler(localweb.LocalHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/":
                self.send(200, page, "text/html; charset=utf-8")
            elif self.path == "/state":
                with lock:
                    body = {"items": items, "labels": labels(), "answers": ANSWERS}
                self.send(200, json.dumps(body).encode(), "application/json")
            elif self.path.startswith("/pdf/") and self.path[5:] in srcs:
                self.send(200, _pdf(srcs[self.path[5:]]).read_bytes(), "application/pdf")
            else:
                self.send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            # a JSON body needs a preflight that this server never answers, so another site in
            # the browser cannot write a label
            if self.path != "/label" or self.headers.get("Content-Type") != "application/json":
                self.send(404, b"not found", "text/plain")
                return
            got = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            kind = kinds.get(got.get("id"))
            if kind is None or got.get("answer") not in ANSWERS[kind]:
                self.send(400, b"bad label", "text/plain")
                return
            with lock:  # requests run in threads; one read-modify-write at a time
                given = labels()
                given[got["id"]] = {"answer": got["answer"]}
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(dict(sorted(given.items())), indent=1) + "\n")
                tmp.replace(path)  # a reader never sees half a file
            self.send(200, b"{}", "application/json")

    localweb.serve(Handler, port, f"{len(items)} items")


def _range(xs: list[float]) -> str:
    return f"{min(xs)} to {max(xs)}" if xs else ""


def score() -> dict[str, Any]:
    given = labels()
    rows = _read(HERE / "rows.json")
    res: dict[str, Any] = {"rows": dict(collections.Counter(r["kind"] for r in rows))}
    res["labeled"] = dict(collections.Counter(r["kind"] for r in rows if r["labeled"]))
    for kind, answers in ANSWERS.items():
        mine = [r for r in rows if r["kind"] == kind and r["labeled"]]
        by = {a: [r for r in mine if given.get(r["id"], {}).get("answer") == a] for a in answers}
        by["not labeled"] = [r for r in mine if r["id"] not in given]
        res[kind] = {}
        for a, rs in by.items():
            c: dict[str, Any] = {"rows": len(rs)}
            if kind == "above":
                c["gap"] = _range([r["gap"] for r in rs])
                c["top"] = _range([r["top"] for r in rs])
                c["height"] = _range([r["height"] for r in rs])
                c["repeat"] = sum(r["repeat"] for r in rs)
            elif kind == "join":
                c["gap"] = _range([r["gap"] for r in rs])
            else:
                c["short in its table"] = sum(r["short in its table"] for r in rs)
                c["fits"] = sum(r["fits"] for r in rs)
            res[kind][a] = c
    return res


def render(res: dict[str, Any]) -> str:
    out = [
        "# Rows that the PDF extract puts in a table (#246, #247)",
        "",
        "Generated by `bench/pdfrows/pdfrows.py results` from `results.json`. Do not edit.",
        "",
        "The statement of net position and the statement of activities of 10 FY2025 state ACFRs "
        "that no rule came from (`bench/pdfrows`). A script lists the rows of the extract's "
        "tables, and a person labels each one blind on the PDF page. The kinds and the features "
        "are defined in `pdfrows.py`.",
        "",
        "| Kind | Rows | Labeled |",
        "|---|---:|---:|",
    ]
    for kind in ANSWERS:
        out.append(f"| {kind} | {res['rows'].get(kind, 0)} | {res['labeled'].get(kind, 0)} |")
    out += [
        "",
        "## Rows above a table (#246)",
        "",
        "| Label | Rows | Gap below, line heights | Top, part of the page height | Height, part "
        "of the table's | Repeated on another page |",
        "|---|---:|---|---|---|---:|",
    ]
    for a, c in res["above"].items():
        out.append(
            f"| {a} | {c['rows']} | {c['gap']} | {c['top']} | {c['height']} | {c['repeat']} |"
        )
    out += [
        "",
        "## Joins across other rows (#246)",
        "",
        "| Label | Rows | Gap, line heights |",
        "|---|---:|---|",
    ]
    for a, c in res["join"].items():
        out.append(f"| {a} | {c['rows']} | {c['gap']} |")
    out += [
        "",
        "## Short rows (#247)",
        "",
        "| Label | Rows | Short in its own table | The columns of the widest rows place each "
        "cell |",
        "|---|---:|---:|---:|",
    ]
    for a, c in res["short"].items():
        out.append(f"| {a} | {c['rows']} | {c['short in its table']} | {c['fits']} |")
    return "\n".join(out)


def results(check: bool) -> None:
    res = score()
    body = json.dumps(res, indent=1) + "\n"
    md = render(res) + "\n"
    if check:
        old = (HERE / "results.json").read_text(), (HERE / "RESULTS.md").read_text()
        same = old == (body, md)
        print("results are up to date" if same else "out of date: run results")
        sys.exit(0 if same else 1)
    (HERE / "results.json").write_text(body)
    (HERE / "RESULTS.md").write_text(md)
    print(md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pick", "rows", "web"):
        sub.add_parser(name)
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "pick":
        pick()
    elif args.cmd == "rows":
        rows()
    elif args.cmd == "web":
        serve(PORT)
    else:
        results(args.check)


if __name__ == "__main__":
    main()
