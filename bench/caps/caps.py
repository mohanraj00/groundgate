"""The caps set for the U.S. and No. rule (#77, #80): every "U.S.", "No." or "Nos." whose dot is
followed by whitespace and an uppercase letter, in documents that v0.1, set 2, the pattern set
and the dots set did not use, labeled by a person as a sentence end or not.

    uv run python bench/caps/caps.py pick --count     # how many dots each kind finds
    uv run python bench/caps/caps.py pick             # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/caps     # download, verify, write docs/
    uv run python bench/caps/caps.py items            # write items.json from docs/
    uv run python bench/caps/caps.py label            # label them in the terminal
    uv run python bench/caps/caps.py score            # RESULTS.md: spec 0.3 before and after #77
    uv run python bench/caps/caps.py score --check    # fail if the committed files differ

The pick uses the walkers of bench/patterns/pairs.py, looks only at counts, and prints no text.
The label tool never shows how a spec reads a dot.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "patterns"), str(HERE.parent / "dots")]

import dots  # noqa: E402  (bench/dots/dots.py)
import pairs  # noqa: E402  (bench/patterns/pairs.py)
import pick as walk  # noqa: E402  (bench/pick.py)

PER_KIND, PER_DOC, CONTEXT = 50, 5, 100
KINDS = ("irs", "fr")
# "U.S.", "No." or "Nos." as a whole word, then whitespace with at most one line break, then an
# uppercase letter
CAP_DOT = re.compile(r"(?<!\w)(?i:u\.s\.|nos?\.)(?=(?:[ \t\r]+|[ \t\r]*\n[ \t\r]*)[A-Z])")
LABELS = dots.LABELS


def caps_in(text: str) -> list[re.Match[str]]:
    """The caps dots in ``text``, except those inside a Federal Register running head."""
    heads = [(h.start(), h.end()) for h in dots.RUNNING_HEAD.finditer(text)]
    return [m for m in CAP_DOT.finditer(text) if not any(a <= m.start() < b for a, b in heads)]


def fresh_finder() -> Callable[[str], list[re.Match[str]]]:
    """A finder of the caps dots on a page that passes over a dot when an earlier dot had the
    same text, CONTEXT code points on each side, whitespace runs read as one space. Federal
    Register rules share printed pages, and IRS publications repeat paragraphs, so the same dot
    can turn up in two documents."""
    seen: set[str] = set()

    def find(page: str) -> list[re.Match[str]]:
        out = []
        for m in caps_in(page):
            key = " ".join(page[max(0, m.start() - CONTEXT) : m.end() + CONTEXT].split())
            if key not in seen:
                seen.add(key)
                out.append(m)
        return out

    return find


def excluded() -> tuple[set[str], set[str]]:
    """IRS publication ids and Federal Register ids used by v0.1, set 2, the pattern set or the
    dots set."""
    _, pubs, frs = dots.excluded()
    used = json.loads((HERE.parent / "dots" / "sources.json").read_text())["sources"]
    ids = {s["id"] for s in used}
    return (
        pubs | {i for i in ids if i.startswith("irs-")},
        frs | {i for i in ids if i.startswith("fr-")},
    )


def pick(count_only: bool) -> None:
    walk.CACHE = HERE / ".cache"
    # set 2 took 2026, the pattern set 2025-07-01 to 2025-12-31, the dots set 2025-01-01 to
    # 2025-06-30
    walk.FR_FROM, walk.FR_TO = "2024-07-01", "2024-12-31"
    walk.CACHE.mkdir(parents=True, exist_ok=True)
    pubs, frs = excluded()
    log: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    limits = {"find": fresh_finder(), "per_kind": PER_KIND, "per_doc": PER_DOC, "group": "dots"}
    irs = [(f"irs-p{n.lower()}", u) for n, u in walk.irs_publications()]
    irs = [(i, u) for i, u in irs if i not in pubs]
    sources = pairs.pick_pdfs("irs", irs, log, seen, **limits)
    fr = [(i, u) for i, u in walk.federal_register_rules() if i not in frs]
    sources += pairs.pick_pdfs("fr", fr, log, seen, **limits)
    found: dict[str, int] = defaultdict(int)
    docs: dict[str, int] = defaultdict(int)
    skips: dict[str, int] = defaultdict(int)
    for entry in log:
        if "skip" in entry:
            skips[f"{entry['kind']}: {entry['skip']}"] += 1
        else:
            found[entry["kind"]] += min(entry["pairs"], PER_DOC)
            docs[entry["kind"]] += 1
    for kind in KINDS:
        print(f"{kind}: {docs[kind]} documents, {found[kind]} dots")
    print("skipped:")
    for why, c in sorted(skips.items()):
        print(f"  {why}: {c}")
    if count_only:
        return
    lock = {"retrieved": datetime.date.today().isoformat(), "sources": sources}
    (HERE / "sources.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    (HERE / "selection-log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print("wrote bench/caps/sources.json and selection-log.json")


def find_items() -> None:
    """items.json: the first PER_DOC caps dots of each document, as the code point offset of the
    abbreviation and of its dot in docs/<id>.txt."""
    out = []
    find = fresh_finder()  # the same pages in the same order as the pick, so the same dots
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        text = (HERE / "docs" / f"{src['id']}.txt").read_text(encoding="utf-8")
        spans, pos = [], 0
        for page in text.split("\f"):
            spans += [(pos + m.start(), pos + m.end()) for m in find(page)]
            pos += len(page) + 1
        for a, b in spans[:PER_DOC]:
            out.append(
                {
                    "id": f"{src['id']}:{b - 1}",
                    "doc": src["id"],
                    "kind": src["kind"],
                    "abbreviation": [a, b],
                }
            )
    (HERE / "items.json").write_text(json.dumps(out, indent=1) + "\n")
    kinds: dict[str, int] = defaultdict(int)
    for it in out:
        kinds[it["kind"]] += 1
    print(f"wrote items.json: {len(out)} dots", dict(kinds))


def label() -> None:
    items = json.loads((HERE / "items.json").read_text())
    path = HERE / "labels.json"
    labels: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
    texts: dict[str, str] = {}
    print("For each marked abbreviation: does the sentence end at its dot (e), or does the")
    print("sentence go on after it (c)?\n")
    i = next((k for k, it in enumerate(items) if it["id"] not in labels), len(items))
    while i < len(items):
        it = items[i]
        if it["doc"] not in texts:
            texts[it["doc"]] = (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8")
        done = sum(x["id"] in labels for x in items)
        print(f"\n[{i + 1}/{len(items)}, {done} labeled] {it['doc']}")
        print(dots.context(texts[it["doc"]], it))
        was = f" (now: {labels[it['id']]})" if it["id"] in labels else ""
        ans = input(f"Sentence{was}: e ends here, c goes on, b back, q quit: ").strip().lower()
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
    print(f"\n{done} of {len(items)} labeled, saved in bench/caps/labels.json")


def score(check: bool) -> None:
    items = json.loads((HERE / "items.json").read_text())
    labels = json.loads((HERE / "labels.json").read_text())
    missing = [it["id"] for it in items if it["id"] not in labels]
    if missing:
        raise SystemExit(f"{len(missing)} of {len(items)} dots have no label; run caps.py label")
    texts = {
        it["doc"]: (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8") for it in items
    }
    rows = []
    for it in items:
        a, b = it["abbreviation"]
        rows.append(
            {
                **it,
                "abbreviation_text": texts[it["doc"]][a:b],
                "label": labels[it["id"]],
                # before #77, spec 0.3 ends a sentence at a listed abbreviation before an
                # uppercase letter, and every dot of this set has one
                "before": "end",
                "spec_0.3": dots.reading(texts[it["doc"]], b - 1),
            }
        )
    keys = [f"{lab} read as {r}" for lab in LABELS.values() for r in LABELS.values()]

    def tally(rs: list[dict[str, Any]], spec: str) -> dict[str, int]:
        return {k: sum(f"{r['label']} read as {r[spec]}" == k for r in rs) for k in keys}

    def word(r: dict[str, Any]) -> str:
        return "U.S." if r["abbreviation_text"].lower() == "u.s." else "No. or Nos."

    specs = ("before", "spec_0.3")
    results = {
        "dots": len(rows),
        "dots_by_kind": {k: sum(r["kind"] == k for r in rows) for k in KINDS},
        "documents_by_kind": {k: len({r["doc"] for r in rows if r["kind"] == k}) for k in KINDS},
        "labels": {lab: sum(r["label"] == lab for r in rows) for lab in LABELS.values()},
        "by_spec": {s: tally(rows, s) for s in specs},
        "by_abbreviation": {
            w: {s: tally([r for r in rows if word(r) == w], s) for s in specs}
            for w in ("U.S.", "No. or Nos.")
        },
        "by_kind": {
            k: {s: tally([r for r in rows if r["kind"] == k], s) for s in specs} for k in KINDS
        },
        "dots_read": [{k: r[k] for k in ("id", "label", *specs)} for r in rows],
    }
    what = {
        "end read as end": "right",
        "end read as goes on": "two sentences joined: a value can go to review",
        "goes on read as end": "a sentence cut: a qualifier before the dot is lost",
        "goes on read as goes on": "right",
    }
    md = [
        "# Caps set: U.S. and No. before an uppercase letter",
        "",
        "Generated by `bench/caps/caps.py score` from `items.json` and `labels.json`. "
        '[README.md](README.md) explains the set. "Before #77" is spec 0.3 with the #63 rule, '
        "which ends a sentence at every dot of this set. Spec 0.3 is the core in this repository.",
        "",
        f"{len(rows)} dots in {sum(results['documents_by_kind'].values())} documents: "
        + ", ".join(
            f"{name} {results['dots_by_kind'][k]} ({results['documents_by_kind'][k]} documents)"
            for k, name in (("irs", "IRS"), ("fr", "Federal Register"))
        )
        + f". Labeled by a person: {results['labels']['end']} sentence ends, "
        f"{results['labels']['goes on']} where the sentence goes on.",
        "",
        "| Label and reading | What it means | Before #77 | Spec 0.3 |",
        "|---|---|---:|---:|",
    ]
    for k in keys:
        a, b = results["by_spec"]["before"][k], results["by_spec"]["spec_0.3"][k]
        md.append(f"| {k} | {what[k]} | {a} | {b} |")
    for title, part in (("By abbreviation", "by_abbreviation"), ("By kind", "by_kind")):
        md += ["", f"## {title}", "", "| | Label and reading | Before #77 | Spec 0.3 |"]
        md += ["|---|---|---:|---:|"]
        for name, by in results[part].items():
            for k in keys:
                a, b = by["before"][k], by["spec_0.3"][k]
                if a or b:
                    md.append(f"| {name} | {k} | {a} | {b} |")
    wrong = [r for r in rows if r["label"] != r["spec_0.3"]]
    md += ["", f"## Spec 0.3 reads against the label ({len(wrong)})", ""]
    if not wrong:
        md.append("None.")
    else:
        md += ["| Dot | Label | 0.3 | Text |", "|---|---|---|---|"]
        for r in wrong:
            text = dots.context(texts[r["doc"]], r, "**{}**").replace("|", "\\|")
            md.append(f"| `{r['id']}` | {r['label']} | {r['spec_0.3']} | {text} |")
    out = {
        HERE / "results.json": json.dumps(results, indent=1) + "\n",
        HERE / "RESULTS.md": "\n".join(md) + "\n",
    }
    if check:
        stale = [p.name for p, body in out.items() if not p.exists() or p.read_text() != body]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run caps.py score")
        print("results are up to date")
        return
    for path, body in out.items():
        path.write_text(body)
    print("wrote results.json, RESULTS.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report dot counts; write nothing")
    sub.add_parser("items")
    sub.add_parser("label")
    p = sub.add_parser("score")
    p.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = ap.parse_args()
    if args.cmd == "pick":
        pick(args.count)
    elif args.cmd == "items":
        find_items()
    elif args.cmd == "label":
        label()
    else:
        score(args.check)


if __name__ == "__main__":
    main()
