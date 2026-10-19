"""Build the conformance vectors in conformance/vectors/ and conformance/invalid/.

Expected outcomes are written by hand below. This script only turns quotes into UTF-8 byte spans
(with str.encode and bytes.find, independent of groundgate) and writes language-agnostic JSON.
Run it after editing a vector; commit the output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
ADMIT = ("admitted", [])
NO_TEXT = object()  # evidence cited without a quote

VECTORS: list[dict[str, Any]] = []
INVALID: list[dict[str, Any]] = []


def q(quote: str, n: int = 1, text: object = None, **item: Any) -> dict[str, Any]:
    """Evidence marker: the n-th occurrence of ``quote``, cited with ``text`` (default: the quote;
    NO_TEXT: no text key). ``item`` adds evidence item members, such as ``role``; with ``ref``,
    the quote is found in that reference."""
    return {"quote": quote, "n": n, "text": quote if text is None else text, **item}


def vector(
    name: str,
    description: str,
    document: str,
    schema: dict[str, Any],
    candidates: list[Any],
    policy: dict[str, Any] | None = None,
    coverage: list[dict[str, str]] | None = None,
    judgments: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
    document_source: str | None = None,
    relations: list[tuple[str, str | None, bool, str, str]] | None = None,
    packs: list[dict[str, Any]] | None = None,
) -> None:
    """``relations`` is the receipt's relation results (SPEC §5), each as (id, key, holds,
    difference, allowance), in receipt order; None when the schema has no relations."""
    VECTORS.append(
        {
            "name": name,
            "description": description,
            "document": document,
            "schema": schema,
            "policy": policy,
            "candidates": candidates,
            "coverage": coverage or [],
            "judgments": judgments,
            "references": references,
            "document_source": document_source,
            "relations": None
            if relations is None
            else [
                {"id": i, "key": k, "holds": h, "difference": d, "allowance": a}
                for i, k, h, d, a in relations
            ],
            "packs": packs,
        }
    )


def c(
    cid: str,
    field: str,
    value: Any,
    unit: str | None = None,
    evidence: Any = None,
    expect: tuple[str, list[str]] = ADMIT,
    **extra: Any,
) -> dict[str, Any]:
    cand: dict[str, Any] = {"id": cid, "field": field, "value": value}
    if unit is not None:
        cand["unit"] = unit
    if evidence is not None:
        cand["evidence"] = evidence
    cand.update(extra)
    return {"candidate": cand, "expect": _expect(expect)}


def raw(candidate: Any, expect: tuple[Any, ...]) -> dict[str, Any]:
    """A candidate written exactly as given (may be malformed)."""
    return {"candidate": candidate, "expect": _expect(expect)}


def _expect(expect: tuple[Any, ...]) -> dict[str, Any]:
    """(outcome, codes), (outcome, codes, missing) or (outcome, codes, missing, parts): the
    decision a candidate must get. ``parts`` is a list of (role, passed) pairs."""
    out: dict[str, Any] = {"outcome": expect[0], "codes": expect[1]}
    if len(expect) > 2:
        out["missing"] = expect[2]
    if len(expect) > 3:
        out["parts"] = [{"role": role, "passed": passed} for role, passed in expect[3]]
    return out


def resolve(document: str, ev: Any, refs: dict[str, str] | None = None) -> Any:
    if isinstance(ev, list):
        return [resolve(document, item, refs) for item in ev]
    if not (isinstance(ev, dict) and "quote" in ev):
        return ev
    source = (refs or {})[ev["ref"]] if "ref" in ev else document
    data, needle = source.encode("utf-8"), ev["quote"].encode("utf-8")
    i = -1
    for _ in range(ev["n"]):
        i = data.find(needle, i + 1)
        if i < 0:
            raise SystemExit(f"quote {ev['quote']!r} occurrence {ev['n']} not in document")
    out = {k: v for k, v in ev.items() if k not in ("quote", "n", "text")}
    out.update({"start": i, "end": i + len(needle)})
    if ev["text"] is not NO_TEXT:
        out["text"] = ev["text"]
    return out


USD = {"type": "integer", "unit": "USD"}
JEV = {"id": "jev", "digest": "jev-1.13.0"}


def j(cid: str, question: str, p: float, answer: Any = None, judge: Any = None) -> dict[str, Any]:
    """A recorded judgment (SPEC §2.6) on the candidate with id ``cid``."""
    out: dict[str, Any] = {"candidate_id": cid, "question": question, "judge": judge or JEV}
    if question == "key":
        out["answer"] = answer
    out["p"] = p
    return out


# ---------------------------------------------------------------- admitted
vector(
    "01-admitted",
    "Values present at the cited span with the right unit are admitted; unit surfaces as prefix or suffix.",
    "For 2025, the contribution limit remains $7,000 ($8,000 for individuals age 50 or older). "
    "A late fee of 250 dollars applies. The starting dose is 500 mg once daily. Mean weight was 88.2 kg. "
    "Plan name: Retirement Savings Plus.",
    {
        "fields": {
            "limit": USD,
            "limit_50": USD,
            "late_fee": USD,
            "start_dose": {"type": "integer", "unit": "mg"},
            "weight": {"type": "number", "unit": "kg"},
            "plan_name": {"type": "string"},
        }
    },
    [
        c("a1", "limit", "7000", "USD", q("$7,000")),
        c("a2", "limit_50", 8000, "USD", q("$8,000")),
        c("a3", "late_fee", "250", "USD", q("250 dollars")),
        c("a4", "start_dose", "500", "mg", q("500 mg")),
        c("a5", "weight", "88.20", "kg", q("88.2 kg")),
        c("a6", "plan_name", "Retirement  Savings Plus", None, q("Retirement Savings Plus")),
    ],
)

# ---------------------------------------------------------------- structure
vector(
    "02-structure",
    "Malformed candidates are CANDIDATE_INVALID; unknown fields are FIELD_UNKNOWN.",
    "The fee is $40.",
    {"fields": {"fee": USD}},
    [
        raw("not an object", ("rejected", ["CANDIDATE_INVALID"])),
        raw({"id": "s2", "field": "fee"}, ("rejected", ["CANDIDATE_INVALID"])),
        raw(
            {"id": "s3", "field": "fee", "value": 40.5, "unit": "USD"},
            ("rejected", ["CANDIDATE_INVALID"]),
        ),
        raw(
            {"id": "s4", "field": "fee", "value": True, "unit": "USD"},
            ("rejected", ["CANDIDATE_INVALID"]),
        ),
        raw(
            {"id": "s5", "field": "fee", "value": "40", "unit": "USD", "evidence": {"start": 11}},
            ("rejected", ["CANDIDATE_INVALID"]),
        ),
        raw(
            {"id": "s6", "field": "fee", "value": "40", "unit": "USD", "confidence": 1.5},
            ("rejected", ["CANDIDATE_INVALID"]),
        ),
        raw({"id": "s7", "field": 3, "value": "40"}, ("rejected", ["CANDIDATE_INVALID"])),
        c("s8", "tax", "40", "USD", q("$40"), ("rejected", ["FIELD_UNKNOWN"])),
        c("s9", "Fee", "40", "USD", q("$40"), ("rejected", ["FIELD_UNKNOWN"])),
    ],
)

# ---------------------------------------------------------------- values
vector(
    "03-values",
    "Null literals, unparseable values, out-of-range values and unit mismatches are rejected before evidence is read.",
    "Adults take 500 mg twice daily. The fee is $1,250.",
    {
        "fields": {
            "dose": {"type": "integer", "unit": "mg", "minimum": 1, "maximum": "2000"},
            "fee": {"type": "integer", "unit": "USD"},
            "note": {"type": "string"},
        }
    },
    [
        c("v1", "dose", "null", "mg", q("500 mg"), ("rejected", ["NULL_STRING_LITERAL"])),
        c("v2", "fee", " N/A ", "USD", q("$1,250"), ("rejected", ["NULL_STRING_LITERAL"])),
        c("v3", "dose", "five hundred", "mg", q("500 mg"), ("rejected", ["TYPE_INVALID"])),
        c("v4", "fee", "1,25", "USD", q("$1,250"), ("rejected", ["TYPE_INVALID"])),
        c("v5", "dose", "500.5", "mg", q("500 mg"), ("rejected", ["TYPE_INVALID"])),
        c("v6", "note", "   ", None, q("Adults"), ("rejected", ["TYPE_INVALID"])),
        c("v7", "dose", "5000", "mg", q("500 mg"), ("rejected", ["RANGE_INVALID"])),
        c("v8", "dose", "0", "mg", q("500 mg"), ("rejected", ["RANGE_INVALID"])),
        c("v9", "dose", "500", "mcg", q("500 mg"), ("rejected", ["UNIT_INVALID"])),
        c("v10", "fee", "1250", None, q("$1,250"), ("rejected", ["UNIT_INVALID"])),
    ],
)

# ---------------------------------------------------------------- evidence
vector(
    "03b-indian-grouping",
    "A number grouped the Indian way (the last three digits, then pairs) has its value, in the "
    "document and in a candidate; a mix of the two groupings has none (spec 0.3).",
    "The exemption is Rs 2,00,000 per year. The cap is ₹12,34,567. The fund holds 1,00,00,000 "
    "rupees. The figures 1,23,456,789 and 252,0000 have no value. The fee is 25,000.",
    {
        "fields": {
            "exemption": {"type": "integer", "unit": "INR"},
            "exemption_as_written": {"type": "integer", "unit": "INR"},
            "cap": {"type": "integer", "unit": "INR"},
            "fund": {"type": "integer", "unit": "INR"},
            "mixed": {"type": "integer"},
            "bad_group": {"type": "integer"},
            "fee": {"type": "integer"},
            "mixed_value": {"type": "integer"},
        }
    },
    [
        c("i1", "exemption", "200000", "INR", q("2,00,000")),
        # a candidate value may be written with the same grouping
        c("i2", "exemption_as_written", "2,00,000", "INR", q("2,00,000")),
        c("i3", "cap", "1234567", "INR", q("12,34,567")),
        c("i4", "fund", "10000000", "INR", q("1,00,00,000")),
        # pairs after a group of three, and four digits after a comma: no value
        c(
            "i5",
            "mixed",
            "123456789",
            None,
            q("1,23,456,789"),
            ("rejected", ["VALUE_NOT_IN_EVIDENCE"]),
        ),
        c(
            "i6",
            "bad_group",
            "2520000",
            None,
            q("252,0000"),
            ("rejected", ["VALUE_NOT_IN_EVIDENCE"]),
        ),
        # grouping in threes still reads
        c("i7", "fee", "25000", None, q("25,000")),
        c(
            "i8",
            "mixed_value",
            "1,23,456,789",
            None,
            q("1,23,456,789"),
            ("rejected", ["TYPE_INVALID"]),
        ),
    ],
)

vector(
    "03c-ascii-digits",
    "A digit is an ASCII digit, 0 to 9. A number in other digits, such as Devanagari, is not a "
    "number token, nor are ASCII digits next to it, and a candidate value in other digits is "
    "invalid. Other digits still block a reading, as in a per-unit (spec 0.3).",
    "The limit is \u0968\u0966\u0966\u0966 rupees. The fee is 300 rupees. The cap is "
    "\u09682000 rupees. The floor is 2000\u0968 rupees. Give 250 mg/\u096b mL. The tip is "
    "2,\u0966\u0966\u0966 rupees. The rate is 7.\u0966 rupees.",
    {
        "fields": {
            "limit": {"type": "integer", "unit": "INR"},
            "fee": {"type": "integer", "unit": "INR"},
            "fee_written": {"type": "integer", "unit": "INR"},
            "cap": {"type": "integer", "unit": "INR"},
            "floor": {"type": "integer", "unit": "INR"},
            "dose": {"type": "number", "unit": "mg"},
            "tip": {"type": "integer", "unit": "INR"},
            "rate": {"type": "integer", "unit": "INR"},
        }
    },
    [
        # the evidence holds the text, but no number token
        c(
            "d1",
            "limit",
            "2000",
            "INR",
            q("\u0968\u0966\u0966\u0966"),
            ("rejected", ["VALUE_NOT_IN_EVIDENCE"]),
        ),
        c("d2", "fee", "300", "INR", q("300")),
        c(
            "d3",
            "fee_written",
            "\u0969\u0966\u0966",
            "INR",
            q("300"),
            ("rejected", ["TYPE_INVALID"]),
        ),
        # ASCII digits next to other digits are part of a number in other digits: no token
        c("d4", "cap", "2000", "INR", q("2000"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("d5", "floor", "2000", "INR", q("2000", n=2), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        # other digits still block: "mg/5 mL" in Devanagari is a concentration, not a dose
        c("d6", "dose", "250", "mg", q("250 mg"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        # nor after a grouping comma or a decimal point
        c(
            "d7",
            "tip",
            "2",
            "INR",
            q("2,\u0966\u0966\u0966"),
            ("rejected", ["VALUE_NOT_IN_EVIDENCE"]),
        ),
        c("d8", "rate", "7", "INR", q("7.\u0966"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
    ],
)

vector(
    "04-evidence",
    "Missing, invalid or unsupportive evidence is rejected.",
    "The limit is $7,000 and the fee is 30 dollars. Take 45 minutes. Altimeter 29.97 inches.",
    {
        "fields": {
            "limit": USD,
            "fee": USD,
            "wait": {"type": "integer", "unit": "minutes"},
            "altimeter": {"type": "number"},
        }
    },
    [
        c("e1", "limit", "7000", "USD", None, ("rejected", ["NO_EVIDENCE"])),
        c("e2", "fee", "30", "USD", None, ("rejected", ["NO_EVIDENCE"])),
        c("e3", "limit", "7000", "USD", {"start": 13, "end": 400}, ("rejected", ["SPAN_INVALID"])),
        c("e4", "limit", "7000", "USD", {"start": 13, "end": 13}, ("rejected", ["SPAN_INVALID"])),
        c("e5", "limit", "7000", "USD", {"start": -1, "end": 5}, ("rejected", ["SPAN_INVALID"])),
        c(
            "e6",
            "limit",
            "7000",
            "USD",
            q("$7,000"),
            ("rejected", ["SPAN_INVALID"]),
            search_region={"start": 10, "end": 2},
        ),
        c("e7", "limit", "70000", "USD", q("$7,000"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("e8", "fee", "7000", "USD", q("30 dollars"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("e9", "wait", "30", "minutes", q("30"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("e10", "fee", "45", "USD", q("45 minutes"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("e11", "altimeter", "29", None, q("29."), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
    ],
)

# ---------------------------------------------------------------- non-ASCII
PER_KG_UNITS = {
    "mg/kg": {"suffix": ["mg/kg"]},
    "mcg/kg/day": {"suffix": ["mcg/kg/day"]},
}
vector(
    "04b-per-units",
    "A unit followed by a per-body-size or per-volume denominator is not that unit; the first "
    "matching suffix after the number decides; per-time keeps the unit (spec 0.2).",
    "Give 10 mg/kg (maximum 500 mg) daily. Start at 1.6 mcg/kg/day. Infuse 75 mg/m2 on day 1. "
    "The dose is 2 mg per kilogram. Oral solution: 250 mg/5 mL. The maximum is 200 mg/day. "
    "Children take 5 to 10 mg/kg. Take 20 mg per day. Use 40 mg/m² weekly. Give 300 mg, "
    "or 5 mg/kg for children.",
    {
        "fields": {
            "dose": {"type": "number", "unit": "mg"},
            "dose_per_kg": {"type": "number", "unit": "mg/kg"},
            "cap": {"type": "number", "unit": "mg"},
            "levo": {"type": "number", "unit": "mcg"},
            "levo_per_kg": {"type": "number", "unit": "mcg/kg/day"},
            "infusion": {"type": "number", "unit": "mg"},
            "per_kilogram": {"type": "number", "unit": "mg"},
            "solution": {"type": "number", "unit": "mg"},
            "daily_max": {"type": "number", "unit": "mg"},
            "child_low": {"type": "number", "unit": "mg"},
            "daily": {"type": "number", "unit": "mg"},
            "weekly": {"type": "number", "unit": "mg"},
            "adult": {"type": "number", "unit": "mg"},
        },
        "units": PER_KG_UNITS,
    },
    [
        # the first mg after 10 is "mg/kg"; the "500 mg" later in the window does not count
        c("u1", "dose", "10", "mg", q("10 mg/kg"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("u2", "dose_per_kg", "10", "mg/kg", q("10 mg/kg")),
        c("u3", "cap", "500", "mg", q("500 mg")),
        c("u4", "levo", "1.6", "mcg", q("1.6 mcg/kg/day"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("u5", "levo_per_kg", "1.6", "mcg/kg/day", q("1.6 mcg/kg/day")),
        c("u6", "infusion", "75", "mg", q("75 mg/m2"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c(
            "u7",
            "per_kilogram",
            "2",
            "mg",
            q("2 mg per kilogram"),
            ("rejected", ["UNIT_NOT_IN_EVIDENCE"]),
        ),
        c("u8", "solution", "250", "mg", q("250 mg/5 mL"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("u9", "daily_max", "200", "mg", q("200 mg/day")),
        c(
            "u10",
            "child_low",
            "5",
            "mg",
            q("5 to 10 mg/kg"),
            ("rejected", ["UNIT_NOT_IN_EVIDENCE"]),
        ),
        c("u11", "daily", "20", "mg", q("20 mg per day")),
        c("u12", "weekly", "40", "mg", q("40 mg/m²"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("u13", "adult", "300", "mg", q("300 mg")),
    ],
)

vector(
    "04c-first-unit",
    "The first suffix of any unit in the table decides a number's unit, so another number's unit "
    "never supplies it; a list like '25 or 50 mg' keeps the unit (spec 0.2).",
    "Give 10 mcg (maximum 500 mg) daily. Take 25 or 50 mg once daily. "
    "Infuse 2 L in 4 hours, then 250 mL. Start at 10 units, then 5 mg.",
    {
        "fields": {
            "dose_mg": {"type": "integer", "unit": "mg", "multiple": True},
            "dose_mcg": {"type": "integer", "unit": "mcg"},
            "volume": {"type": "integer", "unit": "L"},
            "volume_ml": {"type": "integer", "unit": "mL"},
            "duration": {"type": "integer", "unit": "hours", "multiple": True},
            "insulin": {"type": "integer", "unit": "units"},
        },
        "units": {"units": {"suffix": ["units"]}},
    },
    [
        c("v1", "dose_mg", "10", "mg", q("10 mcg"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("v2", "dose_mcg", "10", "mcg", q("10 mcg")),
        c("v3", "dose_mg", "500", "mg", q("500 mg")),
        c("v4", "dose_mg", "25", "mg", q("25 or 50 mg")),
        c("v5", "volume", "2", "L", q("2 L")),
        c(
            "v6",
            "duration",
            "2",
            "hours",
            q("2 L in 4 hours"),
            ("rejected", ["UNIT_NOT_IN_EVIDENCE"]),
        ),
        c("v7", "duration", "4", "hours", q("4 hours")),
        c("v8", "volume_ml", "250", "mL", q("250 mL")),
        c("v9", "dose_mg", "10", "mg", q("10 units"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("v10", "insulin", "10", "units", q("10 units")),
        c("v11", "dose_mg", "5", "mg", q("5 mg")),
    ],
)

vector(
    "05-non-ascii",
    "Offsets are UTF-8 bytes; spans must fall on character boundaries.",
    "Café « naïve » prices: €4,500 per year. 価格は $3,000 です。Dose: 5 mg — ≈ daily.",
    {
        "fields": {
            "price_eur": {"type": "integer", "unit": "EUR"},
            "price_usd": USD,
            "dose": {"type": "integer", "unit": "mg"},
        }
    },
    [
        c("n1", "price_eur", "4500", "EUR", q("€4,500")),
        c("n2", "price_usd", "3000", "USD", q("$3,000")),
        c("n3", "dose", "5", "mg", q("5 mg")),
        c(
            "n4",
            "price_eur",
            "4500",
            "EUR",
            {"start": 4, "end": 30},
            ("rejected", ["SPAN_INVALID"]),
        ),
        raw(
            {
                "id": "n5",
                "field": "price_usd",
                "value": "3000",
                "unit": "USD",
                "evidence": {"start": 2.0, "end": 9},
            },
            ("rejected", ["CANDIDATE_INVALID"]),
        ),
    ],
)

# ---------------------------------------------------------------- collisions
vector(
    "06-collisions",
    "A number never matches inside another number, a malformed grouping, or a number cut off by the span.",
    "The threshold is $150,000. Contributions are barred at $252,0000 or more. Code 12345 applies. "
    "Mean change was -0.7 kg.",
    {
        "fields": {
            "t": USD,
            "bar": USD,
            "code": {"type": "integer"},
            "change": {"type": "number", "unit": "kg"},
        }
    },
    [
        c("k1", "t", "5", "USD", q("$150,000"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("k2", "t", "150", "USD", q("$150,000"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("k3", "bar", "252000", "USD", q("$252,0000"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("k4", "bar", "2520000", "USD", q("$252,0000"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c(
            "k5",
            "code",
            "123",
            None,
            q("123", text=NO_TEXT),
            ("rejected", ["VALUE_NOT_IN_EVIDENCE"]),
        ),
        c("k6", "code", "12345", None, q("12345")),
        c("k7", "change", "-0.7", "kg", q("-0.7 kg")),
    ],
)

# ---------------------------------------------------------------- qualifiers
vector(
    "07-qualifiers",
    "A qualifier that differs from the field's comparator flags the value for review.",
    "Tmax is reached in approximately 7 hours. The deduction phases out for income more than $126,000. "
    "You cannot contribute if income is $165,000 or more. Initiation is not recommended with an eGFR "
    "between 30 to 45 mL/minute. Up to 35% higher peaks were seen. The limit rose to $252,000 (up "
    "from $246,000 for 2025). Eligible ages run from 50 through 70.",
    {
        "fields": {
            "tmax": {"type": "integer", "unit": "hours"},
            "start": {"type": "integer", "unit": "USD", "comparator": "gt"},
            "start_eq": {"type": "integer", "unit": "USD"},
            "end": {"type": "integer", "unit": "USD", "comparator": "ge"},
            "end_eq": {"type": "integer", "unit": "USD"},
            "egfr_low": {"type": "integer"},
            "egfr_high": {"type": "integer"},
            "egfr_low_range": {"type": "integer", "comparator": "range"},
            "peak": {"type": "integer", "unit": "%"},
            "peak_le": {"type": "integer", "unit": "%", "comparator": "le"},
            "prior": {"type": "integer", "unit": "USD"},
            "age_low": {"type": "integer"},
            "age_high": {"type": "integer", "comparator": "range"},
        }
    },
    [
        c("q1", "tmax", "7", "hours", q("7 hours"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("q2", "start", "126000", "USD", q("$126,000")),
        c(
            "q3",
            "start_eq",
            "126000",
            "USD",
            q("$126,000"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        c("q4", "end", "165000", "USD", q("$165,000")),
        c(
            "q5",
            "end_eq",
            "165000",
            "USD",
            q("$165,000"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        c("q6", "egfr_low", "30", None, q("30"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("q7", "egfr_high", "45", None, q("45"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("q8", "egfr_low_range", "30", None, q("30")),
        c("q9", "peak", "35", "%", q("35%"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("q10", "peak_le", "35", "%", q("35%")),
        c("q11", "prior", "246000", "USD", q("$246,000")),  # "up from" is not a qualifier
        c("q12", "age_low", "50", None, q("50"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("q13", "age_high", "70", None, q("70")),
    ],
)

vector(
    "07b-negated-qualifiers",
    "Only the longest of overlapping qualifiers applies, and a negation directly before gt, lt, ge "
    "or le inverts it (spec 0.2).",
    "Your modified AGI must be no more than $7,000. The credit applies if income is not more than "
    "$40,000. Wages must not be more than $50,000. The deduction cannot be less than $1,200. Total "
    "gifts may not exceed $19,000. The payment does not exceed $2,500 in any year. The fee is not "
    "required if the balance is more than $600. Distributions must exceed $1,500. You need no less "
    "than $900 in the account. Your balance can't be over $3,000. Claims can\u2019t be under $100.",
    {
        "fields": {
            "agi_limit": {"type": "integer", "unit": "USD", "comparator": "le"},
            "agi_eq": USD,
            "income_limit": {"type": "integer", "unit": "USD", "comparator": "le"},
            "wage_limit": {"type": "integer", "unit": "USD", "comparator": "le"},
            "deduction_floor": {"type": "integer", "unit": "USD", "comparator": "ge"},
            "gift_limit": {"type": "integer", "unit": "USD", "comparator": "le"},
            "gift_eq": USD,
            "payment_limit": {"type": "integer", "unit": "USD", "comparator": "le"},
            "fee_threshold": {"type": "integer", "unit": "USD", "comparator": "le"},
            "distribution_eq": USD,
            "distribution_min": {"type": "integer", "unit": "USD", "comparator": "gt"},
            "account_floor": {"type": "integer", "unit": "USD", "comparator": "ge"},
            "balance_limit": {"type": "integer", "unit": "USD", "comparator": "le"},
            "claim_floor": {"type": "integer", "unit": "USD", "comparator": "ge"},
        }
    },
    [
        # "no more than" is le only; "more than" inside it does not also apply
        c("n1", "agi_limit", "7000", "USD", q("$7,000")),
        c("n2", "agi_eq", "7000", "USD", q("$7,000"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("n3", "income_limit", "40000", "USD", q("$40,000")),
        c("n4", "wage_limit", "50000", "USD", q("$50,000")),
        c("n5", "deduction_floor", "1200", "USD", q("$1,200")),
        c("n6", "gift_limit", "19000", "USD", q("$19,000")),
        # "exceed" is gt, so "may not exceed" is a qualifier (le) an eq field does not allow
        c(
            "n7",
            "gift_eq",
            "19000",
            "USD",
            q("$19,000"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        c("n8", "payment_limit", "2500", "USD", q("$2,500")),
        # "not" earlier in the sentence is not directly before "more than": still gt
        c(
            "n9",
            "fee_threshold",
            "600",
            "USD",
            q("$600"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        c(
            "n10",
            "distribution_eq",
            "1500",
            "USD",
            q("$1,500"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        c("n11", "distribution_min", "1500", "USD", q("$1,500")),
        c("n12", "account_floor", "900", "USD", q("$900")),
        c("n13", "balance_limit", "3000", "USD", q("$3,000")),
        c("n14", "claim_floor", "100", "USD", q("$100")),
    ],
)

vector(
    "07c-range-unit-words",
    "One unit or scale word between the first number and a word connector keeps the range, for "
    "both ends (spec 0.2).",
    "Take 30 mg to 45 mg daily. Keep levels between 10 mcg and 20 mcg. Reserves of $1 million to "
    "$2 million are held. Give 30 mg daily to 45 patients.",
    {
        "fields": {
            "dose_low": {"type": "integer", "unit": "mg"},
            "dose_high": {"type": "integer", "unit": "mg"},
            "dose_high_range": {"type": "integer", "unit": "mg", "comparator": "range"},
            "level_high": {"type": "integer", "unit": "mcg"},
            "reserve_high": USD,
            "patients": {"type": "integer"},
        }
    },
    [
        c("r1", "dose_low", "30", "mg", q("30 mg"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("r2", "dose_high", "45", "mg", q("45 mg"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("r3", "dose_high_range", "45", "mg", q("45 mg")),
        c(
            "r4",
            "level_high",
            "20",
            "mcg",
            q("20 mcg"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        c(
            "r5",
            "reserve_high",
            "2",
            "USD",
            q("$2 million"),
            ("needs_verification", ["QUALIFIED_VALUE", "SCALE_WORD"]),
        ),
        # two words between the numbers: not a range
        c("r6", "patients", "45", None, q("45 patients")),
    ],
)

vector(
    "07d-change-not-range",
    'After a change word, "from X to Y" is a change: Y is the new value and not a range end; X '
    "keeps the range reading (spec 0.2).",
    "The limit increased from $70,000 to $72,000 for 2026. The dose was reduced from 20 mg to 10 mg. "
    "Sessions run from 7 to 8 hours. The cap rose from $1 million to $2 million. Fees changed from "
    "$5 through $9.",
    {
        "fields": {
            "new_limit": USD,
            "old_limit": USD,
            "new_dose": {"type": "integer", "unit": "mg"},
            "old_dose": {"type": "integer", "unit": "mg"},
            "session_max": {"type": "integer", "unit": "hours"},
            "new_cap": USD,
            "new_fee": USD,
        }
    },
    [
        c("d1", "new_limit", "72000", "USD", q("$72,000")),
        # the old value keeps its range flag, so taking it for the new one is caught
        c(
            "d2",
            "old_limit",
            "70000",
            "USD",
            q("$70,000"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        c("d3", "new_dose", "10", "mg", q("10 mg")),
        c("d4", "old_dose", "20", "mg", q("20 mg"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # no change word: a real range, flagged as before
        c(
            "d5",
            "session_max",
            "8",
            "hours",
            q("8 hours"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        c("d6", "new_cap", "2", "USD", q("$2 million"), ("needs_verification", ["SCALE_WORD"])),
        c("d7", "new_fee", "9", "USD", q("$9")),
    ],
)

vector(
    "07e-change-at-a-distance",
    "A change word may stand a few words before `from` when the words between start with a "
    "determiner and hold no preposition, range word, digit or punctuation (spec 0.3).",
    "The agency is reducing the annual filing fee from $1,200 to $950. The limit increases from "
    "$70,000 to $72,000. An increase in the late fee from $25 to $40 applies in 2027. The board "
    "raised its cap on grants from $10,000 to $15,000. Children with increased body weight from 20 "
    "to 40 kg take the adult dose. The increase in the fee ranges from $31 to $37. The rule lowered "
    "the maximum annual civil monetary penalty amount from $500 to $650. The fee decreased, as "
    "noted, from $81 to $66. The board increased the 2026 fee from $300 to $350.",
    {
        "fields": {
            "filing_fee": USD,
            "old_filing_fee": USD,
            "limit": USD,
            "late_fee": USD,
            "grant_cap": USD,
            "weight_max": {"type": "integer", "unit": "kg"},
            "fee_max": USD,
            "penalty": USD,
            "fee_noted": USD,
            "fee_2026": USD,
        }
    },
    [
        # determiner, then up to six words: a change
        c("e1", "filing_fee", "950", "USD", q("$950")),
        c(
            "e2",
            "old_filing_fee",
            "1200",
            "USD",
            q("$1,200"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        # every form of a change word counts, not only the past tense
        c("e3", "limit", "72000", "USD", q("$72,000")),
        # "in" may come first, before the determiner
        c("e4", "late_fee", "40", "USD", q("$40")),
        # a preposition between them: "from" can belong to "grants"
        c(
            "e5",
            "grant_cap",
            "15000",
            "USD",
            q("$15,000"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        # no determiner: "increased" describes the weight, so it stays a range
        c("e6", "weight_max", "40", "kg", q("40 kg"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # a range word between them wins
        c("e7", "fee_max", "37", "USD", q("$37"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # seven words between them: too far
        c("e8", "penalty", "650", "USD", q("$650"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # punctuation between them
        c("e9", "fee_noted", "66", "USD", q("$66"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # a digit between them
        c("e10", "fee_2026", "350", "USD", q("$350"), ("needs_verification", ["QUALIFIED_VALUE"])),
    ],
)

vector(
    "07f-abbreviation-dots",
    "For the qualifier window only, the dot of a listed abbreviation does not end a sentence when "
    "the next character is a lowercase letter, a digit or a currency sign, so a qualifier before "
    "it still applies; key scope still ends there. `approx` is a qualifier (spec 0.3).",
    "The refund is up to Rs. 50,000 a year. Take approx. 5 mg a day. Take approx 6 mg at night. "
    "The office is open from 6 p.m. to 8 p.m. on weekdays. Taxes are at most due in the U.S. The "
    "fee is $30. Taxes are at most due in the U.S.\r\n\r\nfee is $45. Pay approx. $12 a month. "
    "For hypertension, the package weight is 3 lb. 9 mg is the dose for heart failure. For "
    "hypertension, ship packs of 2 lb. (Heart failure dose is 7 mg.)",
    {
        "fields": {
            "refund": {"type": "integer", "unit": "INR"},
            "day_dose": {"type": "integer", "unit": "mg"},
            "night_dose": {"type": "integer", "unit": "mg"},
            "closing_hour": {"type": "integer"},
            "fee": USD,
            "crlf_fee": USD,
            "monthly": USD,
            "keyed_dose": {
                "type": "number",
                "unit": "mg",
                "keys": ["Hypertension", "Heart Failure"],
            },
            "weight_dose": {
                "type": "number",
                "unit": "mg",
                "keys": ["Hypertension", "Heart Failure"],
            },
        }
    },
    [
        # "up to" before "Rs.": one sentence now, so the value is qualified
        c("a1", "refund", "50000", "INR", q("50,000"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("a2", "day_dose", "5", "mg", q("5 mg"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("a3", "night_dose", "6", "mg", q("6 mg"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # the first "p.m." no longer cuts the range
        c("a4", "closing_hour", "8", None, q("8"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # "U.S." does not end the sentence, even before an uppercase word (vector 07g)
        c("a5", "fee", "30", "USD", q("$30"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # a blank line ends the sentence, with Windows line endings too
        c("a6", "crlf_fee", "45", "USD", q("$45")),
        # a currency sign after the dot keeps the sentence going
        c("a7", "monthly", "12", "USD", q("$12"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # a parenthesis after the dot ends it, so the other sentence's key does not reach 7 mg
        c(
            "a8",
            "keyed_dose",
            "7",
            "mg",
            q("7 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="Hypertension",
        ),
        # a join never moves a key: key scope still ends at every dot
        c(
            "a9",
            "weight_dose",
            "9",
            "mg",
            q("9 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="Hypertension",
        ),
    ],
)

vector(
    "07g-us-and-number-dots",
    "For the qualifier window only, the dot of `U.S.` never ends a sentence, and the dot of `No.` "
    "or `Nos.` does not end one when the next word holds a digit or starts with two uppercase "
    "letters. A blank line still ends the sentence, and key scope still ends at every dot "
    "(spec 0.3).",
    "Fees are up to the U.S. Code cap of $60. At most the sum in Docket No. FDA-N is $75. Is "
    "the fee at most a guess? No. The fee is $80. At least Nos. A1 and A2 cost $90. Fees are at "
    "most paid in the U.S.\n\nThe fee is $95. For hypertension, ask in "
    "the U.S. Heart failure dose is 7 mg.",
    {
        "fields": {
            "code_fee": USD,
            "docket_fee": USD,
            "answer_fee": USD,
            "item_fee": USD,
            "blank_fee": USD,
            "keyed_dose": {
                "type": "number",
                "unit": "mg",
                "keys": ["Hypertension", "Heart Failure"],
            },
        }
    },
    [
        # "U.S." before an uppercase word: one sentence, so "up to" qualifies $60
        c("u1", "code_fee", "60", "USD", q("$60"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # "No." before a code that starts with two uppercase letters
        c("u2", "docket_fee", "75", "USD", q("$75"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # "No." before a word that is not a code ends the sentence, so "at most" stays out
        c("u3", "answer_fee", "80", "USD", q("$80")),
        # "Nos." before a word that holds a digit
        c("u4", "item_fee", "90", "USD", q("$90"), ("needs_verification", ["QUALIFIED_VALUE"])),
        # a blank line after "U.S." still ends the sentence
        c("u5", "blank_fee", "95", "USD", q("$95")),
        # a join never moves a key: the key of the sentence before "U.S." does not reach 7 mg
        c(
            "u6",
            "keyed_dose",
            "7",
            "mg",
            q("7 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="Hypertension",
        ),
    ],
)

# ---------------------------------------------------------------- scale words
vector(
    "08-scale",
    "A scale word after the value flags it; the value alone understates the quantity.",
    "The fund holds $2.5 million in reserves. The exemption is 4 lakh rupees. The fee is $900 per year.",
    {
        "fields": {
            "reserves": {"type": "number", "unit": "USD"},
            "exemption": {"type": "integer", "unit": "INR"},
            "fee": USD,
        }
    },
    [
        c(
            "m1",
            "reserves",
            "2.5",
            "USD",
            q("$2.5 million"),
            ("needs_verification", ["SCALE_WORD"]),
        ),
        c(
            "m2",
            "exemption",
            "4",
            "INR",
            q("4 lakh rupees"),
            ("needs_verification", ["SCALE_WORD"]),
        ),
        c("m3", "fee", "900", "USD", q("$900")),
    ],
)

vector(
    "08b-scaled-values",
    "A number followed by a scale word also has its scaled value; a candidate equal to it passes "
    "and is not flagged SCALE_WORD (spec 0.2).",
    "The fund holds $2.5 million in reserves. Grants total $1.25 billion. The exemption is 4 lakh "
    "rupees. The pool is 3 crore rupees. Staff earned 45 thousand dollars. Millions of dollars were "
    "spent. The cap rose from $1 million to $2 million. Donors gave $3 million.",
    {
        "fields": {
            "reserves": {"type": "number", "unit": "USD"},
            "reserves_wrong": {"type": "number", "unit": "USD"},
            "grants": USD,
            "exemption": {"type": "integer", "unit": "INR"},
            "pool": {"type": "integer", "unit": "INR"},
            "pay": USD,
            "spent": USD,
            "new_cap": USD,
            "old_cap": USD,
            "donations": USD,
        }
    },
    [
        c("v1", "reserves", "2500000", "USD", q("$2.5 million")),
        # neither the written 2.5 nor the scaled 2,500,000
        c(
            "v2",
            "reserves_wrong",
            "250000",
            "USD",
            q("$2.5 million"),
            ("rejected", ["VALUE_NOT_IN_EVIDENCE"]),
        ),
        c("v3", "grants", "1250000000", "USD", q("$1.25 billion")),
        c("v4", "exemption", "400000", "INR", q("4 lakh rupees")),
        c("v5", "pool", "30000000", "INR", q("3 crore rupees")),
        c("v6", "pay", "45000", "USD", q("45 thousand dollars")),
        # a scale word with no number has no value
        c(
            "v7",
            "spent",
            "1000000",
            "USD",
            q("Millions of dollars"),
            ("rejected", ["VALUE_NOT_IN_EVIDENCE"]),
        ),
        # with #4: the new value is neither a range end nor flagged SCALE_WORD
        c("v8", "new_cap", "2000000", "USD", q("$2 million")),
        c(
            "v9",
            "old_cap",
            "1000000",
            "USD",
            q("$1 million"),
            ("needs_verification", ["QUALIFIED_VALUE"]),
        ),
        # the scale word is read from the document, like a unit, even past the span
        c("v10", "donations", "3000000", "USD", q("$3")),
    ],
)

# ---------------------------------------------------------------- verbatim
vector(
    "09-verbatim",
    "Evidence text that differs from the cited span is flagged; whitespace and line-break hyphenation are not.",
    "The maximum is 2,000 mg once daily with the evening meal. The limit for a mar-\nried couple is $146,000.",
    {"fields": {"max": {"type": "integer", "unit": "mg", "comparator": "le"}, "mfj": USD}},
    [
        c(
            "t1",
            "max",
            "2000",
            "mg",
            q("2,000 mg", text="2000 milligrams"),
            ("needs_verification", ["NON_VERBATIM_EVIDENCE"]),
        ),
        c("t2", "max", "2000", "mg", q("2,000 mg once daily", text="2,000   mg once\ndaily")),
        c(
            "t3",
            "mfj",
            "146000",
            "USD",
            q("mar-\nried couple is $146,000", text="married couple is $146,000"),
        ),
        c(
            "t4",
            "mfj",
            "146000",
            "USD",
            q("$146,000", text="$146,000 dollars"),
            ("needs_verification", ["NON_VERBATIM_EVIDENCE"]),
        ),
    ],
)

# ---------------------------------------------------------------- confidence
vector(
    "10-confidence",
    "Below-threshold confidence flags the value; absent confidence does not.",
    "The fee is $40. The rate is 5%.",
    {"fields": {"fee": USD, "rate": {"type": "integer", "unit": "%"}}},
    [
        c(
            "f1",
            "fee",
            "40",
            "USD",
            q("$40"),
            ("needs_verification", ["LOW_CONFIDENCE"]),
            confidence=0.42,
        ),
        c(
            "f2",
            "rate",
            "5",
            "%",
            q("5%"),
            ("needs_verification", ["LOW_CONFIDENCE"]),
            confidence=0,
        ),
        c("f3", "fee", "40", "USD", q("$40"), confidence=0.9),
        c("f4", "rate", "5", "%", q("5%")),
    ],
    policy={"min_confidence": 0.8},
)

# ---------------------------------------------------------------- conflicts
vector(
    "11-conflicts",
    "Surviving candidates that disagree on a single-valued field are all flagged.",
    "The 2025 limit is $7,000. The 2026 limit is $7,500. Strengths: 500 mg and 750 mg tablets.",
    {
        "fields": {
            "limit_2025": USD,
            "limit_2026": USD,
            "strength": {"type": "integer", "unit": "mg", "multiple": True},
        }
    },
    [
        c(
            "x1",
            "limit_2025",
            "7000",
            "USD",
            q("$7,000"),
            ("needs_verification", ["CONFLICTING_CANDIDATES"]),
        ),
        c(
            "x2",
            "limit_2025",
            "7500",
            "USD",
            q("$7,500"),
            ("needs_verification", ["CONFLICTING_CANDIDATES"]),
        ),
        c("x3", "limit_2026", "7500", "USD", q("$7,500")),
        c("x4", "limit_2026", "7500", "USD", q("$7,500"), source="second-model"),
        c("x5", "limit_2026", "75000", "USD", q("$7,500"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("x6", "strength", "500", "mg", q("500 mg", text=NO_TEXT)),
        c("x7", "strength", "750", "mg", q("750 mg", text=NO_TEXT)),
    ],
)

# ---------------------------------------------------------------- re-anchoring
vector(
    "12-reanchor",
    "When the cited span fails, exactly one other passing occurrence of the quote in the search region "
    "re-anchors the evidence.",
    "See section (5.1). Lactate above 5 mmol/L is a risk. Plasma levels are below 1 mcg/mL. "
    "Store 5 units; levels of 5 mcg/mL and 5 mcg/mL were both seen.",
    {
        "fields": {
            "lactate": {"type": "integer", "unit": "mmol/L", "comparator": "gt"},
            "plasma": {"type": "integer", "unit": "mcg/mL", "comparator": "lt"},
            "seen": {"type": "integer", "unit": "mcg/mL"},
        },
        "units": {"mmol/L": {"suffix": ["mmol/L"]}, "mcg/mL": {"suffix": ["mcg/mL"]}},
    },
    [
        c("r1", "lactate", "5", "mmol/L", q("5"), ("admitted", ["EVIDENCE_REANCHORED"])),
        c(
            "r2",
            "plasma",
            "1",
            "mcg/mL",
            q("1", n=1, text="1"),
            ("admitted", ["EVIDENCE_REANCHORED"]),
        ),
        c("r3", "seen", "5", "mcg/mL", q("5"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c(
            "r4",
            "seen",
            "5",
            "mcg/mL",
            q("5"),
            ("admitted", ["EVIDENCE_REANCHORED"]),
            search_region={"quote": "levels of 5 mcg/mL", "n": 1, "text": NO_TEXT},
        ),
        c(
            "r5",
            "lactate",
            "5",
            "mmol/L",
            q("5", text=NO_TEXT),
            ("rejected", ["VALUE_NOT_IN_EVIDENCE"]),
        ),
    ],
)
vector(
    "13-reanchor-off",
    "With policy reanchor false, a failing cited span is rejected even when the quote occurs elsewhere.",
    "See section (5.1). Lactate above 5 mmol/L is a risk.",
    {
        "fields": {"lactate": {"type": "integer", "unit": "mmol/L", "comparator": "gt"}},
        "units": {"mmol/L": {"suffix": ["mmol/L"]}},
    },
    [
        c("o1", "lactate", "5", "mmol/L", q("5"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("o2", "lactate", "5", "mmol/L", q("5 mmol/L")),
    ],
    policy={"reanchor": False},
)

# ---------------------------------------------------------------- coverage
vector(
    "14-coverage",
    "Required fields with no surviving candidate are reported; flagged candidates count as surviving.",
    "The 2025 limit is about $7,000. The fee is $40.",
    {
        "fields": {
            "limit": {"type": "integer", "unit": "USD", "required": True},
            "fee": {"type": "integer", "unit": "USD", "required": True},
            "age": {"type": "integer", "required": True},
            "bonus": {"type": "integer", "unit": "USD", "required": True},
        }
    },
    [
        c("g1", "limit", "7000", "USD", q("$7,000"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("g2", "fee", "400", "USD", q("$40"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
    ],
    coverage=[
        {"field": "age", "code": "REQUIRED_FIELD_MISSING"},
        {"field": "bonus", "code": "REQUIRED_FIELD_MISSING"},
        {"field": "fee", "code": "REQUIRED_FIELD_MISSING"},
    ],
)

# ---------------------------------------------------------------- flags combine
vector(
    "15-combined",
    "Flags combine, in the order the spec lists them, and re-anchoring is reported last.",
    "Ref (2). Reserves of about $2 million were held. Reserves of about $2 million were held.",
    {"fields": {"reserves": {"type": "number", "unit": "USD"}}},
    [
        c(
            "b1",
            "reserves",
            "2",
            "USD",
            q("$2 million", n=1, text="$2 million"),
            ("needs_verification", ["QUALIFIED_VALUE", "SCALE_WORD", "LOW_CONFIDENCE"]),
            confidence=0.1,
        ),
        c(
            "b2",
            "reserves",
            "2",
            "USD",
            q("(2)", text="$2 million."),
            ("needs_verification", ["NON_VERBATIM_EVIDENCE", "PART_MISSING"], ["unit"]),
        ),
    ],
    policy={"min_confidence": 0.5},
)

# ---------------------------------------------------------------- a realistic label
vector(
    "16-label",
    "An invented drug-label excerpt exercising most codes together.",
    "DOSAGE: The recommended starting dose is 250 mg once daily. Increase by 250 mg every week, up to "
    "a maximum of 1,500 mg per day. Section (4.2) lists contraindications: do not use if eGFR is below "
    "30 mL/min. Tablets: 250 mg and 500 mg.",
    {
        "fields": {
            "start_dose": {"type": "integer", "unit": "mg", "required": True},
            "increment": {"type": "integer", "unit": "mg"},
            "max_daily": {"type": "integer", "unit": "mg", "comparator": "le", "maximum": 3000},
            "egfr_floor": {"type": "integer", "unit": "mL/min", "comparator": "lt"},
            "strength": {"type": "integer", "unit": "mg", "multiple": True},
            "duration": {"type": "integer", "unit": "weeks", "required": True},
        },
        "units": {"mL/min": {"suffix": ["mL/min"]}},
    },
    [
        c(
            "L1",
            "start_dose",
            "250",
            "mg",
            q("250 mg"),
            ("needs_verification", ["CONFLICTING_CANDIDATES"]),
        ),
        c(
            "L2",
            "start_dose",
            "500",
            "mg",
            q("500 mg", n=2),
            ("needs_verification", ["CONFLICTING_CANDIDATES"]),
        ),
        c("L3", "increment", "250", "mg", q("250 mg", n=2)),
        c("L4", "max_daily", "1500", "mg", q("1,500 mg")),
        c("L5", "max_daily", "4000", "mg", q("1,500 mg"), ("rejected", ["RANGE_INVALID"])),
        c("L6", "egfr_floor", "30", "mL/min", q("30 mL/min")),
        c(
            "L7",
            "egfr_floor",
            "null",
            "mL/min",
            q("30 mL/min"),
            ("rejected", ["NULL_STRING_LITERAL"]),
        ),
        c("L8", "increment", "250mg", "mg", q("250 mg", n=2), ("rejected", ["TYPE_INVALID"])),
        c("L9", "strength", "250", "mg", q("250 mg", n=3, text=NO_TEXT)),
        c("L10", "strength", "500", "mg", q("500 mg", n=2, text=NO_TEXT)),
        c("L11", "frequency", "1", None, q("once daily"), ("rejected", ["FIELD_UNKNOWN"])),
        c("L12", "increment", "250", "mcg", q("250 mg", n=2), ("rejected", ["UNIT_INVALID"])),
        c("L13", "duration", "1", "weeks", None, ("rejected", ["NO_EVIDENCE"])),
        c(
            "L14",
            "max_daily",
            "1500",
            "mg",
            q("4.2", text="1,500 mg per day"),
            ("admitted", ["EVIDENCE_REANCHORED"]),
        ),
        c(
            "L15",
            "egfr_floor",
            "30",
            "mL/min",
            q("30 mL/min", text="30 mL per minute"),
            ("needs_verification", ["NON_VERBATIM_EVIDENCE"]),
        ),
        # the first bytes "500 mg" sit inside "1,500 mg": never read there, re-anchored to the real one
        c("L16", "strength", "500", "mg", q("500 mg", n=1), ("admitted", ["EVIDENCE_REANCHORED"])),
        c(
            "L17",
            "strength",
            "500",
            "mg",
            q("500 mg", n=1, text=NO_TEXT),
            ("rejected", ["VALUE_NOT_IN_EVIDENCE"]),
        ),
    ],
    coverage=[{"field": "duration", "code": "REQUIRED_FIELD_MISSING"}],
)

# ---------------------------------------------------------------- keyed fields
CONDITIONS = ["hypertension", "heart failure", "acute myocardial infarction"]
KEYED_MG = {"type": "number", "unit": "mg", "keys": CONDITIONS}

vector(
    "17-keyed-fields",
    "A keyed field needs one of its keys. A key mentioned in the value's sentence decides; "
    "otherwise the nearest mention before the value, such as a heading, decides.",
    "2 DOSAGE AND ADMINISTRATION\nTake 20 mg tablets with water.\n\n"
    "2.1 Hypertension\nThe recommended starting dose is 10 mg once daily. "
    "The maximum dose is 40 mg daily.\n\n"
    "2.2 Heart Failure\nThe recommended starting dose is 5 mg once daily, taken with diuretics.\n\n"
    "2.3 Acute Myocardial Infarction\nGive 5 mg within 24 hours. "
    "In patients who also have heart failure, start at 2.5 mg.",
    {
        "fields": {
            "starting_dose": KEYED_MG,
            "max_dose": KEYED_MG,
            "adjusted_dose": KEYED_MG,
            "strength": {"type": "integer", "unit": "mg"},
        }
    },
    [
        c("k1", "starting_dose", "10", "mg", q("10 mg"), key="hypertension"),
        c("k2", "max_dose", "40", "mg", q("40 mg"), key="hypertension"),
        c(
            "k3",
            "max_dose",
            "40",
            "mg",
            q("40 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="heart failure",
        ),
        c("k4", "starting_dose", "5", "mg", q("5 mg once"), key="heart failure"),
        c("k5", "starting_dose", "5", "mg", q("5 mg within"), key="acute myocardial infarction"),
        c("k6", "adjusted_dose", "2.5", "mg", q("2.5 mg"), key="heart failure"),
        c(
            "k7",
            "adjusted_dose",
            "2.5",
            "mg",
            q("2.5 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="acute myocardial infarction",
        ),
        c(
            "k8",
            "adjusted_dose",
            "20",
            "mg",
            q("20 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="hypertension",
        ),
        c("k9", "strength", "20", "mg", q("20 mg"), key="any text"),
        c("k10", "starting_dose", "10", "mg", q("10 mg"), ("rejected", ["KEY_INVALID"])),
        c(
            "k11",
            "starting_dose",
            "10",
            "mg",
            q("10 mg"),
            ("rejected", ["KEY_INVALID"]),
            key="Hypertension",
        ),
        c(
            "k12",
            "starting_dose",
            "10",
            "mg",
            q("10 mg"),
            ("rejected", ["CANDIDATE_INVALID"]),
            key=1,
        ),
        c("k13", "starting_dose", "10", "g", q("10 mg"), ("rejected", ["UNIT_INVALID"])),
        c("k14", "starting_dose", "10", "mg", None, ("rejected", ["KEY_INVALID"])),
    ],
)

vector(
    "17b-keyed-tables",
    "Conflicts are per field and key. Rows of a flattened table share one sentence. When it holds "
    "3 or more line breaks and mentions 2 or more keys, a value is at the keys on its own line "
    "(spec 0.3).",
    "Table 1. Recommended Dosage\nIndication\tStarting dose\tMaximum dose\n"
    "Hypertension\t10 mg\t40 mg\nHeart failure\t5 mg\t20 mg\n\n"
    "In heart failure, titrate every 2 weeks. The usual starting dose is 5 mg. "
    "Patients with hypertension start at 10 mg. Take it once daily for heart failure.",
    {
        "fields": {
            "starting_dose": KEYED_MG,
            "max_dose": KEYED_MG,
            "frequency": {"type": "string", "keys": CONDITIONS},
        }
    },
    [
        c(
            "t1",
            "starting_dose",
            "10",
            "mg",
            q("10 mg"),
            ("needs_verification", ["CONFLICTING_CANDIDATES"]),
            key="hypertension",
        ),
        c("t2", "starting_dose", "5", "mg", q("5 mg"), key="heart failure"),
        # 40 mg is on the hypertension row, so heart failure no longer reaches it
        c(
            "t3",
            "max_dose",
            "40",
            "mg",
            q("40 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="heart failure",
        ),
        c(
            "t4",
            "starting_dose",
            "10",
            "mg",
            q("10 mg", n=2),
            ("needs_verification", ["CONFLICTING_CANDIDATES"]),
            key="hypertension",
        ),
        c(
            "t5",
            "starting_dose",
            "5",
            "mg",
            q("5 mg", n=2),
            ("needs_verification", ["KEY_NOT_AT_VALUE", "CONFLICTING_CANDIDATES"]),
            key="hypertension",
        ),
        c(
            "t6",
            "starting_dose",
            "5",
            "mg",
            q("5 mg"),
            ("rejected", ["KEY_INVALID"]),
            key="renal impairment",
        ),
        c("t7", "frequency", "once daily", None, q("once daily"), key="heart failure"),
        c(
            "t8",
            "frequency",
            "once daily",
            None,
            q("once daily"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="hypertension",
        ),
    ],
)

vector(
    "17c-label-lines",
    "When the value's sentence mentions no key, a label line between the nearest earlier mention "
    "and the value puts the value at no key: a line of at most 12 words with a blank line or the "
    "start of the text before it and a blank line after it, with no sentence end in it and no "
    "final `.` or `;`. Such a line names a condition in a form that is not a key (spec 0.3).",
    "2.1 Hypertension\n\nThe starting dose is 10 mg once daily.\n\n"
    "Treatment of HF:\n\nThe starting dose is 5 mg once daily.\n\n"
    "2.2 Heart Failure\n\nDo not crush;  \n\nThe maximum dose is 20 mg daily.\n\n"
    "Take it with water and food at the same time each day, as your doctor tells you\n\n"
    "The low dose is 2.5 mg daily.\n\n"
    "Older adults\nThe last dose is 7.5 mg daily.\n\n"
    "Adults\n\nThe usual dose is 15 mg daily.",
    {
        "fields": {
            "starting_dose": KEYED_MG,
            "hf_starting_dose": KEYED_MG,
            "max_dose": KEYED_MG,
            "low_dose": KEYED_MG,
            "last_dose": KEYED_MG,
            "usual_dose": KEYED_MG,
        }
    },
    [
        # a heading that is a key mention still reaches past its blank line
        c("l1", "starting_dose", "10", "mg", q("10 mg"), key="hypertension"),
        # "Treatment of HF:" is a label line, so the earlier heading no longer reaches 5 mg
        c(
            "l2",
            "hf_starting_dose",
            "5",
            "mg",
            q("5 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="hypertension",
        ),
        # the short form is not a key, so the right key goes to review too
        c(
            "l3",
            "hf_starting_dose",
            "5",
            "mg",
            q("5 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="heart failure",
        ),
        # a line with ";" before its line break is not a label line, even with spaces between
        c("l4", "max_dose", "20", "mg", q("20 mg"), key="heart failure"),
        # a line of more than 12 words is not a label line
        c("l5", "low_dose", "2.5", "mg", q("2.5 mg"), key="heart failure"),
        # a line with no blank line after it is not a label line
        c("l6", "last_dose", "7.5", "mg", q("7.5 mg"), key="heart failure"),
        # a subheading that is not a key is a label line: the right key goes to review
        c(
            "l7",
            "usual_dose",
            "15",
            "mg",
            q("15 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="heart failure",
        ),
    ],
)

vector(
    "17d-table-sentences",
    "A table sentence holds 3 or more line breaks and mentions 2 or more keys. A value in it is "
    "at the keys mentioned on its own line, or at no key when its line mentions none (spec 0.3).",
    "Recommended dosage\nIndication\nStarting dose\nHypertension\n10 mg\nHeart failure\n5 mg\n\n"
    "For hypertension or heart failure, the maximum\ndose is 40 mg.\n\n"
    "In hypertension and heart failure, take 20 mg\nat night\nwith water\nor food.",
    {
        "fields": {
            "starting_dose": KEYED_MG,
            "hf_starting_dose": KEYED_MG,
            "max_dose": KEYED_MG,
            "night_dose": KEYED_MG,
        }
    },
    [
        # one cell on each line: the value's line mentions no key, so the right key goes to review
        c(
            "d1",
            "starting_dose",
            "10",
            "mg",
            q("10 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="hypertension",
        ),
        c(
            "d2",
            "hf_starting_dose",
            "5",
            "mg",
            q("5 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="heart failure",
        ),
        # and a swapped key is no longer admitted
        c(
            "d3",
            "hf_starting_dose",
            "5",
            "mg",
            q("5 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="hypertension",
        ),
        # 1 line break is not a table: the sentence puts 40 mg at both keys
        c("d4", "max_dose", "40", "mg", q("40 mg"), key="heart failure"),
        # a table sentence whose value line mentions both keys
        c("d5", "night_dose", "20", "mg", q("20 mg"), key="hypertension"),
    ],
)

# ---------------------------------------------------------------- recorded judgments
vector(
    "18-judgments-key",
    "A recorded key judgment clears KEY_NOT_AT_VALUE when it chooses the candidate's key with p at "
    "or above the policy's threshold, and adds MODEL_DOUBT when it chooses another key or none at "
    "that p. Judgments of another judge, on a rejected candidate, or for a question the policy "
    "does not name change nothing.",
    "2 DOSAGE AND ADMINISTRATION\nTake 20 mg tablets with water.\n\n"
    "2.1 Hypertension\nThe recommended starting dose is 10 mg once daily. "
    "The maximum dose is 40 mg daily.\n\n"
    "2.2 Heart Failure\nThe recommended starting dose is 5 mg once daily, taken with diuretics.\n\n"
    "2.3 Acute Myocardial Infarction\nGive 5 mg within 24 hours. "
    "In patients who also have heart failure, start at 2.5 mg.",
    {
        "fields": {
            "starting_dose": KEYED_MG,
            "max_dose": KEYED_MG,
            "adjusted_dose": KEYED_MG,
        }
    },
    [
        # cleared at exactly the threshold
        c(
            "j1",
            "max_dose",
            "40",
            "mg",
            q("40 mg"),
            ("admitted", ["MODEL_CLEARED"]),
            key="heart failure",
        ),
        # the right key, below the threshold: no change
        c(
            "j2",
            "adjusted_dose",
            "2.5",
            "mg",
            q("2.5 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="acute myocardial infarction",
        ),
        # none, at the threshold: doubt, and the flag stays
        c(
            "j3",
            "adjusted_dose",
            "20",
            "mg",
            q("20 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE", "MODEL_DOUBT"]),
            key="hypertension",
        ),
        # another model version: ignored
        c(
            "j4",
            "max_dose",
            "40",
            "mg",
            q("40 mg"),
            ("needs_verification", ["KEY_NOT_AT_VALUE"]),
            key="acute myocardial infarction",
        ),
        # a rejection stays a rejection
        c("j5", "starting_dose", "10", "mg", q("10 mg"), ("rejected", ["KEY_INVALID"])),
        # the key flag clears, the quote flag stays
        c(
            "j6",
            "max_dose",
            "40",
            "mg",
            q("40 mg", text="40 mgs"),
            ("needs_verification", ["NON_VERBATIM_EVIDENCE", "MODEL_CLEARED"]),
            key="heart failure",
        ),
        # the policy names no field_match threshold: ignored
        c("j7", "starting_dose", "10", "mg", q("10 mg"), key="hypertension"),
    ],
    policy={"judge": {**JEV, "clear": {"KEY_NOT_AT_VALUE": 0.9}}},
    judgments=[
        j("j1", "key", 0.9, "heart failure"),
        j("j2", "key", 0.85, "acute myocardial infarction"),
        j("j3", "key", 0.97, None),
        j("j4", "key", 0.99, "acute myocardial infarction", {"id": "jev", "digest": "jev-1.12.0"}),
        j("j5", "key", 0.99, "hypertension"),
        j("j6", "key", 0.95, "heart failure"),
        j("j7", "field_match", 0.0),
    ],
)

vector(
    "18b-judgments-field",
    "A recorded field_match judgment whose p is below the policy's threshold adds MODEL_DOUBT to a "
    "candidate that passes steps 1 to 11, so it goes to review. It never admits a value, and a "
    "rejection stays a rejection.",
    "The annual fee is $40. The late fee is $15. A processing fee of $5 applies. "
    "The reserve is $2 million.",
    {
        "fields": {
            "annual_fee": USD,
            "deposit": USD,
            "late_fee": USD,
            "processing_fee": USD,
            "reserve": USD,
        }
    },
    [
        c("f1", "annual_fee", 40, "USD", q("$40")),
        # a number of another field: doubted
        c("f2", "deposit", 40, "USD", q("$40"), ("needs_verification", ["MODEL_DOUBT"])),
        # no judgment: as in 0.3
        c("f3", "late_fee", 15, "USD", q("$15")),
        # p equal to the threshold is not below it
        c("f4", "processing_fee", 5, "USD", q("$5")),
        # doubt joins a flag
        c(
            "f5",
            "reserve",
            2,
            "USD",
            q("$2 million"),
            ("needs_verification", ["SCALE_WORD", "MODEL_DOUBT"]),
        ),
        c("f6", "late_fee", 99, "USD", q("$15"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
    ],
    policy={"judge": {**JEV, "doubt": {"field_match": 0.2}}},
    judgments=[
        j("f1", "field_match", 0.9),
        j("f2", "field_match", 0.05),
        j("f4", "field_match", 0.2),
        j("f5", "field_match", 0.1),
        j("f6", "field_match", 0.01),
    ],
)

vector(
    "18c-judgments-both",
    "With both thresholds, a key judgment and a field_match judgment act on one candidate "
    "independently: a cleared key with a doubted field still goes to review.",
    "2 DOSAGE AND ADMINISTRATION\nTake 20 mg tablets with water.\n\n"
    "2.1 Hypertension\nThe recommended starting dose is 10 mg once daily. "
    "The maximum dose is 40 mg daily.\n\n"
    "2.2 Heart Failure\nThe recommended starting dose is 5 mg once daily, taken with diuretics.\n\n"
    "2.3 Acute Myocardial Infarction\nGive 5 mg within 24 hours. "
    "In patients who also have heart failure, start at 2.5 mg.",
    {"fields": {"max_dose": KEYED_MG, "adjusted_dose": KEYED_MG}},
    [
        c(
            "b1",
            "adjusted_dose",
            "2.5",
            "mg",
            q("2.5 mg"),
            ("needs_verification", ["MODEL_DOUBT", "MODEL_CLEARED"]),
            key="acute myocardial infarction",
        ),
        c(
            "b2",
            "max_dose",
            "40",
            "mg",
            q("40 mg"),
            ("admitted", ["MODEL_CLEARED"]),
            key="heart failure",
        ),
    ],
    policy={"judge": {**JEV, "clear": {"KEY_NOT_AT_VALUE": 0.9}, "doubt": {"field_match": 0.2}}},
    judgments=[
        j("b1", "key", 0.99, "acute myocardial infarction"),
        j("b1", "field_match", 0.1),
        j("b2", "field_match", 0.5),
        j("b2", "key", 0.99, "heart failure"),
    ],
)

# ---------------------------------------------------------------- evidence items (spec 0.5)
REVIEW = "needs_verification"
URL = "https://www.irs.gov/publications/p970"
DAY = "2026-10-01"


def ext(text: str, url: str = URL) -> dict[str, Any]:
    """An external evidence item (SPEC §2.5)."""
    return {"source": "external", "url": url, "retrieved": DAY, "text": text}


def know(text: str) -> dict[str, Any]:
    """A knowledge evidence item (SPEC §2.5)."""
    return {"source": "knowledge", "text": text}


FEE = {"type": "integer", "unit": "USD"}
vector(
    "19-evidence-list",
    "Evidence is a list of evidence items; one object counts as a list that holds it. A value "
    "item can be a quote with no offsets: the first occurrence where steps 10 and 11 pass is the "
    "evidence, and a quote that does not occur is QUOTE_NOT_FOUND. A candidate with only role "
    "items has no evidence. Malformed items are CANDIDATE_INVALID (spec 0.5).",
    "Take 40 mg daily. The filing fee is $40.\n\nThe late fee is $25, or $40 after 30 days.",
    {"fields": {"fee": FEE, "late": FEE}},
    [
        c("l1", "fee", "40", "USD", [q("$40")]),
        c("l2", "fee", "40", "USD", q("$40", 2)),
        c("l3", "fee", "40", "USD", [{"text": "$40"}]),
        c("l4", "late", "25", "USD", [{"text": "$25"}]),
        c("l5", "fee", "40", "USD", [{"text": "$45"}], ("rejected", ["QUOTE_NOT_FOUND"])),
        c("l6", "fee", "40", "USD", [{"text": "is  $40."}]),
        c("l7", "fee", "40", "USD", [{"role": "sign", "text": "("}], ("rejected", ["NO_EVIDENCE"])),
        c("l8", "fee", "40", "USD", [], ("rejected", ["NO_EVIDENCE"])),
        c("l9", "fee", "40", "USD", [{"text": "40"}]),
        c("l10", "fee", "40", "USD", [{"text": "40 mg"}], ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        *[
            c(f"bad{n}", "fee", "40", "USD", ev, ("rejected", ["CANDIDATE_INVALID"]))
            for n, ev in enumerate(
                [
                    [{"source": "web", "text": "$40"}],
                    [{**ext("$40"), "role": "value"}],
                    [{"start": 31}],
                    [{"start": 31, "end": "34"}],
                    [{"text": "  "}],
                    [q("$40"), {"text": "$40"}],
                    [{"text": "$40", "role": None}],
                    [{"source": "external", "url": URL, "text": "$40"}],
                    [{"source": "knowledge", "text": ""}],
                    [{"source": "reference", "ref": "nope", "text": "$40"}],
                    [{"source": "reference", "text": "$40"}],
                    [{"ref": "nope", "text": "$40"}],
                    [{"role": "colour", "text": "$40"}],
                    [{"text": 40}],
                    [{"text": "$40", "url": URL}],
                    [{**ext("$40"), "start": 0}],
                    "$40",
                    [5],
                ]
            )
        ],
    ],
)

AMOUNT = {"type": "integer", "unit": "USD", "multiple": True}
# the built-in pack that gives the loss words (spec 0.10, #336): the schema names it, and the
# packet does not give it
FINANCE = {"id": "finance", "version": "1.0.0"}
vector(
    "19b-derived-sign",
    "A sign item makes a token negative: brackets around the value, or a loss word before it in "
    "the same sentence with no number, line break, tab or gain word between. Brackets around the "
    "token make it negative with no item. A failing sign item still gives its part, with its flag. "
    "A negative value with no sign is a missing part (spec 0.5). The loss words come from the "
    "built-in pack finance, which the schema names (spec 0.10, #336).",
    "For the year ended December 31, 2024, we had a net loss of $71,000, which consisted of "
    "$71,000 of general and administrative expenses.\n\n"
    "Loss from operations\n\n($105,198\n)\n\n($34,904\n)\n\n"
    "Net (loss) income\n\n$6,152\n\n($13,203\n)\n\n"
    "In 2023 the company reported a loss of $5,000 and revenue of $9,000.\n\n"
    "Loss was $5 million in 2022.",
    {"packs": [FINANCE], "fields": {"amount": AMOUNT}},
    [
        c("s1", "amount", "-71000", "USD", [q("$71,000"), {"role": "sign", "text": "net loss"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("s2", "amount", "-71000", "USD", [q("$71,000", 2), {"role": "sign", "text": "net loss"}],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"])),
        c("s3", "amount", "-71000", "USD", [q("$71,000")], (REVIEW, ["PART_MISSING"], ["sign"])),
        c("s4", "amount", "-105198", "USD", [q("$105,198")], ("admitted", ["VALUE_DERIVED"])),
        c("s5", "amount", "105198", "USD", [q("$105,198")]),
        c("s6", "amount", "-6152", "USD", [q("$6,152"), {"role": "sign", "text": "(loss)"}],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"])),
        c("s7", "amount", "-13203", "USD",
          [q("$13,203"), {"role": "sign", "text": "($13,203\n)"}], ("admitted", ["VALUE_DERIVED"])),
        c("s8", "amount", "-5000", "USD", [q("$5,000"), {"role": "sign", "text": "loss"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("s9", "amount", "-9000", "USD", [q("$9,000"), {"role": "sign", "text": "loss"}],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"])),
        c("s10", "amount", "-5", "USD", [q("$5 million"), {"role": "sign", "text": "Loss"}],
          (REVIEW, ["SCALE_WORD", "VALUE_DERIVED"])),
    ],
)  # fmt: skip


def row(label: str) -> dict[str, Any]:
    return {"role": "field", "text": label}


def year(y: str, n: int | None = None) -> dict[str, Any]:
    return q(y, n, role="key") if n is not None else {"role": "key", "text": y}


MONEY = {
    "type": "number",
    "unit": "USD",
    "multiple": True,
    "aliases": ["operating expenses", "loss from operations", "other items", "interest income"],
}
THOUSANDS = {"role": "scale", "text": "(in thousands"}
DOLLAR = {"role": "unit", "text": "$"}
vector(
    "19c-derived-scale-unit",
    "A scale item multiplies a token that has no scaled value by its scale word, when no other "
    "scale word lies between it and the value. A unit item supplies the unit when no unit is at "
    "the token; another unit at the token still rejects. A missing scale or unit is a missing part "
    "(spec 0.5). A unit item needs a passing field item. In a table with one cell on each line, a "
    "unit item on another line than the value is at no unit place, so it fails (spec 0.7, #164).",
    "Consolidated statements of operations\n(in thousands, except percentages)\n\n"
    "Revenue\n\n$\n\n46,016\n\n$\n\n434,433\n\n"
    "Gross margin\n\n12%\n\n"
    "Operating expenses\n\n195,334\n\n203,625\n\n"
    "Loss from operations\n\n(105,198\n)\n\n"
    "Other items (in millions)\n\n7.5\n\n"
    "Interest income\n\n1,250\n\n"
    "Deferred revenue was $2.2 million at year end.",
    {"fields": {"amount": MONEY}},
    [
        c("r1", "amount", "46016000", "USD", [q("46,016"), THOUSANDS], ("admitted", ["VALUE_DERIVED"])),
        c("r2", "amount", "195334000", "USD", [q("195,334"), THOUSANDS, DOLLAR, row("Operating expenses")],
          (REVIEW, ["UNIT_CITATION_INVALID", "VALUE_DERIVED"])),
        c("r3", "amount", "195334000", "USD", [q("195,334"), THOUSANDS],
          (REVIEW, ["PART_MISSING", "VALUE_DERIVED"], ["unit"])),
        c("r4", "amount", "1250000", "USD", [q("1,250"), THOUSANDS, DOLLAR, row("Interest income")],
          (REVIEW, ["SCALE_CITATION_INVALID", "UNIT_CITATION_INVALID", "VALUE_DERIVED"])),
        c("r5", "amount", "7500000", "USD",
          [q("7.5"), {"role": "scale", "text": "(in millions)"}, DOLLAR, row("Other items (in millions)")],
          (REVIEW, ["UNIT_CITATION_INVALID", "VALUE_DERIVED"])),
        c("r6", "amount", "46016000", "USD", [q("46,016")], (REVIEW, ["PART_MISSING"], ["scale"])),
        c("r7", "amount", "12000", "USD", [q("12"), THOUSANDS, DOLLAR],
          ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("r8", "amount", "2200000", "USD", [q("$2.2 million")]),
        c("r9", "amount", "2200000000", "USD", [q("$2.2 million"), THOUSANDS],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("r11", "amount", "-105198000", "USD",
          [q("105,198"), THOUSANDS, DOLLAR, row("Loss from operations")],
          (REVIEW, ["UNIT_CITATION_INVALID", "VALUE_DERIVED"])),
        c("r12", "amount", "-105198000", "USD", [q("105,198")],
          (REVIEW, ["PART_MISSING"], ["scale", "unit"])),
        c("r13", "amount", "195334000", "USD",
          [q("195,334"), THOUSANDS, {"role": "unit", "text": "%"}, row("Operating expenses")],
          (REVIEW, ["UNIT_CITATION_INVALID", "VALUE_DERIVED"])),
    ],
)  # fmt: skip

YEARS = ["2025", "2024", "2023"]


def money(*aliases: str) -> dict[str, Any]:
    """A keyed USD field by fiscal year, with aliases when given."""
    out: dict[str, Any] = {"type": "integer", "unit": "USD", "keys": YEARS, "multiple": True}
    if aliases:
        out["aliases"] = list(aliases)
    return out


vector(
    "19d-field-and-column",
    "A field item holds an alias of the field, at the value's row or in its sentence. The column "
    "rule puts a key item's key at a table value: the key is the n-th of its header, and the value "
    "is the n-th cell after the row label, where a lone dash is a cell. It records KEY_CITED. A "
    "field item on a field without aliases changes nothing (spec 0.5). A unit item on another "
    "line of a table with one cell on each line fails, but a $ before the brackets around the "
    "value is at a unit place (spec 0.7, #164).",
    "Year Ended December 31,\n\n2025\n\n2024\n\nChange\n\n"
    "Revenue\n\n$\n\n46,016\n\n$\n\n434,433\n\n"
    "Gain on sale\n\n—\n\n40,390\n\n"
    "Loss from operations\n\n$\n\n(140,102\n)\n\n$\n\n(105,198\n)\n\n"
    "Three Months Ended\n\n2025\n\n2024\n\n"
    "Revenue\n\n$\n\n9,100\n\n$\n\n8,800\n\n"
    "In 2024, revenue was $434,433 and operating income was $12.",
    {
        "fields": {
            "revenue": money("revenue", "total revenue"),
            "op_income": money("operating income", "loss from operations"),
            "gain": money("gain on sale"),
            "other": money(),
        }
    },
    [
        c("k1", "revenue", "46016", "USD", [q("46,016"), row("Revenue"), year("2025")],
          ("admitted", ["KEY_CITED"]), key="2025"),
        c("k2", "revenue", "434433", "USD", [q("434,433"), row("Revenue"), year("2024")],
          ("admitted", ["KEY_CITED"]), key="2024"),
        c("k3", "revenue", "434433", "USD", [q("434,433"), row("Revenue"), year("2025")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], []), key="2025"),
        c("k4", "gain", "40390", "USD", [q("40,390"), row("Gain on sale"), year("2024"), DOLLAR],
          (REVIEW, ["UNIT_CITATION_INVALID", "KEY_CITED"]), key="2024"),
        c("k5", "gain", "40390", "USD", [q("40,390"), row("Gain on sale"), year("2025"), DOLLAR],
          (REVIEW, ["UNIT_CITATION_INVALID", "KEY_NOT_AT_VALUE"]), key="2025"),
        c("k6", "op_income", "-105198", "USD",
          [q("105,198"), row("Loss from operations"), year("2024"), DOLLAR],
          ("admitted", ["VALUE_DERIVED", "KEY_CITED"]), key="2024"),
        c("k7", "revenue", "9100", "USD", [q("9,100"), row("Revenue"), year("2025", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("k8", "other", "434433", "USD", [q("434,433"), row("Revenue"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], []), key="2024"),
        c("k9", "op_income", "434433", "USD", [q("434,433"), row("Revenue"), year("2024")],
          (REVIEW, ["FIELD_CITATION_INVALID", "KEY_NOT_AT_VALUE"]), key="2024"),
        c("k10", "revenue", "434433", "USD", [q("$434,433"), row("revenue")], key="2024"),
        c("k11", "revenue", "12", "USD", [q("$12"), row("revenue")],
          (REVIEW, ["FIELD_CITATION_INVALID"]), key="2024"),
        c("k12", "revenue", "434433", "USD", [q("434,433")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2024"),
        c("k13", "revenue", "434433", "USD", [q("434,433"), row("Revenue"), year("Change")],
          (REVIEW, ["KEY_NOT_AT_VALUE", "KEY_CITATION_INVALID"]), key="2024"),
        c("k14", "revenue", "46016", "USD", [q("46,016"), row("Sales"), year("2025")],
          (REVIEW, ["FIELD_CITATION_INVALID", "KEY_NOT_AT_VALUE"]), key="2025"),
        c("k15", "revenue", "434433", "USD", [q("434,433"), row("Revenue"), year("2024")],
          (REVIEW, ["MODEL_DOUBT", "KEY_CITED"]), key="2024"),
        c("k16", "revenue", "434433", "USD", [q("434,433")],
          ("admitted", ["MODEL_CLEARED"], ["key"]), key="2024"),
        c("k17", "op_income", "12", "USD", [q("$12"), row("operating income")], key="2024"),
    ],
    policy={"judge": {**JEV, "clear": {"KEY_NOT_AT_VALUE": 0.9}}},
    judgments=[j("k15", "key", 0.95, "2025"), j("k16", "key", 0.95, "2024")],
)  # fmt: skip

PHASE = {
    "type": "integer",
    "unit": "USD",
    "keys": ["single", "married filing jointly"],
    "multiple": True,
}
IRS_REF = {
    "id": "irs-221",
    "text": "For married filing jointly, the phase-out starts at $170,000.",
    "source": "https://www.irs.gov/publications/p970",
}
vector(
    "19e-references",
    "A reference is a source text that the app supplies. A reference item is checked like a "
    "document item, in the reference's own text and offsets; search_region does not apply to "
    "it. A role item must be from the same text as the value item, but a scale item with offsets "
    "and no text still reads its words from its own text (spec 0.5).",
    "Single filers may deduct student loan interest. The phase-out starts at a MAGI of $85,000.",
    {"fields": {"phase_out": PHASE}},
    [
        c("e1", "phase_out", "170000", "USD",
          [{"source": "reference", "ref": "irs-221", "text": "$170,000"}],
          key="married filing jointly"),
        c("e2", "phase_out", "85000", "USD", [q("$85,000")], key="single"),
        c("e3", "phase_out", "170000", "USD",
          [q("$170,000", source="reference", ref="irs-221")], key="married filing jointly"),
        c("e4", "phase_out", "170000", "USD",
          [{"source": "reference", "ref": "irs-221", "text": "$170,000"},
           {"role": "key", "text": "married filing jointly"}],
          (REVIEW, ["KEY_CITATION_INVALID"]), key="married filing jointly"),
        c("e5", "phase_out", "170000", "USD",
          [{"source": "reference", "ref": "irs-221", "text": "$165,000"}],
          ("rejected", ["QUOTE_NOT_FOUND"]), key="married filing jointly"),
        c("e6", "phase_out", "170000", "USD",
          [{"source": "reference", "ref": "irs-221", "text": "$170,000"}],
          key="married filing jointly", search_region={"start": 0, "end": 10}),
        c("e7", "phase_out", "85000000", "USD",
          [q("$85,000"), q("in thousands", text=NO_TEXT, role="scale", source="reference",
                           ref="irs-scale")],
          (REVIEW, ["SCALE_CITATION_INVALID", "VALUE_DERIVED"]), key="single"),
    ],
    references=[IRS_REF, {"id": "irs-scale", "text": "Amounts are in thousands."}],
    document_source="https://www.irs.gov/publications/p4491x",
)  # fmt: skip

OUTSIDE_DOC = "Taxpayers with MAGI more than $85,000 cannot take the full deduction."
OUTSIDE_SCHEMA = {
    "fields": {
        "threshold": {"type": "integer", "unit": "USD", "comparator": "gt", "multiple": True},
        "mfj": {"type": "integer", "unit": "USD", "multiple": True},
        "mfj_keyed": PHASE,
    }
}
JOINT = "The phase-out begins at $165,000 for joint filers."
vector(
    "19f-outside-default",
    "A candidate with no value item takes the outside path. By default, an external item that "
    "holds the value goes to review with EVIDENCE_QUOTED, and a knowledge item with "
    "EVIDENCE_STATED. An external quote that does not hold the value supports nothing. On the "
    "checked path, outside items change nothing (spec 0.5).",
    OUTSIDE_DOC,
    OUTSIDE_SCHEMA,
    [
        c("o1", "mfj", "165000", "USD", [ext(JOINT)], (REVIEW, ["EVIDENCE_QUOTED"])),
        c("o2", "mfj", "165000", "USD", [know("The phase-out starts at $165,000 for joint filers.")],
          (REVIEW, ["EVIDENCE_STATED"])),
        c("o3", "mfj", "165000", "USD", [ext("The phase-out begins at $160,000.")],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("o4", "mfj", "165000", "USD", [ext("The phase-out begins at $160,000."), know("I know it.")],
          (REVIEW, ["EVIDENCE_STATED"])),
        c("o5", "threshold", "85000", "USD", [q("$85,000"), know("It is $90,000.")]),
        c("o6", "mfj", "165000", "USD", [ext("MAGI more than $165,000")],
          (REVIEW, ["QUALIFIED_VALUE", "EVIDENCE_QUOTED"])),
        c("o7", "mfj", "165000", "USD", [know("The law sets it.")], (REVIEW, ["EVIDENCE_STATED"])),
    ],
    document_source="https://www.irs.gov/publications/p4491x",
)  # fmt: skip

vector(
    "19g-outside-policy",
    "The policy admits an external item whose URL matches an allow entry: document-domain matches "
    "the host of the document source, and other entries are URL prefixes. Other external items "
    "get external.other, and knowledge items get knowledge. The best action decides, and an "
    "admitted candidate records ADMITTED_BY_POLICY; the quote's flags still apply (spec 0.5).",
    OUTSIDE_DOC,
    OUTSIDE_SCHEMA,
    [
        c("g1", "mfj", "165000", "USD", [ext(JOINT)], ("admitted", ["ADMITTED_BY_POLICY"])),
        c("g2", "mfj", "165000", "USD", [ext(JOINT, "https://irs.gov/p970")],
          ("rejected", ["SOURCE_REJECTED"])),
        c("g3", "mfj", "165000", "USD", [ext(JOINT, "https://www.law.cornell.edu/uscode/text/26/221")],
          ("admitted", ["ADMITTED_BY_POLICY"])),
        c("g4", "mfj", "165000", "USD", [ext(JOINT, "https://www.law.cornell.edu.example.com/x")],
          ("rejected", ["SOURCE_REJECTED"])),
        c("g5", "mfj", "165000", "USD", [know("It is $165,000.")], ("admitted", ["ADMITTED_BY_POLICY"])),
        c("g6", "mfj", "165000", "USD", [ext(JOINT, "https://irs.gov/p970"), know("It is $165,000.")],
          ("admitted", ["ADMITTED_BY_POLICY"])),
        c("g7", "mfj", "165000", "USD", [ext("MAGI more than $165,000")],
          (REVIEW, ["QUALIFIED_VALUE", "ADMITTED_BY_POLICY"])),
        c("g8", "mfj", "165000", "USD", [ext(JOINT, "https://user@WWW.IRS.GOV:443/p970")],
          ("admitted", ["ADMITTED_BY_POLICY"])),
        c("g9", "mfj_keyed", "165000", "USD", [ext(JOINT)],
          (REVIEW, ["KEY_NOT_AT_VALUE", "ADMITTED_BY_POLICY"], ["key"]), key="married filing jointly"),
        c("g11", "mfj", "165000", "USD", [ext(JOINT, "https://evil.example\\@www.irs.gov/p")],
          ("rejected", ["SOURCE_REJECTED"])),
        c("g12", "mfj", "165000", "USD", [ext(JOINT, "https://[2001:db8::2]/p")],
          ("rejected", ["SOURCE_REJECTED"])),
        c("g10", "mfj_keyed", "165000", "USD",
          [ext("For married filing jointly, the phase-out begins at $165,000.")],
          ("admitted", ["ADMITTED_BY_POLICY"]), key="married filing jointly"),
    ],
    policy={
        "sources": {
            "external": {"allow": ["document-domain", "https://www.law.cornell.edu/"], "other": "reject"},
            "knowledge": "admit",
        }
    },
    document_source="https://www.irs.gov/publications/p4491x",
)  # fmt: skip

vector(
    "19h-outside-no-source",
    "With no document source, document-domain matches nothing, so an external item gets "
    "external.other. A knowledge action of reject rejects with SOURCE_REJECTED (spec 0.5).",
    OUTSIDE_DOC,
    OUTSIDE_SCHEMA,
    [
        c("h1", "mfj", "165000", "USD", [ext(JOINT)], (REVIEW, ["EVIDENCE_QUOTED"])),
        c("h2", "mfj", "165000", "USD", [know("It is $165,000.")], ("rejected", ["SOURCE_REJECTED"])),
        c("h3", "mfj", "165000", "USD", [ext("It is $160,000."), know("It is $165,000.")],
          ("rejected", ["SOURCE_REJECTED"])),
    ],
    policy={"sources": {"external": {"allow": ["document-domain"]}, "knowledge": "reject"}},
)  # fmt: skip

vector(
    "19i-outside-wildcard",
    'The allow entry "*" admits every external item that holds the value; knowledge keeps its '
    "default, review (spec 0.5).",
    OUTSIDE_DOC,
    OUTSIDE_SCHEMA,
    [
        c("i1", "mfj", "165000", "USD", [ext(JOINT, "https://example.org/a")],
          ("admitted", ["ADMITTED_BY_POLICY"])),
        c("i2", "mfj", "165000", "USD", [know("It is $165,000.")], (REVIEW, ["EVIDENCE_STATED"])),
    ],
    policy={"sources": {"external": {"allow": ["*"]}}},
)  # fmt: skip

NET = {
    "type": "integer",
    "unit": "USD",
    "keys": ["2025", "2024"],
    "aliases": ["net loss", "net income"],
    "multiple": True,
}
vector(
    "19j-role-checks",
    "Each role item is checked at the value: in a table only brackets make a sign, a scale item "
    "after the value fails, a unit item that is not found fails, a field item that holds no alias "
    "fails, and on a string field every role item but a key or field item fails (spec 0.5). The "
    "loss words come from the built-in pack finance (spec 0.10, #336).",
    "Results\n\nYear\n\n2025\n\n2024\n\n"
    "Net loss\n\n$\n\n(2,500\n)\n\n$\n\n(1,900\n)\n\n"
    "Shares outstanding\n\n7,000\n\n6,500\n\n"
    "The net loss for 2025 was $2,500 thousand. The deficit grew to $9 in 2024, and income was $3.",
    {"packs": [FINANCE], "fields": {"net_income": NET, "title": {"type": "string"}}},
    [
        c("j1", "net_income", "-1900", "USD", [q("1,900"), row("Net loss"), year("2024"), DOLLAR],
          ("admitted", ["VALUE_DERIVED", "KEY_CITED"]), key="2024"),
        c("j2", "net_income", "-2500", "USD",
          [q("2,500"), {"role": "sign", "text": "Net loss"}, row("Net loss"), year("2025"), DOLLAR],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED", "KEY_CITED"]), key="2025"),
        c("j3", "net_income", "-2500000", "USD",
          [q("2,500"), {"role": "scale", "text": "thousand"}, row("Net loss"), year("2025"), DOLLAR],
          (REVIEW, ["SCALE_CITATION_INVALID", "VALUE_DERIVED", "KEY_CITED"]), key="2025"),
        c("j4", "net_income", "-1900", "USD",
          [q("1,900"), row("Net loss"), year("2024"), {"role": "unit", "text": "dollars"}],
          (REVIEW, ["UNIT_CITATION_INVALID", "VALUE_DERIVED", "KEY_CITED"]), key="2024"),
        c("j5", "net_income", "6500", "USD",
          [q("6,500"), row("Shares outstanding"), year("2024"), DOLLAR],
          (REVIEW, ["UNIT_CITATION_INVALID", "FIELD_CITATION_INVALID", "KEY_NOT_AT_VALUE"]),
          key="2024"),
        c("j6", "title", "Results", None, [q("Results"), {"role": "sign", "text": "Net loss"}],
          (REVIEW, ["SIGN_CITATION_INVALID"])),
        c("j7", "net_income", "-9", "USD", [q("$9"), {"role": "sign", "text": "deficit"}],
          ("admitted", ["VALUE_DERIVED"]), key="2024"),
        c("j8", "net_income", "-3", "USD", [q("$3"), {"role": "sign", "text": "deficit"}],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"]), key="2024"),
    ],
)  # fmt: skip


LIMITS_YEARS = ["2025", "2024"]


def keyed(*aliases: str, unit: str | None = "USD") -> dict[str, Any]:
    out: dict[str, Any] = {"type": "integer", "keys": LIMITS_YEARS, "multiple": True}
    if unit:
        out["unit"] = unit
    if aliases:
        out["aliases"] = list(aliases)
    return out


vector(
    "19k-role-limits",
    "Limits of the role checks: a dash next to a number is not a cell, a number after the row "
    "label on its line (a footnote) stops the column rule, a $ with no number is an empty cell, a "
    "scale item needs 'in' before its scale word, a unit item needs a passing field item, brackets "
    "alone make no sign on a field without a unit, a negated or distant loss word makes no sign, "
    "and a scale item with offsets and no text reads its span. A quote is trimmed. Brackets take "
    "the longest unit prefix first (spec 0.5). Spec 0.9 keeps m4 and m10 at review because the "
    "two blank lines between their unit cells break the column key (#278).",
    "Amounts (in thousands)\n\nYear\n\n2025\n\n2024\n\n"
    "Units sold\n\n\u2013434,433\n\n46,016\n\n"
    "Sales (1)\n\n$\n\n7,100\n\n$\n\n6,900\n\n"
    "Costs\n\n$\n\n\n\n$\n\n5,500\n\n"
    "We serve a thousand customers. The filing fee is $40.\n\n"
    "Employees\n\n120\n\n"
    "There were 12 adverse events (5) in the trial.\n\n"
    "A refund (US$5) was paid.\n\n"
    "The company had no loss this year and paid $9,000. We recorded a loss on the sale and paid "
    "dividends of $8,000.",
    {
        "fields": {
            "units_sold": keyed("units sold", unit=None),
            "sales": keyed("sales"),
            "costs": keyed("costs"),
            "fee": {"type": "integer", "unit": "USD", "multiple": True},
            "payroll": {"type": "integer", "unit": "USD", "multiple": True},
            "events": {"type": "integer", "multiple": True},
            "paid": {"type": "integer", "unit": "USD", "multiple": True},
            "paid_keyed": keyed(),
            "refund": {"type": "integer", "unit": "UXD", "multiple": True},
        },
        "units": {"UXD": {"prefix": ["$", "US$"]}},
    },
    [
        c("m1", "units_sold", "434433", None, [q("434,433"), row("Units sold"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("m2", "sales", "7100", "USD", [q("7,100"), row("Sales"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("m3", "costs", "5500", "USD", [q("5,500"), row("Costs"), year("2025")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("m4", "costs", "5500", "USD", [q("5,500"), row("Costs"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("m5", "fee", "40000", "USD", [q("$40"), {"role": "scale", "text": "thousand"}],
          (REVIEW, ["SCALE_CITATION_INVALID", "VALUE_DERIVED"])),
        c("m6", "payroll", "120", "USD", [q("120"), DOLLAR], (REVIEW, ["UNIT_CITATION_INVALID"])),
        c("m7", "events", "-5", None, [q("(5)")], (REVIEW, ["PART_MISSING"], ["sign"])),
        c("m8", "paid", "-9000", "USD", [q("$9,000"), {"role": "sign", "text": "no loss"}],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"])),
        c("m9", "paid", "-8000", "USD", [q("$8,000"), {"role": "sign", "text": "loss"}],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"])),
        c("m10", "costs", "5500000", "USD",
          [q("5,500"), q("in thousands", text=NO_TEXT, role="scale"), row("Costs"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE", "VALUE_DERIVED"]), key="2024"),
        c("m11", "costs", "5500000", "USD",
          [q("5,500"), {"role": "scale", "text": "(in"}, row("Costs"), year("2024")],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"]), key="2024"),
        c("m12", "paid_keyed", "9000", "USD", [year("2024"), ext("We paid $9,000.")],
          (REVIEW, ["KEY_NOT_AT_VALUE", "EVIDENCE_QUOTED"], []), key="2024"),
        c("m13", "fee", "40", "USD", [{"text": " $40. "}]),
        c("m14", "refund", "-5", "UXD", [q("US$5")], ("admitted", ["VALUE_DERIVED"])),
    ],
)  # fmt: skip

# ---------------------------------------------------------------- invalid packets
INVALID.extend(
    [
        {
            "name": "document-not-nfc",
            "description": "Documents must be NFC.",
            "document": "Café fee is $40.",
            "schema": {"fields": {"fee": USD}},
            "policy": None,
        },
        {
            "name": "schema-unknown-type",
            "description": "Unknown field types are invalid.",
            "document": "x",
            "schema": {"fields": {"fee": {"type": "money"}}},
            "policy": None,
        },
        {
            "name": "schema-bad-bound",
            "description": "Bounds must be decimals.",
            "document": "x",
            "schema": {"fields": {"fee": {"minimum": "ten"}}},
            "policy": None,
        },
        {
            "name": "schema-unknown-key",
            "description": "Unknown keys are invalid.",
            "document": "x",
            "schema": {"fields": {"fee": {"units": "USD"}}},
            "policy": None,
        },
        {
            "name": "schema-empty-keys",
            "description": "keys is null or a non-empty list of strings.",
            "document": "x",
            "schema": {"fields": {"dose": {"keys": []}}},
            "policy": None,
        },
        {
            "name": "schema-duplicate-keys",
            "description": "Keys that match the same text are invalid.",
            "document": "x",
            "schema": {"fields": {"dose": {"keys": ["Heart failure", "heart  failure"]}}},
            "policy": None,
        },
        {
            "name": "policy-bad-confidence",
            "description": "min_confidence must be in [0, 1].",
            "document": "x",
            "schema": {"fields": {}},
            "policy": {"min_confidence": 2},
        },
        {
            "name": "policy-judge-blank-digest",
            "description": "A judge names one model version, so its digest is not blank.",
            "document": "x",
            "schema": {"fields": {}},
            "policy": {"judge": {"id": "jev", "digest": " ", "clear": {"KEY_NOT_AT_VALUE": 0.9}}},
        },
        {
            "name": "policy-judge-unknown-flag",
            "description": "A judge can clear only KEY_NOT_AT_VALUE.",
            "document": "x",
            "schema": {"fields": {}},
            "policy": {"judge": {**JEV, "clear": {"QUALIFIED_VALUE": 0.9}}},
        },
        {
            "name": "policy-judge-null-threshold",
            "description": "A threshold that is present is a number in [0, 1], not null.",
            "document": "x",
            "schema": {"fields": {}},
            "policy": {"judge": {**JEV, "doubt": {"field_match": None}}},
        },
        {
            "name": "judgment-unknown-candidate",
            "description": "A judgment names the id of one candidate in the packet.",
            "document": "The fee is $40.",
            "schema": {"fields": {"fee": USD}},
            "policy": {"judge": {**JEV, "doubt": {"field_match": 0.2}}},
            "candidates": [{"id": "a", "field": "fee", "value": 40}],
            "judgments": [j("b", "field_match", 0.1)],
        },
        {
            "name": "judgment-ambiguous-candidate",
            "description": "Two candidates with the id that a judgment names are invalid.",
            "document": "The fee is $40.",
            "schema": {"fields": {"fee": USD}},
            "policy": {"judge": {**JEV, "doubt": {"field_match": 0.2}}},
            "candidates": [
                {"id": "a", "field": "fee", "value": 40},
                {"id": "a", "field": "fee", "value": 41},
            ],
            "judgments": [j("a", "field_match", 0.1)],
        },
        {
            "name": "judgment-twice",
            "description": "One candidate has at most one judgment for each question.",
            "document": "The fee is $40.",
            "schema": {"fields": {"fee": USD}},
            "policy": {"judge": {**JEV, "doubt": {"field_match": 0.2}}},
            "candidates": [{"id": "a", "field": "fee", "value": 40}],
            "judgments": [j("a", "field_match", 0.1), j("a", "field_match", 0.9)],
        },
        {
            "name": "judgment-bad-p",
            "description": "p is a number in [0, 1].",
            "document": "The fee is $40.",
            "schema": {"fields": {"fee": USD}},
            "policy": {"judge": {**JEV, "doubt": {"field_match": 0.2}}},
            "candidates": [{"id": "a", "field": "fee", "value": 40}],
            "judgments": [j("a", "field_match", 1.5)],
        },
        {
            "name": "judgment-unknown-question",
            "description": "The question is key or field_match.",
            "document": "The fee is $40.",
            "schema": {"fields": {"fee": USD}},
            "policy": {"judge": {**JEV, "doubt": {"field_match": 0.2}}},
            "candidates": [{"id": "a", "field": "fee", "value": 40}],
            "judgments": [{**j("a", "field_match", 0.1), "question": "unit"}],
        },
        {
            "name": "policy-unknown-key",
            "description": "Unknown policy keys are invalid.",
            "document": "x",
            "schema": {"fields": {}},
            "policy": {"strict": True},
        },
        *[
            {
                "name": f"references-{name}",
                "description": f"References must be a list of objects with a unique non-blank "
                f"id, a non-empty NFC text and a non-blank or null source ({name}).",
                "document": "The fee is $40.",
                "schema": {"fields": {"fee": USD}},
                "policy": None,
                "references": refs,
            }
            for name, refs in [
                ("not-a-list", {"id": "r", "text": "x"}),
                ("duplicate-id", [{"id": "r", "text": "x"}, {"id": "r", "text": "y"}]),
                ("blank-id", [{"id": " ", "text": "x"}]),
                ("empty-text", [{"id": "r", "text": ""}]),
                ("not-nfc", [{"id": "r", "text": "Cafe\u0301"}]),
                ("blank-source", [{"id": "r", "text": "x", "source": ""}]),
                ("unknown-key", [{"id": "r", "text": "x", "page": 2}]),
            ]
        ],
        {
            "name": "document-source-blank",
            "description": "The document source is a non-blank string or null.",
            "document": "The fee is $40.",
            "schema": {"fields": {"fee": USD}},
            "policy": None,
            "document_source": "  ",
        },
        *[
            {
                "name": f"policy-sources-{name}",
                "description": f"policy.sources holds external (allow, other) and knowledge, with "
                f"their listed values only ({name}).",
                "document": "x",
                "schema": {"fields": {}},
                "policy": {"sources": sources},
            }
            for name, sources in [
                ("unknown-key", {"web": "admit"}),
                ("other-admit", {"external": {"other": "admit"}}),
                ("allow-blank", {"external": {"allow": [""]}}),
                ("allow-not-list", {"external": {"allow": "*"}}),
                ("external-unknown-key", {"external": {"deny": []}}),
                ("knowledge-bad", {"knowledge": "trust"}),
                ("null-knowledge", {"knowledge": None}),
            ]
        ],
        *[
            {
                "name": f"schema-aliases-{name}",
                "description": "Aliases follow the rules of keys: null or a non-empty list of "
                f"non-blank strings, no two equal after normalisation ({name}).",
                "document": "x",
                "schema": {"fields": {"op": {"type": "integer", "aliases": aliases}}},
                "policy": None,
            }
            for name, aliases in [
                ("empty", []),
                ("blank", ["operating income", " "]),
                ("duplicate", ["Operating  income", "operating income"]),
                ("not-a-list", "operating income"),
            ]
        ],
    ]
)


# ---------------------------------------------------------------- SPEC text (#158)
SPEC_TEXT_FIRST = "A: 5 apples. B: 5 thousand pears."

vector(
    "20-spec-text",
    "Rules that the SPEC text states since #158: a cited span that passes only with a missing part "
    "re-anchors; 'between the ages of' makes 'and' a connector in spec 0.6; a connector "
    "may have a $ before the next number; unit forms need a boundary, and a suffix lies wholly in "
    "the sentence; a mention inside a longer mention does not count; a string field takes no "
    "qualifier and rejects an integer or blank value; a carriage return is not a line break; a "
    "unit with empty lists is vacuous; an unchecked field item makes a unit item fail.",
    SPEC_TEXT_FIRST + "\n\n"
    "Ages between 18 and 65 qualify. Members between the ages of 18 and 65 pay less.\n\n"
    "The fee is $30 to $45. The score went 31 to US $ 46.\n\n"
    "The award was MRs 500 and the dose was 5 grams. The tablet is 500mg.\n\n"
    "Pressure 29 in. Hg was read.\n\n"
    "Total revenue 500\n\n"
    "The city is approximately Paris.\n\n"
    "fif-\r\nteen and fif-\nteen\n\n"
    "The team scored 12.\n\n"
    "Price list, all amounts in $:\n\nAdult\t40",
    {
        "fields": {
            "count": {"type": "integer", "multiple": True},
            "age": {"type": "integer", "multiple": True},
            "fee": {"type": "integer", "unit": "USD", "multiple": True},
            "award": {"type": "integer", "unit": "INR"},
            "dose": {"type": "integer", "unit": "g"},
            "tablet": {"type": "integer", "unit": "mg"},
            "pressure": {"type": "integer", "unit": "inHg"},
            "revenue": {"type": "integer", "aliases": ["revenue", "total revenue"]},
            "city": {"type": "string", "multiple": True},
            "word": {"type": "string", "multiple": True},
            "points": {"type": "integer", "unit": "PTS"},
            "price": {"type": "integer", "unit": "USD"},
        },
        "units": {"inHg": {"suffix": ["in. Hg"]}, "PTS": {"prefix": [], "suffix": []}},
    },
    [
        c("r1", "count", 5000, None, q("5"), (ADMIT[0], ["EVIDENCE_REANCHORED"]),
          search_region={"start": 0, "end": len(SPEC_TEXT_FIRST.encode())}),
        c("g1", "age", 65, None, q("65", 1), (REVIEW, ["QUALIFIED_VALUE"])),
        c("g2", "age", 65, None, q("65", 2), (REVIEW, ["QUALIFIED_VALUE"])),
        c("f1", "fee", 30, "USD", q("$30"), (REVIEW, ["QUALIFIED_VALUE"])),
        c("f2", "count", 31, None, q("31")),
        c("u1", "award", 500, "INR", q("500", 1), (REVIEW, ["PART_MISSING"], ["unit"])),
        c("u2", "dose", 5, "g", q("5 grams"), (REVIEW, ["PART_MISSING"], ["unit"])),
        c("u3", "tablet", 500, "mg", q("500mg")),
        c("s1", "pressure", 29, "inHg", q("29"), (REVIEW, ["PART_MISSING"], ["unit"])),
        c("m1", "revenue", 500, None, [q("500", 3), {"role": "field", "text": "revenue"}],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        c("c1", "city", "Paris", None, q("Paris")),
        c("c2", "city", 7, None, q("Paris"), ("rejected", ["TYPE_INVALID"])),
        c("c3", "city", "  ", None, q("Paris"), ("rejected", ["TYPE_INVALID"])),
        c("w1", "word", "fif- teen", None, q("fif-\r\nteen", text="fifteen"),
          (REVIEW, ["NON_VERBATIM_EVIDENCE"])),
        c("w2", "word", "fif- teen", None, q("fif-\nteen", text="fifteen")),
        c("p1", "points", 12, "PTS", q("12")),
        c("n1", "price", 40, "USD",
          [q("40"), {"role": "field", "text": "Adult"}, {"role": "unit", "text": "$"}],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
    ],
)  # fmt: skip

vector(
    "20b-spec-text-outside",
    "On the outside path no VALUE_DERIVED is recorded, and a document source without :// has no "
    "host, so document-domain matches nothing (#158).",
    "The annual report is on the company site.",
    {"fields": {"net_income": {"type": "integer", "unit": "USD", "multiple": True}}},
    [
        c("o1", "net_income", -5, "USD", [ext("Net loss was ($5).", "https://www.irs.gov/x")],
          (REVIEW, ["EVIDENCE_QUOTED"])),
        c("o2", "net_income", 7, "USD", [ext("Net income was $7.", "https://www.irs.gov/y")],
          (REVIEW, ["EVIDENCE_QUOTED"])),
    ],
    policy={"sources": {"external": {"allow": ["document-domain"]}}},
    document_source="www.irs.gov/annual",
)  # fmt: skip


# ---- spec 0.6 (#171)
vector(
    "21-field-description",
    "Field descriptions change no decision: values still pass, fail or need verification "
    "under the field's rules, even when its description says otherwise.",
    "The fee is $485. The estimate is about $500. The label is Annual fee.",
    {
        "fields": {
            "fee": {
                "type": "integer",
                "unit": "USD",
                "description": "A fee in cents; only values above 1000 count.",
            },
            "estimate": {
                "type": "integer",
                "unit": "USD",
                "description": "An approximate amount that needs no verification.",
            },
            "label": {"type": "string", "description": "The fee's label."},
        }
    },
    [
        c("d1", "fee", 485, "USD", q("$485"), ("admitted", [])),
        c("d2", "fee", 486, "USD", q("$485"), ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("d3", "estimate", 500, "USD", q("$500"),
          ("needs_verification", ["QUALIFIED_VALUE"])),
        c("d4", "label", "Annual fee", None, q("Annual fee"), ("admitted", [])),
    ],
)  # fmt: skip

INVALID.extend(
    [
        {
            "name": f"schema-description-{name}",
            "description": "A field description must be a non-blank string.",
            "document": "The fee is $485.",
            "schema": {"fields": {"fee": {**USD, "description": description}}},
            "policy": None,
        }
        for name, description in [
            ("empty", ""),
            ("whitespace", " \t\n\u00a0"),
            ("not-string", 485),
        ]
    ]
)

# ---------------------------------------------------------------- spec 0.6 (#145)
vector(
    "22-redundant-unit",
    "A unit item passes when the field's unit is at the token and the item holds a form of it: "
    "the item repeats the unit, so it needs no field item and may follow the number. A form of "
    "another unit still fails. A scale item still matches case: at its offsets, a text in "
    "another case is not found, and its scale word still gives the part (#145).",
    "Consolidated statements (in thousands, except ratios)\n\n"
    "Revenue $ 46,016\n\n"
    "Royalties 1,250 dollars\n\n"
    "Margin 12 percent\n\n"
    "Other items (in millions) $7.5\n",
    {
        "fields": {
            "amount": {
                "type": "number",
                "unit": "USD",
                "multiple": True,
                "aliases": ["revenue", "royalties", "other items"],
            },
            "margin": {"type": "number", "unit": "%"},
        }
    },
    [
        c("d1", "amount", "46016000", "USD", [q("46,016"), THOUSANDS, DOLLAR],
          ("admitted", ["VALUE_DERIVED"])),
        c("d2", "amount", "1250000", "USD",
          [q("1,250"), THOUSANDS, {"role": "unit", "text": "dollars"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("d3", "margin", "12", "%", [q("12"), {"role": "unit", "text": "percent"}]),
        c("d4", "amount", "7500000", "USD",
          [q("7.5"), {"role": "scale", "text": "[in millions]"}, DOLLAR],
          (REVIEW, ["SCALE_CITATION_INVALID", "VALUE_DERIVED"])),
        c("d5", "amount", "46016000", "USD",
          [q("46,016"), q("(in thousands", text="(In Thousands", role="scale")],
          (REVIEW, ["SCALE_CITATION_INVALID", "VALUE_DERIVED"])),
        c("d6", "amount", "46016000", "USD", [q("46,016"), THOUSANDS, row("REVENUE")],
          (REVIEW, ["FIELD_CITATION_INVALID", "VALUE_DERIVED"])),
        c("d7", "amount", "46016000", "USD",
          [q("46,016"), THOUSANDS, {"role": "unit", "text": "percent"}],
          (REVIEW, ["UNIT_CITATION_INVALID", "VALUE_DERIVED"])),
    ],
)  # fmt: skip


# ---- spec 0.6 (#159)
vector(
    "23-between-words",
    "'between' can stand up to six words before the first number of an 'and' range. "
    "Each word holds only letters and combining marks, and only whitespace separates them. The "
    "words stay in one sentence with no intervening number. Each 'between' of the sentence is "
    "tried. Spec 0.5 qualifiers stay set.",
    "Members between the ages of 18 and 65 qualify.\n\n"
    "Members between the minimum and maximum permitted ages 18 and 65 qualify.\n\n"
    "Members between 18 and 65 qualify.\n\n"
    "Members between the minimum and maximum permitted adult ages 18 and 65 qualify.\n\n"
    "Members between 7 the ages of 18 and 65 qualify.\n\n"
    "Choose between the ages. Members aged 18 and 65 qualify.\n\n"
    "Choose between options. Members aged 18 and 65 qualify.\n\n"
    "Members between $18 and $65 qualify.\n\n"
    "Members BETWEEN\tthe\nages of 18 and 65 qualify.\n\n"
    "Members between a b c d e f g 18 and 65 qualify.\n\n"
    "Members between the ages; members aged 18 and 65 qualify.\n\n"
    "Members between the\n\nages of 18 and 65 qualify.\n\n"
    "Members between the ages•members aged 18 and 65 qualify.\n\n"
    "Members between dr. ages 18 and 65 qualify.\n\n"
    "Members between the adult-age limits 18 and 65 qualify.\n\n"
    "Members between the ages² of 18 and 65 qualify.\n\n"
    "Members between les âges de 18 and 65 qualify.\n\n"
    "Members between                              18 and 65 qualify.\n\n"
    "Members between x\u00b2 and between the ages 18 and 65 qualify.\n\n"
    "Members between the q\u0303 ages of 18 and 65 qualify.",
    {
        "fields": {
            "age": {"type": "integer", "multiple": True},
            "age_range": {"type": "integer", "comparator": "range", "multiple": True},
        }
    },
    [
        c("words-low", "age", 18, None, q("18", 1), (REVIEW, ["QUALIFIED_VALUE"])),
        c("words-high", "age", 65, None, q("65", 1), (REVIEW, ["QUALIFIED_VALUE"])),
        c("limit-low", "age", 18, None, q("18", 2), (REVIEW, ["QUALIFIED_VALUE"])),
        c("limit-high", "age", 65, None, q("65", 2), (REVIEW, ["QUALIFIED_VALUE"])),
        c("plain-low", "age", 18, None, q("18", 3), (REVIEW, ["QUALIFIED_VALUE"])),
        c("plain-high", "age", 65, None, q("65", 3), (REVIEW, ["QUALIFIED_VALUE"])),
        c("over-limit-low", "age", 18, None, q("18", 4), ADMIT),
        c("over-limit-high", "age", 65, None, q("65", 4), ADMIT),
        c("number-low", "age", 18, None, q("18", 5), ADMIT),
        c("number-high", "age", 65, None, q("65", 5), ADMIT),
        c("sentence-low", "age", 18, None, q("18", 6), ADMIT),
        c("sentence-high", "age", 65, None, q("65", 6), ADMIT),
        c("earlier-low", "age", 18, None, q("18", 7), ADMIT),
        c("earlier-high", "age", 65, None, q("65", 7), ADMIT),
        c("prefix-low", "age", 18, None, q("18", 8), (REVIEW, ["QUALIFIED_VALUE"])),
        c("prefix-high", "age", 65, None, q("65", 8), (REVIEW, ["QUALIFIED_VALUE"])),
        c("whitespace-low", "age", 18, None, q("18", 9), (REVIEW, ["QUALIFIED_VALUE"])),
        c("whitespace-high", "age", 65, None, q("65", 9), (REVIEW, ["QUALIFIED_VALUE"])),
        c("old-flag-low", "age", 18, None, q("18", 10), (REVIEW, ["QUALIFIED_VALUE"])),
        c("old-flag-high", "age", 65, None, q("65", 10), ADMIT),
        c("semicolon-high", "age", 65, None, q("65", 11), ADMIT),
        c("blank-line-high", "age", 65, None, q("65", 12), ADMIT),
        c("bullet-high", "age", 65, None, q("65", 13), ADMIT),
        c("abbreviation-low", "age", 18, None, q("18", 14), (REVIEW, ["QUALIFIED_VALUE"])),
        c("abbreviation-high", "age", 65, None, q("65", 14), ADMIT),
        c("hyphen-low", "age", 18, None, q("18", 15), (REVIEW, ["QUALIFIED_VALUE"])),
        c("hyphen-high", "age", 65, None, q("65", 15), ADMIT),
        c("nonletter-low", "age", 18, None, q("18", 16), (REVIEW, ["QUALIFIED_VALUE"])),
        c("nonletter-high", "age", 65, None, q("65", 16), ADMIT),
        c("unicode-low", "age", 18, None, q("18", 17), (REVIEW, ["QUALIFIED_VALUE"])),
        c("unicode-high", "age", 65, None, q("65", 17), (REVIEW, ["QUALIFIED_VALUE"])),
        c("spaces-low", "age", 18, None, q("18", 18), (REVIEW, ["QUALIFIED_VALUE"])),
        c("spaces-high", "age", 65, None, q("65", 18), (REVIEW, ["QUALIFIED_VALUE"])),
        c("nearer-low", "age", 18, None, q("18", 19), (REVIEW, ["QUALIFIED_VALUE"])),
        c("nearer-high", "age", 65, None, q("65", 19), (REVIEW, ["QUALIFIED_VALUE"])),
        c("mark-low", "age", 18, None, q("18", 20), (REVIEW, ["QUALIFIED_VALUE"])),
        c("mark-high", "age", 65, None, q("65", 20), (REVIEW, ["QUALIFIED_VALUE"])),
        c("range-low", "age_range", 18, None, q("18", 2), ADMIT),
        c("range-high", "age_range", 65, None, q("65", 2), ADMIT),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- spec 0.6 (#162)
HEADING_TABLE = (
    "CONSOLIDATED STATEMENTS OF OPERATIONS\n\n(in thousands)\n\n2025\t2024\n"
    "Net sales\t$ 84,210\t$ 79,605\n"
    "Gross margin\t12 %\t11 %\n"
    "Loss from operations\t(3,415)\t(2,980)\n"
    "Backlog\t$1.2 million\t$1.0 million\n\n"
    "Other income\t500\t400\n\n"
    "Headcount at year end was 1,250.\n\n"
    "Segment data\n\n2025\t2024\nUnits sold\t1,250\t1,100\n"
)
vector(
    "24-heading-scale",
    "A scale phrase on a heading line with no tab reaches the lines with tabs directly after it, "
    "after any blank lines, up to the first line that holds no tab. A value at a token there, "
    "with no scale item and no scale word after the number, equal to the number as written, "
    "misses its scale. A field with the unit % is not reached. A table after a blank line, a "
    "heading with no scale phrase, and a line with no tab are not reached (#162).",
    HEADING_TABLE,
    {
        "fields": {
            "net_sales": {"type": "number", "unit": "USD", "multiple": True},
            "operating_income": {
                "type": "number",
                "unit": "USD",
                "multiple": True,
                "aliases": ["loss from operations"],
            },
            "margin": {"type": "number", "unit": "%", "multiple": True},
            "backlog": {"type": "number", "unit": "USD"},
            "other": {"type": "number", "multiple": True},
            "headcount": {"type": "integer"},
            "units": {"type": "integer", "multiple": True},
        }
    },
    [
        c("h1", "net_sales", "84210", "USD", [q("$ 84,210")],
          (REVIEW, ["PART_MISSING"], ["scale"])),
        c("h2", "net_sales", "84210000", "USD", [q("$ 84,210"), THOUSANDS],
          ("admitted", ["VALUE_DERIVED"])),
        c("h3", "net_sales", "84210000", "USD", [q("$ 84,210")],
          (REVIEW, ["PART_MISSING"], ["scale"])),
        c("h4", "operating_income", "-2980", "USD",
          [q("(2,980)"), DOLLAR, row("Loss from operations")],
          (REVIEW, ["PART_MISSING"], ["scale"])),
        c("h5", "margin", "12", "%", [q("12 %")]),
        c("h6", "headcount", "1250", None, [q("1,250")]),
        c("h7", "units", "1250", None, [q("1,250", 2)]),
        c("h8", "other", "500", None, [q("500")]),
        c("h9", "backlog", "1200000", "USD", [q("$1.2 million")]),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- spec 0.7 (#164)
UNIT_PLACE = (
    "Results of operations\n(amounts in dollars)\n\n"
    "\t2025\t2024\tChange\n"
    "Rental revenue\t$\t527,534\t$\t425,749\t$\t101,785\n"
    "Other revenue\t2,060\t452\t1,608\n"
    "Total revenues\t529,594\t426,201\t103,393\n"
    "Operating items:\n"
    "Income from operations\t359,921\t278,193\t81,728\n"
    "Stores\t1,200\t1,100\t100\n\n"
    "Segment data\t2025\t2024\nUnits\t57\t43\n\n"
    "Region\t2025\t2024\nNorth\t$\t310\t$\t220\nAs restated in 2024\nSouth\t160\t110\n\n"
    "Fees ($)\t75\t80\n"
    "Interest\t$\t(12)\t$\t(9)\n\n"
    "Wages were 9 dollars an hour.\nCrew\t70\t60\n\n"
    "Caption\nHead\t$\tX\nAmount\t61\t67\n"
)


def usd(*aliases: str) -> dict[str, Any]:
    return {"type": "integer", "unit": "USD", "multiple": True, "aliases": list(aliases)}


vector(
    "25-unit-place",
    "A unit item that the unit at the token does not repeat must be at a unit place of the value: "
    "on its line, in a caption line with no tab and no number that reaches the value's table, or "
    "in the value's column on an earlier line of its table, where each line between holds a tab "
    "or no number. A unit quote takes its last occurrence at a unit place. A blank line or a line "
    "with a number and no tab ends the table. A row of counts in the same column still takes the "
    "column's $ when its field item passes. The place is that of the unit form, not of the item "
    "that holds it (spec 0.7, #164). With a passing field item, a form at a unit place also "
    "means that the unit is not a missing part, also with no unit item (spec 0.8, #249).",
    UNIT_PLACE,
    {
        "fields": {
            "revenue": usd("rental revenue", "other revenue", "total revenues"),
            "operating_income": usd("income from operations"),
            "store_sales": usd("stores"),
            "unit_sales": usd("units"),
            "region_sales": usd("north", "south"),
            "interest": usd("interest"),
            "fees": usd("fees"),
            "crew_pay": usd("crew"),
            "amount": usd("amount"),
        }
    },
    [
        c("p1", "revenue", "426201", "USD", [q("426,201"), DOLLAR, row("Total revenues")]),
        c("p2", "operating_income", "278193", "USD",
          [q("278,193"), DOLLAR, row("Income from operations")]),
        c("p3", "store_sales", "1100", "USD", [q("1,100"), DOLLAR, row("Stores")]),
        c("p4", "unit_sales", "43", "USD", [q("43"), DOLLAR, row("Units")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
        c("p5", "revenue", "2060", "USD", [q("2,060"), q("$", 3, role="unit"), row("Other revenue")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
        c("p6", "revenue", "2060", "USD", [q("2,060"), q("$", 1, role="unit"), row("Other revenue")]),
        c("p7", "revenue", "2060", "USD",
          [q("2,060"), {"role": "unit", "text": "dollars"}, row("Other revenue")]),
        c("p8", "region_sales", "110", "USD", [q("110"), DOLLAR, row("South")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
        c("p9", "interest", "-9", "USD", [q("(9)"), DOLLAR, row("Interest")],
          ("admitted", ["VALUE_DERIVED"])),
        c("p10", "fees", "80", "USD", [q("80"), DOLLAR, row("Fees")]),
        c("p11", "crew_pay", "70", "USD",
          [q("70"), {"role": "unit", "text": "dollars"}, row("Crew")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
        c("p12", "revenue", "426201", "USD", [q("426,201"), row("Total revenues")]),
        c("p13", "amount", "67", "USD",
          [q("67"), q("Caption\nHead\t$", role="unit"), row("Amount")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
    ],
)  # fmt: skip


vector(
    "25b-unit-place-cells",
    "A unit prefix that is also a number token is one cell, not two, when the unit places and "
    "the column rule count the cells of a row. A line of no-break spaces is not blank, so it "
    "does not end the table. A prefix that ends in a space stands before the brackets around "
    "the value. An empty cell ends at the end of its prefix, also when the prefix holds a space "
    "(spec 0.7, #164). Each occurrence of a form or a unit quote counts, also where two overlap. "
    "An empty cell "
    "ends where the longest prefix that makes it ends, not a longer prefix at the same start. "
    "When a number token and an empty cell start at the same place, the cell ends at the later "
    "end of the two. Empty cells that overlap count each, as `a a` twice in `a a a`. An empty "
    "cell at the end of a line counts when the next character after the line end and the "
    "whitespace is not the start of a number token or `(`. Spec 0.9 refuses the column unit "
    "on an ambiguous tab row: q1 has an unrecognized slot, q9 has overlapping cells in one slot, "
    "and q10 has several unit-prefix cells in one source slot (#278).",
    "Head\t1\t$\t4\nAmount\t2\t?\t3\n\nTop\t$ 5\n\u00a0\nLow\t6\n\nNeg V \n(12)\n\n"
    "Rows\tP Q\tZ\nItems\t7\n\nBox\t$$$8\nCrate\t9\n\nTag\tP Q%\tZ\nThing\t11\n\nMark\t2% R\nCount\t13\n\n"
    "Hdr\t1\t2\t$\t16\nSum\ta a a \t?\t17\n\nCap\t1\t$ U\nTotal\t2\t9\t19\n",
    {
        "fields": {
            "amount": {"type": "integer", "unit": "U", "aliases": ["amount"]},
            "low": {"type": "integer", "unit": "USD", "aliases": ["low"]},
            "neg": {"type": "integer", "unit": "V", "aliases": ["neg"]},
            "items": {"type": "integer", "unit": "W", "aliases": ["items"]},
            "crate": {"type": "integer", "unit": "D", "aliases": ["crate"]},
            "thing": {"type": "integer", "unit": "X", "aliases": ["thing"]},
            "count": {"type": "integer", "unit": "Y", "aliases": ["count"]},
            "sum": {"type": "integer", "unit": "Z", "aliases": ["sum"]},
            "total": {"type": "integer", "unit": "T", "aliases": ["total"]},
        },
        "units": {
            "U": {"prefix": ["2", "$"]},
            "V": {"prefix": ["V "]},
            "W": {"prefix": ["P Q"], "suffix": ["Q"]},
            "D": {"prefix": ["$$"]},
            "X": {"prefix": ["P", "P Q"], "suffix": ["%"]},
            "Y": {"prefix": ["2%"], "suffix": ["%"]},
            "Z": {"prefix": ["a a", "$"]},
            "T": {"prefix": ["$", "U"]},
        },
    },
    [
        c("q1", "amount", "3", "U", [q("3"), DOLLAR, row("Amount")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
        c("q2", "low", "6", "USD", [q("6"), DOLLAR, row("Low")]),
        c("q3", "neg", "-12", "V", [q("12"), q("V ", role="unit"), row("Neg")],
          ("admitted", ["VALUE_DERIVED"])),
        c("q4", "items", "7", "W", [q("7"), q("Q", role="unit"), row("Items")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
        c("q5", "crate", "9", "D", [q("9"), q("$$$", role="unit"), row("Crate")]),
        c("q7", "crate", "9", "D", [q("9"), {"role": "unit", "text": "$$"}, row("Crate")]),
        c("q6", "thing", "11", "X", [q("11"), q("%", role="unit"), row("Thing")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
        c("q8", "count", "13", "Y", [q("13"), q("%", 2, role="unit"), row("Count")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
        c("q9", "sum", "17", "Z", [q("17"), {"role": "unit", "text": "$"}, row("Sum")],
          (REVIEW, ["UNIT_CITATION_INVALID", "FIELD_CITATION_INVALID"])),
        c("q10", "total", "19", "T", [q("19"), {"role": "unit", "text": "$"}, row("Total")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
    ],
)  # fmt: skip


vector(
    "26-scale-item-scales",
    "A scale item says that the value is scaled. When the candidate has a scale item whose text "
    "holds a scale word, a token with no scaled value matches only its value times the scale, and "
    "its negative. The number as written does not match, also when the item fails its check. A "
    "token with its own scale word keeps its values (spec 0.8, #242).",
    "Statement of position\n(in thousands)\n\n"
    "Total assets\t$\t1,250\t$\t1,100\nNet loss\t$\t(75)\t$\t(60)\n\n"
    "Cash was $2.2 million at year end.\n\nAmounts are in thousands.",
    {
        "fields": {
            "assets": usd("total assets"),
            "net_loss": usd("net loss"),
            "cash": usd("cash"),
        }
    },
    [
        c("s1", "assets", "1250000", "USD", [q("1,250"), THOUSANDS, row("Total assets")],
          ("admitted", ["VALUE_DERIVED"])),
        c("s2", "assets", "1250", "USD", [q("1,250"), THOUSANDS, row("Total assets")],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("s3", "assets", "1250", "USD",
          [q("1,250"), q("in thousands", 2, role="scale"), row("Total assets")],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("s4", "assets", "1250000", "USD",
          [q("1,250"), q("in thousands", 2, role="scale"), row("Total assets")],
          (REVIEW, ["SCALE_CITATION_INVALID", "VALUE_DERIVED"])),
        c("s5", "net_loss", "-75000", "USD", [q("75"), THOUSANDS, DOLLAR, row("Net loss")],
          ("admitted", ["VALUE_DERIVED"])),
        c("s6", "net_loss", "-75", "USD", [q("75"), THOUSANDS, DOLLAR, row("Net loss")],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("s7", "cash", "2200000", "USD", [q("$2.2 million"), THOUSANDS]),
    ],
)  # fmt: skip

OCCURRENCE = (
    "Rebate\t40\nTotal rebates\t$\t45\n\n"
    "Dues\t70\nTotal paid\t$\t70\n\n"
    "Segment sales\nRegion\t2025\t2024\nNorth\t$\t310\t220\nSouth\t160\t110\n\n"
    "Amounts in dollars\nFee\t75\nCharge\t85\n\n"
    "Statement of net position\n(in thousands)\n\n\t2025\n"
    "Cash\t$\t1,200\nReceivables\t300\nTotal assets\t1,500\nPayables\t$\t350\n"
    "Other liabilities\t50\nTotal liabilities\t400\nNet position\t1,100\n"
    "Total liabilities and net position\t$\t1,500\n\n"
    "Statement of changes in net position\n(in thousands)\n\n\t2025\n"
    "Ending balance\t$\t1,100\n\n"
    "South sales were $160 in the year."
)


def at(text: str) -> dict[str, Any]:
    """A value item as a quote with no offsets, so that its occurrences are searched (4.6)."""
    return {"text": text}


vector(
    "27-occurrence-at-field-and-column-unit",
    "A value quote takes the first occurrence where the field item passes; among those, or when "
    "none passes, the first where steps 10 and 11 pass with no missing part, as before, with the "
    "unit next to the value (#249). "
    "When the field item passes, a form of the field's unit at a unit place of the value, as for "
    "a unit item (4.6), means that the unit is not a missing part: in the value's column on an "
    "earlier line of its table, or in a caption line that reaches its table. A unit form on a "
    "later line is at no unit place, and a cited span where the unit is so not missing does not move "
    "to another occurrence (spec 0.8, #249).",
    OCCURRENCE,
    {
        "fields": {
            "assets": usd("total assets"),
            "net": usd("net position"),
            "region": usd("north", "south"),
            "fee": usd("fee"),
            "rebate": usd("rebate"),
            "dues": usd("dues"),
        }
    },
    [
        c("o1", "assets", "1500000", "USD", [at("1,500"), THOUSANDS, row("Total assets")],
          ("admitted", ["VALUE_DERIVED"])),
        c("o2", "assets", "1500000", "USD", [at("1,500"), THOUSANDS], ("admitted", ["VALUE_DERIVED"])),
        c("o3", "assets", "1100000", "USD", [at("1,100"), THOUSANDS, row("Total assets")],
          (REVIEW, ["FIELD_CITATION_INVALID", "VALUE_DERIVED"])),
        c("o4", "net", "1100000", "USD", [at("1,100"), THOUSANDS, row("Net position")],
          ("admitted", ["VALUE_DERIVED"])),
        c("o5", "dues", "70", "USD", [at("70"), row("Dues")], (REVIEW, ["PART_MISSING"], ["unit"])),
        c("o6", "rebate", "40", "USD", [at("40"), row("Rebate")], (REVIEW, ["PART_MISSING"], ["unit"])),
        c("o7", "region", "160", "USD", [at("160"), row("South")]),
        c("o8", "region", "110", "USD", [at("110"), row("South")], (REVIEW, ["PART_MISSING"], ["unit"])),
        c("o9", "fee", "75", "USD", [at("75"), row("Fee")]),
        c("o10", "region", "160", "USD", [q("160"), row("South")]),
    ],
)  # fmt: skip

TITLE_KEY = (
    "Balance sheet\nAs of September 30, 2025\n\nReport of the year\n\n"
    "Assets:\nCash\t$\t1,200\nTotal assets\t$\t1,500\n\n"
    "Statement of cost\nFor the year ended September 30, 2025\n\nReport of the year\n\n"
    "Program\t$\t300\t$\t280\nNet cost\t$\t900\t$\t850\n\n"
    "Changes in net position\nFor the year ended September 30, 2025\n\nReport of the year\n\n"
    "Notes to the statements\n\fEnding net position\t$\t1,100\n\n"
    "Revenue summary\nFor the year ended September 30, 2025\n\nReport of the year\n\n"
    "Revenue was $700 for the year."
)


def keyed_usd(*aliases: str) -> dict[str, Any]:
    return {"type": "integer", "unit": "USD", "keys": ["2025", "2024"], "multiple": True,
            "aliases": list(aliases)}  # fmt: skip


vector(
    "28-title-key",
    "When no key is at the value (4.5), the key of the nearest earlier mention reaches it also "
    "across a label line, when no page break stands between them, the value's line holds a tab "
    "before the value, and each line after the mention, up to the value's line, holds at most "
    "one number token after its first tab: a table with one number column under a title such "
    "as \"As of September 30, 2025\" (spec 0.8, #250).",
    TITLE_KEY,
    {
        "fields": {
            "assets": keyed_usd("total assets"),
            "cost": keyed_usd("net cost"),
            "net": keyed_usd("net position"),
            "revenue": keyed_usd("revenue"),
        }
    },
    [
        c("t1", "assets", "1500", "USD", [q("1,500"), row("Total assets")], key="2025"),
        c("t2", "assets", "1500", "USD", [q("1,500"), row("Total assets")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2024"),
        c("t3", "cost", "900", "USD", [q("900"), row("Net cost")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2025"),
        c("t4", "net", "1100", "USD", [q("1,100"), row("Ending net position")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2025"),
        c("t5", "revenue", "700", "USD", [q("$700"), row("Revenue")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2025"),
    ],
)  # fmt: skip


STRING_PLACE = (
    "Dosage\n\nHeart failure: take 5 mg daily. Hypertension: take with food.\n\n"
    "Angina: take at bedtime. Hypertension: take at bedtime."
)
TWO = "Heart failure: take 5 mg daily. Hypertension: take with food."
CROSS = "Hypertension: take with food.\n\nAngina: take at bedtime. Hypertension: take at bedtime."

vector(
    "29-string-value-place",
    "A string value is at its first occurrence in its evidence span, where whitespace runs match "
    "any whitespace run, and not at the start of the span: key scope reads the text there. When "
    "the span does not hold the value, step 10 rejects as before. A role quote that holds the "
    "value's occurrence is found there, and on the outside path the key check also reads the "
    "value's first occurrence in the quote (spec 0.8, #140).",
    STRING_PLACE,
    {"fields": {"instruction": {"type": "string", "keys": ["heart failure", "hypertension", "angina"], "multiple": True}}},
    [
        c("p1", "instruction", "take with food", None, q(TWO), key="hypertension"),
        c("p2", "instruction", "take with food", None, q(TWO),
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="heart failure"),
        c("p3", "instruction", "take 5 mg daily", None, q(TWO), key="heart failure"),
        c("p4", "instruction", "take at bedtime", None, q(CROSS), key="angina"),
        c("p5", "instruction", "take at bedtime", None, q(CROSS),
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="hypertension"),
        c("p6", "instruction", "take twice daily", None, q(TWO),
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"]), key="hypertension"),
        c("p7", "instruction", "take with food", None,
          [q("Hypertension: take with food."), {"role": "key", "text": "Hypertension: take with food."}],
          key="hypertension"),
        c("p8", "instruction", "take with food", None, [q(TWO), {"role": "key", "text": TWO}],
          key="hypertension"),
        c("p9", "instruction", "take with food", None, [ext(TWO)], (REVIEW, ["EVIDENCE_QUOTED"]),
          key="hypertension"),
        c("p10", "instruction", "take with food", None, [ext(TWO)],
          (REVIEW, ["KEY_NOT_AT_VALUE", "EVIDENCE_QUOTED"], ["key"]), key="heart failure"),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- explicit tab slots (spec 0.9, #278)
TAB_CASH = {
    "type": "number",
    "unit": "USD",
    "aliases": ["Cash"],
    "multiple": True,
    "keys": ["2025", "2024", "2023"],
}

vector(
    "30-empty-tab-leading",
    "An explicit empty tab slot counts before a number. A short table uses its own row keys, "
    "not both keys of a separate header line (spec 0.9, #278).",
    "2025\t2024\nCash\t\t$100",
    {"fields": {"cash": TAB_CASH}},
    [
        c("e1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("e2", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024")],
          ("admitted", ["KEY_CITED"]), key="2024"),
    ],
)  # fmt: skip

vector(
    "31-empty-tab-middle",
    "Spaces and carriage returns inside a tab slot do not fill it. A dash is a cell and an "
    "empty tab slot after it is another cell (spec 0.9, #278).",
    "2025\t2024\t2023\nCash\t-\t \r\t$100",
    {"fields": {"cash": TAB_CASH}},
    [
        c("m1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("m2", "cash", "100", "USD", [q("$100"), row("Cash"), year("2023")],
          ("admitted", ["KEY_CITED"]), key="2023"),
    ],
)  # fmt: skip

vector(
    "32-no-tab-row",
    "A field and value on the same line need a tab between them for the column rule. A short "
    "header made only of keys and whitespace does not supply both keys to the next line. "
    "Long tables have the same protection (spec 0.9, #278).",
    "2025\t2024\nCash $100\n\n2025 2024\nCash $200\n\n"
    "2025\t2024\nCash $300\nOther\t$20\t$30\nLast\t$40\t$50",
    {"fields": {"cash": TAB_CASH}},
    [
        c("n1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("n2", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("n3", "cash", "200", "USD", [q("$200"), row("Cash"), year("2025", 2)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("n4", "cash", "300", "USD", [q("$300"), row("Cash"), year("2025", 3)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
    ],
)  # fmt: skip

vector(
    "33-ambiguous-tab-row",
    "A tab row with several number cells inside one slot, or a nonempty slot with no cell, "
    "cannot supply a column key, including at the first number (spec 0.9, #278).",
    "2025\t2024\nCash\t$100 $200\t$300\n\n2025\t2024\nCash\t$400\tunknown",
    {"fields": {"cash": TAB_CASH}},
    [
        c("a1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("a2", "cash", "200", "USD", [q("$200"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("a3", "cash", "400", "USD", [q("$400"), row("Cash"), year("2025", 2)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
    ],
)  # fmt: skip

vector(
    "34-separate-line-cells",
    "The column rule still supports one cell on each line. A key on the value's own line "
    "still applies, including beside an ambiguous tab slot (spec 0.9, #278).",
    "2025\n2024\nCash\n$100\n$200\n\n2025\t2024\nCash for 2024\t$300 $400",
    {"fields": {"cash": TAB_CASH}},
    [
        c("s1", "cash", "200", "USD", [q("$200"), row("Cash"), year("2025", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("s2", "cash", "200", "USD", [q("$200"), row("Cash"), year("2024", 1)],
          ("admitted", ["KEY_CITED"]), key="2024"),
        c("s3", "cash", "300", "USD", [q("$300")], key="2024"),
    ],
)  # fmt: skip

UNIT_CASH = {"type": "number", "unit": "USD", "aliases": ["Cash"], "multiple": True}
vector(
    "35-empty-tab-unit-wrong-column",
    "An empty tab slot keeps a value out of the preceding unit column. An implicit unit stays "
    "missing, and an explicit item from that other column fails (spec 0.9, #278).",
    "Top\t$10\t20\nCash\t\t100\nOther\t30\t40",
    {"fields": {"cash": UNIT_CASH}},
    [
        c("u1", "cash", "100", "USD", [q("100"), row("Cash")],
          (REVIEW, ["PART_MISSING"], ["unit"])),
        c("u2", "cash", "100", "USD", [q("100"), row("Cash"), q("$", role="unit")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
    ],
)  # fmt: skip

vector(
    "36-empty-tab-unit-aligned",
    "A unit in the same numeric column still reaches a value after an explicit empty slot "
    "(spec 0.9, #278).",
    "Top\t10\t$20\nCash\t\t100\nOther\t30\t40",
    {"fields": {"cash": UNIT_CASH}},
    [
        c("u3", "cash", "100", "USD", [q("100"), row("Cash")]),
        c("u4", "cash", "100", "USD", [q("100"), row("Cash"), q("$", role="unit")]),
    ],
)  # fmt: skip

vector(
    "37-empty-tab-unit-source",
    "Empty slots in the unit's row count too. A lone currency prefix is a cell. A final blank "
    "slot is distinct from a lone prefix. A prefix alone does not end before its own cell's "
    "start, so it cannot itself supply a column unit. A blank slot cannot borrow the prior unit "
    "(spec 0.9, #278).",
    "Top\t\t$20\nCash\t10\t100\n\nTop\t10\t$\nCash\t\t200\n\n"
    "Top\t$30\t\nCash\t\t300",
    {"fields": {"cash": UNIT_CASH}},
    [
        c("u5", "cash", "100", "USD", [q("100"), row("Cash")]),
        c("u6", "cash", "200", "USD", [q("200"), row("Cash")],
          (REVIEW, ["PART_MISSING"], ["unit"])),
        c("u7", "cash", "300", "USD", [q("300"), row("Cash")],
          (REVIEW, ["PART_MISSING"], ["unit"])),
    ],
)  # fmt: skip

vector(
    "38-ambiguous-tab-unit-source",
    "A unit row with multiple cells in a tab slot cannot supply a unit by column, nor can a "
    "target row with multiple cells in one slot (spec 0.9, #278).",
    "Top\t$10 20\t30\nCash\t100\t200\n\nTop\t$40\t50\nCash\t300 400\t500",
    {"fields": {"cash": UNIT_CASH}},
    [
        c("u8", "cash", "100", "USD", [q("100"), row("Cash")],
          (REVIEW, ["PART_MISSING"], ["unit"])),
        c("u9", "cash", "300", "USD", [q("300"), row("Cash")],
          (REVIEW, ["PART_MISSING"], ["unit"])),
    ],
)  # fmt: skip


# A reader isolates an unaligned numeric-only row with two blank lines on both sides.
vector(
    "39-isolated-numeric-row",
    "Two adjacent blank lines break key inheritance and the column rule. An isolated numeric "
    "row cannot take any header key through the nearest-key or cited-column path "
    "(spec 0.9, #278).",
    "2025\t2024\t2023\nCash\n\n\n$100\n\n\nOther\t$20\t$30\t$40",
    {"fields": {"cash": TAB_CASH}},
    [
        c("b1", "cash", "100", "USD", [q("$100")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2025"),
        c("b2", "cash", "100", "USD", [q("$100")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2024"),
        c("b3", "cash", "100", "USD", [q("$100")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2023"),
        c("b4", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("b5", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("b6", "cash", "100", "USD", [q("$100"), row("Cash"), year("2023")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2023"),
    ],
)  # fmt: skip

vector(
    "40-isolated-field-block",
    "The break also stops an earlier header before a new field block. One blank line between "
    "separate cells retains the existing column rule (spec 0.9, #278).",
    "2025\t2024\n\n\nCash\t$100\t$200\n\n"
    "2025\n\n2024\n\nCash\n\n$300\n\n$400",
    {"fields": {"cash": TAB_CASH}},
    [
        c("b7", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("b8", "cash", "200", "USD", [q("$200"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("b9", "cash", "300", "USD", [q("$300"), row("Cash"), year("2025", 2)],
          ("admitted", ["KEY_CITED"]), key="2025"),
        c("b10", "cash", "400", "USD", [q("$400"), row("Cash"), year("2024", 2)],
          ("admitted", ["KEY_CITED"]), key="2024"),
    ],
)  # fmt: skip


vector(
    "41-header-nearest-key",
    "After a paragraph end, the last key of a header is not a nearest prose key. A no-tab "
    "row cannot inherit that last header key, while a cited aligned tab row still uses columns "
    "(spec 0.9, #278).",
    "2025\t2024\n\nCash $100\n\n2025\t2024\n\nCash\t$200\t$300",
    {"fields": {"cash": TAB_CASH}},
    [
        c("h1", "cash", "100", "USD", [q("$100")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2025"),
        c("h2", "cash", "100", "USD", [q("$100")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2024"),
        c("h3", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("h4", "cash", "300", "USD", [q("$300"), row("Cash"), year("2024", 2)],
          ("admitted", ["KEY_CITED"]), key="2024"),
    ],
)  # fmt: skip


vector(
    "42-empty-unit-source-slot",
    "A unit form cannot anchor to an empty tab slot in its own row. A bare currency prefix "
    "in an earlier slot must not supply a later blank column (spec 0.9, #278).",
    "Top\t$\t \r\nCash\t\t100",
    {"fields": {"cash": UNIT_CASH}},
    [
        c("z1", "cash", "100", "USD", [q("100"), row("Cash")],
          (REVIEW, ["PART_MISSING"], ["unit"])),
        c("z2", "cash", "100", "USD", [q("100"), row("Cash"), q("$", role="unit")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
    ],
)  # fmt: skip


vector(
    "43-break-inside-header",
    "A key break also splits a run of header keys. An earlier key cannot regain scope through "
    "a later key after the break (spec 0.9, #278).",
    "2025\n\n\n2024\n\nCash\t$100",
    {"fields": {"cash": TAB_CASH}},
    [
        c("r1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("r2", "cash", "100", "USD", [q("$100")], key="2024"),
    ],
)  # fmt: skip


vector(
    "44-labeled-short-header",
    "A separate tabbed line with several keys is a table header even when it has a label. "
    "Neither header key applies directly to the next no-tab row (spec 0.9, #278).",
    "Year\t2025\t2024\nCash $100",
    {"fields": {"cash": TAB_CASH}},
    [
        c("l1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("l2", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
    ],
)  # fmt: skip

vector(
    "45-labeled-header-key-scope",
    "A labeled tab header does not supply a nearest prose key after a paragraph end. A tabbed "
    "data row can use the header, also with a non-key column after the known keys "
    "(spec 0.9, #278).",
    "Year\t2025\t2024\n\nCash $100\n\nYear\t2025\t2024\tChange\nCash\t\t$200\t$10",
    {"fields": {"cash": TAB_CASH}},
    [
        c("l3", "cash", "100", "USD", [q("$100")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="2024"),
        c("l4", "cash", "200", "USD", [q("$200"), row("Cash"), year("2024", 2)],
          ("admitted", ["KEY_CITED"]), key="2024"),
    ],
)  # fmt: skip

vector(
    "46-unknown-header-slot",
    "A key run that starts after an unknown header slot cannot treat its first key as the first "
    "data column. A non-key slot between keys also stops the later run (spec 0.9, #278).",
    "Year\tChange\t2025\t2024\nCash\t$100\t$200\t$300\n\n"
    "Year\t2025\tChange\t2024\nCash\t$400\t$500\t$600",
    {"fields": {"cash": TAB_CASH}},
    [
        c("l5", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("l6", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("l7", "cash", "400", "USD", [q("$400"), row("Cash"), year("2024", 2)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
    ],
)  # fmt: skip

vector(
    "47-empty-leading-header-slot",
    "A leading empty data slot in a header does not shift the first known key to column one. "
    "The column rule refuses that header instead (spec 0.9, #278).",
    "Year\t\t2025\t2024\nCash\t$100\t$200\t$300",
    {"fields": {"cash": TAB_CASH}},
    [
        c("l8", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("l9", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
    ],
)  # fmt: skip


vector(
    "48-ambiguous-header-prefix",
    "A header's first slot that contains a key plus other text, or several keys, cannot be "
    "discarded as a row label and shift the next key to the first numeric column "
    "(spec 0.9, #278).",
    "2025 (restated)\t2024\nCash\t$100\t$200\n\n"
    "2025 2024\t2023\nCash\t$300\t$400\t$500",
    {"fields": {"cash": TAB_CASH}},
    [
        c("p1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("p2", "cash", "300", "USD", [q("$300"), row("Cash"), year("2023")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2023"),
    ],
)  # fmt: skip


vector(
    "49-prose-key-break",
    "Two adjacent blank lines stop a prose heading from reaching its value. One blank line "
    "retains the heading, and a key in the value's own sentence still applies after a break "
    "(spec 0.9, #278).",
    "Hypertension\n\n\nThe dose is 5 mg.\n\n"
    "Angina\n\nThe dose is 7 mg.\n\n"
    "Hypertension\n\n\nFor Hypertension the dose is 9 mg.",
    {"fields": {"dose": {"type": "integer", "unit": "mg", "multiple": True,
                         "keys": ["Hypertension", "Angina"]}}},
    [
        c("p1", "dose", "5", "mg", [q("5 mg")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]), key="Hypertension"),
        c("p2", "dose", "7", "mg", [q("7 mg")], key="Angina"),
        c("p3", "dose", "9", "mg", [q("9 mg")], key="Hypertension"),
    ],
)  # fmt: skip


vector(
    "50-empty-middle-header-slot",
    "A blank slot between known header keys cannot be compressed out of their ordinals. "
    "The header stays unusable even when a data value is physically aligned to its later key "
    "(spec 0.9, #278 security review).",
    "2025\t\t2024\nCash\t\t$100\n\n"
    "2025\t\t2024\nCash\t\t\t$200\n\n"
    "Year\t2025\t \r\t2024\nCash\t\t$300",
    {"fields": {"cash": TAB_CASH}},
    [
        c("h1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("h2", "cash", "200", "USD", [q("$200"), row("Cash"), year("2024", 2)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("h3", "cash", "300", "USD", [q("$300"), row("Cash"), year("2024", 3)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
    ],
)  # fmt: skip

vector(
    "51-header-tab-boundaries",
    "Adjacent keys in a tabbed header need exactly one tab between them. Keys merged into "
    "one data slot cannot supply two column ordinals. A trailing non-key column remains "
    "supported after the known keys (spec 0.9, #278 security review).",
    "Year\t2025 2024\nCash\t$400\t$500\n\n"
    "Year\t2025\t2024\tChange\nCash\t\t$900\t$5",
    {"fields": {"cash": TAB_CASH}},
    [
        c("h4", "cash", "500", "USD", [q("$500"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("h5", "cash", "900", "USD", [q("$900"), row("Cash"), year("2024", 2)],
          ("admitted", ["KEY_CITED"]), key="2024"),
    ],
)  # fmt: skip

vector(
    "52-cross-line-tab-header",
    "A header run mixing tabs and line breaks has ambiguous ordinals and cannot supply a "
    "column key. It cannot bypass the column check through short-sentence keys. The existing "
    "separate-line header and cell stream with no tabs remains supported "
    "(spec 0.9, #278 security review).",
    "2025\n\t\t2024\nCash\t\t$600\n\n"
    "2025\t\n2024\nCash\t\t$700\n\n"
    "2025\t2024\n2023\nCash\t\t$800\n\n"
    "2025\n2024\nCash\n$1,000\n$1,100",
    {"fields": {"cash": TAB_CASH}},
    [
        c("h6", "cash", "600", "USD", [q("$600"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("h7", "cash", "700", "USD", [q("$700"), row("Cash"), year("2024", 2)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("h8", "cash", "800", "USD", [q("$800"), row("Cash"), year("2024", 3)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("h9", "cash", "1100", "USD", [q("$1,100"), row("Cash"), year("2024", 4)],
          ("admitted", ["KEY_CITED"]), key="2024"),
    ],
)  # fmt: skip

vector(
    "53-short-separate-key-header",
    "A short header on separate key-only lines does not supply both keys to a no-tab row "
    "(spec 0.9, #278 security review).",
    "2025\n2024\nCash $100",
    {"fields": {"cash": TAB_CASH}},
    [
        c("h10", "cash", "100", "USD", [q("$100"), row("Cash"), year("2025")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2025"),
        c("h11", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
    ],
)  # fmt: skip


vector(
    "54-labeled-mixed-header",
    "Optional labels and trailing non-key slots do not turn a mixed tab/separate-line key "
    "header into prose. Such a header must reach the conservative column refusal "
    "(spec 0.9, #278 security review).",
    "Year\t2025\n2024\nCash\t\t$100\n\n"
    "Year\t2025\n\t2024\nCash\t\t$200\n\n"
    "Year\t2025\n2024\tChange\nCash\t\t$300\n\n"
    "Year\t2025\n\t2024\tChange\nCash\t\t$400",
    {"fields": {"cash": TAB_CASH}},
    [
        c("m1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("m2", "cash", "200", "USD", [q("$200"), row("Cash"), year("2024", 2)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("m3", "cash", "300", "USD", [q("$300"), row("Cash"), year("2024", 3)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("m4", "cash", "400", "USD", [q("$400"), row("Cash"), year("2024", 4)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
    ],
)  # fmt: skip

vector(
    "55-mixed-header-direct-key",
    "A direct key on the value's own line still applies beneath an ambiguous mixed header. "
    "A single-key heading retains its existing scope (spec 0.9, #278 security review).",
    "Year\t2025\n\t2024\nCash for 2024\t$500\n\n"
    "Year\t2024\nCash $600",
    {"fields": {"cash": TAB_CASH}},
    [
        c("m5", "cash", "500", "USD", [q("$500"), row("Cash for 2024"), year("2024", 2)],
          ("admitted", []), key="2024"),
        c("m6", "cash", "600", "USD", [q("$600")], key="2024"),
    ],
)  # fmt: skip


vector(
    "56-interrupted-mixed-header",
    "A trailing non-key slot on an earlier key line cannot hide a mixed tabbed header. One "
    "blank line between its key lines does not restore a prose heading or a compressed "
    "column ordinal (spec 0.9, #278 security review).",
    "Year\t2025\tChange\n2024\nCash\t\t$100\n\n"
    "Year\t2025\tChange\n2024\nCash\t$200\n\n"
    "Year\t2025\tChange\n\n2024\tChange\nCash\t\t$300\n\n"
    "Data for 2025.\n\nFor 2024\nCash $400",
    {"fields": {"cash": TAB_CASH}},
    [
        c("i1", "cash", "100", "USD", [q("$100"), row("Cash"), year("2024", 1)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("i2", "cash", "200", "USD", [q("$200"), row("Cash"), year("2024", 2)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("i3", "cash", "300", "USD", [q("$300"), row("Cash"), year("2024", 3)],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
        c("i4", "cash", "400", "USD", [q("$400")], key="2024"),
    ],
)  # fmt: skip


vector(
    "57-lone-prefix-row-slot",
    "A tabbed row whose only data slot holds a lone unit prefix is not ambiguous. Its cells on "
    "separate lines keep the column rule, as with no tab (spec 0.9 review).",
    "2025\n2024\nCash\t$\n100\n200",
    {"fields": {"cash": TAB_CASH}},
    [
        c("w1", "cash", "100", "USD", [q("100"), row("Cash"), year("2025"), q("$", role="unit")],
          ("admitted", ["KEY_CITED"]), key="2025"),
        c("w2", "cash", "100", "USD", [q("100"), row("Cash"), year("2024"), q("$", role="unit")],
          (REVIEW, ["KEY_NOT_AT_VALUE"]), key="2024"),
    ],
)  # fmt: skip


vector(
    "58-split-currency-slots",
    "A lone unit prefix in its own slot before an empty slot or a lone dash belongs to that "
    "column. It is not a second cell, so the next value keeps its own key (spec 0.9 review).",
    "\t2025\t2024\t2023\nCash\t$\t\t$\t200\t$\t300\n\n"
    "\t2025\t2024\t2023\nCash\t$\t-\t$\t400\t$\t500",
    {"fields": {"cash": TAB_CASH}},
    [
        c("w3", "cash", "200", "USD", [q("200"), q("$", 2, role="unit"), row("Cash"),
                                       year("2024", 1)], ("admitted", ["KEY_CITED"]), key="2024"),
        c("w4", "cash", "200", "USD", [q("200"), q("$", 2, role="unit"), row("Cash"),
                                       year("2023", 1)], (REVIEW, ["KEY_NOT_AT_VALUE"]),
          key="2023"),
        c("w5", "cash", "300", "USD", [q("300"), q("$", 3, role="unit"), row("Cash"),
                                       year("2023", 1)], ("admitted", ["KEY_CITED"]), key="2023"),
        c("w6", "cash", "400", "USD", [q("400"), q("$", 5, role="unit"), row("Cash"),
                                       year("2024", 2)], ("admitted", ["KEY_CITED"]), key="2024"),
        c("w7", "cash", "400", "USD", [q("400"), q("$", 5, role="unit"), row("Cash"),
                                       year("2023", 2)], (REVIEW, ["KEY_NOT_AT_VALUE"]),
          key="2023"),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- several field items (spec 0.10, #300)
SEVERAL = {"type": "number", "unit": "USD", "aliases": ["Cash", "Ending balance"], "multiple": True}
NO_ALIASES = {"type": "number", "unit": "USD", "multiple": True}
F, T = ("field", False), ("field", True)
vector(
    "59-several-field-items",
    "A candidate may cite several field items, such as a row label and a column header. Each one "
    "is checked and listed in parts. The field check passes when one of them passes. Only when "
    "none passes does the decision get FIELD_CITATION_INVALID. A passing one lets a unit item or "
    "a unit at a unit place supply the unit, and selects the value's quote occurrence. Two items "
    "of any other role stay CANDIDATE_INVALID, and so does a candidate with more than 8 field "
    "items (spec 0.10, #300).",
    "Ending balance\n\nCash\t$100\n\n"
    "Amounts in $\nEnding balance\nCash\t200\n\n"
    "Other items were about $50.\nCash\t50",
    {"fields": {"cash": SEVERAL, "plain": NO_ALIASES}},
    [
        # the header is in another sentence; the row label passes
        c("p1", "cash", "100", "USD", [q("$100"), row("Ending balance"), row("Cash")],
          ("admitted", [], [], [F, T])),
        c("p2", "cash", "100", "USD", [q("$100"), row("Cash"), row("Ending balance")],
          ("admitted", [], [], [T, F])),
        c("p3", "cash", "100", "USD", [q("$100"), row("Ending balance"), row("Revenue")],
          (REVIEW, ["FIELD_CITATION_INVALID"], [], [F, F])),
        c("p4", "cash", "100", "USD", [q("$100"), row("Cash"), row("Cash")],
          ("admitted", [], [], [T, T])),
        # no aliases: the field items are not checked and add no flag
        c("p5", "plain", "100", "USD", [q("$100"), row("Cash"), row("Ending balance")],
          ("admitted", [], [], [F, F])),
        # the header in the value's sentence also passes; the $ of the caption is at a unit place
        c("p6", "cash", "200", "USD", [q("200"), row("Ending balance"), row("Cash")],
          ("admitted", [], [], [T, T])),
        c("p7", "cash", "200", "USD", [q("200"), row("Revenue"), row("Ending balance")],
          ("admitted", [], [], [F, T])),
        c("p8", "cash", "200", "USD", [q("200"), row("Amounts"), row("Cash"), DOLLAR],
          ("admitted", [], [], [("unit", True), F, T])),
        c("p9", "cash", "200", "USD", [q("200"), row("Amounts"), row("Revenue"), DOLLAR],
          (REVIEW, ["UNIT_CITATION_INVALID", "FIELD_CITATION_INVALID"], [],
           [("unit", False), F, F])),
        c("p10", "cash", "200", "USD", [q("200"), row("Amounts"), row("Revenue")],
          (REVIEW, ["PART_MISSING", "FIELD_CITATION_INVALID"], ["unit"], [F, F])),
        # a quote: the occurrence where the second field item passes, not the first occurrence
        c("p11", "cash", "50", "USD", [{"text": "50"}, row("Revenue"), row("Cash")],
          (REVIEW, ["PART_MISSING"], ["unit"], [F, T])),
        c("p12", "cash", "50", "USD", [{"text": "50"}, row("Revenue")],
          (REVIEW, ["QUALIFIED_VALUE", "FIELD_CITATION_INVALID"], [], [F])),
        # at most 8 field items: 8 are checked, 9 make the candidate invalid
        c("p13", "cash", "100", "USD", [q("$100"), *[row("Revenue")] * 7, row("Cash")],
          ("admitted", [], [], [F, F, F, F, F, F, F, T])),
        c("p14", "cash", "100", "USD", [q("$100"), *[row("Revenue")] * 8, row("Cash")],
          ("rejected", ["CANDIDATE_INVALID"])),
        # two items of another role
        *[
            c(f"x{n}", "cash", "100", "USD", [q("$100"), *ev], ("rejected", ["CANDIDATE_INVALID"]))
            for n, ev in enumerate(
                [
                    [{"text": "$100"}],
                    [DOLLAR, DOLLAR],
                    [THOUSANDS, {"role": "scale", "text": "in thousands"}],
                    [{"role": "sign", "text": "("}, {"role": "sign", "text": "loss"}],
                    [year("2024"), year("2025")],
                    [row("Cash"), DOLLAR, {"role": "unit", "text": "USD"}],
                ],
                1,
            )
        ],
    ],
)  # fmt: skip

BALANCES = {
    "type": "number",
    "unit": "USD",
    "aliases": ["Cash", "Balances"],
    "multiple": True,
    "keys": ["Current", "Prior"],
}
vector(
    "63-several-field-items-column",
    "The column rule reads the first field item that passes at the value's row (spec 0.10, "
    "#300). A column header in the corner slot, before the first tab of the header line, is in a "
    "label slot, so it does not pass for a value on a later line (spec 0.10, #316). The row "
    "label after it still passes and places the key.",
    "Balances\tCurrent\tPrior\nCash\t$400\t$500",
    {"fields": {"cash": BALANCES}},
    [
        c("k1", "cash", "400", "USD", [q("$400"), row("Balances"), row("Cash"), year("Current")],
          ("admitted", ["KEY_CITED"], [], [F, T, ("key", True)]), key="Current"),
        c("k2", "cash", "500", "USD", [q("$500"), row("Cash"), row("Balances"), year("Prior")],
          ("admitted", ["KEY_CITED"], [], [T, F, ("key", True)]), key="Prior"),
        c("k3", "cash", "400", "USD", [q("$400"), row("Balances"), year("Current")],
          (REVIEW, ["FIELD_CITATION_INVALID", "KEY_NOT_AT_VALUE"], [], [F, ("key", True)]),
          key="Current"),
        c("k4", "cash", "400", "USD", [q("$400"), row("Balances"), row("Cash"), year("Prior")],
          (REVIEW, ["KEY_NOT_AT_VALUE"], [], [F, T, ("key", True)]), key="Prior"),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- spec 0.10 (#301)
vector(
    "60-currency-scale-suffix",
    "A number with a currency sign directly before it and k, m or bn (and the listed case "
    "variants) directly after it has a scaled value, as a scale word gives one. A candidate equal "
    "to the number as written is flagged SCALE_WORD. Without the currency sign (70 m, 5m), with a "
    "space before the m (£5 m) or after the sign (£ 9m), or with mm, the number has no scaled "
    "value: such an m can be a unit (spec 0.10, #301).",
    "Revenue was €70,471m in 2025. Debt was £32.7bn at year end. Fees were $250k and costs "
    "were $1.2M. Grants were £3Bn. Taxes were ₹4m. The site is 70 m long. The pole is 5m high. "
    "The fund holds £5 m in cash. The levy is £ 9m. The pipe is £5mm wide.",
    {
        "fields": {
            "revenue": {"type": "number", "unit": "EUR", "multiple": True},
            "debt": {"type": "number", "unit": "GBP"},
            "fees": USD,
            "costs": USD,
            "grants": {"type": "integer", "unit": "GBP"},
            "taxes": {"type": "integer", "unit": "INR"},
            "length": {"type": "number"},
            "height": {"type": "number", "multiple": True},
            "cash": {"type": "integer", "unit": "GBP", "multiple": True},
            "levy": {"type": "integer", "unit": "GBP"},
            "width": {"type": "number", "unit": "GBP"},
        }
    },
    [
        c("cs1", "revenue", "70471000000", "EUR", [q("€70,471m")]),
        c("cs2", "revenue", "70471", "EUR", [q("€70,471m")], (REVIEW, ["SCALE_WORD"])),
        c("cs3", "debt", "32700000000", "GBP", [q("£32.7bn")]),
        c("cs4", "fees", "250000", "USD", [q("$250k")]),
        c("cs5", "costs", "1200000", "USD", [q("$1.2M")]),
        c("cs6", "grants", "3000000000", "GBP", [q("£3Bn")]),
        c("cs7", "taxes", "4000000", "INR", [q("₹4m")]),
        # metres: no currency sign, so no scale
        c("cs8", "length", "70", None, [q("70 m long")]),
        c("cs9", "height", "5", None, [q("5m high")]),
        c("cs10", "height", "5000000", None, [q("5m high")],
          (REVIEW, ["PART_MISSING"], ["scale"])),
        # a space between the number and the m: the m is not read as a scale
        c("cs11", "cash", "5", "GBP", [q("£5 m in")]),
        c("cs12", "cash", "5000000", "GBP", [q("£5 m in")],
          (REVIEW, ["PART_MISSING"], ["scale"])),
        # a space between the sign and the number
        c("cs13", "levy", "9", "GBP", [q("£ 9m")]),
        # mm is not m
        c("cs14", "width", "5", "GBP", [q("£5mm")]),
    ],
)  # fmt: skip

vector(
    "61-currency-scale-heading",
    "A currency scale (£m, £'000, $bn) is a heading scale on any line, with or without a tab. It "
    "reaches the lines with tabs after it, as a heading scale in words does, so a value there "
    "equal to the number as written misses its scale. A table after a blank line, a line with no "
    "tab, a bare (m) and a £ m with a space are not reached (spec 0.10, #301).",
    "Group income statement\n\n\t2025\t2024\n\t£m\t£m\nRevenue\t5,210\t4,980\n\n"
    "Balance sheet\n£'000\t2025\t2024\nCash\t1,250\t1,100\n\n"
    "Cash flow\n\t$bn\nCapex\t1.5\n\n"
    "Segment note\n\t2025\nUnits\t870\n\n"
    "Figures are in £m.\nStaff numbers were 640 at year end.\n\n"
    "Pipe lengths (m)\n\t2025\nMain\t75\n\n"
    "Water use\n\t£ m\nWater\t63\n",
    {"fields": {"amount": {"type": "number", "multiple": True}}},
    [
        c("ch1", "amount", "5210", None, [q("5,210")], (REVIEW, ["PART_MISSING"], ["scale"])),
        c("ch2", "amount", "1250", None, [q("1,250")], (REVIEW, ["PART_MISSING"], ["scale"])),
        c("ch3", "amount", "1.5", None, [q("1.5")], (REVIEW, ["PART_MISSING"], ["scale"])),
        c("ch4", "amount", "870", None, [q("870")]),
        # a £m with no line with a tab after it reaches no number
        c("ch5", "amount", "640", None, [q("640")]),
        c("ch6", "amount", "75", None, [q("75")]),
        c("ch7", "amount", "63", None, [q("63")]),
    ],
)  # fmt: skip

CURRENCY_TABLES = (
    "Group income statement\n\n\t2025\t2024\n\t£m\t£m\nRevenue\t5,210\t4,980\n\n"
    "Balance sheet\n£'000\t2025\t2024\nCash\t1,250\t1,100\n\n"
    "Notes\n\t£\u2019000\nFees\t75\n\n"
    "Cash flow\n\t$M\nCapex\t42\n\n"
    "Debt\n\t£m\nLoans\t30\n\t£bn\nBonds\t19\n\n"
    "Interest of 12 is stated in £m.\n\n"
    "Pipe lengths (m)\n\t2025\nMain\t96\n"
)
vector(
    "62-currency-scale-item",
    "A scale item can hold a currency scale (£m, £'000, £\u2019000, $M, £bn) in place of 'in' and a "
    "scale word. It scales the number as written. It fails when it ends after the value, or when "
    "a currency scale of another power of ten lies between it and the value; the same currency "
    "scale in the next column does not stop it. A bare (m) is no scale (spec 0.10, #301).",
    CURRENCY_TABLES,
    {"fields": {"amount": {"type": "number", "multiple": True}}},
    [
        c("ci1", "amount", "5210000000", None, [q("5,210"), {"role": "scale", "text": "£m"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("ci2", "amount", "4980000000", None, [q("4,980"), q("£m", 1, role="scale")],
          ("admitted", ["VALUE_DERIVED"])),
        c("ci3", "amount", "5210", None, [q("5,210"), {"role": "scale", "text": "£m"}],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("ci4", "amount", "1250000", None, [q("1,250"), {"role": "scale", "text": "£'000"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("ci5", "amount", "75000", None, [q("75"), {"role": "scale", "text": "£\u2019000"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("ci6", "amount", "42000000", None, [q("42"), {"role": "scale", "text": "$M"}],
          ("admitted", ["VALUE_DERIVED"])),
        # £bn lies between the £m and the value
        c("ci7", "amount", "19000000", None, [q("19"), q("£m", 3, role="scale")],
          (REVIEW, ["SCALE_CITATION_INVALID", "VALUE_DERIVED"])),
        c("ci8", "amount", "19000000000", None, [q("19"), {"role": "scale", "text": "£bn"}],
          ("admitted", ["VALUE_DERIVED"])),
        # the scale item ends after the value: it fails, but still gives its scale
        c("ci9", "amount", "12000000", None, [q("12"), q("£m", 4, role="scale")],
          (REVIEW, ["SCALE_CITATION_INVALID", "VALUE_DERIVED"])),
        c("ci10", "amount", "96000000", None, [q("96"), {"role": "scale", "text": "(m)"}],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
    ],
)  # fmt: skip

# ---------------------------------------------------------------- dash variants (spec 0.10, #317)
OOP = {"type": "integer", "unit": "USD", "multiple": True}
vector(
    "74-alias-dash-variants",
    "A dash in an alias matches any of the five dashes: U+002D, U+2010, U+2011, U+2012 and "
    "U+2013. A dash between two letters also matches a dash, one line break and spaces or "
    "carriage returns around it. The minus sign, the em dash, a space, a blank line or a tab after "
    "the dash, a space for a dash, and a line break in a word with no dash do not match "
    "(spec 0.10, #317).",
    "Out\u2013of\u2013pocket limit\t$3,001\n\n"
    "Out\u2010of\u2010pocket limit\t$3,002\n\n"
    "Out\u2011of\u2011pocket limit\t$3,003\n\n"
    "Out\u2012of\u2012pocket limit\t$3,004\n\n"
    "Out-of-pocket limit\t$3,005\n\n"
    "Out-of-\npocket limit\t$3,006\n\n"
    "Out-of- \r\n  pocket limit\t$3,007\n\n"
    "Out\u2212of\u2212pocket limit\t$3,008\n\n"
    "Out\u2014of\u2014pocket limit\t$3,009\n\n"
    "Out-of- pocket limit\t$3,010\n\n"
    "Out-of-\n\npocket limit\t$3,011\n\n"
    "Out-of-\tpocket limit\t$3,012\n\n"
    "Out of pocket limit\t$3,013\n\n"
    "Out-of-pocket limit\t$3,014\n\n"
    "Overall deduct-\nible\t$500",
    {
        "fields": {
            "oop": {**OOP, "aliases": ["out-of-pocket limit"]},
            "oop_en": {**OOP, "aliases": ["out\u2013of\u2013pocket limit"]},
            "oop_space": {**OOP, "aliases": ["out of pocket limit"]},
            "ded": {**OOP, "aliases": ["deductible"]},
        }
    },
    [
        c("d1", "oop", "3001", "USD", [q("$3,001"), q("Out\u2013of\u2013pocket limit", role="field")]),
        c("d2", "oop", "3002", "USD", [q("$3,002"), q("Out\u2010of\u2010pocket limit", role="field")]),
        c("d3", "oop", "3003", "USD", [q("$3,003"), q("Out\u2011of\u2011pocket limit", role="field")]),
        c("d4", "oop", "3004", "USD", [q("$3,004"), q("Out\u2012of\u2012pocket limit", role="field")]),
        # an alias with en dashes matches the text with hyphens
        c("d5", "oop_en", "3005", "USD", [q("$3,005"), q("Out-of-pocket limit", role="field")]),
        # a line break after the dash: the quote finds the text with any whitespace run
        c("d6", "oop", "3006", "USD", [q("$3,006"), row("Out-of- pocket limit")]),
        c("d7", "oop", "3007", "USD",
          [q("$3,007"), q("Out-of- \r\n  pocket limit", role="field")]),
        # the minus sign and the em dash are not dashes here
        c("d8", "oop", "3008", "USD", [q("$3,008"), q("Out\u2212of\u2212pocket limit", role="field")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        c("d9", "oop", "3009", "USD", [q("$3,009"), q("Out\u2014of\u2014pocket limit", role="field")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        # a space, a blank line or a tab after the dash does not join
        c("d10", "oop", "3010", "USD", [q("$3,010"), q("Out-of- pocket limit", role="field")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        c("d11", "oop", "3011", "USD",
          [q("$3,011"), q("Out-of-\n\npocket limit", role="field")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        c("d12", "oop", "3012", "USD", [q("$3,012"), q("Out-of-\tpocket limit", role="field")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        # a space is not a dash, and a dash is not a space
        c("d13", "oop", "3013", "USD", [q("$3,013"), q("Out of pocket limit", role="field")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        c("d14", "oop_space", "3014", "USD",
          [q("$3,014"), q("Out-of-pocket limit", 2, role="field")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        # a line break in a word with no dash in the alias does not join
        c("d15", "ded", "500", "USD", [q("$500"), q("Overall deduct-\nible", role="field")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
    ],
)  # fmt: skip

vector(
    "75-key-dash-variants",
    "Keys follow the same rule as aliases. A key with an en dash matches the text with a hyphen, "
    "and a key with a dash between two letters matches across one line break. A dash between two "
    "digits does not join across a line break, and the minus sign is not a dash "
    "(spec 0.10, #317).",
    "For 2024-25: $100.\n\n\n"
    "For non-\nsmall cell lung cancer, the dose is 150 mg.\n\n\n"
    "For 2024-\n25: $200.\n\n\n"
    "For FY2024\u221225: $300.",
    {
        "fields": {
            "year_en": {**OOP, "keys": ["2024\u201325"]},
            "dose": {"type": "number", "unit": "mg", "keys": ["non-small cell lung cancer"]},
            "year": {**OOP, "keys": ["2024-25"]},
            "fiscal": {**OOP, "keys": ["FY2024-25"]},
        }
    },
    [
        c("y1", "year_en", "100", "USD", [q("$100")], key="2024\u201325"),
        c("y2", "dose", "150", "mg", [q("150 mg")], key="non-small cell lung cancer"),
        c("y3", "year", "200", "USD", [q("$200")], (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]),
          key="2024-25"),
        c("y4", "fiscal", "300", "USD", [q("$300")], (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]),
          key="FY2024-25"),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- label cells (spec 0.10, #316)
QUESTION = "What is the overall deductible?"
vector(
    "76-label-cells",
    "On a line with a tab, a field item in the label slot (before the first tab) is a label cell "
    "for a value in the answer slot (the next slot): no number token between, at most 4 words "
    "before the value in the answer slot, no sentence end there and no alias mention there. A "
    "field item in a label slot reaches a later slot or a later line only at the row. A value in "
    "the label slot, and a line with no tab, keep the sentence rule (spec 0.10, #316).",
    f"{QUESTION}\tIn-Network: Individual $850 / Family $1,700\tGenerally, you must pay all of "
    "the costs.\n\n"
    f"{QUESTION}\t$500 individual\n\n"
    f"{QUESTION}\tFor all network providers: $500\n\n"
    f"{QUESTION}\tFor all of the network providers: $500\n\n"
    f"{QUESTION}\tYes. $250 for drugs\n\n"
    f"{QUESTION}\tOut-of-pocket limit $3,000\n\n"
    f"{QUESTION}\tNone\tThis plan pays after a $40 copay\n\n"
    f"{QUESTION}\tNone\nAre there other costs?\tA $40 copay\n\n"
    f"{QUESTION}\n\nIn-Network: Individual $850\n\n"
    "The overall deductible is $500 per person.\tSee page 2\n\n"
    f"{QUESTION} In-Network: Individual $850\n\n"
    "Cash\tn/a\t$100",
    {
        "fields": {
            "ded": {**OOP, "aliases": ["overall deductible"]},
            "oop": {**OOP, "aliases": ["out-of-pocket limit"]},
            "cash": {**OOP, "aliases": ["cash"]},
        }
    },
    [
        c("l1", "ded", "850", "USD", [q("$850"), row("overall deductible")]),
        # at the row, as before
        c("l2", "ded", "500", "USD", [q("$500"), row("overall deductible")]),
        # 4 words before the value
        c("l3", "ded", "500", "USD", [q("$500", 2), row("overall deductible")]),
        # a number token between
        c("l4", "ded", "1700", "USD", [q("$1,700"), row("overall deductible")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        # 6 words before the value
        c("l5", "ded", "500", "USD", [q("$500", 3), row("overall deductible")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        # a sentence end in the answer slot
        c("l6", "ded", "250", "USD", [q("$250"), row("overall deductible")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        # an alias of another field in the answer slot
        c("l7", "ded", "3000", "USD", [q("$3,000"), row("overall deductible")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        # a later slot and a later line: admitted before spec 0.10
        c("l8", "ded", "40", "USD", [q("$40"), row("overall deductible")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        c("l9", "ded", "40", "USD", [q("$40", 2), row("overall deductible")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        # the question and the answer in two blocks, as the PDF reader writes them today
        c("l10", "ded", "850", "USD", [q("$850", 2), row("overall deductible")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
        # the value in the label slot keeps the sentence rule
        c("l11", "ded", "500", "USD", [q("$500", 4), row("overall deductible")]),
        # a line with no tab keeps the sentence rule
        c("l12", "ded", "850", "USD", [q("$850", 3), row("overall deductible")]),
        # a text cell between the label and the value: admitted before spec 0.10
        c("l13", "cash", "100", "USD", [q("$100"), row("Cash")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
    ],
)  # fmt: skip


vector(
    "77-label-line-spaces",
    "A line that holds only spaces is a blank line (§4.2), also before and after a label line. "
    "So the label line stops the key of the earlier heading, and the value goes to review (#348).",
    "2.1 Hypertension\n\nThe starting dose is 10 mg once daily.\n \n"
    "Adults\n \nThe usual dose is 15 mg daily.",
    {"fields": {"starting_dose": KEYED_MG, "usual_dose": KEYED_MG}},
    [
        c("s1", "starting_dose", "10", "mg", q("10 mg"), key="hypertension"),
        # "Adults" has a line of spaces on each side, so it is a label line
        c("s2", "usual_dose", "15", "mg", q("15 mg"), (REVIEW, ["KEY_NOT_AT_VALUE"]),
          key="hypertension"),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- case of listed words (#350, #356)
vector(
    "78-scale-word-letters",
    "A scale word matches case-insensitively by the fold of each letter (SPEC §4): the long s "
    "(U+017F) folds to s, and the dotted capital I (U+0130) and the dotless i (U+0131) fold to i. "
    "So 'thou\u017fand', 'b\u0130llion' and 'm\u0131ll\u0131on' are scale words, and "
    "'(in thou\u017fands)' is a heading scale and a scale item. Before #350, such a packet raised "
    "an error and gave no receipt (spec 0.10, #350, #356).",
    "The fee is 5 thou\u017fand. The levy is 2 b\u0130llion. The toll is 3 m\u0131ll\u0131on. The cap is 4 THOUSAND."
    "\n\nAmounts (in thou\u017fands)\nFees\t75\n",
    {
        "fields": {
            "fee": {"type": "integer"},
            "fee_scaled": {"type": "integer"},
            "levy": {"type": "integer"},
            "toll": {"type": "integer"},
            "cap": {"type": "integer"},
            "fees": {"type": "number"},
            "fees_scaled": {"type": "number"},
        }
    },
    [
        # the input of #350: the number as written before a scale word
        c("t1", "fee", "5", None, q("5 thou\u017fand"), (REVIEW, ["SCALE_WORD"])),
        # the scaled value of the token
        c("t2", "fee_scaled", "5000", None, q("5 thou\u017fand")),
        c("t3", "levy", "2", None, q("2 b\u0130llion"), (REVIEW, ["SCALE_WORD"])),
        c("t4", "toll", "3", None, q("3 m\u0131ll\u0131on"), (REVIEW, ["SCALE_WORD"])),
        c("t5", "cap", "4000", None, q("4 THOUSAND")),
        # the heading scale reaches the row, so the number as written misses its scale (SPEC §3.1)
        c("t6", "fees", "75", None, [q("75")], (REVIEW, ["PART_MISSING"], ["scale"])),
        # the scale item gives 10^3
        c("t7", "fees_scaled", "75000", None, [q("75"), q("(in thou\u017fands", role="scale")],
          ("admitted", ["VALUE_DERIVED"])),
    ],
)  # fmt: skip

vector(
    "79-abbreviation-letters",
    "An abbreviation matches case-insensitively by the fold of each letter (SPEC §4). So "
    "'U.\u017f.' with a long s (U+017F) is the abbreviation 'u.s.', and it joins as 'U.S.' does: "
    "'up to' reaches $60 and $70 (spec 0.10, #350, #356).",
    "Fees are up to the U.\u017f. code cap of $60. Fees are up to the U.S. code cap of $70.",
    {"fields": {"long_s_fee": USD, "us_fee": USD}},
    [
        c("a1", "long_s_fee", "60", "USD", q("$60"), (REVIEW, ["QUALIFIED_VALUE"])),
        c("a2", "us_fee", "70", "USD", q("$70"), (REVIEW, ["QUALIFIED_VALUE"])),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- spec 0.10 (#313)
POUND_000 = "Statement of financial position\n\t£000\t£000\nRevenue\t15,961,328\t14,200,105\n"
REVENUE_313 = {"type": "number", "aliases": ["Revenue"], "multiple": True}
vector(
    "64-currency-scale-000",
    "A currency sign directly followed by 000 is a currency scale of 10^3, as £'000 is. A scale "
    "item £000 scales the number as written, and the header is a heading scale. The 000 of a "
    "currency scale is no number token, so £000, £'000 and £\u2019000 are never an amount of zero "
    "(spec 0.10, #313).",
    POUND_000,
    {"fields": {"revenue": REVENUE_313,
                "revenue_gbp": {"type": "number", "unit": "GBP", "aliases": ["Revenue"]}}},
    [
        c("p1", "revenue", "15961328000", None,
          [q("15,961,328"), row("Revenue"), {"role": "scale", "text": "£000"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("p2", "revenue", "15961328000", None, [q("15,961,328"), row("Revenue")],
          (REVIEW, ["PART_MISSING"], ["scale"])),
        # the number as written under a £000 heading misses its scale
        c("p2b", "revenue", "15961328", None, [q("15,961,328"), row("Revenue")],
          (REVIEW, ["PART_MISSING"], ["scale"])),
        # with #315: the £ of the header gives the unit
        c("p5", "revenue_gbp", "15961328000", "GBP",
          [q("15,961,328"), row("Revenue"), {"role": "scale", "text": "£000"},
           {"role": "unit", "text": "£000"}],
          ("admitted", ["VALUE_DERIVED"])),
        # £000 is not an amount of zero
        c("z6", "revenue", "0", None, [q("000")], ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("z12", "revenue", "15961328", None,
          [q("15,961,328"), row("Revenue"), {"role": "scale", "text": "£000"}],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
    ],
)  # fmt: skip

vector(
    "65-currency-scale-000-zero",
    "The 000 of £'000 and £\u2019000 is no number token either, so a value of zero is not in the "
    "evidence there (spec 0.10, #313).",
    "Notes\n\t£'000\t£\u2019000\nFees\t75\t80\n",
    {"fields": {"fees": {"type": "number"}}},
    [
        c("z7a", "fees", "0", None, [q("000", 1)], ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("z7b", "fees", "0", None, [q("000", 2)], ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
    ],
)  # fmt: skip

vector(
    "66-currency-scale-000-signs",
    "$000, €000, ₹000 and US$000 are currency scales of 10^3, and a blank line may stand between "
    "the header and the rows (spec 0.10, #313).",
    "Cash flow\n\t$000\nCapex\t42\n\nNotes\n\t€000\nFees\t75\n\nLedger\n\t₹000\nTaxes\t31\n\n"
    "Segment\n\tUS$000\nSales\t58\n\nBalance sheet\n\t£000\t£000\n\nRevenue\t15,961,328\n",
    {"fields": {"amount": {"type": "number", "multiple": True}}},
    [
        c("p3a", "amount", "42000", None, [q("42"), q("$000", 1, role="scale")],
          ("admitted", ["VALUE_DERIVED"])),
        c("p3b", "amount", "75000", None, [q("75"), q("€000", role="scale")],
          ("admitted", ["VALUE_DERIVED"])),
        c("p3c", "amount", "31000", None, [q("31"), q("₹000", role="scale")],
          ("admitted", ["VALUE_DERIVED"])),
        c("p3d", "amount", "58000", None, [q("58"), q("US$000", role="scale")],
          ("admitted", ["VALUE_DERIVED"])),
        c("p4", "amount", "15961328000", None, [q("15,961,328"), q("£000", 2, role="scale")],
          ("admitted", ["VALUE_DERIVED"])),
    ],
)  # fmt: skip

vector(
    "67-currency-scale-000-strict",
    "The 000 form is strict. A letter or a number after 000, a , or . and then a digit, or a "
    "space after the sign stops it: £000s, £0001, £000,000, £000.5 and £ 000 are no currency "
    "scale, so no heading scale reaches their rows, and a scale item £000s holds no scale. A £000 "
    "header followed by a line with no tab reaches no row (spec 0.10, #313).",
    "Table A\n\t£0001\nRevenue\t15,961,328\n\n"
    "Table B\n\t£000,000\nGrants\t2,345,678\n\n"
    "Table C\n\t£000.5\nFees\t3,456,789\n\n"
    "Table D\n\t£ 000\nRents\t4,567,890\n\n"
    "Table E\n\t£000\nFigures follow.\nTaxes\t5,678,901\n\n"
    "Table F\n\t£000s\nLoans\t6,789,012\n",
    {"fields": {"amount": {"type": "number", "multiple": True}}},
    [
        c("z8", "amount", "6789012000", None, [q("6,789,012"), q("£000s", role="scale")],
          ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        # the number as written: no heading scale reaches it, so no scale is missing
        c("z9", "amount", "15961328", None, [q("15,961,328")]),
        c("z10a", "amount", "2345678", None, [q("2,345,678")]),
        c("z10b", "amount", "3456789", None, [q("3,456,789")]),
        c("z11", "amount", "4567890", None, [q("4,567,890")]),
        c("z13", "amount", "5678901", None, [q("5,678,901")]),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- spec 0.10 (#315)
def revenue(unit: str) -> dict[str, Any]:
    return {"type": "number", "unit": unit, "aliases": ["Revenue"]}


def unit_item(text: str) -> dict[str, Any]:
    return {"role": "unit", "text": text}


def scale_item(text: str) -> dict[str, Any]:
    return {"role": "scale", "text": text}


REV = row("Revenue")
HEADING_UNIT_FIELDS = {
    "fields": {code.lower(): revenue(code) for code in ("USD", "AUD", "CAD", "GBP", "HKD")}
}
DERIVED = ("admitted", ["VALUE_DERIVED"])
UNIT_REVIEW = (REVIEW, ["UNIT_CITATION_INVALID", "VALUE_DERIVED"])
AUD_STATEMENT = (
    "The figures are presented in Australian dollars.\n\t$m\t$m\nRevenue\t5,200\t4,900\n"
)
vector(
    "68-heading-unit-statement",
    "A currency statement ('in', an optional scale word and 'of', and a currency name) on a line "
    "with no tab is a heading unit. It reaches the table rows as a heading scale does, and a "
    "unit item that holds it gives the field's unit there. A lone $ agrees with each dollar "
    "currency, so $m under 'presented in Australian dollars' gives AUD, and a USD field there "
    "goes to review. A unit form next to the value, or a field check that does not pass, makes "
    "the item fail (spec 0.10, #315).",
    AUD_STATEMENT,
    HEADING_UNIT_FIELDS,
    [
        c("u2", "aud", "5200000000", "AUD",
          [q("5,200"), REV, scale_item("$m"), unit_item("presented in Australian dollars")],
          DERIVED),
        c("u3", "aud", "5200000000", "AUD", [q("5,200"), REV, scale_item("$m"), unit_item("$m")],
          DERIVED),
        # the statement and the field disagree
        c("u11", "usd", "5200000000", "USD", [q("5,200"), REV, scale_item("$m"), unit_item("$m")],
          UNIT_REVIEW),
        # the field check must pass
        c("u20", "aud", "5200000000", "AUD",
          [q("5,200"), scale_item("$m"), unit_item("presented in Australian dollars")],
          UNIT_REVIEW),
    ],
)  # fmt: skip

vector(
    "69-heading-unit-reach",
    "A currency statement reaches the rows after it as a heading scale does: across blank lines "
    "before the first line with a tab, and up to the first line with no tab. A line of prose "
    "after it, or the end of a table, stops it, and a line with a tab holds no statement "
    "(spec 0.10, #315).",
    "Income statement (in millions of Canadian dollars)\n\t2025\t2024\nRevenue\t5,200\t4,900\n\n"
    "The figures are presented in Australian dollars.\n\n\t$m\t$m\nRevenue\t6,300\t5,800\n\n"
    "Amounts are presented in Australian dollars.\nThe notes form part of these statements.\n"
    "\t$m\nRevenue\t7,400\n\n"
    "(in Australian dollars)\n\t$m\nCash\t1,100\nThe table ends here.\n\t$m\nRevenue\t8,500\n\n"
    "Revenue (in Australian dollars)\t9,600\t9,100\n",
    {"fields": {"cad": {**revenue("CAD"), "multiple": True},
                "aud": {**revenue("AUD"), "multiple": True}}},
    [
        c("u1", "cad", "5200000000", "CAD",
          [q("5,200"), REV, q("in millions", role="scale"),
           unit_item("in millions of Canadian dollars")],
          DERIVED),
        # blank lines between the statement and the table
        c("u8", "aud", "6300000000", "AUD",
          [q("6,300"), q("Revenue", 2, role="field"), q("$m", 2, role="scale"),
           q("presented in Australian dollars", 1, role="unit")],
          DERIVED),
        # a line of prose stands between the statement and the table
        c("u15", "aud", "7400000000", "AUD",
          [q("7,400"), q("Revenue", 3, role="field"), q("$m", 3, role="scale"),
           q("presented in Australian dollars", 2, role="unit")],
          UNIT_REVIEW),
        # the value is in the second table
        c("u16", "aud", "8500000000", "AUD",
          [q("8,500"), q("Revenue", 4, role="field"), q("$m", 5, role="scale"),
           q("in Australian dollars", 3, role="unit")],
          UNIT_REVIEW),
        # the statement is on the value's own line, which holds a tab
        c("u17", "aud", "9600", "AUD",
          [q("9,600"), q("Revenue", 5, role="field"), q("in Australian dollars", 4, role="unit")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
    ],
)  # fmt: skip

vector(
    "70-heading-unit-header",
    "A currency scale is also a currency header. Its form is the sign with the letters directly "
    "before it. £m gives GBP, US$000 and $m give USD by their prefixes in the unit table, and $m "
    "alone never gives CAD. HK$ is not in the unit table, so HK$'000 is unknown: it gives no "
    "unit, and its $ is never read as a lone $. A heading unit acts only through a unit item "
    "(spec 0.10, #315).",
    "Group\n\t£m\t£m\nRevenue\t5,200\t4,900\n\n"
    "Segment\n\tUS$000\tUS$000\nRevenue\t6,300\t5,800\n\n"
    "Parent\n\t$m\t$m\nRevenue\t7,400\t6,900\n\n"
    "Branch\n\tHK$'000\nRevenue\t8,500\n\n"
    "(in Hong Kong dollars)\n\tHK$'000\nRevenue\t9,600\n",
    {"fields": {code.lower(): {**revenue(code), "multiple": True}
                for code in ("USD", "CAD", "GBP", "HKD")}},
    [
        c("u4", "gbp", "5200000000", "GBP", [q("5,200"), REV, scale_item("£m"), unit_item("£m")],
          DERIVED),
        c("u21", "gbp", "5200000000", "GBP", [q("5,200"), REV, scale_item("£m")],
          (REVIEW, ["PART_MISSING", "VALUE_DERIVED"], ["unit"])),
        c("u5", "usd", "6300000", "USD",
          [q("6,300"), q("Revenue", 2, role="field"), scale_item("US$000"), unit_item("US$000")],
          DERIVED),
        c("u6", "usd", "7400000000", "USD",
          [q("7,400"), q("Revenue", 3, role="field"), scale_item("$m"), unit_item("$m")],
          DERIVED),
        # the sign alone does not settle a currency that shares it
        c("u10", "cad", "7400000000", "CAD",
          [q("7,400"), q("Revenue", 3, role="field"), scale_item("$m"), unit_item("$m")],
          UNIT_REVIEW),
        c("u14", "usd", "8500000", "USD",
          [q("8,500"), q("Revenue", 4, role="field"), q("HK$'000", 1, role="scale"),
           q("HK$'000", 1, role="unit")],
          UNIT_REVIEW),
        c("u7", "hkd", "9600000", "HKD",
          [q("9,600"), q("Revenue", 5, role="field"), q("HK$'000", 2, role="scale"),
           q("HK$'000", 2, role="unit")],
          DERIVED),
    ],
)  # fmt: skip

vector(
    "71-heading-unit-disagree",
    "When the heading units that reach a value do not agree on the field's unit, the unit item "
    "fails and the value goes to review. groundgate never chooses between them: two statements "
    "of two currencies, a statement of another currency over £m, or a unit form next to the "
    "value (spec 0.10, #315).",
    "Group figures in Australian dollars, parent figures in New Zealand dollars\n\t$m\n"
    "Revenue\t5,200\n\n"
    "(in thousands of US dollars)\n\t£m\nRevenue\t6,300\n\n"
    "(in millions of dollars)\n\t$m\nRevenue\t7,400\n\n"
    "The figures are presented in Australian dollars.\n\t$m\t$m\nRevenue\t£8,500\t£7,900\n",
    {"fields": {code.lower(): {**revenue(code), "multiple": True}
                for code in ("AUD", "CAD", "GBP")}},
    [
        c("u12", "aud", "5200000000", "AUD",
          [q("5,200"), REV, q("$m", 1, role="scale"), q("in Australian dollars", role="unit")],
          UNIT_REVIEW),
        c("u13", "gbp", "6300000000", "GBP",
          [q("6,300"), q("Revenue", 2, role="field"), q("£m", role="scale"),
           q("£m", role="unit")],
          UNIT_REVIEW),
        # "dollars" alone names no currency
        c("u18", "cad", "7400000000", "CAD",
          [q("7,400"), q("Revenue", 3, role="field"), q("$m", 2, role="scale"),
           q("in millions of dollars", role="unit")],
          UNIT_REVIEW),
        # a unit form next to the value
        c("u19", "aud", "8500000000", "AUD",
          [q("8,500"), q("Revenue", 4, role="field"), q("$m", 4, role="scale"),
           q("presented in Australian dollars", role="unit")],
          UNIT_REVIEW),
    ],
)  # fmt: skip

vector(
    "72-heading-unit-schema-prefix",
    "When the schema gives CAD the prefix $, a lone $ in a header settles CAD: the app says what "
    "$ means in its documents (spec 0.10, #315).",
    "\t$m\t$m\nRevenue\t5,200\t4,900\n",
    {"fields": {"cad": revenue("CAD")}, "units": {"CAD": {"prefix": ["$"], "suffix": []}}},
    [
        c("u9", "cad", "5200000000", "CAD", [q("5,200"), REV, scale_item("$m"), unit_item("$m")],
          DERIVED),
    ],
)  # fmt: skip


vector(
    "73-heading-unit-one-line",
    "A currency statement lies on one line, which holds no tab. A statement that runs onto a "
    "line with a tab is none, so it gives no unit (spec 0.10, #315).",
    "Figures in\nAustralian dollars\t2025\t2024\nRevenue\t5,200\t4,900\n",
    {"fields": {"aud": revenue("AUD")}},
    [
        c("u22", "aud", "5200", "AUD",
          [q("5,200"), REV, q("in\nAustralian dollars", role="unit")],
          (REVIEW, ["UNIT_CITATION_INVALID"])),
    ],
)  # fmt: skip


# ---------------------------------------------------------------- spec 0.10 (#321, #284)
# Relations across fields (SPEC §2.3, §3.4). Every difference and allowance below is worked out by
# hand: the difference is the total minus each part times its factor, and the allowance is the
# tolerance plus half of the place of each value, times |factor| for a part.
YEARS3 = ["2025", "2024", "2023"]
BALANCE = {
    "id": "balance",
    "total": "assets",
    "parts": [{"field": "liabilities"}, {"field": "equity"}],
}
vector(
    "80-relation-keyed",
    "A relation is checked once for each key that all of its fields list. In 2025 the total "
    "assets equal the liabilities plus the equity, so the relation holds and admits nothing more. "
    "In 2024 the equity candidate took the cash figure, a right number for the wrong field: the "
    "relation fails by 50, and each of its three values goes to review. 2023 is a key of the "
    "assets only, so no relation is checked there (spec 0.10, #321).",
    "In 2025, total assets were $1,500, total liabilities were $900 and total equity was $600. "
    "In 2024, total assets were $1,400, total liabilities were $900, total equity was $500 and "
    "cash was $450. In 2023, total assets were $1,300.",
    {
        "fields": {
            "assets": {"type": "integer", "unit": "USD", "keys": YEARS3},
            "liabilities": {"type": "integer", "unit": "USD", "keys": YEARS3[:2]},
            "equity": {"type": "integer", "unit": "USD", "keys": YEARS3[:2]},
        },
        "relations": [BALANCE],
    },
    [
        c("a25", "assets", 1500, "USD", [q("$1,500")], key="2025"),
        c("l25", "liabilities", 900, "USD", [q("$900", 1)], key="2025"),
        c("e25", "equity", 600, "USD", [q("$600")], key="2025"),
        c("a24", "assets", 1400, "USD", [q("$1,400")], (REVIEW, ["RELATION_FAILED"]), key="2024"),
        c("l24", "liabilities", 900, "USD", [q("$900", 2)], (REVIEW, ["RELATION_FAILED"]),
          key="2024"),
        c("e24", "equity", 450, "USD", [q("$450")], (REVIEW, ["RELATION_FAILED"]), key="2024"),
        c("a23", "assets", 1300, "USD", [q("$1,300")], key="2023"),
    ],
    relations=[("balance", "2024", False, "50", "1.5"), ("balance", "2025", True, "0", "1.5")],
)  # fmt: skip

MILLIONS = {"role": "scale", "text": "(in millions"}
vector(
    "81-relation-scale",
    "The place of a value is one unit of its last written digit, times the scale that the value "
    "takes: a scale item, or a missing scale under a heading. So values in thousands may differ "
    "by half a thousand each: 10,001 against 6,000 plus 4,000 holds, with an allowance of 1500. "
    "In millions, 12 against 7 plus 3 fails by 2000000, more than its allowance of 1500000. A "
    "value with a missing part still counts (spec 0.10, #321, #284).",
    "Balance sheet (in thousands)\n\nTotal assets\t$10,001\nTotal liabilities\t$6,000\n"
    "Total equity\t$4,000\n\nDebt (in millions)\n\nTotal debt\t$12\nBank loans\t$7\nBonds\t$3\n",
    {
        "fields": {
            "assets": USD, "liabilities": USD, "equity": USD,
            "debt": USD, "loans": USD, "bonds": USD,
        },
        "relations": [
            BALANCE,
            {"id": "debt", "total": "debt", "parts": [{"field": "loans"}, {"field": "bonds"}]},
        ],
    },
    [
        c("s1", "assets", 10001000, "USD", [q("$10,001"), THOUSANDS],
          ("admitted", ["VALUE_DERIVED"])),
        c("s2", "liabilities", 6000000, "USD", [q("$6,000")], (REVIEW, ["PART_MISSING"], ["scale"])),
        c("s3", "equity", 4000000, "USD", [q("$4,000"), THOUSANDS], ("admitted", ["VALUE_DERIVED"])),
        c("s4", "debt", 12000000, "USD", [q("$12"), MILLIONS],
          (REVIEW, ["RELATION_FAILED", "VALUE_DERIVED"])),
        c("s5", "loans", 7000000, "USD", [q("$7"), MILLIONS],
          (REVIEW, ["RELATION_FAILED", "VALUE_DERIVED"])),
        c("s6", "bonds", 3000000, "USD", [q("$3"), MILLIONS],
          (REVIEW, ["RELATION_FAILED", "VALUE_DERIVED"])),
    ],
    relations=[("balance", None, True, "1000", "1500"),
               ("debt", None, False, "2000000", "1500000")],
)  # fmt: skip

vector(
    "82-relation-factor",
    "A factor changes the unit of a part (mg to g, 0.001) or subtracts it (-1), and also scales "
    "the part's place in the allowance. A tolerance adds to the allowance in the unit of the "
    "total. The net pay is 100 below gross pay minus tax: the relation with a tolerance of 100 "
    "holds, the one without it fails, and one failing relation is enough for the flag. A factor "
    "reads as a bound does, so 1,000 is 1000 (spec 0.10, #321, #284).",
    "Each tablet weighs 1.2 g. It holds 950 mg of drug and 250 mg of filler. "
    "Gross pay was $5,000, tax was $1,200 and net pay was $3,700.",
    {
        "fields": {
            "tablet": {"type": "number", "unit": "g"},
            "drug": {"type": "integer", "unit": "mg"},
            "filler": {"type": "integer", "unit": "mg"},
            "gross": USD, "tax": USD, "net": USD,
        },
        "relations": [
            {"id": "weight", "total": "tablet",
             "parts": [{"field": "drug", "factor": "0.001"}, {"field": "filler", "factor": "0.001"}]},
            {"id": "net", "total": "net",
             "parts": [{"field": "gross"}, {"field": "tax", "factor": "-1"}], "tolerance": "100"},
            {"id": "net_strict", "total": "net",
             "parts": [{"field": "gross"}, {"field": "tax", "factor": -1}]},
            # 950 = 1.2 * 1000 - 250; allowance 1/2 + 1000 * 0.1/2 + 1/2
            {"id": "weight_mg", "total": "drug",
             "parts": [{"field": "tablet", "factor": "1,000"}, {"field": "filler", "factor": "-1"}]},
        ],
    },
    [
        c("f1", "tablet", "1.2", "g", [q("1.2 g")]),
        c("f2", "drug", 950, "mg", [q("950 mg")]),
        c("f3", "filler", 250, "mg", [q("250 mg")]),
        c("f4", "gross", 5000, "USD", [q("$5,000")], (REVIEW, ["RELATION_FAILED"])),
        c("f5", "tax", 1200, "USD", [q("$1,200")], (REVIEW, ["RELATION_FAILED"])),
        c("f6", "net", 3700, "USD", [q("$3,700")], (REVIEW, ["RELATION_FAILED"])),
    ],
    relations=[("net", None, True, "-100", "101.5"), ("net_strict", None, False, "-100", "1.5"),
               ("weight", None, True, "0", "0.051"), ("weight_mg", None, True, "0", "51")],
)  # fmt: skip

vector(
    "83-relation-not-applied",
    "A relation applies only when each of its fields has values that passed, with one canonical "
    "value. A rejected sales value stops the gross relation, and two profit values stop the "
    "profit relation: no value gets RELATION_FAILED, and the receipt lists no result "
    "(spec 0.10, #321).",
    "Sales were $600 and fees were $300, so revenue was $900. Costs were $500. Profit was $400. "
    "The draft said profit was $300.",
    {
        "fields": {"sales": USD, "fees": USD, "revenue": USD, "costs": USD, "profit": USD},
        "relations": [
            {"id": "gross", "total": "revenue", "parts": [{"field": "sales"}, {"field": "fees"}]},
            {"id": "profit", "total": "profit",
             "parts": [{"field": "revenue"}, {"field": "costs", "factor": "-1"}]},
        ],
    },
    [
        c("n1", "sales", 700, "USD", [q("$600")], ("rejected", ["VALUE_NOT_IN_EVIDENCE"])),
        c("n2", "fees", 300, "USD", [q("$300", 1)]),
        c("n3", "revenue", 900, "USD", [q("$900")]),
        c("n4", "costs", 500, "USD", [q("$500")]),
        c("n5", "profit", 400, "USD", [q("$400")], (REVIEW, ["CONFLICTING_CANDIDATES"])),
        c("n6", "profit", 300, "USD", [q("$300", 2)], (REVIEW, ["CONFLICTING_CANDIDATES"])),
    ],
    relations=[],
)  # fmt: skip

PERCENT = {"type": "number", "unit": "%"}
vector(
    "84-relation-places",
    "The place of a token comes from its written digits, not from the canonical value: 4.00% "
    "has the place 0.01. Two values of one field that are equal take the smaller place, 0.001 "
    "from 7.250%. A knowledge item has the place of the canonical value, 0.1 for 3.3. So the "
    "allowance is 0.0005 + 0.005 + 0.05 = 0.0555 (spec 0.10, #321).",
    "The fund's total return was 7.25%. The audited total return was 7.250%. "
    "The income return was 4.00%.",
    {
        "fields": {"total_return": PERCENT, "income": PERCENT, "growth": PERCENT},
        "relations": [{"id": "returns", "total": "total_return",
                       "parts": [{"field": "income"}, {"field": "growth"}]}],
    },
    [
        c("t1", "total_return", "7.25", "%", [q("7.25%")]),
        c("t2", "total_return", "7.25", "%", [q("7.250%")]),
        c("i1", "income", "4", "%", [q("4.00%")]),
        c("g1", "growth", "3.3", "%", [know("The growth return was 3.3%.")],
          ("admitted", ["ADMITTED_BY_POLICY"])),
    ],
    {"sources": {"knowledge": "admit"}},
    relations=[("returns", None, True, "-0.05", "0.0555")],
)  # fmt: skip

TWO_USD = {"a": USD, "b": USD, "c": USD}
INVALID.extend(
    [
        {
            "name": f"schema-relation-{name}",
            "description": f"A relation is invalid: {why} (SPEC §2.3, spec 0.10, #321).",
            "document": "A is $3, B is $1 and C is $2.",
            "schema": {"fields": fields or TWO_USD, "relations": relations},
            "policy": None,
        }
        for name, why, fields, relations in [
            ("not-list", "relations must be a list", None,
             {"id": "r", "total": "a", "parts": [{"field": "b"}]}),
            ("not-object", "a relation must be an object", None, ["a = b + c"]),
            ("unknown-member", "a relation has only id, total, parts and tolerance", None,
             [{"id": "r", "total": "a", "parts": [{"field": "b"}], "op": "sum"}]),
            ("blank-id", "the id must be a non-blank string", None,
             [{"id": " ", "total": "a", "parts": [{"field": "b"}]}]),
            ("duplicate-id", "two relations have one id", None,
             [{"id": "r", "total": "a", "parts": [{"field": "b"}]},
              {"id": "r", "total": "a", "parts": [{"field": "c"}]}]),
            ("unknown-field", "the total names no field of the schema", None,
             [{"id": "r", "total": "d", "parts": [{"field": "b"}]}]),
            ("unknown-part", "a part names no field of the schema", None,
             [{"id": "r", "total": "a", "parts": [{"field": "d"}]}]),
            ("empty-parts", "parts must be a non-empty list", None,
             [{"id": "r", "total": "a", "parts": []}]),
            ("part-not-object", "a part must be an object with field and factor", None,
             [{"id": "r", "total": "a", "parts": ["b"]}]),
            ("part-unknown-member", "a part has only field and factor", None,
             [{"id": "r", "total": "a", "parts": [{"field": "b", "sign": "-"}]}]),
            ("zero-factor", "a factor must not be zero", None,
             [{"id": "r", "total": "a", "parts": [{"field": "b", "factor": "0"}]}]),
            ("bad-factor", "a factor must be a decimal", None,
             [{"id": "r", "total": "a", "parts": [{"field": "b", "factor": "1/1000"}]}]),
            ("negative-tolerance", "a tolerance must not be negative", None,
             [{"id": "r", "total": "a", "parts": [{"field": "b"}], "tolerance": "-1"}]),
            ("string-field", "a field of a relation must not be a string field",
             {**TWO_USD, "b": {"type": "string"}},
             [{"id": "r", "total": "a", "parts": [{"field": "b"}]}]),
            ("multiple-field", "a field of a relation must not be multiple",
             {**TWO_USD, "b": {**USD, "multiple": True}},
             [{"id": "r", "total": "a", "parts": [{"field": "b"}]}]),
            ("total-is-part", "the total must not also be a part", None,
             [{"id": "r", "total": "a", "parts": [{"field": "b"}, {"field": "a"}]}]),
            ("part-twice", "two parts must not name one field", None,
             [{"id": "r", "total": "a", "parts": [{"field": "b"}, {"field": "b"}]}]),
            ("unit-without-factor", "a part in another unit needs a factor",
             {**TWO_USD, "b": {"type": "integer", "unit": "EUR"}},
             [{"id": "r", "total": "a", "parts": [{"field": "b"}]}]),
            ("no-unit-without-factor", "a part without a unit under a total with one needs a factor",
             {**TWO_USD, "b": {"type": "integer"}},
             [{"id": "r", "total": "a", "parts": [{"field": "b"}]}]),
            ("mixed-keys", "either every field of a relation has keys, or none has",
             {**TWO_USD, "a": {**USD, "keys": ["2025"]}},
             [{"id": "r", "total": "a", "parts": [{"field": "b"}]}]),
        ]
    ]
)  # fmt: skip


# ---------------------------------------------------------------- vocabulary packs (#334)
def pack(pid: str = "words-x-test", version: str = "1.0.0", **lists: Any) -> dict[str, Any]:
    """An app's own vocabulary pack in format 1 (SPEC §4.8)."""
    return {"groundgate_pack": 1, "type": "vocabulary", "id": pid, "version": version, **lists}


def uses(*packs: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """A schema that names each pack by id and version."""
    return {
        "packs": [{"id": p["id"], "version": p["version"]} for p in packs],
        "fields": fields,
    }


NULLS = pack(null_literals=["unknown"])
LAC = pack(scale={"words": {"lac": 5}})
UPWARDS = pack(qualifiers={"before": {"gt": ["upwards of"]}})

vector(
    "85-pack-null-literal",
    "A pack adds a null literal. A string value that is the literal is rejected before evidence "
    "is read, as the base literals are (spec 0.10, #334).",
    "Status: unknown. Plan: pending.",
    uses(NULLS, status={"type": "string"}, plan={"type": "string"}),
    [
        c("p1", "status", "unknown", None, q("unknown"), ("rejected", ["NULL_STRING_LITERAL"])),
        c("p2", "status", " Unknown ", None, q("unknown"), ("rejected", ["NULL_STRING_LITERAL"])),
        c("p3", "plan", "pending", None, q("pending")),
    ],
    packs=[NULLS],
)
vector(
    "86-pack-scale-word",
    "A pack adds a scale word with its power of ten. The value before it gets SCALE_WORD, as "
    "before a base scale word (spec 0.10, #334).",
    "The grant is 5 lac. The levy is 7 lakh. The fee is 9 sites.",
    uses(LAC, grant={"type": "integer"}, levy={"type": "integer"}, fee={"type": "integer"}),
    [
        c("p4", "grant", "5", None, q("5 lac"), ("needs_verification", ["SCALE_WORD"])),
        c("p5", "levy", "7", None, q("7 lakh"), ("needs_verification", ["SCALE_WORD"])),
        c("p6", "fee", "9", None, q("9 sites")),
    ],
    packs=[LAC],
)
vector(
    "87-pack-qualifier",
    "A pack adds a qualifier phrase for a comparator. A value after it gets QUALIFIED_VALUE, as "
    "after a base qualifier (spec 0.10, #334).",
    "Upwards of 20 sites joined. Then 5 sites closed.",
    uses(UPWARDS, joined={"type": "integer"}, closed={"type": "integer"}),
    [
        c("p7", "joined", "20", None, q("20"), ("needs_verification", ["QUALIFIED_VALUE"])),
        c("p8", "closed", "5", None, q("5")),
    ],
    packs=[UPWARDS],
)


def bad_pack(name: str, description: str, *packs: dict[str, Any], schema: Any = None) -> None:
    """An invalid packet: the packs or the schema's packs break a loader check (SPEC §4.8)."""
    INVALID.append(
        {
            "name": name,
            "description": description,
            "document": "The fee is 5 dollars.",
            "schema": uses(*packs, fee={"type": "integer"}) if schema is None else schema,
            "policy": None,
            "packs": list(packs),
        }
    )


bad_pack("pack-l1-unknown-member", "L1: a member that the format does not list.", pack(window=80))
bad_pack("pack-l1-format", "L1: a pack format other than 1.", {**pack(), "groundgate_pack": 2})
bad_pack("pack-l1-type", "L1: a type other than vocabulary or kind.", {**pack(), "type": "words"})
bad_pack(
    "pack-l2-float",
    "L2: a power of ten that is not an integer.",
    pack(scale={"words": {"lac": 5.0}}),
)
bad_pack(
    "pack-l2-bool", "L2: a boolean where a power of ten goes.", pack(scale={"words": {"lac": True}})
)
bad_pack("pack-l3-blank", "L3: a blank word.", pack(per_units=[" "]))
bad_pack(
    "pack-l3-line-break", "L3: a word that holds a line break.", pack(per_units=["square\nfoot"])
)
bad_pack("pack-l3-not-nfc", "L3: a word that is not NFC.", pack(per_units=["café"]))
bad_pack("pack-l3-long", "L3: a word of more than 64 code points.", pack(per_units=["x" * 65]))
bad_pack(
    "pack-l4-list",
    "L4: a list of more than 2,000 entries.",
    pack(per_units=[f"u{i}" for i in range(2001)]),
)
bad_pack(
    "pack-l4-depth", "L4: a JSON nesting depth of more than 8.", pack(status=[[[[[[[[["x"]]]]]]]]])
)
bad_pack(
    "pack-l5-negation",
    "L5: a pack adds to the negations of a qualifier, a list that only the base pack gives.",
    pack(qualifiers={"negations": ["hardly"]}),
)
bad_pack(
    "pack-l5-change-word",
    "L5: a pack adds to the change words, a list that only the base pack gives.",
    pack(changes={"words": ["shift"]}),
)
bad_pack(
    "pack-l6-two-powers",
    "L6: a scale word with a power other than its power in the base.",
    pack(scale={"words": {"million": 9}}),
)
bad_pack(
    "pack-l6-power",
    "L6: a power of ten other than 3, 5, 6, 7, 9 or 12.",
    pack(scale={"words": {"lac": 4}}),
)
bad_pack(
    "pack-l6-holds-base",
    "L6: a qualifier phrase that holds a base phrase of another "
    'comparator: "less than or equal to" as le holds "less than" (lt).',
    pack(qualifiers={"before": {"le": ["less than or equal to"]}}),
)
bad_pack(
    "pack-l6-held-by-base",
    "L6: a qualifier phrase that a base phrase of another "
    'comparator holds: "more" as lt is in "more than" (gt).',
    pack(qualifiers={"before": {"lt": ["more"]}}),
)
bad_pack(
    "pack-l6-two-comparators",
    "L6: a word in two comparator lists.",
    pack(qualifiers={"before": {"lt": ["about"]}}),
)
bad_pack(
    "pack-l6-unit-two-codes",
    "L6: a unit form under two unit codes.",
    pack(units={"EUR": {"prefixes": ["$"]}}),
)
bad_pack(
    "pack-l6-suffix-unit",
    "L6: a scale suffix that is also a unit suffix.",
    pack(scale={"suffixes": {"mg": 6}}),
)
bad_pack(
    "pack-l6-two-packs",
    "L6: two packs give one scale word two powers.",
    pack("lac-x-five", scale={"words": {"lac": 5}}),
    pack("lac-x-seven", scale={"words": {"lac": 7}}),
)
bad_pack("pack-l7-built-in-id", "L7: a given pack with the id of a built-in pack.", pack("en"))
bad_pack("pack-l7-no-app-name", "L7: an app's own pack with no -x- name.", pack("words"))
bad_pack("pack-l7-version", "L7: a version that is not MAJOR.MINOR.PATCH.", pack(version="1.0"))
bad_pack(
    "pack-l7-two-versions",
    "L7: one id with two versions in one packet.",
    pack(version="1.0.0"),
    pack(version="1.1.0"),
)
bad_pack(
    "pack-l7-two-digests",
    "L7: two copies of one id and version with different digests.",
    pack(per_units=["acre"]),
    pack(per_units=["hectare"]),
)
bad_pack(
    "pack-l8-measured",
    "L8: a measured status row in a pack that is not built in.",
    pack(
        status=[
            {
                "kind": "us-10k",
                "field": "revenue",
                "code": "SCALE_WORD",
                "status": "measured",
                "documents": 60,
                "bound": "0.0487",
                "limit": "0.05",
                "results": "bench/example/results.json",
            }
        ]
    ),
)
bad_pack("pack-l8-row", "L8: a malformed status row.", pack(status=[{"status": "draft"}]))
bad_pack(
    "pack-l12-text", "L12: a member that holds document text.", pack(text="The fee is 5 dollars.")
)
bad_pack(
    "pack-schema-not-given",
    "The schema names a pack that is neither built in nor given.",
    schema=uses(pack("other-x-test"), fee={"type": "integer"}),
)
bad_pack(
    "pack-schema-not-named",
    "A given pack that the schema does not name.",
    pack(),
    schema={"fields": {"fee": {"type": "integer"}}},
)
bad_pack(
    "pack-schema-base",
    "The schema names the base pack, which always applies.",
    schema={"packs": [{"id": "en", "version": "1.0.0"}], "fields": {"fee": {"type": "integer"}}},
)
bad_pack(
    "pack-schema-pin",
    "A pinned sha256 that differs from the digest of the given pack.",
    pack(),
    schema={
        "packs": [{"id": "words-x-test", "version": "1.0.0", "sha256": "sha256:" + "0" * 64}],
        "fields": {"fee": {"type": "integer"}},
    },
)
bad_pack("pack-schema-entry", "A schema packs entry with an unknown member.",
         pack(), schema={"packs": [{"id": "words-x-test", "version": "1.0.0", "url": "x"}],
                         "fields": {"fee": {"type": "integer"}}})  # fmt: skip


# ---------------------------------------------------------------- kind packs (#335)
def kind(pid: str = "filings-x-test", version: str = "1.0.0", **members: Any) -> dict[str, Any]:
    """An app's own kind pack in format 1 (SPEC §4.9)."""
    return {"groundgate_pack": 1, "type": "kind", "id": pid, "version": version, **members}


SALES = {"type": "integer", "unit": "USD", "aliases": ["net sales", "revenue"]}
FILINGS = kind(fields={"net_sales": SALES})
TEMPLATE = {"template": "filings-x-test/net_sales"}
SALES_DOC = "Net sales were $5,200 in 2025. The fee was $90."

vector(
    "88-kind-template",
    "A field takes a template of a kind pack. The template fills the type, the unit and the "
    "aliases, and the field adds multiple. A field item that holds an alias of the template "
    "passes, and a field item that holds another word fails (spec 0.10, #335).",
    SALES_DOC,
    uses(FILINGS, sales={**TEMPLATE, "multiple": True}),
    [
        c("t1", "sales", "5200", "USD", [q("$5,200"), row("Net sales")]),
        c("t2", "sales", "90", "USD", [q("$90"), row("fee")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
    ],
    packs=[FILINGS],
)  # fmt: skip
vector(
    "89-kind-schema-wins",
    "A member that the field gives wins over the template, also aliases: the template does not "
    "add its aliases to the field's. A type that is equal to the template's is no conflict "
    "(spec 0.10, #335).",
    SALES_DOC,
    uses(FILINGS, fee={**TEMPLATE, "type": "integer", "aliases": ["fee"], "multiple": True}),
    [
        c("w1", "fee", "90", "USD", [q("$90"), row("fee")]),
        c("w2", "fee", "5200", "USD", [q("$5,200"), row("Net sales")],
          (REVIEW, ["FIELD_CITATION_INVALID"])),
    ],
    packs=[FILINGS],
)  # fmt: skip
GRANTS = kind(
    "grants-x-test",
    needs=[{"id": "words-x-test", "version": "1.0.0"}],
    fields={"grant": {"type": "integer"}},
)
vector(
    "90-kind-needs",
    "A kind pack names a vocabulary pack in needs. The schema names only the kind pack, and the "
    "packet gives both. The words of the needed pack apply, so the value before its scale word "
    "gets SCALE_WORD (spec 0.10, #335).",
    "The grant is 5 lac. The fee is 9 sites.",
    {"packs": [{"id": "grants-x-test", "version": "1.0.0"}],
     "fields": {"grant": {"template": "grants-x-test/grant"}, "fee": {"type": "integer"}}},
    [
        c("n1", "grant", "5", None, q("5 lac"), ("needs_verification", ["SCALE_WORD"])),
        c("n2", "fee", "9", None, q("9 sites")),
    ],
    packs=[GRANTS, LAC],
)  # fmt: skip

UNTYPED = kind("untyped-x-test", fields={"amount": {"unit": "USD"}})
vector(
    "91-kind-template-no-type",
    "A template with no type has no defaults of its own. The field fills them after it takes the "
    "template: the field that gives integer is an integer field, and the field that gives no "
    "type is a number field (spec 0.10, #335).",
    SALES_DOC,
    {"packs": [{"id": "untyped-x-test", "version": "1.0.0"}],
     "fields": {"fee": {"template": "untyped-x-test/amount", "type": "integer"},
                "sales": {"template": "untyped-x-test/amount"}}},
    [
        c("u1", "fee", "90", "USD", q("$90")),
        c("u2", "sales", "5200", "USD", q("$5,200")),
    ],
    packs=[UNTYPED],
)  # fmt: skip


def bad_kind(
    name: str, description: str, *packs: dict[str, Any], fields: Any = None, schema: Any = None
) -> None:
    """An invalid packet with a kind pack: the schema names the first pack, and its field fee
    takes the template filings-x-test/net_sales unless ``fields`` says otherwise."""
    fee = {"fee": TEMPLATE} if fields is None else fields
    bad_pack(name, description, *packs, schema=uses(packs[0], **fee) if schema is None else schema)


# fmt: off
bad_kind("pack-l1-kind-word", "L1: a kind pack holds no reading words.",
         kind(fields={"net_sales": SALES}, per_units=["acre"]))
bad_kind("pack-l1-kind-relations", "L1: relations in a kind pack, which #321 adds later.",
         kind(fields={"net_sales": SALES}, relations=[]))
bad_kind("pack-l4-templates", "L4: more than 200 field templates.",
         kind(fields={"net_sales": SALES, **{f"f{i}": {} for i in range(200)}}))
bad_kind("pack-l9-template-member", "L9: a template member other than the five of the format.",
         kind(fields={"net_sales": {**SALES, "keys": ["2025"]}}))
bad_kind("pack-l9-template-form", "L9: a template that fails the rules of a field.",
         kind(fields={"net_sales": {**SALES, "type": "date"}}))
bad_kind("pack-l9-needs-kind", "L9: a needs entry that names a kind pack.",
         kind(needs=[{"id": "other-x-test", "version": "1.0.0"}], fields={"net_sales": SALES}),
         kind("other-x-test"))
bad_kind("pack-l9-needs-missing", "L9: a needs entry that names a pack that is not given.",
         kind(needs=[{"id": "words-x-test", "version": "1.0.0"}], fields={"net_sales": SALES}))
bad_kind("pack-l9-needs-base", "L9: a needs entry that names the base pack.",
         kind(needs=[{"id": "en", "version": "1.0.0"}], fields={"net_sales": SALES}))
bad_kind("pack-l7-needs-version",
         "L7: the schema names a pack in one version, and a kind pack needs it in another.",
         kind(needs=[{"id": "words-x-test", "version": "1.0.0"}], fields={"net_sales": SALES}),
         pack(version="1.1.0"),
         schema={"packs": [{"id": "filings-x-test", "version": "1.0.0"},
                           {"id": "words-x-test", "version": "1.1.0"}],
                 "fields": {"fee": TEMPLATE}})
bad_kind("pack-l10-no-pack", "L10: a template whose pack is not in the schema's packs.",
         pack(), fields={"fee": TEMPLATE})
bad_kind("pack-l10-no-field", "L10: a template whose field is not in its pack.",
         FILINGS, fields={"fee": {"template": "filings-x-test/revenue"}})
bad_kind("pack-l10-form", "L10: a template that is not a pack id and a field name.",
         FILINGS, fields={"fee": {"template": "net_sales"}})
bad_kind("pack-l10-vocabulary", "L10: a template that names a vocabulary pack.",
         pack(), fields={"fee": {"template": "words-x-test/net_sales"}})
bad_kind("pack-l10-type", "L10: a field type that differs from the template's.",
         FILINGS, fields={"fee": {**TEMPLATE, "type": "number"}})
bad_kind("pack-l10-unit", "L10: a field unit that differs from the template's.",
         FILINGS, fields={"fee": {**TEMPLATE, "unit": "EUR"}})
bad_kind("pack-l10-untyped-bad-type",
         "L10: a template with no type, and a field that gives a type that SPEC 2.3 does not list.",
         UNTYPED, fields={"fee": {"template": "untyped-x-test/amount", "type": "text"}})
bad_kind("pack-l10-pin", "L10: a pinned sha256 of a kind pack that differs from its digest.",
         FILINGS,
         schema={"packs": [{"id": "filings-x-test", "version": "1.0.0",
                            "sha256": "sha256:" + "0" * 64}],
                 "fields": {"fee": TEMPLATE}})
# fmt: on


# ---------------------------------------------------------------- the finance pack (#336)
LOSS_DOC = (
    "For the year ended December 31, 2024, we had a net loss of $71,000.\n\n"
    "Net (loss) income\n\n$6,152\n\n($13,203\n)\n\n"
    "The deficit was $9 in 2024."
)
vector(
    "101-sign-without-finance",
    "Without the pack finance, the packet reads no loss word. A sign item that holds only a loss "
    "word still gives its part, but it fails: the decision gets SIGN_CITATION_INVALID and goes to "
    "review, and sign is not missing. Brackets still make a sign, with or without an item "
    "(spec 0.10, #336).",
    LOSS_DOC,
    {"fields": {"amount": AMOUNT}},
    [
        c("f1", "amount", "-71000", "USD", [q("$71,000"), {"role": "sign", "text": "net loss"}],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"], [])),
        c("f2", "amount", "-9", "USD", [q("$9"), {"role": "sign", "text": "deficit"}],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"], [])),
        c("f3", "amount", "-13203", "USD",
          [q("$13,203"), {"role": "sign", "text": "($13,203\n)"}], ("admitted", ["VALUE_DERIVED"])),
        c("f4", "amount", "-71000", "USD", [q("$71,000")], (REVIEW, ["PART_MISSING"], ["sign"])),
    ],
)  # fmt: skip
vector(
    "102-sign-with-finance",
    "The same candidates with the pack finance: a loss word before the value in its sentence "
    "passes the sign check (spec 0.10, #336).",
    LOSS_DOC,
    {"packs": [FINANCE], "fields": {"amount": AMOUNT}},
    [
        c("g1", "amount", "-71000", "USD", [q("$71,000"), {"role": "sign", "text": "net loss"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("g2", "amount", "-9", "USD", [q("$9"), {"role": "sign", "text": "deficit"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("g3", "amount", "-13203", "USD",
          [q("$13,203"), {"role": "sign", "text": "($13,203\n)"}], ("admitted", ["VALUE_DERIVED"])),
        c("g4", "amount", "-71000", "USD", [q("$71,000")], (REVIEW, ["PART_MISSING"], ["sign"])),
    ],
)  # fmt: skip
OWN_LOSS = pack("shortfall-x-test", sign={"loss": ["shortfall"]})
vector(
    "103-sign-own-loss-word",
    "An app's own vocabulary pack can give a loss word without the pack finance. Then only its "
    "words are loss words (spec 0.10, #336).",
    "There was a shortfall of $40 in 2024. The deficit was $9 in 2024.",
    uses(OWN_LOSS, amount=AMOUNT),
    [
        c("h1", "amount", "-40", "USD", [q("$40"), {"role": "sign", "text": "shortfall"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("h2", "amount", "-9", "USD", [q("$9"), {"role": "sign", "text": "deficit"}],
          (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"], [])),
    ],
    packs=[OWN_LOSS],
)  # fmt: skip
bad_pack("pack-l7-finance-given", "L7: a given pack with the id of the built-in pack finance.",
         {**pack("finance"), "sign": {"loss": ["loss"]}})  # fmt: skip
bad_pack("pack-schema-built-in-version",
         "The schema names a version of the built-in pack finance that is not built in.",
         schema={"packs": [{"id": "finance", "version": "9.9.9"}],
                 "fields": {"fee": {"type": "integer"}}})  # fmt: skip
bad_pack("pack-schema-finance-pin",
         "A pinned sha256 that differs from the digest of the built-in pack finance.",
         schema={"packs": [{**FINANCE, "sha256": "sha256:" + "0" * 64}],
                 "fields": {"fee": {"type": "integer"}}})  # fmt: skip
bad_pack("pack-l6-finance-gain",
         "L6: a pack gives a gain word that the pack finance gives as a loss word.",
         pack(sign={"gain": ["deficit"]}),
         schema={"packs": [FINANCE, {"id": "words-x-test", "version": "1.0.0"}],
                 "fields": {"fee": {"type": "integer"}}})  # fmt: skip


# ---------------------------------------------------------------- the fold of each letter (#356)
# SPEC §4: two letters match when they have the same fold. The long s (U+017F) folds to s, the
# dotless i (U+0131) and the dotted capital I (U+0130) to i, and the Kelvin sign (U+212A) to k.
# Each vector checks capitals and these letters, and shows that a stop check still fires.
vector(
    "95-qualifier-letters",
    "A qualifier matches by the fold of each letter (SPEC §4). 'at lea\u017ft', 'max\u0131mum of', "
    "'or le\u017fs', 'AT LEAST' and 'MAX\u0130MUM OF' each qualify the value (spec 0.10, #356).",
    "The base is $40. The fee is at lea\u017ft $50. The cap is max\u0131mum of $60. The levy is $70 "
    "or le\u017fs. The toll is AT LEAST $80. The rate is MAX\u0130MUM OF $90.",
    {"fields": {f: USD for f in ("base", "fee", "cap", "levy", "toll", "rate")}},
    [
        c("q1", "base", "40", "USD", q("$40")),
        c("q2", "fee", "50", "USD", q("$50"), (REVIEW, ["QUALIFIED_VALUE"])),
        c("q3", "cap", "60", "USD", q("$60"), (REVIEW, ["QUALIFIED_VALUE"])),
        c("q4", "levy", "70", "USD", q("$70"), (REVIEW, ["QUALIFIED_VALUE"])),
        c("q5", "toll", "80", "USD", q("$80"), (REVIEW, ["QUALIFIED_VALUE"])),
        c("q6", "rate", "90", "USD", q("$90"), (REVIEW, ["QUALIFIED_VALUE"])),
    ],
)  # fmt: skip

vector(
    "96-change-letters",
    "A change word and the range words match by the fold of each letter (SPEC §4). After "
    "'increa\u017fed from' and 'INCREASED from', the second number is the new value, and the "
    "first keeps its range reading. 'BETWEEN $5 AND $9' is a range (spec 0.10, #356).",
    "The fee increa\u017fed from $10 to $20. The cap INCREASED from $30 to $40. The levy is "
    "BETWEEN $5 AND $9.",
    {"fields": {f: USD for f in ("new_fee", "old_fee", "new_cap", "old_cap", "low", "high")}},
    [
        c("d1", "new_fee", "20", "USD", q("$20")),
        c("d2", "old_fee", "10", "USD", q("$10"), (REVIEW, ["QUALIFIED_VALUE"])),
        c("d3", "new_cap", "40", "USD", q("$40")),
        c("d4", "old_cap", "30", "USD", q("$30"), (REVIEW, ["QUALIFIED_VALUE"])),
        c("d5", "low", "5", "USD", q("$5"), (REVIEW, ["QUALIFIED_VALUE"])),
        c("d6", "high", "9", "USD", q("$9"), (REVIEW, ["QUALIFIED_VALUE"])),
    ],
)  # fmt: skip

MG = {"type": "number", "unit": "mg"}
vector(
    "97-per-unit-letters",
    "A per-unit matches by the fold of each letter (SPEC §4). 'k\u0131logram', 'ml' for 'mL', 'KG' "
    "and 'l\u0130ter' are per-units, so mg is not at 10, 20, 30 or 40 (spec 0.10, #356).",
    "Give 10 mg/k\u0131logram daily. Give 20 mg/ml daily. Give 30 mg/KG daily. Give 40 mg/l\u0130ter "
    "daily. Give 50 mg daily.",
    {"fields": {f: MG for f in ("a", "b", "c", "d", "e")}},
    [
        c("p1", "a", "10", "mg", q("10 mg"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("p2", "b", "20", "mg", q("20 mg"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("p3", "c", "30", "mg", q("30 mg"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("p4", "d", "40", "mg", q("40 mg"), ("rejected", ["UNIT_NOT_IN_EVIDENCE"])),
        c("p5", "e", "50", "mg", q("50 mg")),
    ],
)  # fmt: skip

SIGN_REVIEW = (REVIEW, ["SIGN_CITATION_INVALID", "VALUE_DERIVED"], [])
vector(
    "98-sign-word-letters",
    "The loss words, the negations and the gain words of a sign item match by the fold of each "
    "letter (SPEC §4). 'lo\u017fs' and 'LOSS' are loss words. 'w\u0131thout' and 'W\u0130THOUT' are "
    "negations, and 'ga\u0131n\u017f' is a gain word, so those items fail (spec 0.10, #356).",
    "Net lo\u017fs of $500 in 2024. Net LOSS of $600 in 2024. The plan ended w\u0131thout loss of $700 "
    "in 2024. The plan ended W\u0130THOUT loss of $800 in 2024. Operating loss and ga\u0131n\u017f of "
    "$900 in 2024.",
    {"packs": [FINANCE], "fields": {"amount": AMOUNT}},
    [
        c("s1", "amount", "-500", "USD", [q("$500"), {"role": "sign", "text": "Net lo\u017fs"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("s2", "amount", "-600", "USD", [q("$600"), {"role": "sign", "text": "Net LOSS"}],
          ("admitted", ["VALUE_DERIVED"])),
        c("s3", "amount", "-700", "USD",
          [q("$700"), {"role": "sign", "text": "w\u0131thout loss"}], SIGN_REVIEW),
        c("s4", "amount", "-800", "USD",
          [q("$800"), {"role": "sign", "text": "W\u0130THOUT loss"}], SIGN_REVIEW),
        c("s5", "amount", "-900", "USD",
          [q("$900"), {"role": "sign", "text": "loss and ga\u0131n\u017f"}], SIGN_REVIEW),
    ],
)  # fmt: skip

vector(
    "99-heading-letters",
    "The 'in' of a heading scale, and the words of a currency statement, match by the fold of "
    "each letter (SPEC §4). '(\u0131n thousands)' is a heading scale, 'presented in "
    "Au\u017ftralian dollars' is a statement of AUD, and 'IN MILLIONS OF CANADIAN DOLLARS' is a "
    "statement of CAD by its capital S (spec 0.10, #356).",
    "Fees (\u0131n thousands)\nFees\t75\n\n"
    "The figures are presented in Au\u017ftralian dollars.\n\t$m\t$m\nRevenue\t5,200\t4,900\n\n"
    "INCOME STATEMENT (IN MILLIONS OF CANADIAN DOLLARS)\n\t2025\t2024\nRevenue\t6,300\t5,800\n",
    {"fields": {**HEADING_UNIT_FIELDS["fields"], "fees": {"type": "number"},
                "fees_scaled": {"type": "number"}}},
    [
        c("h1", "fees", "75", None, [q("75")], (REVIEW, ["PART_MISSING"], ["scale"])),
        c("h2", "fees_scaled", "75000", None, [q("75"), q("(\u0131n thousands", role="scale")],
          DERIVED),
        c("h3", "aud", "5200000000", "AUD",
          [q("5,200"), q("Revenue", 1, role="field"), scale_item("$m"),
           unit_item("presented in Au\u017ftralian dollars")],
          DERIVED),
        c("h4", "aud", "5200000000", "AUD",
          [q("5,200"), q("Revenue", 1, role="field"), scale_item("$m"), unit_item("$m")],
          DERIVED),
        # the statement of AUD and the field disagree
        c("h5", "usd", "5200000000", "USD",
          [q("5,200"), q("Revenue", 1, role="field"), scale_item("$m"), unit_item("$m")],
          UNIT_REVIEW),
        c("h6", "cad", "6300000000", "CAD",
          [q("6,300"), q("Revenue", 2, role="field"), q("IN MILLIONS", role="scale"),
           unit_item("IN MILLIONS OF CANADIAN DOLLARS")],
          DERIVED),
    ],
)  # fmt: skip

KELVIN_RATE = "\u212aelvin rate"  # with the Kelvin sign (U+212A): a key need not be NFC
vector(
    "100-key-letters",
    "Keys and aliases match by the fold of each letter (SPEC §4). 'state income' has a mention "
    "in '\u017ftate income', 'STATE \u0131NCOME' and 'state \u0130ncome'. A key with the Kelvin "
    "sign (U+212A) has a mention in 'KELVIN RATE'. The alias 'State Income' matches "
    "'\u017ftate income' (spec 0.10, #356).",
    "The federal rate is 41. The \u017ftate income rate is 52. The STATE \u0131NCOME rate is 63. The "
    "state \u0130ncome rate is 74. The KELVIN RATE is 85.",
    {"fields": {"rate": {"type": "integer", "keys": ["state income", KELVIN_RATE],
                         "aliases": ["State Income"], "multiple": True}}},
    [
        c("k1", "rate", "41", None, q("41"), (REVIEW, ["KEY_NOT_AT_VALUE"], ["key"]),
          key="state income"),
        c("k2", "rate", "52", None, q("52"), key="state income"),
        c("k3", "rate", "63", None, q("63"), key="state income"),
        c("k4", "rate", "74", None, q("74"), key="state income"),
        c("k5", "rate", "85", None, q("85"), key=KELVIN_RATE),
        c("k6", "rate", "52", None, [q("52"), q("\u017ftate income", role="field")],
          key="state income"),
    ],
)  # fmt: skip

INVALID.append(
    {
        "name": "keys-fold-equal",
        "description": "Two keys with the same fold of each letter (SPEC §2.3, §4) are invalid: "
        "'State' and '\u017ftate' match the same text (spec 0.10, #356).",
        "document": "x",
        "schema": {"fields": {"dose": {"keys": ["State", "\u017ftate"]}}},
        "policy": None,
    }
)


def main() -> None:
    out_dir = HERE / "vectors"
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*.json"):
        old.unlink()
    for v in VECTORS:
        doc = v["document"]
        refs = {r["id"]: r["text"] for r in v["references"] or []}
        cands, expected = [], []
        for item in v["candidates"]:
            cand = item["candidate"]
            if isinstance(cand, dict):
                cand = {
                    k: resolve(doc, val, refs) if k in ("evidence", "search_region") else val
                    for k, val in cand.items()
                }
            cands.append(cand)
            expected.append(item["expect"])
        body = {
            "name": v["name"],
            "description": v["description"],
            "document": doc,
            "schema": v["schema"],
            "policy": v["policy"],
            **({"document_source": v["document_source"]} if v["document_source"] else {}),
            **({"references": v["references"]} if v["references"] is not None else {}),
            **({"packs": v["packs"]} if v["packs"] is not None else {}),
            "candidates": cands,
            **({"judgments": v["judgments"]} if v["judgments"] is not None else {}),
            "expected": {
                "decisions": expected,
                "coverage": v["coverage"],
                **({"relations": v["relations"]} if v["relations"] is not None else {}),
            },
        }
        (out_dir / f"{v['name']}.json").write_text(
            json.dumps(body, indent=1, ensure_ascii=False) + "\n"
        )
    inv_dir = HERE / "invalid"
    inv_dir.mkdir(exist_ok=True)
    for inv in INVALID:
        (inv_dir / f"{inv['name']}.json").write_text(
            json.dumps(
                {**inv, "candidates": inv.get("candidates", []), "expected": {"error": True}},
                indent=1,
                ensure_ascii=False,
            )
            + "\n"
        )
    print(f"wrote {len(VECTORS)} vectors and {len(INVALID)} invalid packets")


if __name__ == "__main__":
    main()
