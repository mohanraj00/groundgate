"""The measure of keyed claims (#131): spec 0.5 lets a candidate cite the span that names its key
(#129), and the extractor gives it when the prompt asks (#130). Two sets that the rule was not
written from: the status set (IRS filing status, bench/status) and the 10-K key labels
(bench/sec/work-key). Each has a run of the plain keyed prompt and a run with --key-span.

    uv run python bench/keyspan/keyspan.py gold        # bench/status/gold/: the one keyed field
    uv run --group langextract python bench/propose.py --set bench/status --provider claude-cli \\
        --model claude-haiku-4-5-20251001 --label "Claude Haiku 4.5" --buffer 4000 [--key-span]
    uv run --group langextract python bench/propose.py --set bench/sec ... --key-span
    uv run python bench/keyspan/keyspan.py decide      # decisions.json, from the runs and docs
    uv run python bench/keyspan/keyspan.py results     # results.json, RESULTS.md
    uv run python bench/keyspan/keyspan.py results --check

The spec 0.4 decision is the 0.5 decision of the same candidate without key_evidence (SPEC §4.5,
vectors 19 and 19b). decisions.json holds offsets, keys, values and codes, and no document text,
so CI rescores results without the 10-K text, which stays out of git.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

import groundgate as gg
from groundgate.adapters.langextract import to_candidates
from groundgate.canonical import Offsets
from groundgate.text import tokens

HERE = Path(__file__).parent
BENCH = HERE.parent
STATUS, SEC = BENCH / "status", BENCH / "sec"
RUN = "Claude_Haiku_4.5"
RUNS = {"plain": f"{RUN}/4000", "key span": f"{RUN}_key_span/4000"}
SPECS = ("0.4", "0.5")
STATUS_KEYS = [
    "Single",
    "Married filing jointly",
    "Married filing separately",
    "Head of household",
    "Qualifying surviving spouse",
]
STATUS_FIELD = {
    "schema": {"type": "number", "unit": "USD", "multiple": True, "keys": STATUS_KEYS},
    "description": "A dollar amount that the text states for one or more filing statuses.",
}


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def gold() -> None:
    sources = json.loads((STATUS / "sources.json").read_text(encoding="utf-8"))["sources"]
    out = STATUS / "gold"
    out.mkdir(exist_ok=True)
    for s in sources:
        body = {"doc": s["id"], "kind": "irs", "fields": {"amount": STATUS_FIELD}}
        (out / f"{s['id']}.json").write_text(_dump(body), encoding="utf-8")
    print(f"wrote {len(sources)} gold files")


def _schema(name: str) -> dict[str, Any]:
    if name == "status":
        return {"fields": {"amount": STATUS_FIELD["schema"]}}
    return json.loads((SEC / "schema.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _char(offsets: Offsets, span: Any) -> list[int] | None:
    if span is None:
        return None
    s, e = offsets.to_char(span[0]), offsets.to_char(span[1])
    return None if s is None or e is None else [s, e]


def _at(text: str, ev: list[int] | None, value: str | None) -> int | None:
    """The start of the first number token in the evidence that equals the value."""
    if ev is None or value is None:
        return None
    want = Decimal(value)
    for t in tokens(text, ev[0], ev[1]):
        if t.value == want:
            return t.start
    return None


def decide() -> None:
    out: dict[str, Any] = {}
    for name, set_dir in (("status", STATUS), ("sec", SEC)):
        schema = _schema(name)
        out[name] = {}
        for run, rel in RUNS.items():
            rows = []
            paths = sorted((set_dir / "runs" / rel).glob("*.json"))
            if not paths:
                raise SystemExit(f"no run in {set_dir / 'runs' / rel}")
            for path in paths:
                rec = json.loads(path.read_text(encoding="utf-8"))
                doc = rec["document"]["document_id"]
                text = (set_dir / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
                rec["document"]["text"] = text
                cands = to_candidates(rec["document"])
                plain = [{k: v for k, v in c.items() if k != "key_evidence"} for c in cands]
                by_spec = {
                    "0.5": gg.admit(text, schema, cands).decisions,
                    "0.4": gg.admit(text, schema, plain).decisions,
                }
                offsets = Offsets(text)
                ids = {"0.4": {}, "0.5": {}}  # type: dict[str, dict[object, gg.Decision]]
                for spec, ds in by_spec.items():
                    ids[spec] = {d.candidate_id: d for d in ds}
                for c in cands:
                    d5, d4 = ids["0.5"][c["id"]], ids["0.4"][c["id"]]
                    if d5.outcome == "rejected":
                        continue
                    ev = _char(offsets, d5.evidence)
                    rows.append(
                        {
                            "doc": doc,
                            "id": c["id"],
                            "field": d5.field,
                            "key": d5.key,
                            "value": d5.value,
                            "at": _at(text, ev, d5.value),
                            "evidence": ev,
                            "key_evidence": _char(offsets, d5.key_evidence),
                            "0.5": [d5.outcome, list(d5.codes)],
                            "0.4": [d4.outcome, list(d4.codes)],
                        }
                    )
            out[name][run] = rows
    (HERE / "decisions.json").write_text(_dump(out), encoding="utf-8")
    print("wrote decisions.json")


def _population(name: str) -> dict[tuple[str, int], list[str]]:
    """(doc, value start) -> the labeled keys, for every amount with a key label."""
    if name == "status":
        items = json.loads((STATUS / "items.json").read_text(encoding="utf-8"))
        labels = json.loads((STATUS / "labels.json").read_text(encoding="utf-8"))
        where = {it["id"]: (it["doc"], it["span"][0]) for it in items}
    else:
        items = json.loads((SEC / "work-key" / "items.json").read_text(encoding="utf-8"))
        labels = json.loads((SEC / "work-key" / "labels.json").read_text(encoding="utf-8"))
        where = {it["id"]: (it["doc"], it["mark"][0]) for it in items}
    return {where[i]: keys for i, keys in labels.items() if keys is not None}


def _extra_labels() -> dict[str, Any]:
    path = HERE / "labels.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def cited(decisions: dict[str, Any]) -> list[dict[str, Any]]:
    """Every candidate that spec 0.5 admits with KEY_CITED, once per set, doc, value and key."""
    seen, out = set(), []
    for name, runs in decisions.items():
        for run, rows in runs.items():
            for r in rows:
                if r["0.5"] == ["admitted", ["KEY_CITED"]]:
                    k = (name, r["doc"], r["at"], r["key"])
                    if k not in seen:
                        seen.add(k)
                        out.append({"set": name, "run": run, **r})
    return out


def label_id(name: str, doc: str, at: int | None) -> str:
    return f"{name}:{doc}:{at}"


def score(decisions: dict[str, Any]) -> dict[str, Any]:
    extra = _extra_labels()
    res: dict[str, Any] = {"sets": {}, "cited": []}
    for name, runs in decisions.items():
        pop = _population(name)
        res["sets"][name] = {"labeled_amounts": len(pop), "runs": {}}
        for run, rows in runs.items():
            at: dict[tuple[str, int], list[dict[str, Any]]] = {}
            for r in rows:
                if r["at"] is not None and (r["doc"], r["at"]) in pop:
                    at.setdefault((r["doc"], r["at"]), []).append(r)
            by_spec = {}
            for spec in SPECS:
                facts: Counter[str] = Counter()
                amounts: Counter[str] = Counter()
                for where, right in pop.items():
                    rs = at.get(where, [])
                    admitted = {r["key"] for r in rs if r[spec][0] == "admitted"}
                    review = {r["key"] for r in rs if r[spec][0] == "needs_verification"}
                    facts["right keys admitted"] += len(admitted & set(right))
                    facts["wrong keys admitted"] += len(admitted - set(right))
                    if admitted - set(right):
                        amounts["a wrong key admitted"] += 1
                    elif set(right) <= admitted:
                        amounts["every right key admitted"] += 1
                    elif (set(right) - admitted) & review:
                        amounts["a right key in review"] += 1
                    else:
                        amounts["a right key not proposed"] += 1
                by_spec[spec] = {"facts": dict(sorted(facts.items())), "amounts": dict(amounts)}
            res["sets"][name]["runs"][run] = by_spec
        pop_ids = {label_id(name, d, a): keys for (d, a), keys in pop.items()}
        for c in cited({name: runs}):
            lid = label_id(name, c["doc"], c["at"])
            keys = pop_ids.get(lid, extra.get(lid, "unlabeled"))
            verdict = (
                "unlabeled"
                if keys == "unlabeled"
                else "not sure"
                if keys is None
                else "right"
                if c["key"] in keys
                else "escape"
            )
            res["cited"].append(
                {
                    "set": name,
                    "doc": c["doc"],
                    "at": c["at"],
                    "field": c["field"],
                    "key": c["key"],
                    "value": c["value"],
                    "label": keys,
                    "verdict": verdict,
                }
            )
    res["cited_verdicts"] = dict(Counter(c["verdict"] for c in res["cited"]))
    return res


ORDER = [
    "every right key admitted",
    "a wrong key admitted",
    "a right key in review",
    "a right key not proposed",
]
NAMES = {"status": "Status set (IRS filing status)", "sec": "10-K fiscal years"}


def render(res: dict[str, Any]) -> str:
    md = [
        "# Keyed claims: results",
        "",
        "Generated by `bench/keyspan/keyspan.py results` from `decisions.json` and the labels. "
        "[README.md](README.md) explains the measure. Claude Haiku 4.5, buffer 4000. Spec 0.4 is "
        "the same candidates without `key_evidence`.",
        "",
    ]
    for name, s in res["sets"].items():
        md += [f"## {NAMES[name]}", "", f"Labeled amounts: {s['labeled_amounts']}.", ""]
        md += ["| Run | Spec | Right keys admitted | Wrong keys admitted (escapes) | "
               + " | ".join(o.capitalize() for o in ORDER) + " |"]  # fmt: skip
        md += ["|---|---|---:|---:|" + "---:|" * len(ORDER)]
        for run, by_spec in s["runs"].items():
            for spec, r in by_spec.items():
                f, a = r["facts"], r["amounts"]
                cells = [str(a.get(o, 0)) for o in ORDER]
                md.append(
                    f"| {run} | {spec} | {f.get('right keys admitted', 0)} | "
                    f"{f.get('wrong keys admitted', 0)} | " + " | ".join(cells) + " |"
                )
        md.append("")
    md += [
        "## Every key admitted by a cited span",
        "",
        "Each candidate that spec 0.5 admits with `KEY_CITED`, once per amount and key, in "
        "either run. A wrong one is an escape.",
        "",
        "| Set | Amount | Field | Key | Label | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for c in res["cited"]:
        label = "not sure" if c["label"] is None else "; ".join(c["label"]) or "none"
        if c["label"] == "unlabeled":
            label = "unlabeled"
        md.append(
            f"| {c['set']} | `{c['doc']}:{c['at']}` | {c['field']} | {c['key']} | {label} | "
            f"{c['verdict']} |"
        )
    return "\n".join(md) + "\n"


def results(check: bool) -> None:
    decisions = json.loads((HERE / "decisions.json").read_text(encoding="utf-8"))
    res = score(decisions)
    files = {"results.json": _dump(res), "RESULTS.md": render(res)}
    if check:
        stale = [n for n, body in files.items() if (HERE / n).read_text(encoding="utf-8") != body]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run keyspan.py results")
        print("results are up to date")
        return
    for n, body in files.items():
        (HERE / n).write_text(body, encoding="utf-8")
    print("wrote results.json, RESULTS.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gold")
    sub.add_parser("decide")
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "gold":
        gold()
    elif args.cmd == "decide":
        decide()
    else:
        results(args.check)


if __name__ == "__main__":
    sys.exit(main())
