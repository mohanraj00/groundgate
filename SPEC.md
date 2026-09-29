# groundgate specification v0.1

Status: draft. Version string: `groundgate/0.1`. An implementation conforms if it produces the
decisions and coverage findings in every vector under `conformance/vectors/`, and the receipt
hashes for vectors that pin them.

## 1. Purpose

An extractor (an LLM, LangExtract, a human, a rules engine) **proposes** candidate facts about a
document. groundgate **decides** what happens to each one, deterministically:

| Outcome | Meaning |
|---|---|
| `admitted` | Every check passed and nothing needs a person. |
| `needs_verification` | Nothing failed, but at least one flag says a person should look. The decision carries the evidence location. |
| `rejected` | A check failed. The fact must not enter the dataset. |

Every run produces a **receipt**: the inputs' hashes, one decision per candidate with its reason
codes, coverage findings, and a hash of the whole. Re-running on the same inputs reproduces the
receipt byte for byte.

groundgate checks what can be checked mechanically: the value is present at the cited location,
with the right unit, and nothing nearby changes its meaning (a qualifier, a scale word, a
conflicting proposal). It does **not** judge whether the text means what the field claims.
Anything it cannot prove is flagged, not silently admitted.

## 2. Inputs

### 2.1 Document

UTF-8 text in Unicode Normalization Form C. A document that is not NFC is an **invalid packet**:
the implementation raises an error and emits no receipt. Callers normalise before extracting.

`document_sha256` is the digest (§6) of kind `document` over `{"text": <text>}`.

### 2.2 Offsets

A **span** is `{"start": s, "end": e}`: zero-based, half-open **UTF-8 byte** offsets into the
document. A span is valid when `0 <= s < e <= len(bytes)` and both `s` and `e` fall on character
boundaries. Heuristic windows in §4 are measured in Unicode code points.

### 2.3 Schema

```json
{"fields": {"<name>": {
  "type": "number" | "integer" | "string",
  "unit": "<unit code>" | null,
  "comparator": "eq" | "gt" | "ge" | "lt" | "le" | "approx" | "range",
  "minimum": "<decimal>" | null,
  "maximum": "<decimal>" | null,
  "required": false,
  "multiple": false
}},
 "units": {"<unit code>": {"prefix": ["<surface>"], "suffix": ["<surface>"]}}}
```

Defaults: `unit` null, `comparator` `"eq"`, bounds null, `required` false, `multiple` false.
`units` extends and overrides the built-in table (§4.3). `schema_sha256` is the digest of kind
`schema` over the schema object **after** defaults are filled in.

### 2.4 Policy

```json
{"min_confidence": null, "unit_window": 24, "reanchor": true}
```

`policy_sha256` is the digest of kind `policy` over the policy object after defaults.

### 2.5 Candidate

```json
{"id": "c1", "field": "max_daily_dose", "value": "2000", "unit": "mg",
 "evidence": {"start": 120, "end": 128, "text": "2,000 mg"},
 "search_region": {"start": 0, "end": 1000}, "confidence": 0.93}
```

| Key | Required | Meaning |
|---|---|---|
| `field` | yes | Schema field name. |
| `value` | yes | A string, or a JSON integer. JSON numbers with a fraction are not allowed (use a decimal string). |
| `unit` | no | Unit code the extractor claims. |
| `evidence` | no | Span the extractor cites, with the text it quoted (`text` optional). |
| `search_region` | no | Span within which re-anchoring may look (§3 step 9). Default: the whole document. |
| `confidence` | no | Number in [0, 1]. |
| `id` | no | Caller's identifier, echoed in the decision. |

Other keys are allowed and ignored by the checks (for example the proposer's name); they are covered
by `candidate_sha256`, the digest of kind `candidate` over the candidate object as given.

## 3. Decision procedure

Checks run in this order. The first failing check **rejects** the candidate with its code and no
later check runs. `value` means the candidate's value parsed per its field type.

| Step | Code | Rejects when |
|---:|---|---|
| 1 | `CANDIDATE_INVALID` | The candidate is not an object, `field` is not a string, `value` is missing or not a string/integer, `unit` is not a string, `confidence` is not a number in [0, 1], or `evidence`/`search_region` is present but not an object with integer `start` and `end`. |
| 2 | `FIELD_UNKNOWN` | `field` is not in the schema. |
| 3 | `NULL_STRING_LITERAL` | `value`, trimmed and lower-cased, is `null`, `none`, `nil` or `n/a`. |
| 4 | `TYPE_INVALID` | `value` does not parse as the field type (§4.1). |
| 5 | `RANGE_INVALID` | `value` is below `minimum` or above `maximum`. |
| 6 | `UNIT_INVALID` | The candidate's `unit` differs from the field's `unit` (both absent is a match). |
| 7 | `NO_EVIDENCE` | `evidence` is absent. |
| 8 | `SPAN_INVALID` | The evidence span, or `search_region`, is not a valid span (§2.2). |
| 9 | `VALUE_NOT_IN_EVIDENCE` | No number token (§4.1) in the span equals `value` (for `string` fields: the whitespace-normalised value is not a substring of the whitespace-normalised span text). |
| 10 | `UNIT_NOT_IN_EVIDENCE` | The field has a unit, and no matching number token in the span has that unit at its location (§4.3). |

**Re-anchoring (steps 9–10).** When step 9 or 10 fails, `policy.reanchor` is true and the candidate
has a non-blank `evidence.text`, the implementation finds every occurrence of `evidence.text` inside
`search_region` (whitespace runs in the quote match any whitespace run in the document). If
**exactly one** occurrence other than the cited span passes steps 9 and 10, that occurrence becomes
the evidence, the decision records code `EVIDENCE_REANCHORED`, and checking continues. Otherwise
the original failure stands.

A candidate that passes every step is then **flagged**. Each flag adds its code; any flag makes the
outcome `needs_verification`, no flag makes it `admitted`.

| Code | Flags when |
|---|---|
| `NON_VERBATIM_EVIDENCE` | `evidence.text` is present and differs from the span's text after whitespace normalisation and joining of line-break hyphenation (§4.4). |
| `QUALIFIED_VALUE` | A qualifier (§4.2) applies to the value in the document and its comparator differs from the field's `comparator`. |
| `SCALE_WORD` | A scale word (`thousand`, `million`, `billion`, `trillion`, `lakh`, `crore`) follows the value within 2 code points, ignoring whitespace. |
| `LOW_CONFIDENCE` | `policy.min_confidence` is set and `confidence` is below it. |
| `CONFLICTING_CANDIDATES` | Another candidate for the same non-`multiple` field also passed steps 1–10 with a different canonical value. Set on every such candidate. |

`EVIDENCE_REANCHORED` is informational: it never changes the outcome.

**Coverage.** For every `required` field with no candidate that is `admitted` or
`needs_verification`, the receipt lists `{"field": <name>, "code": "REQUIRED_FIELD_MISSING"}`.

## 4. Text rules

### 4.1 Numbers

A **number token** is a maximal match of `[-−]?\d[\d,]*(\.\d+)?` that is not preceded by a letter,
digit, `.` or `,`, with one trailing `,` dropped. A leading `-` or `−` (U+2212) counts only when
it is not preceded by a letter or digit. The token has a value when its digits are either
ungrouped (`\d+`) or grouped in threes after the first group (`\d{1,3}(,\d{3})+`); otherwise it
has **no** value (`252,0000` never equals 252000 or 2520000). When tokens are read inside a span, a
token that continues past the span's end is ignored, so a span can never read a prefix of a longer
number.

Candidate values parse the same way after trimming, and must be a single token. `integer` fields
additionally require an integral value. The **canonical value** is the decimal without grouping,
exponent, trailing fractional zeros or a trailing `.`, with `-0` written `0`.

### 4.2 Qualifiers

A qualifier applies when it appears between the value and the nearest of: the previous number token,
the start of the sentence, or 40 code points before the value (qualifiers *before*); or between the
value and the nearest of the next number token, the end of the sentence, or 40 code points after it
(qualifiers *after*). Sentences end at `.` or `;` followed by whitespace (a line break counts), at
`•`, or at a blank line. Matching is case-insensitive on whole words. `from` is deliberately absent:
"from 7 to 8" is already a range through its connector, and "up from $236,000" is not a qualifier.

| Comparator | Before the value | After the value |
|---|---|---|
| `approx` | approximately, about, around, nearly, roughly, generally, ~, ≈ | |
| `gt` | more than, greater than, above, over, exceeds, exceeding, > | |
| `lt` | less than, fewer than, below, under, < | |
| `ge` | at least, minimum of, no less than, ≥ | or more, or greater, or older, or higher, or above |
| `le` | up to, maximum of, at most, no more than, ≤ | or less, or fewer, or younger, or lower, or below |
| `range` | between | the value is followed by `to`, `through`, `thru`, `-` or `–` and then another number token, or is preceded by such a connector and a number token; `and` counts as a connector only when `between` comes before the first number |

### 4.3 Units

Built-in unit table (a schema's `units` extends or overrides it):

| Code | Prefix | Suffix |
|---|---|---|
| `USD` | `$`, `US$` | `USD`, `dollars` |
| `EUR` | `€` | `EUR`, `euros` |
| `GBP` | `£` | `GBP` |
| `INR` | `₹`, `Rs.`, `Rs` | `INR`, `rupees` |
| `%` | | `%`, `percent` |
| `mg`, `mcg`, `g`, `kg`, `mL`, `L` | | the code itself |
| `hours`, `days`, `weeks`, `months`, `years`, `minutes` | | the code, its singular, and `-<singular>` |

A unit **is at** a number token when a prefix ends at the token start (whitespace between them
allowed), or a suffix starts within `policy.unit_window` code points after the token end without
crossing a sentence end. A unit code not in the table and without prefixes or suffixes is at every
token (the check is vacuous).

### 4.4 Whitespace normalisation

Collapse every whitespace run to one space and trim. For the verbatim comparison only, also delete
`-` followed by a line break and optional whitespace (line-break hyphenation).

## 5. Receipt

```json
{"groundgate": "0.1",
 "document": {"id": null, "sha256": "sha256:..."},
 "schema_sha256": "sha256:...", "policy_sha256": "sha256:...",
 "decisions": [{"candidate_id": "c1", "candidate_sha256": "sha256:...", "field": "...",
                "outcome": "admitted", "codes": [], "value": "2000", "unit": "mg",
                "evidence": {"start": 120, "end": 128}}],
 "coverage": [],
 "summary": {"admitted": 1, "needs_verification": 0, "rejected": 0},
 "receipt_sha256": "sha256:..."}
```

Decisions are sorted by `candidate_sha256`, then by input position. `codes` lists the rejecting
code, or the flag codes in the order of the table in §3, followed by `EVIDENCE_REANCHORED` when it
applies. `value` is the canonical value and `unit` the candidate's unit, each `null` when the candidate
does not provide a parseable one. `evidence` is the span the decision rests on: the re-anchored span
when re-anchoring applied, otherwise the cited span if it is valid, otherwise `null`. Coverage is sorted by field name. `receipt_sha256` is the digest of kind `receipt`
over the receipt without its `receipt_sha256` key.

## 6. Canonical JSON and digests

Canonical JSON is RFC 8785 (JCS): keys sorted by UTF-16 code units, no insignificant whitespace,
strings escaped as ECMAScript `JSON.stringify` does, numbers serialised as ECMAScript
`Number.prototype.toString`. NaN and infinities are not permitted. Integers outside
[-(2^53-1), 2^53-1] are not permitted (they are not exactly representable).

`digest(kind, obj) = "sha256:" + hex(SHA-256("groundgate/0.1:" + kind + "\0" + JCS(obj)))`, where
the prefix is ASCII and `JCS(obj)` is UTF-8.

## 7. Non-goals for v0.1

Semantic correctness (whether the sentence describes the field), dates, arrays of records,
cross-document checks, and PDF geometry (page and bounding box) as evidence. Adapters may convert
richer evidence into spans.
