"""The pattern set for the change rule (#58): every "from X to Y" pair in documents that v0.1 and
set 2 did not use, labeled by a person as a change, a range or neither.

    uv run python bench/patterns/pairs.py pick --count     # how many pairs each kind finds
    uv run python bench/patterns/pairs.py pick             # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/patterns      # download, verify, write docs/
    uv run python bench/patterns/pairs.py pairs            # write pairs.json from docs/
    uv run python bench/patterns/pairs.py label            # label them in the terminal

The pick looks only at titles, section codes, page counts and pair counts, and prints no text.
The label tool shows each pair in its sentence and never shows how a spec reads it.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
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


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report pair counts; write nothing")
    sub.add_parser("pairs")
    sub.add_parser("label")
    args = ap.parse_args()
    if args.cmd == "pick":
        pick(args.count)
    elif args.cmd == "pairs":
        find_pairs()
    else:
        label()


if __name__ == "__main__":
    main()
