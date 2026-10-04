"""The dots set for the abbreviation sentence-end rule (#73): every dot that ends a listed
abbreviation and is followed by whitespace, in documents that v0.1, set 2 and the pattern set
did not use, labeled by a person as a sentence end or not.

    uv run python bench/dots/dots.py pick --count     # how many dots each kind finds
    uv run python bench/dots/dots.py pick             # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/dots     # download, verify, write docs/
    uv run python bench/dots/dots.py items            # write items.json from docs/
    uv run python bench/dots/dots.py label            # label them in the terminal
    uv run python bench/dots/dots.py score            # RESULTS.md: spec 0.2 and 0.3
    uv run python bench/dots/dots.py score --check    # fail if the committed files differ

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
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "patterns")]

import pairs  # noqa: E402  (bench/patterns/pairs.py)
import pick as walk  # noqa: E402  (bench/pick.py)

PER_KIND, PER_DOC, FDA_MAX_RANK = 50, 5, 400
# SPEC 0.3 §4.2, written out here so the pick does not run the rule it measures
# fmt: off
ABBREVIATIONS = [
    "a.m.", "p.m.", "approx.", "ca.", "cf.", "e.g.", "i.e.", "etc.", "vs.", "viz.", "no.", "nos.",
    "p.", "pp.", "para.", "fig.", "figs.", "vol.", "rs.", "u.s.", "u.k.", "dr.", "mr.", "mrs.",
    "ms.", "jr.", "sr.", "st.", "inc.", "co.", "corp.", "ltd.", "est.", "min.", "max.", "hr.",
    "hrs.", "mo.", "mos.", "yr.", "yrs.", "wk.", "wks.", "wt.", "oz.", "lb.", "lbs.",
]
# fmt: on
DOT = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(a) for a in sorted(ABBREVIATIONS, key=len, reverse=True))
    + r")(?=\s)",
    re.I,
)
LABELS = {"e": "end", "c": "goes on"}


# the running head of a Federal Register page, "Federal Register / Vol. 90, No. 123", which may
# be split over lines by the extraction
RUNNING_HEAD = re.compile(r"Federal\s+Register\s*/?\s*Vol\.\s*\d+\s*,\s*No\.\s*\d+", re.I)


def dots_in(text: str) -> list[re.Match[str]]:
    """The listed-abbreviation dots in ``text``, except those inside a Federal Register running
    head, which repeats on every page."""
    heads = [(h.start(), h.end()) for h in RUNNING_HEAD.finditer(text)]
    return [m for m in DOT.finditer(text) if not any(a <= m.start() < b for a, b in heads)]


def excluded() -> tuple[set[str], set[str], set[str]]:
    """Drugs, IRS publication ids and Federal Register ids used by v0.1, set 2 or the pattern
    set."""
    drugs, pubs, frs = pairs.excluded()
    used = json.loads((HERE.parent / "patterns" / "sources.json").read_text())["sources"]
    ids = {s["id"] for s in used}
    drugs |= {i.removeprefix("fda-") for i in ids if i.startswith("fda-")}
    return (
        drugs,
        pubs | {i for i in ids if i.startswith("irs-")},
        frs | {i for i in ids if i.startswith("fr-")},
    )


def pick(count_only: bool) -> None:
    walk.CACHE = HERE / ".cache"
    # set 2 took 2026, the pattern set 2025-07-01 to 2025-12-31
    walk.FR_FROM, walk.FR_TO = "2025-01-01", "2025-06-30"
    walk.CACHE.mkdir(parents=True, exist_ok=True)
    drugs, pubs, frs = excluded()
    log: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    limits = {"find": dots_in, "per_kind": PER_KIND, "per_doc": PER_DOC, "group": "dots"}
    sources = pairs.pick_fda(log, drugs, max_rank=FDA_MAX_RANK, **limits)
    irs = [(f"irs-p{n.lower()}", u) for n, u in walk.irs_publications()]
    irs = [(i, u) for i, u in irs if i not in pubs]
    sources += pairs.pick_pdfs("irs", irs, log, seen, **limits)
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
    for kind in ("fda", "irs", "fr"):
        print(f"{kind}: {docs[kind]} documents, {found[kind]} dots")
    print("skipped:")
    for why, c in sorted(skips.items()):
        print(f"  {why}: {c}")
    if count_only:
        return
    lock = {"retrieved": datetime.date.today().isoformat(), "sources": sources}
    (HERE / "sources.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    (HERE / "selection-log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print("wrote bench/dots/sources.json and selection-log.json")


def find_items() -> None:
    """items.json: the first PER_DOC dots of each document, as the code point offset of the
    abbreviation and of its dot in docs/<id>.txt."""
    out = []
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        text = (HERE / "docs" / f"{src['id']}.txt").read_text(encoding="utf-8")
        for m in dots_in(text)[:PER_DOC]:
            out.append(
                {
                    "id": f"{src['id']}:{m.end() - 1}",
                    "doc": src["id"],
                    "kind": src["kind"],
                    "abbreviation": [m.start(), m.end()],
                }
            )
    (HERE / "items.json").write_text(json.dumps(out, indent=1) + "\n")
    kinds: dict[str, int] = defaultdict(int)
    for it in out:
        kinds[it["kind"]] += 1
    print(f"wrote items.json: {len(out)} dots", dict(kinds))


def context(text: str, it: dict[str, Any], bold: str = "\033[1;7m{}\033[0m") -> str:
    """The abbreviation with up to 250 code points on each side, the abbreviation marked."""
    a0, a1 = it["abbreviation"]
    a, b = max(0, a0 - 250), min(len(text), a1 + 250)
    return " ".join((text[a:a0] + bold.format(text[a0:a1]) + text[a1:b]).split())


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
        print(context(texts[it["doc"]], it))
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
    print(f"\n{done} of {len(items)} labeled, saved in bench/dots/labels.json")


def reading(text: str, dot: int) -> str:
    """Spec 0.3 (the core in this repository): "end" if a sentence of the qualifier window
    starts after the dot."""
    from groundgate.text import sentence

    gap = re.match(r"\s*", text[dot + 1 :])
    assert gap is not None
    nxt = dot + 1 + gap.end()
    if nxt >= len(text):
        return "end"
    return "end" if sentence(text, nxt, qualifiers=True)[0] > dot else "goes on"


def score(check: bool) -> None:
    items = json.loads((HERE / "items.json").read_text())
    labels = json.loads((HERE / "labels.json").read_text())
    missing = [it["id"] for it in items if it["id"] not in labels]
    if missing:
        raise SystemExit(f"{len(missing)} of {len(items)} dots have no label; run dots.py label")
    texts = {
        it["doc"]: (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8") for it in items
    }
    rows = []
    for it in items:
        dot = it["abbreviation"][1] - 1
        rows.append(
            {
                **it,
                "label": labels[it["id"]],
                "spec_0.2": "end",  # 0.2 ends a sentence at every "." followed by whitespace
                "spec_0.3": reading(texts[it["doc"]], dot),
            }
        )
    keys = [f"{lab} read as {r}" for lab in LABELS.values() for r in LABELS.values()]

    def tally(rs: list[dict[str, Any]], spec: str) -> dict[str, int]:
        return {k: sum(f"{r['label']} read as {r[spec]}" == k for r in rs) for k in keys}

    specs = ("spec_0.2", "spec_0.3")
    results = {
        "dots": len(rows),
        "dots_by_kind": {k: sum(r["kind"] == k for r in rows) for k in ("fda", "irs", "fr")},
        "documents_by_kind": {
            k: len({r["doc"] for r in rows if r["kind"] == k}) for k in ("fda", "irs", "fr")
        },
        "labels": {lab: sum(r["label"] == lab for r in rows) for lab in LABELS.values()},
        "by_spec": {s: tally(rows, s) for s in specs},
        "by_kind": {
            k: {s: tally([r for r in rows if r["kind"] == k], s) for s in specs}
            for k in ("fda", "irs", "fr")
        },
        "dots_read": [{k: r[k] for k in ("id", "label", *specs)} for r in rows],
    }
    what = {
        "end read as end": "right",
        "end read as goes on": "two sentences joined: a qualifier can reach the wrong value",
        "goes on read as end": "a sentence cut: a qualifier before the dot is lost",
        "goes on read as goes on": "right",
    }
    md = [
        "# Dots set: the abbreviation sentence-end rule",
        "",
        "Generated by `bench/dots/dots.py score` from `items.json` and `labels.json`. "
        "[README.md](README.md) explains the set. Spec 0.2 ends a sentence at every `.` followed "
        "by whitespace. Spec 0.3 is the core in this repository.",
        "",
        f"{len(rows)} dots in {sum(results['documents_by_kind'].values())} documents: "
        + ", ".join(
            f"{name} {results['dots_by_kind'][k]} ({results['documents_by_kind'][k]} documents)"
            for k, name in (("fda", "FDA"), ("irs", "IRS"), ("fr", "Federal Register"))
        )
        + f". Labeled by a person: {results['labels']['end']} sentence ends, "
        f"{results['labels']['goes on']} where the sentence goes on.",
        "",
        "| Label and reading | What it means | Spec 0.2 | Spec 0.3 |",
        "|---|---|---:|---:|",
    ]
    for k in keys:
        a, b = results["by_spec"]["spec_0.2"][k], results["by_spec"]["spec_0.3"][k]
        md.append(f"| {k} | {what[k]} | {a} | {b} |")
    md += ["", "## By kind", "", "| Kind | Label and reading | Spec 0.2 | Spec 0.3 |"]
    md += ["|---|---|---:|---:|"]
    for kind, by in results["by_kind"].items():
        for k in keys:
            a, b = by["spec_0.2"][k], by["spec_0.3"][k]
            if a or b:
                md.append(f"| {kind} | {k} | {a} | {b} |")
    wrong = [r for r in rows if r["label"] != r["spec_0.3"]]
    md += ["", f"## Spec 0.3 reads against the label ({len(wrong)})", ""]
    if not wrong:
        md.append("None.")
    else:
        md += ["| Dot | Label | 0.3 | Text |", "|---|---|---|---|"]
        for r in wrong:
            text = context(texts[r["doc"]], r, "**{}**").replace("|", "\\|")
            md.append(f"| `{r['id']}` | {r['label']} | {r['spec_0.3']} | {text} |")
    out = {
        HERE / "results.json": json.dumps(results, indent=1) + "\n",
        HERE / "RESULTS.md": "\n".join(md) + "\n",
    }
    if check:
        stale = [p.name for p, body in out.items() if not p.exists() or p.read_text() != body]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run dots.py score")
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
