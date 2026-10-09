"""The outside-knowledge measure (#132). No spec change and no new model runs. How often does
groundgate reject a value that the document does not state, and how often is that value right?

    uv export --only-group langextract --no-emit-project --no-hashes -o /tmp/lx.txt
    uv run --isolated --no-project --no-sources --python 3.12 --with groundgate==0.4.0 \
        --with-requirements /tmp/lx.txt python bench/outside/outside.py items   # items.json
    uv run --isolated --no-project --no-sources --python 3.12 --with groundgate==0.6.1 \
        --with-requirements /tmp/lx.txt python bench/outside/outside.py still   # still.json
    uv run --group langextract python bench/outside/outside.py web     # label at 127.0.0.1:8768
    uv run python bench/outside/outside.py results [--check]           # results.json, RESULTS.md

An item is a rejected candidate of an existing run of set 2 (bench/set2/runs) or the 10-K set
(the #120 run in bench/sec/runs), for a field that the set's gold has, whose value is not in its
cited evidence (VALUE_NOT_IN_EVIDENCE, or NO_EVIDENCE when the extractor's quote was not found)
and not anywhere in the document: no number token of the document equals it, as written or
scaled. Candidates with the same document, field, key, value and unit are one item.

The 229 items were fixed on #132 with a groundgate before spec 0.5, and the 0.4.0 wheel gives the
same items. Spec 0.5 sends most 10-K values with a missing sign or scale to review, so still.json
lists the items that spec 0.6.1 still rejects. Those answer #125, and the page shows them.

A person labels each item: right (the value is true for the field and the document's subject,
with a public source), wrong, or not sure. The page never shows which model proposed it.
items.json holds no document text, as the 10-K text stays out of git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import groundgate as gg
from groundgate.text import normalize_ws, parse_value, scaled_value, tokens

HERE = Path(__file__).parent
BENCH = HERE.parent
SETS = {
    "set2": (BENCH / "set2", "*/*/*.json"),
    "sec": (BENCH / "sec", "Claude_Haiku_4.5/4000/*.json"),  # the #120 run only
}
CODES = ("VALUE_NOT_IN_EVIDENCE", "NO_EVIDENCE")
VERDICTS = ("right", "wrong", "not sure")
COLUMNS = (
    "right, from the outside",
    "right, from the document",
    "wrong",
    "not sure",
    "unlabeled",
)


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def in_document(text: str, ftype: str, value: str) -> bool:
    if ftype == "string":
        return normalize_ws(value).lower() in normalize_ws(text).lower()
    want = parse_value(value)
    if want is None:
        return True  # not a number: not an outside-knowledge value
    for t in tokens(text):
        if t.value is not None and want in (t.value, scaled_value(text, t)):
            return True
    return False


def item_id(it: dict[str, Any]) -> str:
    parts = [it["set"], it["doc"], it["field"], it["key"] or "", it["value"], it["unit"] or ""]
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]


def walk(every: bool = False) -> Iterator[tuple[dict[str, Any], dict[str, Any], gg.Decision, str]]:
    """Each rejected candidate that is an item: (item, candidate, decision, document text). With
    every, each candidate of a gold field, whatever its decision."""
    from groundgate.adapters.langextract import to_candidates

    for name, (set_dir, pattern) in SETS.items():
        golds = {p.stem: _read(p) for p in (set_dir / "gold").glob("*.json")}
        for path in sorted((set_dir / "runs").glob(pattern)):
            rec = _read(path)
            doc = rec["document"]["document_id"]
            if doc not in golds:
                continue
            gold = golds[doc]
            schema = {"fields": {f: s["schema"] for f, s in gold["fields"].items()}}
            text = (set_dir / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
            rec["document"]["text"] = text
            cands = to_candidates(rec["document"])
            for c, d in zip(cands, _decisions(text, schema, cands), strict=True):
                rejected = d.outcome == "rejected" and d.codes[0] in CODES
                if not (every or rejected) or d.field not in gold["fields"]:
                    continue
                ftype = schema["fields"][d.field].get("type", "number")
                value = d.value if d.value is not None else str(c.get("value"))
                if not every and in_document(text, ftype, value):
                    continue
                it = {
                    "set": name,
                    "kind": gold["kind"],
                    "doc": doc,
                    "field": d.field,
                    "key": d.key,
                    "value": value,
                    "unit": d.unit,
                    "code": d.codes[0] if d.codes else None,
                }
                # The extractor's quote, also for candidates that have no aligned evidence.
                quote = rec["document"]["extractions"][c["id"]].get("extraction_text")
                yield {"id": item_id(it), **it}, {**c, "extraction_text": quote}, d, text


def _need(version: str) -> None:
    if gg.__version__ != version:
        raise SystemExit(f"this step needs the groundgate {version} wheel, not {gg.__version__}")


def items() -> None:
    _need("0.4.0")
    found: dict[str, dict[str, Any]] = {}
    for it, _, _, _ in walk():
        found.setdefault(it["id"], {**it, "proposals": 0})["proposals"] += 1
    out = sorted(found.values(), key=lambda it: it["id"])
    (HERE / "items.json").write_text(_dump(out), encoding="utf-8")
    print(f"wrote {len(out)} items", dict(Counter(it["set"] for it in out)))


def still() -> None:
    """still.json: the items that spec 0.6.1 still rejects as an item."""
    _need("0.6.1")
    fixed = {it["id"] for it in _read(HERE / "items.json")}
    ids = sorted({it["id"] for it, _, _, _ in walk()} & fixed)
    (HERE / "still.json").write_text(_dump({"groundgate": gg.__version__, "ids": ids}))
    print(f"wrote still.json: {len(ids)} of {len(fixed)} items")


def still_ids() -> set[str]:
    return set(_read(HERE / "still.json")["ids"])


def _decisions(text: str, schema: dict[str, Any], cands: list[Any]) -> list[gg.Decision]:
    by_id = {d.candidate_id: d for d in gg.admit(text, schema, cands).decisions}
    return [by_id[c["id"]] for c in cands]


def labels() -> dict[str, Any]:
    path = HERE / "labels.json"
    return _read(path) if path.exists() else {}


def score() -> dict[str, Any]:
    its, labs, now = _read(HERE / "items.json"), labels(), still_ids()
    by: dict[str, dict[str, Counter[str]]] = {"still": {}, "all": {}}
    sources = []
    for it in its:
        lab = labs.get(it["id"])
        verdict = "unlabeled" if not lab else lab["verdict"]
        if verdict == "right":
            verdict = f"right, from the {'document' if lab['basis'] == 'document' else 'outside'}"
        for scope in ("still", "all") if it["id"] in now else ("all",):
            for group in (it["set"], f"{it['set']}/{it['kind']}"):
                by[scope].setdefault(group, Counter())[verdict] += 1
        if lab and lab["verdict"] == "right":
            sources.append({"id": it["id"], "doc": it["doc"], "field": it["field"],
                            "key": it["key"], "value": it["value"], "unit": it["unit"],
                            "basis": lab["basis"], "source": lab["source"],
                            "still": it["id"] in now})  # fmt: skip
    return {
        "items": len(its),
        "still": len(now),
        "by": {
            scope: {g: dict(sorted(c.items())) for g, c in sorted(groups.items())}
            for scope, groups in by.items()
        },
        "right": sources,
    }


def render(res: dict[str, Any]) -> str:
    md = [
        "# Outside knowledge: results",
        "",
        "Generated by `bench/outside/outside.py results` from `items.json` and `labels.json`. "
        "[README.md](README.md) explains the measure.",
        "",
        f"Items: {res['items']}, fixed with a groundgate before spec 0.5. Spec 0.6.1 still "
        f"rejects {res['still']} of them. These answer #125.",
    ]
    titles = {
        "still": f"## The {res['still']} items that spec 0.6.1 still rejects",
        "all": f"## All {res['items']} items",
    }
    for scope, title in titles.items():
        md += ["", title, "",
               "| Set / kind | Right, from outside | Right, from the document | Wrong | "
               "Not sure | Unlabeled |",
               "|---|---:|---:|---:|---:|---:|"]  # fmt: skip
        for g, c in res["by"][scope].items():
            cells = [c.get(v, 0) for v in COLUMNS]
            md.append(f"| {g} | " + " | ".join(str(x) for x in cells) + " |")
    md += ["", "## Each right value and its source", "",
           "| Document | Field | Key | Value | Basis | Source | Spec 0.6.1 rejects it |",
           "|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in res["right"]:
        unit = f" {r['unit']}" if r["unit"] else ""
        md.append(
            f"| `{r['doc']}` | {r['field']} | {r['key'] or ''} | {r['value']}{unit} | "
            f"{r['basis']} | {r['source']} | {'yes' if r['still'] else 'no'} |"
        )
    return "\n".join(md) + "\n"


def results(check: bool) -> None:
    res = score()
    files = {"results.json": _dump(res), "RESULTS.md": render(res)}
    if check:
        stale = [n for n, b in files.items() if (HERE / n).read_text(encoding="utf-8") != b]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run outside.py results")
        print("results are up to date")
        return
    for n, b in files.items():
        (HERE / n).write_text(b, encoding="utf-8")
    print("wrote results.json, RESULTS.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("items")
    sub.add_parser("still")
    w = sub.add_parser("web")
    w.add_argument("--port", type=int, default=8768)
    w.add_argument("--all", action="store_true", help="every item, not only those 0.6.1 rejects")
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "items":
        items()
    elif args.cmd == "still":
        still()
    elif args.cmd == "web":
        sys.path.insert(0, str(HERE))
        import web  # bench/outside/web.py

        web.serve(args.port, args.all)
    else:
        results(args.check)


if __name__ == "__main__":
    main()
