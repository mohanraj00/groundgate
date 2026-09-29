"""M0.5 spike: does value-level admission catch errors that LangExtract's alignment accepts?

For each gold fact we build the extraction a LangExtract model would emit (verbatim
`extraction_text` plus `value`/`unit` attributes), apply one controlled corruption at a time,
and align it with LangExtract's own `Resolver.align` inside the same 1,000-character chunk that
`lx.extract` would have sent to the model. No model is called, so the run is deterministic.

Configurations compared, per corruption class:
  lx-all      accept every extraction LangExtract returns
  lx-aligned  accept extractions with a char_interval (any alignment status)
  lx-exact    accept only MATCH_EXACT
  gg-strict   LangExtract + throwaway groundgate checker, reject rules only
  gg-flags    gg-strict plus needs_verification flags (qualifier, multiple values, scale)

Run: .venv-spike/bin/python spikes/m0_5/spike.py
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from langextract import chunking
from langextract import resolver as lx_resolver
from langextract import tokenizer as lx_tokenizer
from langextract.core import data

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from gold import GOLD  # noqa: E402

DOCS = {"irs-p590a": HERE / "sources/p590a.txt", "fda-metformin-er": HERE / "sources/metformin-er.txt"}
MAX_CHAR_BUFFER = 1000  # lx.extract default

UNIT_FORMS = {
    "USD": ["$"],
    "mg": ["mg"],
    "mcg": ["mcg"],
    "mL/min/1.73m2": ["mL/minute/1.73 m2"],
    "mg/dL": ["mg/dL"],
    "hours": ["hours", "hour"],
    "days": ["days", "day"],
    "mmol/L": ["mmol/Liter", "mmol/L"],
    "mcg/mL": ["mcg/mL"],
    "mg/mL": ["mg/mL"],
    "years": ["years"],
    "months": ["months"],
    "%": ["%"],
    "mg/kg/day": ["mg/kg/day"],
    "mg/day": ["mg/day"],
    "times": ["times"],
    "weeks": ["-week", "weeks"],
    "count": [],
}
UNIT_SWAP = {
    "mg": "mcg",
    "hours": "days",
    "mcg/mL": "mg/mL",
    "mmol/L": "mg/dL",
    "years": "months",
    "%": "mg",
    "mg/kg/day": "mg/day",
    "weeks": "days",
    "mL/min/1.73m2": "mg/dL",
}
UNIT_WORDS = {"USD": "dollars", "mg": "milligrams", "hours": "hrs", "%": "percent", "weeks": "wks"}

QUALIFIERS_BEFORE = [
    (r"approximately|about|around|nearly|generally|roughly", "approx"),
    (r"more than|greater than|above|over|exceeds?|>", "gt"),
    (r"less than|fewer than|below|under|<", "lt"),
    (r"at least|minimum of|≥", "ge"),
    (r"up to|maximum of|at most|no more than|≤", "le"),
]
QUALIFIERS_AFTER = [
    (r"or more|or greater|or older|or higher|or above", "ge"),
    (r"or less|or fewer|or younger|or lower|or below", "le"),
]
DECLARED = {"more_than": "gt", "above": "gt", "less_than": "lt", "below": "lt", "at_least": "ge", "up_to": "le"}
SCALE = re.compile(r"^\s*(million|billion|thousand|lakh|crore)\b", re.I)

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
GROUPED = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^\d+(?:\.\d+)?$")


@dataclasses.dataclass
class Num:
    start: int
    end: int
    value: Decimal | None  # None when the digit grouping is invalid, e.g. "252,0000"


def numbers(text: str, base: int = 0) -> list[Num]:
    out = []
    for m in NUM.finditer(text):
        tok = m.group().rstrip(",")
        s = m.start()
        if s > 0 and (text[s - 1].isalnum() or text[s - 1] in ".,"):
            continue
        val = Decimal(tok.replace(",", "")) if GROUPED.match(tok) else None
        out.append(Num(base + s, base + s + len(tok), val))
    return out


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def dehyphen(s: str) -> str:
    return re.sub(r"-\s+", "", s)


def fmt_int(v: Decimal) -> str:
    return f"{int(v):,}" if v == v.to_integral_value() else str(v)


@dataclasses.dataclass
class Fact:
    doc: str
    id: str
    field: str
    value: Decimal
    unit: str
    qualifier: str | None
    start: int
    end: int
    chunk_start: int
    chunk_end: int
    chunk_token_start: int


def locate(text: str, pattern: str) -> tuple[int, int]:
    ms = list(re.finditer(pattern.replace(" ", r"\s+"), text))
    if len(ms) != 1:
        raise SystemExit(f"pattern matched {len(ms)} times: {pattern}")
    return ms[0].span("v")


def chunks(text: str) -> list[tuple[int, int, int]]:
    it = chunking.ChunkIterator(text, max_char_buffer=MAX_CHAR_BUFFER, tokenizer_impl=lx_tokenizer.RegexTokenizer())
    return [(c.char_interval.start_pos, c.char_interval.end_pos, c.token_interval.start_index) for c in it]


def load() -> tuple[dict[str, str], list[Fact]]:
    texts = {k: p.read_text() for k, p in DOCS.items()}
    doc_chunks = {k: chunks(t) for k, t in texts.items()}
    facts = []
    for doc, fid, field, value, unit, qual, pattern in GOLD:
        s, e = locate(texts[doc], pattern)
        cs, ce, ct = next(c for c in doc_chunks[doc] if c[0] <= s and e <= c[1])
        facts.append(Fact(doc, fid, field, Decimal(value), unit, qual, s, e, cs, ce, ct))
    return texts, facts


# ---------------------------------------------------------------- corruptions


@dataclasses.dataclass
class Proposal:
    text: str
    value: str
    unit: str


def clean(f: Fact, doc: str) -> Proposal:
    return Proposal(ws(doc[f.start : f.end]), str(f.value), f.unit)


def value_attr_x10(f: Fact, doc: str) -> Proposal:
    p = clean(f, doc)
    return Proposal(p.text, str(f.value * 10), f.unit)


def text_value_x10(f: Fact, doc: str) -> Proposal:
    p = clean(f, doc)
    n = numbers(p.text)[0]
    new = f.value * 10
    return Proposal(p.text[: n.start] + fmt_int(new) + p.text[n.end :], str(new), f.unit)


def near_miss(f: Fact, doc: str) -> Proposal:
    p = clean(f, doc)
    digits = str(int(f.value))
    if len(digits) == 1:
        new = Decimal(int(digits) + 1)
    else:
        d = (int(digits[1]) + 2) % 10
        new = Decimal(digits[0] + str(d) + digits[2:])
    n = numbers(p.text)[0]
    return Proposal(p.text[: n.start] + fmt_int(new) + p.text[n.end :], str(new), f.unit)


def _has_unit(doc: str, n: Num, unit: str) -> bool:
    forms = UNIT_FORMS.get(unit, [])
    if unit == "USD":
        return n.start > 0 and doc[n.start - 1] == "$"
    if not forms:
        return True
    window = doc[n.end : n.end + 25]
    return any(form in window for form in forms)


def adjacent_value(f: Fact, doc: str) -> Proposal | None:
    """Another real value with the same unit from the same chunk: exists verbatim, wrong field."""
    cands = [
        n
        for n in numbers(doc[f.chunk_start : f.chunk_end], f.chunk_start)
        if n.value is not None and n.value != f.value and _has_unit(doc, n, f.unit)
    ]
    if not cands:
        return None
    n = min(cands, key=lambda c: abs(c.start - f.start))
    p = clean(f, doc)
    old = numbers(p.text)[0]
    surface = doc[n.start : n.end]
    return Proposal(p.text[: old.start] + surface + p.text[old.end :], str(n.value), f.unit)


def unit_swap(f: Fact, doc: str) -> Proposal | None:
    if f.unit not in UNIT_SWAP:
        return None
    p = clean(f, doc)
    return Proposal(p.text, p.value, UNIT_SWAP[f.unit])


def null_literal(f: Fact, doc: str) -> Proposal:
    return Proposal("null", "null", f.unit)


def paraphrase(f: Fact, doc: str) -> Proposal:
    """Correct value, but the evidence text is not verbatim."""
    word = UNIT_WORDS.get(f.unit, f.unit)
    return Proposal(f"{int(f.value)} {word}", str(f.value), f.unit)


CORRUPTIONS = {
    "value_attr_x10": value_attr_x10,
    "text_value_x10": text_value_x10,
    "near_miss_digit": near_miss,
    "adjacent_value": adjacent_value,
    "unit_swap": unit_swap,
    "null_literal": null_literal,
}
CORRECT = {"clean": clean, "paraphrase": paraphrase}


# ------------------------------------------------------------------ alignment


def lx_align(p: Proposal, f: Fact, doc: str) -> data.Extraction:
    ext = data.Extraction(
        extraction_class=f.field,
        extraction_text=p.text,
        attributes={"value": p.value, "unit": p.unit},
    )
    aligned = list(
        lx_resolver.Resolver().align(
            [ext], doc[f.chunk_start : f.chunk_end], f.chunk_token_start, f.chunk_start
        )
    )
    return aligned[0]


# ------------------------------------------------------------ throwaway gate


def _sentence(doc: str, pos: int) -> tuple[int, int]:
    left = max(doc.rfind(b, 0, pos) for b in (". ", "\n\n", "•", "; "))
    right_c = [i for b in (". ", "\n\n", "•", "; ") if (i := doc.find(b, pos)) != -1]
    return (left + 1 if left >= 0 else 0), (min(right_c) if right_c else len(doc))


def _qualifiers(doc: str, n: Num) -> set[str]:
    s0, s1 = _sentence(doc, n.start)
    nums = numbers(doc[s0:s1], s0)
    prev_end = max([m.end for m in nums if m.end <= n.start] + [s0, n.start - 30])
    next_start = min([m.start for m in nums if m.start >= n.end] + [s1, n.end + 30])
    before = doc[prev_end : n.start].lower()
    after = doc[n.end : next_start].lower()
    found = set()
    for pat, q in QUALIFIERS_BEFORE:
        if re.search(rf"(?:^|[\s(]|\$)(?:{pat})\s*\$?\s*$|(?:{pat})\s*\$?$", before):
            found.add(q)
    for pat, q in QUALIFIERS_AFTER:
        if re.search(rf"^[^.;]*?\b(?:{pat})\b", after):
            found.add(q)
    return found


def _value_at(doc: str, s: int, e: int, value: Decimal, unit: str) -> tuple[Num | None, str]:
    hits = [n for n in numbers(doc[s:e], s) if n.value == value]
    if not hits:
        return None, "VALUE_NOT_IN_EVIDENCE"
    for n in hits:
        if _has_unit(doc, n, unit):
            return n, ""
    return None, "UNIT_NOT_IN_EVIDENCE"


def groundgate(
    ext: data.Extraction, f: Fact, doc: str, flags: bool, verbatim: bool = True, multi: bool = True
) -> tuple[str, list[str]]:
    """flags: add review flags. verbatim=False (v2): non-verbatim evidence is a review flag, not a
    rejection, provided the value and unit still verify at the aligned location. multi=False (v2):
    drop the blunt other-values-in-sentence flag."""
    attrs = ext.attributes or {}
    raw, unit = str(attrs.get("value", "")), attrs.get("unit")
    if raw.strip().lower() == "null":
        return "rejected", ["NULL_STRING_LITERAL"]
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return "rejected", ["TYPE_INVALID"]
    if unit != f.unit:  # the schema pins each field's unit
        return "rejected", ["UNIT_INVALID"]
    ci = ext.char_interval
    if ci is None or ci.start_pos is None or ci.end_pos is None:
        return "rejected", ["NO_EVIDENCE_SPAN"]
    s, e = ci.start_pos, ci.end_pos
    if not (0 <= s < e <= len(doc)):
        return "rejected", ["SPAN_OUT_OF_BOUNDS"]
    span = doc[s:e]
    codes: list[str] = []
    if ws(span) != ws(ext.extraction_text):
        if dehyphen(ws(span)) == dehyphen(ws(ext.extraction_text)):
            codes.append("NORMALIZED_MATCH_ONLY")
        elif not verbatim:
            codes.append("NON_VERBATIM_EVIDENCE")
        else:
            return "rejected", ["EVIDENCE_TEXT_MISMATCH"]
    n, why = _value_at(doc, s, e, value, unit)
    if n is None:
        # LangExtract anchors a short extraction_text to its first occurrence in the chunk.
        # Re-anchor only if exactly one other verbatim occurrence in the chunk passes.
        passing = []
        for m in re.finditer(r"\s+".join(map(re.escape, ws(ext.extraction_text).split(" "))),
                             doc[f.chunk_start : f.chunk_end]):
            a, b = f.chunk_start + m.start(), f.chunk_start + m.end()
            if a != s and _value_at(doc, a, b, value, unit)[0] is not None:
                passing.append((a, b))
        if len(passing) != 1:
            return "rejected", [why]
        s, e = passing[0]
        n = _value_at(doc, s, e, value, unit)[0]
        codes.append("EVIDENCE_REANCHORED")
    assert n is not None
    if flags:
        declared = DECLARED.get(f.qualifier or "")
        quals = _qualifiers(doc, n)
        if quals - ({declared} if declared else set()):
            codes.append("QUALIFIED_VALUE")
        s0, s1 = _sentence(doc, n.start)
        others = [
            m for m in numbers(doc[s0:s1], s0)
            if m.start != n.start and m.value is not None and _has_unit(doc, m, unit)
        ]
        if others and multi:
            codes.append("MULTIPLE_VALUES_IN_EVIDENCE")
        if SCALE.match(doc[n.end : n.end + 15]):
            codes.append("SCALE_WORD")
    review = [c for c in codes if c != "EVIDENCE_REANCHORED"]
    return ("needs_verification" if review else "admitted"), codes


# -------------------------------------------------------------------- scoring


def run() -> dict[str, object]:
    texts, facts = load()
    rows = []
    for f in facts:
        doc = texts[f.doc]
        for kind, fn in {**CORRECT, **CORRUPTIONS}.items():
            p = fn(f, doc)
            if p is None:
                continue
            ext = lx_align(p, f, doc)
            status = ext.alignment_status.value if ext.alignment_status else None
            strict = groundgate(ext, f, doc, flags=False)
            flagged = groundgate(ext, f, doc, flags=True)
            v2 = groundgate(ext, f, doc, flags=True, verbatim=False, multi=False)
            rows.append({
                "fact": f.id, "doc": f.doc, "kind": kind, "correct": kind in CORRECT,
                "text": p.text, "value": p.value, "unit": p.unit,
                "lx_status": status,
                "lx_span": [ext.char_interval.start_pos, ext.char_interval.end_pos] if ext.char_interval else None,
                "gold_span": [f.start, f.end], "lx_aligned": ext.char_interval is not None and ext.char_interval.start_pos is not None,
                "gg_strict": strict[0], "gg_strict_codes": strict[1],
                "gg_flags": flagged[0], "gg_flags_codes": flagged[1],
                "gg_v2": v2[0], "gg_v2_codes": v2[1],
            })
    return {"facts": len(facts), "rows": rows}


def accepted(row: dict, config: str) -> str:
    """'accept' | 'review' | 'reject' for one row under one configuration."""
    if config == "lx-all":
        return "accept"
    if config == "lx-aligned":
        return "accept" if row["lx_aligned"] else "reject"
    if config == "lx-exact":
        return "accept" if row["lx_status"] == "match_exact" else "reject"
    outcome = row[{"gg-strict": "gg_strict", "gg-flags": "gg_flags", "gg-v2": "gg_v2"}[config]]
    return {"admitted": "accept", "needs_verification": "review", "rejected": "reject"}[outcome]


CONFIGS = ["lx-all", "lx-aligned", "lx-exact", "gg-strict", "gg-flags", "gg-v2"]


def report(res: dict) -> str:
    rows = res["rows"]
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)
    out = [f"facts: {res['facts']}  rows: {len(rows)}\n"]
    out.append("Wrong facts: share ACCEPTED silently (escape rate; lower is better). gg-flags shows accepted / sent to review.\n")
    out.append(f"{'corruption':<18}{'n':>4}" + "".join(f"{c:>13}" for c in CONFIGS))
    tot = Counter()
    for kind in CORRUPTIONS:
        rs = by_kind[kind]
        line = f"{kind:<18}{len(rs):>4}"
        for c in CONFIGS:
            acc = sum(accepted(r, c) == "accept" for r in rs)
            rev = sum(accepted(r, c) == "review" for r in rs)
            tot[(c, "accept")] += acc
            tot[(c, "review")] += rev
            cell = f"{acc / len(rs):.0%}" + (f" /{rev / len(rs):.0%}" if c in ("gg-flags", "gg-v2") else "")
            line += f"{cell:>13}"
        out.append(line)
    n_wrong = sum(len(by_kind[k]) for k in CORRUPTIONS)
    line = f"{'ALL WRONG':<18}{n_wrong:>4}"
    for c in CONFIGS:
        cell = f"{tot[(c, 'accept')] / n_wrong:.0%}" + (f" /{tot[(c, 'review')] / n_wrong:.0%}" if c in ("gg-flags", "gg-v2") else "")
        line += f"{cell:>13}"
    out.append(line)

    out.append("\nCorrect facts: accepted / sent to review / rejected (higher accept is better)\n")
    out.append(f"{'kind':<18}{'n':>4}" + "".join(f"{c:>18}" for c in CONFIGS))
    for kind in CORRECT:
        rs = by_kind[kind]
        line = f"{kind:<18}{len(rs):>4}"
        for c in CONFIGS:
            a = Counter(accepted(r, c) for r in rs)
            line += f"{a['accept'] / len(rs):>7.0%}/{a['review'] / len(rs):.0%}/{a['reject'] / len(rs):.0%}".rjust(18)
        out.append(line)

    cl = by_kind["clean"]
    hit = sum(1 for r in cl if r["lx_span"] and r["lx_span"][0] < r["gold_span"][1] and r["gold_span"][0] < r["lx_span"][1])
    out.append(f"\nLangExtract char_interval overlaps the gold location on {hit}/{len(cl)} correct facts")
    rean = sum("EVIDENCE_REANCHORED" in r["gg_strict_codes"] for r in cl)
    out.append(f"groundgate re-anchored {rean}/{len(cl)} correct facts to a unique passing occurrence")
    out.append("\nLangExtract alignment status by kind")
    for kind, rs in by_kind.items():
        out.append(f"  {kind:<18}" + ", ".join(f"{k}={v}" for k, v in Counter(str(r['lx_status']) for r in rs).most_common()))
    for cfg in ("gg_flags", "gg_v2"):
        out.append(f"\n{cfg} reason codes by kind")
        for kind, rs in by_kind.items():
            c = Counter(code for r in rs for code in r[f"{cfg}_codes"])
            out.append(f"  {kind:<18}" + ", ".join(f"{k}={v}" for k, v in c.most_common()))
    return "\n".join(out)


if __name__ == "__main__":
    res = run()
    (HERE / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    text = report(res)
    (HERE / "results.txt").write_text(text + "\n")
    print(text)
