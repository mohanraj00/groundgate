"""The India set for the Indian digit grouping (#76): every number token with a comma in it, in
SEBI circulars that no rule was written from, labeled by a person as one number or not.

    uv run python bench/india/india.py pick --count     # how many tokens the walk finds
    uv run python bench/india/india.py pick             # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/india      # download, verify, write docs/
    uv run python bench/india/india.py items            # write items.json from docs/
    uv run python bench/india/india.py label            # label them in the terminal
    uv run python bench/india/india.py score            # RESULTS.md: spec 0.2 and 0.3
    uv run python bench/india/india.py score --check    # fail if the committed files differ

The pick uses the walkers of bench/patterns/pairs.py, looks only at counts, and prints no text.
The label tool never shows the value a spec reads.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "patterns")]

import pairs  # noqa: E402  (bench/patterns/pairs.py)
import pick as walk  # noqa: E402  (bench/pick.py)

# SEBI circulars, newest first: the listing page, then its own pagination request, which needs
# the session cookie the listing page sets
SEBI = "https://www.sebi.gov.in"
SEBI_LISTING = SEBI + "/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0"
SEBI_PAGE = SEBI + "/sebiweb/ajax/home/getnewslistinfo.jsp"
SEBI_FORM = (
    "nextValue=1&next=n&search=&fromDate=&toDate=&fromYear=&toYear=&deptId=&sid=1&ssid=7&smid=0"
    "&ssidhidden=7&intmid=-1&sText=Legal&ssText=Circulars&smText=&doDirect={}"
)
SEBI_MAX_PAGES = 40
CIRCULAR = re.compile(r"legal/circulars/[a-z]{3}-\d{4}/[^\"']+_(\d+)\.html")
CIRCULAR_PDF = re.compile(r"https://www\.sebi\.gov\.in/sebi_data/attachdocs/[^'\"]+\.pdf")
PER_SET, PER_DOC = 100, 5
LABELS = {"y": "one number", "n": "not one number"}
SPEC02 = [
    *("uv", "run", "--isolated", "--no-project", "--quiet", "--python", "3.12"),
    *("--with", "groundgate[pdf]==0.2.0", "python", str(HERE / "india.py"), "read"),
]


def commas_in(text: str) -> list[Any]:
    """The number tokens (SPEC §4.1) with a comma in them. The core's tokenizer decides where a
    token starts and ends; #59 changes only which tokens have a value, not their bounds."""
    from groundgate.text import tokens

    return [t for t in tokens(text) if "," in text[t.start : t.end]]


def _opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    opener.addheaders = [("User-Agent", "Mozilla/5.0"), ("Referer", SEBI_LISTING)]
    opener.open(SEBI_LISTING, timeout=60).read()  # sets the session cookie
    return opener


def circulars() -> Iterator[tuple[str, str]]:
    """(id, pdf url) for each circular, newest first, skipping a circular with no PDF. Each
    listing page is cached after its first download."""
    opener: urllib.request.OpenerDirector | None = None
    seen: set[str] = set()
    for page in range(1, SEBI_MAX_PAGES + 1):
        path = walk.CACHE / f"sebi-list-{page}.html"
        if not path.exists():
            opener = opener or _opener()
            path.write_bytes(opener.open(SEBI_PAGE, SEBI_FORM.format(page).encode(), 60).read())
            time.sleep(1)  # be polite to the publisher
        html = path.read_text(encoding="utf-8", errors="replace")
        for m in CIRCULAR.finditer(html):
            if m.group(1) in seen:
                continue
            seen.add(m.group(1))
            name = f"sebi-page-{m.group(1)}.html"
            page_html = walk.get(f"{SEBI}/{m.group(0)}", name).decode("utf-8", "replace")
            if pdf := CIRCULAR_PDF.search(page_html):
                yield f"sebi-{m.group(1)}", pdf.group(0)


def pick(count_only: bool) -> None:
    walk.CACHE = HERE / ".cache"
    walk.CACHE.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, Any]] = []
    sources = pairs.pick_pdfs(
        "sebi",
        circulars(),
        log,
        {},
        find=commas_in,
        per_kind=PER_SET,
        per_doc=PER_DOC,
        group="india",
    )
    taken = [e for e in log if "skip" not in e]
    print(f"sebi: {len(taken)} documents, {sum(min(e['pairs'], PER_DOC) for e in taken)} tokens")
    skips: dict[str, int] = {}
    for e in log:
        if "skip" in e:
            skips[e["skip"]] = skips.get(e["skip"], 0) + 1
    print("skipped:", skips)
    if count_only:
        return
    lock = {"retrieved": datetime.date.today().isoformat(), "sources": sources}
    (HERE / "sources.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    (HERE / "selection-log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print("wrote bench/india/sources.json and selection-log.json")


def find_items() -> None:
    out = []
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        text = (HERE / "docs" / f"{src['id']}.txt").read_text(encoding="utf-8")
        for t in commas_in(text)[:PER_DOC]:
            out.append({"id": f"{src['id']}:{t.start}", "doc": src["id"], "span": [t.start, t.end]})
    (HERE / "items.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote items.json: {len(out)} tokens in {len({i['doc'] for i in out})} documents")


def context(text: str, it: dict[str, Any], bold: str = "\033[1;7m{}\033[0m") -> str:
    a0, a1 = it["span"]
    a, b = max(0, a0 - 200), min(len(text), a1 + 200)
    return " ".join((text[a:a0] + bold.format(text[a0:a1]) + text[a1:b]).split())


def label() -> None:
    items = json.loads((HERE / "items.json").read_text())
    path = HERE / "labels.json"
    labels: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
    texts: dict[str, str] = {}
    print("For each marked text: is it one number written with grouping commas (y), or not one")
    print("number, such as a list, two values or a reference (n)?\n")
    i = next((k for k, it in enumerate(items) if it["id"] not in labels), len(items))
    while i < len(items):
        it = items[i]
        if it["doc"] not in texts:
            texts[it["doc"]] = (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8")
        done = sum(x["id"] in labels for x in items)
        print(f"\n[{i + 1}/{len(items)}, {done} labeled] {it['doc']}")
        print(context(texts[it["doc"]], it))
        was = f" (now: {labels[it['id']]})" if it["id"] in labels else ""
        ans = input(f"One number{was}? y yes, n no, b back, q quit: ").strip().lower()
        if ans == "q":
            break
        if ans == "b":
            i = max(0, i - 1)
            continue
        if ans not in LABELS:
            continue
        labels[it["id"]] = LABELS[ans]
        path.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
        i += 1
    done = sum(x["id"] in labels for x in items)
    print(f"\n{done} of {len(items)} labeled, saved in bench/india/labels.json")


def read() -> dict[str, bool]:
    """Whether the installed groundgate gives each token a value."""
    from groundgate.text import tokens

    out = {}
    for it in json.loads((HERE / "items.json").read_text()):
        text = (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8")
        a, b = it["span"]
        tok = next(t for t in tokens(text, a, b) if t.start == a)
        out[it["id"]] = tok.value is not None
    return out


def score(check: bool) -> None:
    items = json.loads((HERE / "items.json").read_text())
    labels = json.loads((HERE / "labels.json").read_text())
    missing = [it["id"] for it in items if it["id"] not in labels]
    if missing:
        raise SystemExit(f"{len(missing)} of {len(items)} tokens have no label; run india.py label")
    run = subprocess.run(SPEC02, capture_output=True, text=True, check=True)
    v02, v03 = json.loads(run.stdout), read()
    rows = [
        {**it, "label": labels[it["id"]], "spec_0.2": v02[it["id"]], "spec_0.3": v03[it["id"]]}
        for it in items
    ]
    cells = {
        "one number, with a value": ("one number", True, "right"),
        "one number, no value": ("one number", False, "a right extraction is rejected"),
        "not one number, with a value": ("not one number", True, "a possible wrong match"),
        "not one number, no value": ("not one number", False, "right"),
    }
    specs = ("spec_0.2", "spec_0.3")
    results = {
        "tokens": len(rows),
        "documents": len({r["doc"] for r in rows}),
        "labels": {lab: sum(r["label"] == lab for r in rows) for lab in LABELS.values()},
        "by_spec": {
            s: {
                k: sum(r["label"] == lab and r[s] == v for r in rows)
                for k, (lab, v, _) in cells.items()
            }
            for s in specs
        },
        "tokens_read": [{k: r[k] for k in ("id", "label", *specs)} for r in rows],
    }
    md = [
        "# India set: the Indian digit grouping",
        "",
        "Generated by `bench/india/india.py score` from `items.json` and `labels.json`. "
        "[README.md](README.md) explains the set. Spec 0.2 is the released 0.2.0 wheel and spec "
        "0.3 is the core in this repository.",
        "",
        f"{results['tokens']} number tokens with a comma in {results['documents']} SEBI "
        f"circulars, labeled by a person: {results['labels']['one number']} one number, "
        f"{results['labels']['not one number']} not one number.",
        "",
        "| Label and reading | What happens | Spec 0.2 | Spec 0.3 |",
        "|---|---|---:|---:|",
    ]
    for k, (_, _, what) in cells.items():
        md.append(
            f"| {k} | {what} | {results['by_spec']['spec_0.2'][k]} "
            f"| {results['by_spec']['spec_0.3'][k]} |"
        )
    texts = {
        r["doc"]: (HERE / "docs" / f"{r['doc']}.txt").read_text(encoding="utf-8") for r in rows
    }
    wrong = [r for r in rows if (r["label"] == "one number") != r["spec_0.3"]]
    md += ["", f"## Spec 0.3 reads against the label ({len(wrong)})", ""]
    if not wrong:
        md.append("None.")
    else:
        md += ["| Token | Label | 0.3 value | Text |", "|---|---|---|---|"]
        for r in wrong:
            text = context(texts[r["doc"]], r, "**{}**").replace("|", "\\|")
            md.append(
                f"| `{r['id']}` | {r['label']} | {'yes' if r['spec_0.3'] else 'no'} | {text} |"
            )
    out = {
        HERE / "results.json": json.dumps(results, indent=1) + "\n",
        HERE / "RESULTS.md": "\n".join(md) + "\n",
    }
    if check:
        stale = [p.name for p, body in out.items() if not p.exists() or p.read_text() != body]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run india.py score")
        print("results are up to date")
        return
    for path, body in out.items():
        path.write_text(body)
    print("wrote results.json, RESULTS.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report token counts; write nothing")
    sub.add_parser("items")
    sub.add_parser("label")
    sub.add_parser("read", help="print whether the installed groundgate reads each token (JSON)")
    p = sub.add_parser("score")
    p.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = ap.parse_args()
    if args.cmd == "pick":
        pick(args.count)
    elif args.cmd == "items":
        find_items()
    elif args.cmd == "label":
        label()
    elif args.cmd == "read":
        print(json.dumps(read()))
    else:
        score(args.check)


if __name__ == "__main__":
    main()
