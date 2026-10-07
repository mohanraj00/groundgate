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
so CI rescores results without the 10-K text, which stays out of git. It also holds the position
of each labeled amount: the start of the first number token in its span, the way a decision
places a value.

Labeling stays blind. A value that spec 0.5 admits by a cited span and that has no label yet shows
no key in results.json or RESULTS.md, only "hidden until labeled". Label it with web.py.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

import groundgate as gg
from groundgate.adapters.langextract import to_candidates
from groundgate.canonical import Offsets
from groundgate.text import Token, scaled_value, tokens

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


def _holds(text: str, t: Token, want: Decimal) -> bool:
    """The token holds the value as the core reads it (admit._value_at): as written, or times its
    scale word."""
    return t.value is not None and want in (t.value, scaled_value(text, t))


def _at(text: str, ev: list[int] | None, value: str | None) -> int | None:
    """The start of the first number token in the evidence that holds the value."""
    if ev is None or value is None:
        return None
    want = Decimal(value)
    for t in tokens(text, ev[0], ev[1]):
        if _holds(text, t, want):
            return t.start
    return None


def _items(name: str) -> tuple[list[dict[str, Any]], dict[str, list[str] | None], str]:
    """The labeled amounts of a set: the items, their labels, and the item's span field."""
    if name == "status":
        work, mark = STATUS, "span"
    else:
        work, mark = SEC / "work-key", "mark"
    items = json.loads((work / "items.json").read_text(encoding="utf-8"))
    labels = json.loads((work / "labels.json").read_text(encoding="utf-8"))
    return items, labels, mark


def _anchors(name: str, set_dir: Path) -> dict[str, int]:
    """Item id -> the start of the first number token in the item's span. A 10-K mark can start
    at "$" ("$35.1 million"); the decisions place a value at its token, so both sides do."""
    items, _, mark = _items(name)
    texts: dict[str, str] = {}
    out = {}
    for it in items:
        doc = it["doc"]
        if doc not in texts:
            texts[doc] = (set_dir / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
        s, e = it[mark]
        starts = [t.start for t in tokens(texts[doc], s, e) if t.value is not None]
        if not starts:
            raise SystemExit(f"{name}: item {it['id']} has no number token in its {mark}")
        out[it["id"]] = starts[0]
    return out


def _cited(r: dict[str, Any]) -> bool:
    outcome, codes = r["0.5"]
    return bool(outcome == "admitted" and "KEY_CITED" in codes)


def decide(only: str | None) -> None:
    path = HERE / "decisions.json"
    old: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    # a set in an older layout (runs at the top, no population) is dropped, not mixed in
    out = {k: v for k, v in old.items() if isinstance(v, dict) and "runs" in v}
    for name, set_dir in (("status", STATUS), ("sec", SEC)):
        if only and name != only:
            continue
        schema = _schema(name)
        sources = json.loads((set_dir / "sources.json").read_text(encoding="utf-8"))["sources"]
        want = {s["id"] for s in sources}
        runs: dict[str, list[dict[str, Any]]] = {}
        for run, rel in RUNS.items():
            run_dir = set_dir / "runs" / rel
            paths = sorted(run_dir.glob("*.json"))
            missing = want - {p.stem for p in paths}
            if missing:
                raise SystemExit(
                    f"{run_dir}: {len(missing)} of {len(want)} documents in sources.json have "
                    "no run file"
                )
            rows = []
            for run_file in paths:
                rec = json.loads(run_file.read_text(encoding="utf-8"))
                doc = rec["document"]["document_id"]
                if doc != run_file.stem or doc not in want:
                    raise SystemExit(f"{run_file}: document {doc} is not this file's source")
                text = (set_dir / "docs" / f"{doc}.txt").read_text(encoding="utf-8")
                rec["document"]["text"] = text
                cands = to_candidates(rec["document"])
                plain = [{k: v for k, v in c.items() if k != "key_evidence"} for c in cands]
                by_spec = {
                    "0.5": gg.admit(text, schema, cands).decisions,
                    "0.4": gg.admit(text, schema, plain).decisions,
                }
                offsets = Offsets(text)
                ids = {spec: {d.candidate_id: d for d in ds} for spec, ds in by_spec.items()}
                for c in cands:
                    d5, d4 = ids["0.5"][c["id"]], ids["0.4"][c["id"]]
                    if d5.outcome == "rejected":
                        continue
                    ev = _char(offsets, d5.evidence)
                    row = {
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
                    if _cited(row) and row["at"] is None:
                        raise SystemExit(
                            f"{run_file}: candidate {c['id']} is admitted with KEY_CITED, but no "
                            f"number token in its evidence holds {d5.value}"
                        )
                    rows.append(row)
            runs[run] = rows
        out[name] = {"population": _anchors(name, set_dir), "runs": runs}
    out = {name: out[name] for name in ("status", "sec") if name in out}
    path.write_text(_dump(out), encoding="utf-8")
    print("wrote decisions.json")


Label = list[str] | None  # None is "not sure"


def _population(name: str, decisions: dict[str, Any]) -> dict[tuple[str, int], Label]:
    """(doc, value token start) -> the labeled keys, for every labeled amount. None is "not sure":
    such an amount counts as labeled, but no score counts it."""
    items, labels, _ = _items(name)
    anchors = decisions[name]["population"]
    doc_of = {it["id"]: it["doc"] for it in items}
    out: dict[tuple[str, int], Label] = {}
    for i, keys in labels.items():
        if i not in anchors:
            raise SystemExit(f"{name}: item {i} has no position; run keyspan.py decide")
        where = (doc_of[i], anchors[i])
        if where in out and out[where] != keys:
            raise SystemExit(f"{name}: two labels for the amount at {where[0]}:{where[1]}")
        out[where] = keys
    return out


def _extra_labels() -> dict[str, Any]:
    path = HERE / "labels.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def cited(decisions: dict[str, Any]) -> list[dict[str, Any]]:
    """Every candidate that spec 0.5 admits with KEY_CITED, once per set, doc, value and key."""
    seen, out = set(), []
    for name, s in decisions.items():
        for run, rows in s["runs"].items():
            for r in rows:
                if not _cited(r):
                    continue
                if r["at"] is None:
                    raise SystemExit(
                        f"{name} {run}: {r['doc']} candidate {r['id']} is cited, but has no "
                        "value position; run keyspan.py decide"
                    )
                k = (name, r["doc"], r["at"], r["key"])
                if k not in seen:
                    seen.add(k)
                    out.append({"set": name, "run": run, **r})
    return out


def label_id(name: str, doc: str, at: int | None) -> str:
    return f"{name}:{doc}:{at}"


def labeled_ids(name: str, decisions: dict[str, Any]) -> dict[str, Label]:
    """Label id -> label, from the set's own labels and then bench/keyspan/labels.json."""
    pop = {label_id(name, d, a): keys for (d, a), keys in _population(name, decisions).items()}
    extra = {k: v for k, v in _extra_labels().items() if k.startswith(f"{name}:")}
    return {**extra, **pop}


def _verdict(key: str, keys: Label) -> str:
    if keys is None:
        return "not sure"
    return "right" if key in keys else "escape"


ORDER = [
    "every right key admitted",
    "no key, none admitted",
    "a wrong key admitted",
    "a right key in review",
    "a right key neither admitted nor in review",
]
HIDDEN = "hidden until labeled"
SHIP_RUN = "key span"


def _amount(right: set[str], admitted: set[str], review: set[str]) -> str:
    if admitted - right:
        return "a wrong key admitted"
    if not right:
        return "no key, none admitted"
    if right <= admitted:
        return "every right key admitted"
    if (right - admitted) & review:
        return "a right key in review"
    return "a right key neither admitted nor in review"


def score(decisions: dict[str, Any]) -> dict[str, Any]:
    res: dict[str, Any] = {"sets": {}, "cited": []}
    for name in ("status", "sec"):
        if name not in decisions:
            continue
        runs = decisions[name]["runs"]
        pop = _population(name, decisions)
        scored = {w: set(k) for w, k in pop.items() if k is not None}
        out: dict[str, Any] = {
            "labeled_amounts": len(scored),
            "not_sure_amounts": len(pop) - len(scored),
            "runs": {},
        }
        for run, rows in runs.items():
            at: dict[tuple[str, int], list[dict[str, Any]]] = {}
            for r in rows:
                if r["at"] is not None and (r["doc"], r["at"]) in scored:
                    at.setdefault((r["doc"], r["at"]), []).append(r)
            by_spec = {}
            for spec in SPECS:
                facts: Counter[str] = Counter()
                amounts: Counter[str] = Counter()
                for where, right in scored.items():
                    rs = at.get(where, [])
                    admitted = {r["key"] for r in rs if r[spec][0] == "admitted"}
                    review = {r["key"] for r in rs if r[spec][0] == "needs_verification"}
                    facts["right keys admitted"] += len(admitted & right)
                    facts["wrong keys admitted"] += len(admitted - right)
                    amounts[_amount(right, admitted, review)] += 1
                by_spec[spec] = {
                    "facts": dict(sorted(facts.items())),
                    "amounts": {o: amounts[o] for o in ORDER},
                }
            out["runs"][run] = by_spec
        known = labeled_ids(name, decisions)
        hidden: set[str] = set()
        for c in cited({name: decisions[name]}):
            lid = label_id(name, c["doc"], c["at"])
            row = {"set": name, "doc": c["doc"], "at": c["at"], "field": c["field"]}
            if lid not in known:  # blind: no key until a person labels the amount
                if lid not in hidden:
                    hidden.add(lid)
                    res["cited"].append(
                        {
                            **row,
                            "key": HIDDEN,
                            "value": c["value"],
                            "label": "unlabeled",
                            "verdict": "unlabeled",
                        }
                    )
                continue
            label = known[lid]
            res["cited"].append(
                {
                    **row,
                    "key": c["key"],
                    "value": c["value"],
                    "label": label,
                    "verdict": _verdict(c["key"], label),
                }
            )
        if SHIP_RUN in runs:
            outside: dict[tuple[str, int, str], str] = {}
            for r in runs[SHIP_RUN]:
                if _cited(r) and (r["doc"], r["at"]) not in scored:
                    lid = label_id(name, r["doc"], r["at"])
                    v = _verdict(r["key"], known[lid]) if lid in known else "unlabeled"
                    outside[(r["doc"], r["at"], r["key"])] = v
            n = Counter(outside.values())
            facts4 = out["runs"][SHIP_RUN]["0.4"]["facts"]
            facts5 = out["runs"][SHIP_RUN]["0.5"]["facts"]
            inside = facts5.get("wrong keys admitted", 0)
            out["escapes for the ship rule"] = {
                "run": SHIP_RUN,
                "0.4": facts4.get("wrong keys admitted", 0),
                "0.5": inside + n["escape"],
                "0.5 wrong keys admitted in the population": inside,
                "0.5 cited escapes outside the population": n["escape"],
                "0.5 cited outside the population, unlabeled amounts": len(
                    {(d, a) for (d, a, _), v in outside.items() if v == "unlabeled"}
                ),
            }
        res["sets"][name] = out
    res["cited_verdicts"] = dict(sorted(Counter(c["verdict"] for c in res["cited"]).items()))
    return res


NAMES = {"status": "Status set (IRS filing status)", "sec": "10-K fiscal years"}
BIAS = (
    "The 10-K population is biased. Its items come from the review queue of the #120 plain "
    "run, so on the plain run spec 0.4 admits 0 right keys here by construction. Compare the two "
    "specs on the key-span run, not the two runs."
)


def _label_text(label: Any) -> str:
    if label == "unlabeled":
        return "unlabeled"
    if label is None:
        return "not sure"
    return "; ".join(label) or "none"


def render(res: dict[str, Any]) -> str:
    md = [
        "# Keyed claims: results",
        "",
        "Generated by `bench/keyspan/keyspan.py results` from `decisions.json` and the labels. "
        "[README.md](README.md) explains the measure. Claude Haiku 4.5, buffer 4000. Spec 0.4 is "
        "the same candidates without `key_evidence`.",
        "",
    ]
    for name in ("status", "sec"):
        md += [f"## {NAMES[name]}", ""]
        s = res["sets"].get(name)
        if s is None:
            md += [f"No decisions yet. Run `keyspan.py decide --set {name}`.", ""]
            continue
        if name == "sec":
            md += [BIAS, ""]
        md += [
            f"Labeled amounts: {s['labeled_amounts']}. Labeled not sure, and not scored: "
            f"{s['not_sure_amounts']}.",
            "",
        ]
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
        ship = s.get("escapes for the ship rule")
        if ship:
            inside = ship["0.5 wrong keys admitted in the population"]
            line = (
                f"Escapes for the ship rule, {ship['run']} run: {ship['0.4']} under spec 0.4 and "
                f"{ship['0.5']} under spec 0.5 ({inside} in the population, "
                f"{ship['0.5 cited escapes outside the population']} cited outside it)."
            )
            u = ship["0.5 cited outside the population, unlabeled amounts"]
            if u:
                line += (
                    " 1 cited amount outside the population has no label yet."
                    if u == 1
                    else f" {u} cited amounts outside the population have no label yet."
                )
            md += [line, ""]
    md += [
        "## Every key admitted by a cited span",
        "",
        "Each candidate that spec 0.5 admits with `KEY_CITED`, once per amount and key, in "
        f'either run. A wrong one is an escape. An amount with no label yet shows "{HIDDEN}" '
        "for its key, so that the label page stays blind.",
        "",
        "| Set | Amount | Field | Key | Label | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for c in res["cited"]:
        md.append(
            f"| {c['set']} | `{c['doc']}:{c['at']}` | {c['field']} | {c['key']} | "
            f"{_label_text(c['label'])} | {c['verdict']} |"
        )
    return "\n".join(md) + "\n"


def results(check: bool) -> None:
    path = HERE / "decisions.json"
    if not path.exists():
        raise SystemExit("no decisions.json; run keyspan.py decide")
    res = score(json.loads(path.read_text(encoding="utf-8")))
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
    d = sub.add_parser("decide")
    d.add_argument("--set", choices=["status", "sec"], help="only this set")
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "gold":
        gold()
    elif args.cmd == "decide":
        decide(args.set)
    else:
        results(args.check)


if __name__ == "__main__":
    main()
