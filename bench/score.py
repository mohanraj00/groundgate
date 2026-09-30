"""Score the benchmark from the cached runs and write bench/RESULTS.md and bench/results.json.

    uv run --group langextract python bench/score.py            # needs every document checked
    uv run --group langextract python bench/score.py --drafts   # score against draft gold (dev)
    uv run --group langextract python bench/score.py --check    # fail if the committed files differ

--check scores in the same mode as the committed results.json, so CI checks draft results
until the gold is checked.

No model is called. Track B scores what real models proposed (bench/runs). Track A plants one
controlled error at a time into the gold facts, aligns each with LangExtract's own Resolver, and
measures what each configuration lets through.

Terms:
- a candidate is *wrong* when its value is not a gold value for its field, when the field is
  absent from the document, or when its unit is not the field's unit;
- *escape rate*: wrong candidates accepted without review / wrong candidates;
- *review load*: candidates groundgate sends to a person / all candidates;
- *false reject rate*: correct candidates citing the right place, rejected / correct candidates;
- *recall*: gold facts with at least one correct candidate accepted / gold facts.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any

import groundgate as gg
from groundgate.adapters.langextract import to_candidates
from groundgate.text import canonical, parse_value, tokens, unit_at

HERE = Path(__file__).parent
SET = HERE  # the benchmark set: gold, docs, runs and results (--set)
WRONG = ("wrong_value", "absent_field", "wrong_unit", "unparsable")
LX_CONFIGS = ("lx_all", "lx_aligned", "lx_exact")


# ------------------------------------------------------------------------------ gold


@dataclass
class Gold:
    doc: str
    kind: str
    text: str
    schema: dict[str, Any]
    values: dict[str, set[str]]  # field -> canonical gold values
    evidence: dict[tuple[str, str], list[tuple[int, int]]]
    absent: set[str]
    excluded: set[str]
    checked: bool
    seconds: int = 0  # labeling time

    def facts(self) -> list[tuple[str, str]]:
        return [(f, v) for f, vs in self.values.items() for v in sorted(vs)]


def load_gold(drafts: bool) -> dict[str, Gold]:
    out = {}
    for path in sorted((SET / "gold").glob("*.json")):
        g = json.loads(path.read_text(encoding="utf-8"))
        ok_fact = {"confirmed", "draft"} if drafts else {"confirmed"}
        ok_absent = {"confirmed", "draft"} if drafts else {"confirmed"}
        values: dict[str, set[str]] = defaultdict(set)
        evidence: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        for fact in g["facts"]:
            if fact["status"] not in ok_fact:
                continue
            v = canonical(parse_value(fact["value"]) or Decimal(0))
            values[fact["field"]].add(v)
            evidence[(fact["field"], v)].extend((e["start"], e["end"]) for e in fact["evidence"])
        schema = {
            "fields": {n: s["schema"] for n, s in g["fields"].items()},
            "units": g["units"],
        }
        out[g["doc"]] = Gold(
            doc=g["doc"],
            kind=g["kind"],
            text=(SET / "docs" / f"{g['doc']}.txt").read_text(encoding="utf-8"),
            schema=schema,
            values=dict(values),
            evidence=dict(evidence),
            absent={k for k, v in g["absent"].items() if v in ok_absent},
            excluded=set(g["excluded"]),
            checked=g.get("checked") is not None,
            seconds=int(g.get("seconds_spent", 0)),
        )
    return out


def field_unit(g: Gold, name: str) -> str | None:
    return g.schema["fields"][name]["unit"]


def judge(g: Gold, cand: dict[str, Any]) -> tuple[str, bool]:
    """(label, evidence_ok) for one candidate. evidence_ok only means something when correct."""
    name = cand.get("field")
    if name not in g.schema["fields"]:
        return "off_schema", False
    if name in g.excluded or (name not in g.values and name not in g.absent):
        return "unscored", False
    if name in g.absent:
        return "absent_field", False
    raw = cand.get("value")
    parsed = parse_value(raw) if isinstance(raw, str) else None
    if isinstance(raw, int) and not isinstance(raw, bool):
        parsed = Decimal(raw)
    if parsed is None:
        return "unparsable", False
    value = canonical(parsed)
    if value not in g.values[name]:
        return "wrong_value", False
    if cand.get("unit") != g.schema["fields"][name]["unit"]:
        return "wrong_unit", False
    ev = cand.get("evidence")
    ok = isinstance(ev, dict) and any(
        ev["start"] < e and s < ev["end"] for s, e in g.evidence.get((name, value), [])
    )
    return "correct", ok


# ---------------------------------------------------------------------------- scoring


@dataclass
class Row:
    """One candidate under one configuration."""

    doc: str
    kind: str
    model: str
    buffer: int
    label: str
    evidence_ok: bool
    lx: str | None  # alignment status
    outcome: str  # admitted | needs_verification | rejected
    codes: tuple[str, ...]
    field: str
    value: object
    quote: object
    span: tuple[int, int] | None


def decide(config: str, r: Row) -> str:
    """accept | review | reject under a configuration."""
    if config == "lx_all":
        return "accept"
    if config == "lx_aligned":
        return "accept" if r.lx is not None else "reject"
    if config == "lx_exact":
        return "accept" if r.lx == "match_exact" else "reject"
    return {"admitted": "accept", "needs_verification": "review"}.get(r.outcome, "reject")


def rows_for(g: Gold, cands: list[dict[str, Any]], model: str, buffer: int) -> list[Row]:
    receipt = gg.admit(g.text, g.schema, cands)
    by_sha = {d.candidate_sha256: d for d in receipt.decisions}
    out = []
    for c in cands:
        d = by_sha[gg.digest("candidate", c)]
        label, ev_ok = judge(g, c)
        ev = c.get("evidence")
        span = (ev["start"], ev["end"]) if isinstance(ev, dict) else None
        out.append(
            Row(
                g.doc,
                g.kind,
                model,
                buffer,
                label,
                ev_ok,
                c.get("alignment_status"),
                d.outcome,
                d.codes,
                str(c.get("field")),
                c.get("value"),
                ev.get("text") if isinstance(ev, dict) else None,
                span,
            )
        )
    return out


Runs = dict[tuple[str, int], dict[str, list[dict[str, Any]]]]


def load_runs(golds: dict[str, Gold]) -> tuple[Runs, dict[tuple[str, int], dict[str, Any]]]:
    """(model, buffer) -> doc -> candidates, and (model, buffer) -> harness health."""
    import warnings

    from langextract import resolver as lx_resolver

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        parse = lx_resolver.Resolver(fence_output=False)
    runs: Runs = defaultdict(dict)
    health: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    providers: dict[tuple[str, int], str] = {}
    for path in sorted((SET / "runs").glob("*/*/*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        doc = rec["document"]["document_id"]
        if doc not in golds:
            continue
        key = (rec["model"], rec["max_char_buffer"])
        runs[key][doc] = to_candidates(rec["document"])
        providers[key] = rec["provider"]
        h = health[key]
        h["seconds"] += rec["seconds"]
        for raw in rec.get("raw_outputs", []):
            h["chunks"] += 1
            notes = raw.get("harness", {})
            h["discarded"] += notes.get("discarded_for_tool_use", 0)
            h["discarded"] += notes.get("discarded_for_harness", 0)
            try:
                parse.resolve(raw["output"], suppress_parse_errors=False)
            except Exception:  # LangExtract skipped this chunk
                h["unusable_chunks"] += 1
    meta = {k: {"provider": providers[k], **dict(sorted(h.items()))} for k, h in health.items()}
    return runs, meta


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    z, p = 1.96, k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def rate(k: int, n: int) -> dict[str, Any]:
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4), "ci95": [round(lo, 4), round(hi, 4)]}


@dataclass
class Metrics:
    candidates: int = 0
    correct: int = 0
    wrong: int = 0
    wrong_accepted: int = 0
    wrong_review: int = 0
    correct_rejected: int = 0
    correct_rejected_bad_evidence: int = 0
    correct_review: int = 0
    review: int = 0
    accepted_correct_bad_evidence: int = 0
    accepted_correct: int = 0
    wrong_by_class: Counter[str] = field(default_factory=Counter)
    escaped_by_class: Counter[str] = field(default_factory=Counter)

    def add(self, r: Row, verdict: str) -> None:
        if r.label in ("off_schema", "unscored"):
            return
        self.candidates += 1
        self.review += verdict == "review"
        if r.label == "correct":
            self.correct += 1
            self.correct_rejected += verdict == "reject" and r.evidence_ok
            self.correct_rejected_bad_evidence += verdict == "reject" and not r.evidence_ok
            self.correct_review += verdict == "review"
            if verdict == "accept":
                self.accepted_correct += 1
                self.accepted_correct_bad_evidence += not r.evidence_ok
        else:
            self.wrong += 1
            self.wrong_by_class[r.label] += 1
            self.wrong_accepted += verdict == "accept"
            self.wrong_review += verdict == "review"
            if verdict == "accept":
                self.escaped_by_class[r.label] += 1

    def summary(self) -> dict[str, Any]:

        return {
            "candidates": self.candidates,
            "correct": self.correct,
            "wrong": self.wrong,
            "escape": rate(self.wrong_accepted, self.wrong),
            "wrong_sent_to_review": rate(self.wrong_review, self.wrong),
            "false_reject": rate(self.correct_rejected, self.correct),
            "rejected_right_value_wrong_place": rate(
                self.correct_rejected_bad_evidence, self.correct
            ),
            "correct_sent_to_review": rate(self.correct_review, self.correct),
            "review_load": rate(self.review, self.candidates),
            "accepted_correct_citing_wrong_place": rate(
                self.accepted_correct_bad_evidence, self.accepted_correct
            ),
            "wrong_by_class": dict(sorted(self.wrong_by_class.items())),
            "escaped_by_class": dict(sorted(self.escaped_by_class.items())),
        }


def recall(golds: dict[str, Gold], rows: list[Row], config: str, docs: set[str]) -> dict:
    """Share of gold facts with a correct candidate accepted (and accepted or sent to review)."""
    total = [(d, f, v) for d in sorted(docs) for f, v in golds[d].facts()]
    out = {}
    for name, ok in (("accepted", {"accept"}), ("accepted_or_review", {"accept", "review"})):
        found = {
            (r.doc, r.field, canonical(parse_value(str(r.value)) or Decimal(0)))
            for r in rows
            if r.label == "correct" and decide(config, r) in ok
        }
        out[name] = rate(sum(t in found for t in total), len(total))
    return out


def track_b(golds: dict[str, Gold]) -> dict[str, Any]:
    runs, health = load_runs(golds)
    out: dict[str, Any] = {"runs": {}, "pairs": {}, "all_models": {}, "escapes": []}
    for (model, buffer), docs in sorted(runs.items()):
        rows = [
            r for doc, cands in docs.items() for r in rows_for(golds[doc], cands, model, buffer)
        ]
        per: dict[str, Any] = {"documents": len(docs), "harness": health[(model, buffer)]}
        for config in (*LX_CONFIGS, "groundgate"):
            m = Metrics()
            for r in rows:
                m.add(r, decide(config, r))
            per[config] = m.summary() | {"recall": recall(golds, rows, config, set(docs))}
        per["caught_by"] = dict(
            sorted(
                Counter(
                    r.codes[0]
                    for r in rows
                    if r.label in WRONG and decide("groundgate", r) != "accept" and r.codes
                ).items()
            )
        )
        per["by_kind"] = {}
        for kind in ("fda", "ntsb", "irs"):
            sub = [r for r in rows if r.kind == kind]
            per["by_kind"][kind] = {}
            for config in ("lx_exact", "groundgate"):
                m = Metrics()
                for r in sub:
                    m.add(r, decide(config, r))
                per["by_kind"][kind][config] = m.summary()
        out["runs"][f"{model} @ {buffer}"] = per
        for r in rows:
            if r.label in WRONG and decide("groundgate", r) == "accept":
                out["escapes"].append(_row_json(golds, r))
    # several independent models through one gate: disagreements become CONFLICTING_CANDIDATES
    by_buffer: dict[int, list[str]] = defaultdict(list)
    for model, buffer in runs:
        by_buffer[buffer].append(model)
    for buffer, models in sorted(by_buffer.items()):
        groups = [tuple(p) for p in combinations(sorted(models), 2)]
        if len(models) > 2:
            groups.append(tuple(sorted(models)))
        for group in groups:
            docs = set.intersection(*(set(runs[(m, buffer)]) for m in group))
            together, apart = Metrics(), Metrics()
            rows: list[Row] = []
            for doc in sorted(docs):
                name = " + ".join(group)
                rows += rows_for(
                    golds[doc], [c for m in group for c in runs[(m, buffer)][doc]], name, buffer
                )
                for m in group:
                    for r in rows_for(golds[doc], runs[(m, buffer)][doc], m, buffer):
                        apart.add(r, decide("groundgate", r))
            for r in rows:
                together.add(r, decide("groundgate", r))
            entry = together.summary() | {
                "documents": len(docs),
                "models": list(group),
                "recall": recall(golds, rows, "groundgate", docs),
                "escape_when_admitted_separately": apart.summary()["escape"],
                "review_load_when_admitted_separately": apart.summary()["review_load"],
            }
            target = out["all_models"] if len(group) > 2 else out["pairs"]
            target[f"{' + '.join(group)} @ {buffer}"] = entry
    out["pooled"] = {
        c: {
            m: rate(
                sum(r[c][m]["k"] for r in out["runs"].values()),
                sum(r[c][m]["n"] for r in out["runs"].values()),
            )
            for m in ("escape", "false_reject", "review_load")
        }
        for c in ("lx_all", "lx_aligned", "lx_exact", "groundgate")
    }
    return out


def _row_json(golds: dict[str, Gold], r: Row) -> dict[str, Any]:
    g = golds[r.doc]
    ctx = None
    if r.span:
        raw = g.text.encode()
        ctx = raw[max(0, r.span[0] - 60) : r.span[1] + 40].decode("utf-8", "replace")
        ctx = " ".join(ctx.split())
    return {
        "doc": r.doc,
        "model": r.model,
        "buffer": r.buffer,
        "field": r.field,
        "value": r.value,
        "gold": sorted(g.values.get(r.field, [])),
        "label": r.label,
        "codes": list(r.codes),
        "context": ctx,
    }


# ---------------------------------------------------------------------------- Track A


SWAP = {
    "mg": "mcg",
    "mcg": "mg",
    "USD": "cents",
    "cents": "USD",
    "hours": "minutes",
    "ft": "miles",
    "miles": "ft",
    "knots": "ft",
    "years": "months",
    "C": "F",
    "inHg": "ft",
    "%": "USD",
}
WORDS = {
    "mg": "milligrams",
    "mcg": "micrograms",
    "USD": "dollars",
    "cents": "cents",
    "hours": "hr",
    "ft": "foot",
    "miles": "statute miles",
    "knots": "kt",
    "years": "yrs",
    "C": "degrees Celsius",
    "inHg": "inches of mercury",
    "%": "percent",
    None: "years old",
}
PLANTED = (
    "clean",
    "paraphrase",
    "value_x10",
    "text_and_value_x10",
    "near_miss_digit",
    "decimal_dropped",
    "comma_as_decimal",
    "adjacent_value",
    "unit_swap",
    "null_literal",
    "qualifier_in_text",
    "scale_word_in_text",
)
CORRECT_CLASSES = ("clean", "paraphrase")


def track_a(golds: dict[str, Gold]) -> dict[str, Any]:
    """Plant one error at a time into each gold fact, align it the way lx.extract would, admit it.

    The proposal is built from the gold evidence, so the extraction text is what a model that
    read the right place would write. LangExtract's Resolver aligns it inside the same
    1,000-character chunk lx.extract would have sent. No model is called.

    Most classes change the extraction. The last two change the document instead: a qualifier
    or a scale word is written next to the value, so the unchanged extraction no longer says
    what the text says.
    """
    results: dict[str, Counter[str]] = {c: Counter() for c in PLANTED}

    def record(cls: str, row: Row) -> None:
        results[cls]["n"] += 1
        results[cls][f"judged:{row.label}"] += 1
        for config in (*LX_CONFIGS, "groundgate"):
            results[cls][f"{config}:{decide(config, row)}"] += 1
        for code in row.codes:
            results[cls][f"code:{code}"] += 1

    for g in golds.values():
        text, raw = g.text, g.text.encode()
        chunk_list = _chunks(text)
        for (name, value), spans in sorted(g.evidence.items()):
            if value not in g.values.get(name, ()):
                continue
            s, e = (len(raw[:b].decode()) for b in spans[0])
            chunk = next((c for c in chunk_list if c[0] <= s and e <= c[1]), None)
            num = next((t for t in tokens(text, s, e) if t.value is not None), None)
            if chunk is None or num is None:
                continue
            for cls, (quote, v, unit) in _plant(g, text, chunk, name, value, s, e, num).items():
                if (
                    cls not in CORRECT_CLASSES
                    and v in g.values[name]
                    and unit == field_unit(g, name)
                ):
                    results[cls]["skipped_planted_value_is_gold"] += 1
                    continue
                record(cls, _aligned_row(g, text, chunk, name, quote, v, unit))
            for cls, (new_text, at, grown) in _plant_text(g, text, name, num).items():
                s2 = s + grown if at <= s else s
                e2 = e + grown
                chunk2 = next((c for c in _chunks(new_text) if c[0] <= s2 and e2 <= c[1]), None)
                if chunk2 is None:
                    continue
                moved = replace(g, text=new_text)
                quote = new_text[s2:e2]
                row = _aligned_row(moved, new_text, chunk2, name, quote, value, field_unit(g, name))
                record(cls, replace(row, label="wrong_meaning"))
                b0, b1 = len(new_text[:s2].encode()), len(new_text[:e2].encode())
                cited_here = row.span is not None and row.span[0] < b1 and b0 < row.span[1]
                if row.outcome == "admitted" and not cited_here:
                    results[cls]["groundgate:accept_cited_elsewhere"] += 1
    return {c: dict(sorted(v.items())) for c, v in results.items() if v}


def _chunks(text: str) -> list[tuple[int, int, int]]:
    """The chunks lx.extract sends at its default max_char_buffer: (start, end, first token)."""
    from langextract import chunking
    from langextract import tokenizer as lx_tokenizer

    it = chunking.ChunkIterator(
        text, max_char_buffer=1000, tokenizer_impl=lx_tokenizer.RegexTokenizer()
    )
    return [
        (c.char_interval.start_pos, c.char_interval.end_pos, c.token_interval.start_index)
        for c in it
    ]


def _aligned_row(
    g: Gold,
    text: str,
    chunk: tuple[int, int, int],
    name: str,
    quote: str,
    value: str,
    unit: str | None,
) -> Row:
    """The candidate LangExtract would produce for this extraction, decided by groundgate."""
    from langextract import resolver as lx_resolver
    from langextract.core import data

    attrs = {"value": value} | ({"unit": unit} if unit else {})
    ext = data.Extraction(extraction_class=name, extraction_text=quote, attributes=attrs)
    aligned = next(
        iter(lx_resolver.Resolver().align([ext], text[chunk[0] : chunk[1]], chunk[2], chunk[0]))
    )
    (cand,) = to_candidates({"text": text, "extractions": [aligned]})
    (row,) = rows_for(g, [cand], "planted", 1000)
    return row


def _plant_text(g: Gold, text: str, name: str, num: Any) -> dict[str, tuple[str, int, int]]:
    """class -> (changed document, insertion point, characters inserted)."""
    f = g.schema["fields"][name]
    out = {}
    if f.get("comparator", "eq") != "gt":
        at = num.start  # before a currency sign too: "more than $184,500"
        while at > 0 and text[at - 1] in "$€£":
            at -= 1
        out["qualifier_in_text"] = (text[:at] + "more than " + text[at:], at, len("more than "))
    if f["unit"] in (None, "USD"):
        out["scale_word_in_text"] = (text[: num.end] + " million" + text[num.end :], num.end, 8)
    return out


def _plant(
    g: Gold, text: str, chunk: tuple[int, int, int], name: str, value: str, s: int, e: int, num: Any
) -> dict[str, tuple[str, str, str | None]]:
    """class -> (extraction_text, value attribute, unit attribute)."""
    unit = g.schema["fields"][name]["unit"]
    quote = text[s:e]
    ns, ne = num.start - s, num.end - s
    gold = Decimal(value)

    def rewrite(v: Decimal) -> str:
        return quote[:ns] + _fmt(v, quote[ns:ne]) + quote[ne:]

    near = _near(gold)
    out = {
        "clean": (quote, value, unit),
        "paraphrase": (f"{value} {WORDS.get(unit, unit)}", value, unit),
        "value_x10": (quote, canonical(gold * 10), unit),
        "text_and_value_x10": (rewrite(gold * 10), canonical(gold * 10), unit),
        "near_miss_digit": (rewrite(near), canonical(near), unit),
        "null_literal": ("null", "null", unit),
    }
    if "." in value:
        out["decimal_dropped"] = (quote, value.replace(".", "").lstrip("0") or "0", unit)
    if quote[ns:ne].count(",") == 1:
        out["comma_as_decimal"] = (quote, canonical(Decimal(quote[ns:ne].replace(",", "."))), unit)
    if unit in SWAP:
        out["unit_swap"] = (quote, value, SWAP[unit])
    adj = _adjacent(g, text, chunk, s, gold, unit)
    if adj is not None:
        out["adjacent_value"] = (
            quote[:ns] + text[adj.start : adj.end] + quote[ne:],
            canonical(adj.value),
            unit,
        )
    return out


def _fmt(v: Decimal, like: str) -> str:
    """``v`` written the way ``like`` writes its number (thousands commas or not)."""
    s = canonical(v)
    if "," in like and "." not in s:
        s = f"{int(s):,}"
    return s


def _near(v: Decimal) -> Decimal:
    """Change the second significant digit by 2, or the only digit by 1."""
    s = canonical(v)
    idx = [i for i, ch in enumerate(s) if ch.isdigit()]
    if len(idx) == 1:
        return v + 1
    i = idx[1]
    return Decimal(s[:i] + str((int(s[i]) + 2) % 10) + s[i + 1 :])


def _adjacent(
    g: Gold, text: str, chunk: tuple[int, int, int], s: int, v: Decimal, unit: str | None
) -> Any:
    """The nearest other number in the chunk that carries the field's unit."""
    schema = gg.Schema.from_dict(g.schema)
    pre, suf = schema.units.get(unit, ([], [])) if unit else ([], [])
    found = [
        t
        for t in tokens(text, chunk[0], chunk[1])
        if t.value is not None and t.value != v and unit_at(text, t, pre, suf, 24)
    ]
    return min(found, key=lambda t: abs(t.start - s), default=None)


# ---------------------------------------------------------------------------- report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts", action="store_true", help="score against draft gold")
    ap.add_argument("--check", action="store_true", help="fail if outputs would change")
    ap.add_argument("--set", type=Path, default=HERE, help="benchmark set directory")
    args = ap.parse_args()
    global SET
    SET = args.set.resolve()
    committed = SET / "results.json"
    if args.check and committed.exists():  # re-score the way the committed results were scored
        args.drafts = json.loads(committed.read_text())["gold"]["status"].startswith("draft")
    golds = load_gold(args.drafts)
    unchecked = [d for d, g in golds.items() if not g.checked]
    if unchecked and not args.drafts:
        raise SystemExit(f"{len(unchecked)} documents are not checked yet; use --drafts")
    results = {
        "gold": {
            "status": "draft (model-written, not yet checked by a person)"
            if args.drafts
            else "checked by a person",
            "documents": len(golds),
            "facts": sum(len(g.facts()) for g in golds.values()),
            "absent_fields": sum(len(g.absent) for g in golds.values()),
            "excluded_fields": sum(len(g.excluded) for g in golds.values()),
            "labeling_hours": round(sum(g.seconds for g in golds.values()) / 3600, 1),
        },
        "track_b": track_b(golds),
        "track_a": track_a(golds),
    }
    from report import render  # bench/report.py

    files = {"results.json": json.dumps(results, indent=1, sort_keys=True) + "\n"}
    files |= render(results)
    if args.check:
        stale = [
            n for n, t in files.items() if not (SET / n).exists() or (SET / n).read_text() != t
        ]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run bench/score.py")
        print("results are up to date")
        return
    (SET / "charts").mkdir(exist_ok=True)
    for name, text in files.items():
        (SET / name).write_text(text, encoding="utf-8")
    print(f"wrote {', '.join(files)}", file=sys.stderr)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
