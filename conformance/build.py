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
) -> None:
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
    """(outcome, codes) or (outcome, codes, missing): the decision a candidate must get."""
    out: dict[str, Any] = {"outcome": expect[0], "codes": expect[1]}
    if len(expect) > 2:
        out["missing"] = expect[2]
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
vector(
    "19b-derived-sign",
    "A sign item makes a token negative: brackets around the value, or a loss word before it in "
    "the same sentence with no number, line break, tab or gain word between. Brackets around the "
    "token make it negative with no item. A failing sign item still gives its part, with its flag. "
    "A negative value with no sign is a missing part (spec 0.5).",
    "For the year ended December 31, 2024, we had a net loss of $71,000, which consisted of "
    "$71,000 of general and administrative expenses.\n\n"
    "Loss from operations\n\n($105,198\n)\n\n($34,904\n)\n\n"
    "Net (loss) income\n\n$6,152\n\n($13,203\n)\n\n"
    "In 2023 the company reported a loss of $5,000 and revenue of $9,000.\n\n"
    "Loss was $5 million in 2022.",
    {"fields": {"amount": AMOUNT}},
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
    "fails, and on a string field every role item but a key or field item fails (spec 0.5).",
    "Results\n\nYear\n\n2025\n\n2024\n\n"
    "Net loss\n\n$\n\n(2,500\n)\n\n$\n\n(1,900\n)\n\n"
    "Shares outstanding\n\n7,000\n\n6,500\n\n"
    "The net loss for 2025 was $2,500 thousand. The deficit grew to $9 in 2024, and income was $3.",
    {"fields": {"net_income": NET, "title": {"type": "string"}}},
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
    "the longest unit prefix first (spec 0.5).",
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
          ("admitted", ["KEY_CITED"]), key="2024"),
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
          ("admitted", ["VALUE_DERIVED", "KEY_CITED"]), key="2024"),
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
    "Wages were 9 dollars an hour.\nCrew\t70\t60\n"
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
    "column's $ when its field item passes (spec 0.7, #164).",
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
        c("p12", "revenue", "426201", "USD", [q("426,201"), row("Total revenues")],
          (REVIEW, ["PART_MISSING"], ["unit"])),
    ],
)  # fmt: skip


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
            "candidates": cands,
            **({"judgments": v["judgments"]} if v["judgments"] is not None else {}),
            "expected": {"decisions": expected, "coverage": v["coverage"]},
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
