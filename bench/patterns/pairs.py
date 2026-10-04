"""The pattern set for the change rule (#58): every "from X to Y" pair in documents that v0.1 and
set 2 did not use, labeled by a person as a change, a range or neither.

    uv run python bench/patterns/pairs.py pick --count     # how many pairs each kind finds
    uv run python bench/patterns/pairs.py pick             # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/patterns      # download, verify, write docs/
    uv run python bench/patterns/pairs.py pairs            # write pairs.json from docs/
    uv run python bench/patterns/pairs.py label            # label them in the terminal
    uv run python bench/patterns/pairs.py score            # RESULTS.md: spec 0.2 and 0.3
    uv run python bench/patterns/pairs.py score --check    # fail if the committed files differ

The pick looks only at titles, section codes, page counts and pair counts, and prints no text.
The label tool shows each pair in its sentence and never shows how a spec reads it.
`score` reads each Y under spec 0.3 (the core in this repository) and under spec 0.2 (the
released 0.2.0 wheel, through `pairs.py read` in a second process), and compares both with the
labels.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

import pick as walk  # noqa: E402  (bench/pick.py: the set-2 walkers and their caches)
from fetch import spl_sections  # noqa: E402

PAIRS_PER_KIND, PAIRS_PER_DOC = 70, 5
# sections 1 and 2 of a label rarely hold a pair (5 pairs in the first 336 ranks), so the FDA
# walk stops at a rank instead of a pair count
FDA_MAX_RANK = 400
NUMBER = r"\d[\d,]*(?:\.\d+)?"
# SPEC §4.2: `from`, a number, at most one word of up to 12 characters, a range connector and a
# number, each number with up to 4 characters before it ("$", "US$")
PAIR = re.compile(
    rf"\bfrom\s+\S{{0,4}}?({NUMBER})(?:\s*[^\s\d]{{1,12}})?\s*"
    rf"(?:(?:to|through|thru)\b|-|\u2013)\s*\S{{0,4}}?({NUMBER})",
    re.I,
)
LABELS = {"c": "change", "r": "range", "o": "neither"}


def excluded() -> tuple[set[str], set[str], set[str]]:
    """Drugs, IRS publication ids and Federal Register ids used by v0.1 or set 2."""
    set2 = json.loads((HERE.parent / "set2" / "sources.json").read_text())["sources"]
    ids = {s["id"] for s in set2}
    drugs = set(walk.V01_DRUGS) | {i.removeprefix("fda-") for i in ids if i.startswith("fda-")}
    pubs = {f"irs-p{p.lower()}" for p in walk.V01_PUBS} | {i for i in ids if i.startswith("irs-")}
    return drugs, pubs, {i for i in ids if i.startswith("fr-")}


def pairs_in(text: str) -> list[re.Match[str]]:
    return list(PAIR.finditer(text))


def pick_fda(log: list[dict[str, Any]], drugs: set[str]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for rank, name in enumerate(walk.ranked_generics()[:FDA_MAX_RANK], 1):
        base = walk.base_word(name)
        entry: dict[str, Any] = {"kind": "fda", "rank": rank, "name": name}
        log.append(entry)
        if "/" in name:
            entry["skip"] = "combination"
        elif base in drugs:
            entry["skip"] = "used in v0.1 or set 2"
        elif base in seen:
            entry["skip"] = "same drug ranked higher"
        if "skip" in entry:
            continue
        seen.add(base)
        label, why = walk.find_label(name)
        if label is None:
            entry["skip"] = why
            continue
        data = walk.get(label["url"], f"spl-{label['setid']}.xml")
        found = len(pairs_in(spl_sections(data, [walk.INDICATIONS, walk.DOSAGE])))
        entry.update({"setid": label["setid"], "pairs": found})
        if not found:
            entry["skip"] = "no pair in sections 1 and 2"
            continue
        total += min(found, PAIRS_PER_DOC)
        print(f"fda: rank {rank}, {len(chosen) + 1} documents, {total} pairs", file=sys.stderr)
        chosen.append(
            {
                "id": f"fda-{base}",
                "kind": "fda",
                "groups": ["change"],
                "url": label["url"],
                "sha256": label["sha256"],
                "select": {"sections": [walk.INDICATIONS, walk.DOSAGE]},
                "source": f"{label['title']}; Part D 2024 claims rank {rank}",
            }
        )
    return chosen


def pick_pdfs(
    kind: str, docs: list[tuple[str, str]], log: list[dict[str, Any]], seen: dict[str, str]
) -> list[dict[str, Any]]:
    """Take documents (id, url) in order until the kind has PAIRS_PER_KIND pairs. A document
    gives the pages that hold its first PAIRS_PER_DOC pairs."""
    chosen: list[dict[str, Any]] = []
    total = 0
    for doc_id, url in docs:
        if total >= PAIRS_PER_KIND:
            break
        entry: dict[str, Any] = {"kind": kind, "id": doc_id}
        log.append(entry)
        try:
            pages, sha = walk.page_texts(doc_id, url)
        except Exception as e:  # an unreadable file is skipped, and the log says why
            entry["skip"] = f"unreadable: {type(e).__name__}"
            continue
        idx: list[int] = []
        found = 0
        for i, page in enumerate(pages):
            if found >= PAIRS_PER_DOC:
                break
            if n := len(pairs_in(page)):
                idx.append(i)
                found += n
        if not idx:
            entry["skip"] = "no pair"
            continue
        text_sha = hashlib.sha256("\f".join(pages[i] for i in idx).encode()).hexdigest()
        if text_sha in seen:  # Federal Register rules share printed pages
            entry["skip"] = f"same text as {seen[text_sha]}"
            continue
        seen[text_sha] = doc_id
        total += min(found, PAIRS_PER_DOC)
        print(f"{kind}: {len(chosen) + 1} documents, {total} pairs", file=sys.stderr)
        entry.update({"pages": [i + 1 for i in idx], "pairs": found})
        chosen.append(walk.source(doc_id, kind, url, sha, ["change"], [i + 1 for i in idx]))
    return chosen


def pick(count_only: bool) -> None:
    walk.CACHE = HERE / ".cache"
    # set 2 took Federal Register rules from 2026-01-01 to 2026-09-30; these come from before it
    walk.FR_FROM, walk.FR_TO = "2025-07-01", "2025-12-31"
    walk.CACHE.mkdir(parents=True, exist_ok=True)
    drugs, pubs, frs = excluded()
    log: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    irs = [(f"irs-p{n.lower()}", u) for n, u in walk.irs_publications()]
    sources = pick_fda(log, drugs)
    sources += pick_pdfs("irs", [(i, u) for i, u in irs if i not in pubs], log, seen)
    fr = [(i, u) for i, u in walk.federal_register_rules() if i not in frs]
    sources += pick_pdfs("fr", fr, log, seen)
    pairs: dict[str, int] = defaultdict(int)
    docs: dict[str, int] = defaultdict(int)
    for entry in log:
        if "skip" not in entry:
            pairs[entry["kind"]] += min(entry["pairs"], PAIRS_PER_DOC)
            docs[entry["kind"]] += 1
    for kind in ("fda", "irs", "fr"):
        print(f"{kind}: {docs[kind]} documents, {pairs[kind]} pairs")
    skips: dict[str, int] = defaultdict(int)
    for entry in log:
        if "skip" in entry:
            skips[f"{entry['kind']}: {entry['skip']}"] += 1
    print("skipped:")
    for why, c in sorted(skips.items()):
        print(f"  {why}: {c}")
    if count_only:
        return
    lock = {"retrieved": datetime.date.today().isoformat(), "sources": sources}
    (HERE / "sources.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    (HERE / "selection-log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print("wrote bench/patterns/sources.json and selection-log.json")


def find_pairs() -> None:
    """pairs.json: the first PAIRS_PER_DOC pairs of each document, as code point offsets of X
    and Y in docs/<id>.txt."""
    out = []
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        text = (HERE / "docs" / f"{src['id']}.txt").read_text(encoding="utf-8")
        for m in pairs_in(text)[:PAIRS_PER_DOC]:
            out.append(
                {
                    "id": f"{src['id']}:{m.start(1)}",
                    "doc": src["id"],
                    "kind": src["kind"],
                    "x": [m.start(1), m.end(1)],
                    "y": [m.start(2), m.end(2)],
                }
            )
    (HERE / "pairs.json").write_text(json.dumps(out, indent=1) + "\n")
    kinds = defaultdict(int)
    for p in out:
        kinds[p["kind"]] += 1
    print(f"wrote pairs.json: {len(out)} pairs", dict(kinds))


def context(text: str, p: dict[str, Any]) -> str:
    """The pair with up to 300 code points before it and 200 after, X and Y in bold."""
    (x0, x1), (y0, y1) = p["x"], p["y"]
    a, b = max(0, x0 - 300), min(len(text), y1 + 200)
    bold = "\033[1;7m{}\033[0m"
    parts = [
        text[a:x0],
        bold.format(text[x0:x1]),
        text[x1:y0],
        bold.format(text[y0:y1]),
        text[y1:b],
    ]
    return " ".join("".join(parts).split())


def label() -> None:
    pairs = json.loads((HERE / "pairs.json").read_text())
    path = HERE / "labels.json"
    labels: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
    texts: dict[str, str] = {}
    print("For each pair: is Y the new value that replaces X (a change), the end of a range,")
    print("or neither (a form number, a phone number)?\n")
    i = next((k for k, p in enumerate(pairs) if p["id"] not in labels), len(pairs))
    while i < len(pairs):
        p = pairs[i]
        if p["doc"] not in texts:
            texts[p["doc"]] = (HERE / "docs" / f"{p['doc']}.txt").read_text(encoding="utf-8")
        text = texts[p["doc"]]
        x, y = text[p["x"][0] : p["x"][1]], text[p["y"][0] : p["y"][1]]
        done = sum(q["id"] in labels for q in pairs)
        print(f"\n[{i + 1}/{len(pairs)}, {done} labeled] {p['doc']}")
        print(context(text, p))
        was = f" (now: {labels[p['id']]})" if p["id"] in labels else ""
        ans = input(f"X = {x}, Y = {y}{was}. c change, r range, o neither, b back, q quit: ")
        ans = ans.strip().lower()
        if ans == "q":
            break
        if ans == "b":
            i = max(0, i - 1)
            continue
        if ans not in LABELS:
            continue
        labels[p["id"]] = LABELS[ans]
        path.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
        i += 1
    done = sum(q["id"] in labels for q in pairs)
    print(f"\n{done} of {len(pairs)} labeled, saved in bench/patterns/labels.json")


# ------------------------------------------------------------------------------- scoring

SPEC02 = [
    *("uv", "run", "--isolated", "--no-project", "--quiet", "--python", "3.12"),
    *("--with", "groundgate[pdf]==0.2.0", "python", str(HERE / "pairs.py"), "read"),
]
READINGS = ("change", "range")


def read() -> dict[str, str]:
    """How the installed groundgate reads each Y: "range" if it is a range end, else "change"."""
    from groundgate.text import qualifiers, tokens

    out: dict[str, str] = {}
    texts: dict[str, tuple[str, list[Any]]] = {}
    for p in json.loads((HERE / "pairs.json").read_text()):
        if p["doc"] not in texts:
            text = (HERE / "docs" / f"{p['doc']}.txt").read_text(encoding="utf-8")
            texts[p["doc"]] = (text, tokens(text))
        text, toks = texts[p["doc"]]
        y = p["y"][0]
        tok = next(t for t in toks if t.start <= y < t.end)
        out[p["id"]] = "range" if "range" in qualifiers(text, tok) else "change"
    return out


def tally(pairs: list[dict[str, Any]], labels: dict[str, str], spec: str) -> dict[str, int]:
    counts = {f"{lab} read as {r}": 0 for lab in LABELS.values() for r in READINGS}
    for p in pairs:
        counts[f"{labels[p['id']]} read as {p[spec]}"] += 1
    return counts


def snippet(text: str, p: dict[str, Any]) -> str:
    (x0, x1), (y0, y1) = p["x"], p["y"]
    a = text.rfind(". ", max(0, x0 - 160), x0)
    a = a + 2 if a >= 0 else max(0, x0 - 120)
    b = text.find(". ", y1, y1 + 120)
    b = b + 1 if b >= 0 else min(len(text), y1 + 80)
    parts = [text[a:x0], f"**{text[x0:x1]}**", text[x1:y0], f"**{text[y0:y1]}**", text[y1:b]]
    return " ".join("".join(parts).split()).replace("|", "\\|")


def score(check: bool) -> None:
    pairs = json.loads((HERE / "pairs.json").read_text())
    labels = json.loads((HERE / "labels.json").read_text())
    missing = [p["id"] for p in pairs if p["id"] not in labels]
    if missing:
        raise SystemExit(f"{len(missing)} of {len(pairs)} pairs have no label; run pairs.py label")
    run = subprocess.run(SPEC02, capture_output=True, text=True, check=True)
    v02, v03 = json.loads(run.stdout), read()
    for p in pairs:
        p.update({"label": labels[p["id"]], "spec_0.2": v02[p["id"]], "spec_0.3": v03[p["id"]]})
    kinds = ("fda", "irs", "fr")
    results: dict[str, Any] = {
        "pairs": len(pairs),
        "labels": {lab: sum(p["label"] == lab for p in pairs) for lab in LABELS.values()},
        "by_spec": {s: tally(pairs, labels, s) for s in ("spec_0.2", "spec_0.3")},
        "by_kind": {
            k: {
                s: tally([p for p in pairs if p["kind"] == k], labels, s)
                for s in ("spec_0.2", "spec_0.3")
            }
            for k in kinds
        },
        "pairs_read": [{k: p[k] for k in ("id", "label", "spec_0.2", "spec_0.3")} for p in pairs],
    }
    texts = {
        p["doc"]: (HERE / "docs" / f"{p['doc']}.txt").read_text(encoding="utf-8") for p in pairs
    }
    md = report(results, pairs, texts)
    out = {
        HERE / "results.json": json.dumps(results, indent=1) + "\n",
        HERE / "RESULTS.md": md,
    }
    if check:
        stale = [p.name for p, body in out.items() if not p.exists() or p.read_text() != body]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run pairs.py score")
        print("results are up to date")
        return
    for path, body in out.items():
        path.write_text(body)
    print("wrote results.json, RESULTS.md")


def report(res: dict[str, Any], pairs: list[dict[str, Any]], texts: dict[str, str]) -> str:
    lab = res["labels"]
    rows = [
        ("change read as change", "Y passes as a new value: right"),
        ("change read as range", "Y goes to review: more review"),
        ("range read as range", "Y goes to review: right"),
        ("range read as change", "Y passes without a range flag: a possible escape"),
        ("neither read as change", "neither: Y passes without a range flag"),
        ("neither read as range", "neither: Y goes to review"),
    ]
    md = [
        "# Pattern set: the change rule",
        "",
        "Generated by `bench/patterns/pairs.py score` from `pairs.json` and `labels.json`. "
        "[README.md](README.md) explains the set. Spec 0.2 is the released 0.2.0 wheel and spec "
        "0.3 is the core in this repository.",
        "",
        f"{res['pairs']} pairs, labeled by a person: {lab['change']} changes, {lab['range']} "
        f"ranges, {lab['neither']} neither.",
        "",
        "| Label and reading of Y | What happens | Spec 0.2 | Spec 0.3 |",
        "|---|---|---:|---:|",
    ]
    for key, what in rows:
        a, b = res["by_spec"]["spec_0.2"][key], res["by_spec"]["spec_0.3"][key]
        md.append(f"| {key} | {what} | {a} | {b} |")
    md += [
        "",
        "## By kind",
        "",
        "| Kind | Label and reading of Y | Spec 0.2 | Spec 0.3 |",
        "|---|---|---:|---:|",
    ]
    for kind, by in res["by_kind"].items():
        for key, _ in rows:
            a, b = by["spec_0.2"][key], by["spec_0.3"][key]
            if a or b:
                md.append(f"| {kind} | {key} | {a} | {b} |")
    sections = [
        ("Read differently by 0.2 and 0.3", lambda p: p["spec_0.2"] != p["spec_0.3"]),
        (
            "Spec 0.3 reads a range as a change",
            lambda p: p["label"] == "range" and p["spec_0.3"] == "change",
        ),
        (
            "Spec 0.3 reads a change as a range",
            lambda p: p["label"] == "change" and p["spec_0.3"] == "range",
        ),
    ]
    for title, keep in sections:
        chosen = [p for p in pairs if keep(p)]
        md += ["", f"## {title} ({len(chosen)})", ""]
        if not chosen:
            md.append("None.")
            continue
        md += ["| Pair | Label | 0.2 | 0.3 | Text |", "|---|---|---|---|---|"]
        for p in chosen:
            text = snippet(texts[p["doc"]], p)
            md.append(
                f"| `{p['id']}` | {p['label']} | {p['spec_0.2']} | {p['spec_0.3']} | {text} |"
            )
    return "\n".join(md) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report pair counts; write nothing")
    sub.add_parser("pairs")
    sub.add_parser("label")
    sub.add_parser("read", help="print how the installed groundgate reads each Y (JSON)")
    p = sub.add_parser("score")
    p.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = ap.parse_args()
    if args.cmd == "pick":
        pick(args.count)
    elif args.cmd == "pairs":
        find_pairs()
    elif args.cmd == "label":
        label()
    elif args.cmd == "read":
        print(json.dumps(read()))
    else:
        score(args.check)


if __name__ == "__main__":
    main()
