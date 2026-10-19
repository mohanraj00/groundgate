"""The changed-value test (#322): change approved values the way that real errors occur, and
count which check stops each changed value and how many get through.

    uv run python bench/changed/changed.py changes            # changes.json, the fixed list
    uv run python bench/changed/changed.py results            # results.json and RESULTS.md
    uv run python bench/changed/changed.py results --check    # fail if a file differs

No model runs. The source is the held-out set of agency financial reports (bench/afr): its values
that a person labeled right (bench/afr/labels.json), on the text with table rows (#230). Each
value starts from the first proposal of that value that the groundgate of this checkout admits.
That proposal is the base. The script changes the base in seven fixed ways (KINDS), with a fixed
seed for the one random choice, and decides each changed candidate in the packet of its document,
next to the other bases. It decides each packet twice: with the relation of the balance sheet
(spec 0.10, SPEC 3.4) and without it, so the counts show what the relation adds.

results reads only changes.json and the document texts, so a later spec that changes a decision
changes results.json, and results --check then fails until the results are written again.
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import math
import random
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
BENCH = HERE.parent
AFR = BENCH / "afr"
DOCS = AFR / "tabs" / "docs"
sys.path[:0] = [str(AFR), str(BENCH / "requested")]  # not packages
import measure  # noqa: E402  (bench/afr/measure.py)
import metrics  # noqa: E402  (bench/requested/metrics.py)
import tabs  # noqa: E402  (bench/afr/tabs.py)

SEED = "322"
KINDS = {
    "next row": "the number in the same column on the next row that holds a number",
    "next column": "the next number on the same row, or the one before it in the last column",
    "wrong scale": "the value times 1000, and the value divided by 1000",
    "sign": "the value with its sign changed: a negative value loses its sign, others get one",
    "digit swap": "two adjacent digits of the written number change places",
    "other field": "the value of each other field at the same year, at its own place",
    "rounded": "the written number rounded to 3 significant digits",
}
# The kinds that cite the place of the new value. The others keep the evidence of the base.
MOVES = ("next row", "next column", "other field")
RELATION = {
    "id": "balance",
    "total": "total_assets",
    "parts": [{"field": "total_liabilities"}, {"field": "total_net_position"}],
}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _text(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def schema(relation: bool) -> dict[str, Any]:
    """The schema of bench/afr with one value for each field and year, and with or without the
    relation. A relation needs fields with multiple false (SPEC 2.3). Each packet here has one
    candidate for each field and year, so this changes no other decision."""
    out = copy.deepcopy(_read(AFR / "schema.json"))
    for field in out["fields"].values():
        field["multiple"] = False
    if relation:
        out["relations"] = [RELATION]
    return out


# ------------------------------------------------------------------------------------- bases


def bases() -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """For each document, the base of each value that a person labeled right: the first
    proposal of the value, in the order of tabs.PAIRS on the text with table rows, that this
    groundgate admits. The value item is pinned at the place where groundgate found it."""
    import groundgate as gg

    labels = measure.labels()
    right = {fid for fid, label in labels.items() if label["verdict"] == "right"}
    found: dict[str, dict[str, Any]] = {}
    for run, read in tabs.PAIRS:
        if tabs._docs(read) != DOCS:
            continue
        replies = tabs._replies(run, read)
        for doc_path in sorted(DOCS.glob("*.txt")):
            doc = doc_path.stem
            reply = _read(replies / f"{doc}.json")["reply"]
            cands = [] if reply is None else reply["candidates"]
            cands = [{"id": f"c{i}", **c} for i, c in enumerate(cands)]
            text = doc_path.read_text(encoding="utf-8")
            by_sha = {d.candidate_sha256: d for d in gg.admit(text, schema(False), cands).decisions}
            for c in cands:
                d = by_sha[gg.digest("candidate", c)]
                if d.outcome != "admitted" or d.value is None or d.evidence is None:
                    continue
                fid = measure.item_id(doc, d.field or "", d.key, d.value)
                if fid in right and fid not in found:
                    found[fid] = {"doc": doc, "candidate": _pin(text, c, d.evidence)}
    per_doc: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for fid, got in sorted(found.items()):
        c = got["candidate"]
        slots = {(b["field"], b["key"]) for b in per_doc[got["doc"]]}
        if (c["field"], c["key"]) in slots:  # two right values for one field and year
            continue
        per_doc[got["doc"]].append({"fact": fid, **c})
    for doc in per_doc:
        per_doc[doc].sort(key=lambda b: (b["field"], b["key"]))
    counts = {"right labels": len(right), "bases": sum(len(v) for v in per_doc.values())}
    return dict(sorted(per_doc.items())), counts


def _pin(text: str, cand: dict[str, Any], span: tuple[int, int]) -> dict[str, Any]:
    """The candidate with its value item at ``span`` and every other item as proposed."""
    raw = text.encode("utf-8")
    start, end = span
    out = {k: v for k, v in cand.items() if k not in ("id", "evidence", "confidence")}
    items = [i for i in cand["evidence"] if i.get("role", "value") != "value"]
    value = {"start": start, "end": end, "text": raw[start:end].decode("utf-8")}
    out["evidence"] = [value, *items]
    return out


# ------------------------------------------------------------------------------------ changes


def _token(text: str, start: int, end: int, value: Decimal) -> Any:
    """The number token in the code point span that gives ``value`` with a sign and a power of
    ten as its scale."""
    from groundgate.text import tokens

    for tok in tokens(text, start, end):
        if tok.value:
            ratio = abs(value) / abs(tok.value)
            if any(ratio == 10**p for p in (0, 3, 5, 6, 7, 9, 12)):
                return tok
    raise ValueError(f"no token for {value} in {text[start:end]!r}")


def _bracketed(text: str, start: int, end: int) -> bool:
    return bool(re.search(r"\(\s*\$?\s*$", text[:start])) and bool(re.match(r"\s*\)", text[end:]))


def _cells(text: str, line_start: int) -> list[Any]:
    """The number tokens of a line after its first tab: its number cells."""
    from groundgate.text import tokens

    line_end = text.find("\n", line_start)
    line_end = len(text) if line_end < 0 else line_end
    tab = text.find("\t", line_start, line_end)
    if tab < 0:
        return []
    return [t for t in tokens(text, tab, line_end) if t.value is not None]


def _value(written: Decimal, factor: Decimal, negative: bool) -> str:
    from groundgate.text import canonical

    out = abs(written) * abs(factor)
    return canonical(-out if negative else out)


def _moved(text: str, base: dict[str, Any], tok: Any, factor: Decimal) -> dict[str, Any]:
    """The base with the value of ``tok``, cited at its place."""
    out = copy.deepcopy(base)
    start = len(text[: tok.start].encode("utf-8"))
    end = len(text[: tok.end].encode("utf-8"))
    out["value"] = _value(tok.value, factor, _bracketed(text, tok.start, tok.end))
    out["evidence"][0] = {"start": start, "end": end, "text": text[tok.start : tok.end]}
    return out


def _valued(base: dict[str, Any], value: str) -> dict[str, Any]:
    out = copy.deepcopy(base)
    out["value"] = value
    return out


def changes_of(text: str, base: dict[str, Any], others: list[dict[str, Any]]) -> list[Any]:
    """Each change of ``base`` as (kind, detail, candidate), or (kind, reason, None) when the
    kind does not apply to it."""
    from groundgate.text import canonical

    raw = text.encode("utf-8")
    item = base["evidence"][0]
    start = len(raw[: item["start"]].decode("utf-8"))
    end = len(raw[: item["end"]].decode("utf-8"))
    value = Decimal(base["value"])
    tok = _token(text, start, end, value)
    factor = value / tok.value
    negative = value < 0
    out: list[Any] = []

    line_start = text.rfind("\n", 0, start) + 1
    cells = _cells(text, line_start)
    index = next((i for i, c in enumerate(cells) if c.start == tok.start), None)
    below, after = None, text.find("\n", start)
    while after >= 0 and below is None:
        row = _cells(text, after + 1)
        if row:
            below = row[min(index or 0, len(row) - 1)]
        after = text.find("\n", after + 1)
    if index is None or below is None:
        out.append(("next row", "no number cell below", None))
    else:
        out.append(("next row", text[below.start : below.end], _moved(text, base, below, factor)))
    if index is None or len(cells) < 2:
        out.append(("next column", "one number cell on the row", None))
    else:
        side = cells[index + 1] if index + 1 < len(cells) else cells[index - 1]
        out.append(("next column", text[side.start : side.end], _moved(text, base, side, factor)))

    out.append(("wrong scale", "x1000", _valued(base, canonical(value * 1000))))
    out.append(("wrong scale", "/1000", _valued(base, canonical(value / 1000))))
    out.append(("sign", "dropped" if negative else "added", _valued(base, canonical(-value))))

    digits = text[tok.start : tok.end]
    pairs = [
        i
        for i in range(len(digits) - 1)
        if digits[i].isdigit() and digits[i + 1].isdigit() and digits[i] != digits[i + 1]
    ]
    if not pairs:
        out.append(("digit swap", "no two adjacent digits differ", None))
    else:
        i = random.Random(f"{SEED}:{base['fact']}").choice(pairs)
        swapped = digits[:i] + digits[i + 1] + digits[i] + digits[i + 2 :]
        written = Decimal(swapped.replace(",", ""))
        out.append(
            (
                "digit swap",
                f"{digits} as {swapped}",
                _valued(base, _value(written, factor, negative)),
            )
        )

    same_year = [o for o in others if o["key"] == base["key"] and o["field"] != base["field"]]
    if not same_year:
        out.append(("other field", "no other field at the year", None))
    for other in same_year:
        item = other["evidence"][0]
        s = len(raw[: item["start"]].decode("utf-8"))
        e = len(raw[: item["end"]].decode("utf-8"))
        moved = _moved(text, base, _token(text, s, e, Decimal(other["value"])), factor)
        moved["value"] = other["value"]  # its own sign and scale
        out.append(("other field", other["field"], moved))

    shown = abs(tok.value)
    if shown == 0:
        out.append(("rounded", "zero", None))
    else:
        place = Decimal(1).scaleb(shown.adjusted() - 2)
        rounded = (shown / place).quantize(Decimal(1), rounding=ROUND_HALF_UP) * place
        if rounded == shown:
            out.append(("rounded", "3 significant digits or fewer", None))
        else:
            out.append(
                (
                    "rounded",
                    f"{canonical(shown)} as {canonical(rounded)}",
                    _valued(base, _value(rounded, factor, negative)),
                )
            )
    return out


def changes() -> dict[str, Any]:
    """The fixed list: each document's bases, and each change of each base."""
    per_doc, counts = bases()
    docs: dict[str, Any] = {}
    skipped: collections.Counter[str] = collections.Counter()
    same: collections.Counter[str] = collections.Counter()
    for doc, found in per_doc.items():
        text = (DOCS / f"{doc}.txt").read_text(encoding="utf-8")
        rows = []
        for base in found:
            for kind, detail, cand in changes_of(text, base, found):
                if cand is None:
                    skipped[kind] += 1
                    continue
                if cand["value"] == base["value"]:  # it lands on the right value
                    same[kind] += 1
                    continue
                cand = {k: v for k, v in cand.items() if k != "fact"}
                rows.append(
                    {"fact": base["fact"], "kind": kind, "detail": detail, "candidate": cand}
                )
        docs[doc] = {"bases": found, "changes": rows}
    return {
        "source": "bench/afr, labels.json, text of bench/afr/tabs/docs",
        "seed": SEED,
        "kinds": KINDS,
        "relation": RELATION,
        "counts": counts
        | {"not applied": dict(sorted(skipped.items())), "same value": dict(sorted(same.items()))},
        "documents": docs,
    }


# ------------------------------------------------------------------------------------ results


def _decide(doc: str, cands: list[dict[str, Any]], relation: bool) -> Any:
    import groundgate as gg

    text = (DOCS / f"{doc}.txt").read_text(encoding="utf-8")
    return gg.admit(text, schema(relation), cands)


def _packet(found: dict[str, Any], change: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The bases of the document with ids, and the change in place of its base."""
    out = []
    for i, base in enumerate(found["bases"]):
        cand = {k: v for k, v in base.items() if k != "fact"}
        if change is not None and base["fact"] == change["fact"]:
            cand = copy.deepcopy(change["candidate"])
            out.append({"id": "changed", **cand})
        else:
            out.append({"id": f"b{i}", **cand})
    return out


def _stop(decision: Any) -> str:
    """What stopped a changed candidate: its rejection code, its flags, or "admitted"."""
    if decision.outcome == "admitted":
        return "admitted"
    if decision.outcome == "rejected":
        return decision.codes[0]
    flags = [c for c in decision.codes if c not in INFO]
    return " + ".join(flags)


INFO = ("EVIDENCE_REANCHORED", "VALUE_DERIVED", "KEY_CITED", "ADMITTED_BY_POLICY", "MODEL_CLEARED")


def bound(k: int, n: int, effect: int) -> dict[str, Any]:
    """k of n with one-sided 95% bounds that allow for clusters by document: the counts are
    divided by the design effect, the trials rounded down, and the count rounded toward the
    side of each bound (docs/design/extensions.md, section 10)."""
    trials = n // effect
    if trials == 0:
        return {"k": k, "n": n, "lower95": None, "upper95": None}
    up = min(trials, math.ceil(k / effect))
    down = min(trials, k // effect)
    low = metrics.upper95(trials - down, trials)
    return {
        "k": k,
        "n": n,
        "lower95": None if low is None else round(1 - low, 10),
        "upper95": metrics.upper95(up, trials),
    }


def results() -> dict[str, Any]:
    """Decide each change of changes.json, with and without the relation, and count."""
    fixed = _read(HERE / "changes.json")
    related = {RELATION["total"], *(p["field"] for p in RELATION["parts"])}
    controls = {"bases": 0, "admitted": 0, "admitted with the relation": 0}
    clean_relations = {"applied": 0, "holds": 0}
    rows: list[dict[str, Any]] = []
    for doc, found in fixed["documents"].items():
        clean = {rel: _decide(doc, _packet(found, None), rel) for rel in (False, True)}
        controls["bases"] += len(found["bases"])
        for rel, name in ((False, "admitted"), (True, "admitted with the relation")):
            controls[name] += sum(d.outcome == "admitted" for d in clean[rel].decisions)
        for r in clean[True].relations or ():
            clean_relations["applied"] += 1
            clean_relations["holds"] += r.holds
        for change in found["changes"]:
            got = {}
            for rel in (False, True):
                receipt = _decide(doc, _packet(found, change), rel)
                (d,) = [x for x in receipt.decisions if x.candidate_id == "changed"]
                got[rel] = (receipt, d)
            receipt, d = got[True]
            cand = change["candidate"]
            checked = (
                d.outcome != "rejected"
                and cand["field"] in related
                and any(r.key == cand["key"] for r in receipt.relations or ())
            )
            rows.append(
                {
                    "doc": doc,
                    "kind": change["kind"],
                    "detail": change["detail"],
                    "field": cand["field"],
                    "key": cand["key"],
                    "value": cand["value"],
                    "outcome": d.outcome,
                    "stop": _stop(d),
                    "without relation": _stop(got[False][1]),
                    "relation checked": checked,
                    "right values to review": sum(
                        "RELATION_FAILED" in x.codes
                        for x in receipt.decisions
                        if x.candidate_id != "changed"
                    ),
                }
            )
    kinds = {kind: _count([r for r in rows if r["kind"] == kind]) for kind in KINDS}
    return {
        "spec": _spec(),
        "source": fixed["source"],
        "seed": fixed["seed"],
        "counts": fixed["counts"],
        "controls": controls | {"relation on the clean packets": clean_relations},
        "kinds": {k: v for k, v in kinds.items() if v is not None},
        "all": _count(rows),
        "admitted changes": [
            {k: r[k] for k in ("doc", "kind", "detail", "field", "key", "value")}
            for r in rows
            if r["outcome"] == "admitted"
        ],
    }


def _count(mine: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The counts of one kind, each with its bounds."""
    if not mine:
        return None
    per_doc = collections.Counter(r["doc"] for r in mine)
    effect = max(per_doc.values())
    n = len(mine)
    codes = collections.Counter(
        code for r in mine if r["outcome"] != "admitted" for code in r["stop"].split(" + ")
    )
    first = collections.Counter(r["stop"] for r in mine if r["outcome"] == "rejected")
    escaped = [r for r in mine if r["outcome"] == "admitted"]
    alone = [r for r in mine if r["without relation"] == "admitted" and r["outcome"] != "admitted"]
    checked = [r for r in mine if r["relation checked"]]
    failed = [r for r in checked if "RELATION_FAILED" in r["stop"].split(" + ")]
    escape_docs = len({r["doc"] for r in escaped})
    return {
        "changed values": n,
        "documents": len(per_doc),
        "design effect": effect,
        "rejected": bound(sum(r["outcome"] == "rejected" for r in mine), n, effect),
        "sent to review": bound(sum(r["outcome"] == "needs_verification" for r in mine), n, effect),
        "admitted": bound(len(escaped), n, effect),
        "admitted without the relation": bound(
            sum(r["without relation"] == "admitted" for r in mine), n, effect
        ),
        "rejected by code": {c: bound(k, n, effect) for c, k in sorted(first.items())},
        "codes": {c: bound(k, n, effect) for c, k in sorted(codes.items())},
        "flags": dict(
            sorted(
                collections.Counter(
                    r["stop"] for r in mine if r["outcome"] == "needs_verification"
                ).items()
            )
        ),
        "relation": {
            "checked": len(checked),
            "failed": len(failed),
            "stopped alone": bound(len(alone), n, effect),
            "right values sent to review": sum(r["right values to review"] for r in mine),
        },
        "documents with an admitted change": {
            "k": escape_docs,
            "n": len(per_doc),
            "upper95": metrics.upper95(escape_docs, len(per_doc)),
        },
    }


def _spec() -> str:
    from groundgate.canonical import SPEC_VERSION

    return SPEC_VERSION


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def _cell(b: dict[str, Any]) -> str:
    return f"{b['k']} ({_pct(b['lower95'])} to {_pct(b['upper95'])})"


def _table(head: list[str], rows: list[list[Any]], text: int = 1) -> list[str]:
    """A table whose first ``text`` columns are text, and the rest numbers."""
    out = [
        "| " + " | ".join(head) + " |",
        "|" + "|".join(["---"] * text + ["---:"] * (len(head) - text)) + "|",
    ]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return [*out, ""]


def report(res: dict[str, Any]) -> str:
    """RESULTS.md from results.json."""
    kinds = res["kinds"]
    every = {**kinds, "all": res["all"]}
    counts, controls = res["counts"], res["controls"]
    clean = controls["relation on the clean packets"]
    lines = [
        "# The changed-value test (#322)",
        "",
        "Generated by `bench/changed/changed.py results` from `results.json`. Do not edit.",
        "",
        f"Spec {res['spec']}, decided in process. Source: the values that a person labeled right "
        f"in `bench/afr` ({counts['right labels']}), on the text with table rows. "
        f"{counts['bases']} of them have a base: a proposal of the value that this spec admits. "
        f"Seed `{res['seed']}`. [README.md](README.md) gives the method.",
        "",
        f"Controls: {controls['admitted']} of {controls['bases']} bases are admitted in their "
        f"packets without the relation, and {controls['admitted with the relation']} with it. On "
        f"the clean packets the relation applies at {clean['applied']} document years and holds "
        f"at {clean['holds']}.",
        "",
        "Each count has one-sided 95% bounds in brackets, lower to upper. They allow for "
        "clusters by document: the design effect is the largest number of changed values of "
        "one document.",
        "",
        "## Outcomes",
        "",
    ]
    rows = []
    for kind, k in every.items():
        d = k["documents with an admitted change"]
        rows.append(
            [
                kind,
                k["changed values"],
                k["documents"],
                k["design effect"],
                _cell(k["rejected"]),
                _cell(k["sent to review"]),
                _cell(k["admitted"]),
                f"{d['k']} of {d['n']} ({_pct(d['upper95'])})",
            ]
        )
    head = ["Change", "n", "Docs", "Effect", "Rejected", "Review", "Admitted", "Docs with an admit"]
    lines += _table(head, rows)
    lines += [
        "The last column is the number of documents with at least one admitted change, with "
        "its exact upper bound.",
        "",
        "## The check that stops each changed value",
        "",
        "A rejected value counts under its code. A value sent to review counts under each of its "
        "flags, so a row can sum to more than n.",
        "",
    ]
    codes = sorted({c for k in every.values() for c in k["codes"]})
    rows = [
        [
            kind,
            k["changed values"],
            *(_cell(k["codes"][c]) if c in k["codes"] else "0" for c in codes),
        ]
        for kind, k in every.items()
    ]
    lines += _table(["Change", "n", *(f"`{c}`" for c in codes)], rows)
    lines += [
        "## The relation",
        "",
        "The relation `balance` says that total assets equal total liabilities plus total net "
        "position, for each year. It checks a changed value only when the value passed, its "
        "field is in the relation, and the two other fields have a base at that year.",
        "",
    ]
    rows = []
    for kind, k in every.items():
        r = k["relation"]
        rows.append(
            [
                kind,
                k["changed values"],
                r["checked"],
                r["failed"],
                _cell(k["admitted without the relation"]),
                _cell(r["stopped alone"]),
                r["right values sent to review"],
            ]
        )
    head = [
        "Change",
        "n",
        "Checked",
        "Failed",
        "Admitted without it",
        "Stopped by it alone",
        "Right values sent to review",
    ]
    lines += _table(head, rows)
    lines += [
        '"Stopped by it alone" counts the changed values that the schema without the relation '
        "admits. The last column counts the right values of the other fields that a failed "
        "relation sends to review with the changed value.",
        "",
        "## Changed values that groundgate admits",
        "",
    ]
    esc = res["admitted changes"]
    if esc:
        lines += _table(
            ["Document", "Change", "Detail", "Field", "Year", "Value"],
            [[e["doc"], e["kind"], e["detail"], e["field"], e["key"], e["value"]] for e in esc],
            text=5,
        )
    else:
        lines += ["None.", ""]
    skipped = counts["not applied"]
    lines += [
        "## Changes that do not apply",
        "",
        "A kind does not apply to a base when the text gives no such value, as a row with one "
        "number cell for the next column. A change that lands on the right value is left out.",
        "",
    ]
    rows = [[k, skipped.get(k, 0), counts["same value"].get(k, 0)] for k in KINDS]
    lines += _table(["Change", "Does not apply", "Same value"], rows)
    return "\n".join(lines).rstrip("\n") + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("changes", "results"))
    ap.add_argument("--check", action="store_true", help="fail if a written file would differ")
    args = ap.parse_args()
    if args.command == "changes":
        files = {HERE / "changes.json": _text(changes())}
    else:
        res = results()
        files = {HERE / "results.json": _text(res), HERE / "RESULTS.md": report(res)}
    stale = [p.name for p, body in files.items() if not p.exists() or p.read_text("utf-8") != body]
    if args.check:
        if stale:
            raise SystemExit(f"differ: {', '.join(stale)}")
        print("all files match")
        return
    for path, body in files.items():
        path.write_text(body, encoding="utf-8")
    print(f"wrote {', '.join(p.name for p in files)}")


if __name__ == "__main__":
    main()
