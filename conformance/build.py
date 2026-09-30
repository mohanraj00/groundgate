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


def q(quote: str, n: int = 1, text: object = None) -> dict[str, Any]:
    """Evidence marker: the n-th occurrence of ``quote``, cited with ``text`` (default: the quote;
    NO_TEXT: no text key)."""
    return {"quote": quote, "n": n, "text": quote if text is None else text}


def vector(
    name: str,
    description: str,
    document: str,
    schema: dict[str, Any],
    candidates: list[Any],
    policy: dict[str, Any] | None = None,
    coverage: list[dict[str, str]] | None = None,
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
    return {"candidate": cand, "expect": {"outcome": expect[0], "codes": expect[1]}}


def raw(candidate: Any, expect: tuple[str, list[str]]) -> dict[str, Any]:
    """A candidate written exactly as given (may be malformed)."""
    return {"candidate": candidate, "expect": {"outcome": expect[0], "codes": expect[1]}}


def resolve(document: str, ev: Any) -> Any:
    if not (isinstance(ev, dict) and "quote" in ev):
        return ev
    data, needle = document.encode("utf-8"), ev["quote"].encode("utf-8")
    i = -1
    for _ in range(ev["n"]):
        i = data.find(needle, i + 1)
        if i < 0:
            raise SystemExit(f"quote {ev['quote']!r} occurrence {ev['n']} not in document")
    out = {"start": i, "end": i + len(needle)}
    if ev["text"] is not NO_TEXT:
        out["text"] = ev["text"]
    return out


USD = {"type": "integer", "unit": "USD"}

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
            ("rejected", ["UNIT_NOT_IN_EVIDENCE"]),
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
            "name": "policy-bad-confidence",
            "description": "min_confidence must be in [0, 1].",
            "document": "x",
            "schema": {"fields": {}},
            "policy": {"min_confidence": 2},
        },
        {
            "name": "policy-unknown-key",
            "description": "Unknown policy keys are invalid.",
            "document": "x",
            "schema": {"fields": {}},
            "policy": {"strict": True},
        },
    ]
)


def main() -> None:
    out_dir = HERE / "vectors"
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*.json"):
        old.unlink()
    for v in VECTORS:
        doc = v["document"]
        cands, expected = [], []
        for item in v["candidates"]:
            cand = item["candidate"]
            if isinstance(cand, dict):
                cand = {
                    k: resolve(doc, val) if k in ("evidence", "search_region") else val
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
            "candidates": cands,
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
                {**inv, "candidates": [], "expected": {"error": True}}, indent=1, ensure_ascii=False
            )
            + "\n"
        )
    print(f"wrote {len(VECTORS)} vectors and {len(INVALID)} invalid packets")


if __name__ == "__main__":
    main()
