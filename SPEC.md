# groundgate specification v0.3 (draft)

Status: draft, not released. Version string: `groundgate/0.3`. Spec 0.2 was released with
groundgate 0.2.0 and is in the `v0.2.0` tag, and spec 0.1 in the `v0.1.0` tag. Any change to how
a candidate is decided is a new version with a new version string. An implementation conforms if
it produces the decisions and coverage findings in every vector under `conformance/vectors/`,
and the receipt hashes for vectors that pin them.

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
  "multiple": false,
  "keys": ["<key>"] | null
}},
 "units": {"<unit code>": {"prefix": ["<surface>"], "suffix": ["<surface>"]}}}
```

Defaults: `unit` null, `comparator` `"eq"`, bounds null, `required` false, `multiple` false,
`keys` null.

`keys` makes a field **keyed**: its values belong to one of several conditions, such as the
indications of a drug, and each candidate names its condition. The keys are written in the
document's words (§4.5). `keys` is null or a non-empty list of strings, no key is blank, and no
two keys are equal after whitespace normalisation (§4.4) and lower-casing; otherwise the packet is
invalid.
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
| `key` | no | For a keyed field, the key the value belongs to. Ignored on a field without `keys`. |
| `evidence` | no | Span the extractor cites, with the text it quoted (`text` optional). |
| `search_region` | no | Span within which re-anchoring may look (§3 step 10). Default: the whole document. |
| `confidence` | no | Number in [0, 1]. |
| `id` | no | Caller's identifier, echoed in the decision. |

Other keys are allowed and ignored by the checks (for example the proposer's name); they are covered
by `candidate_sha256`, the digest of kind `candidate` over the candidate object as given.

## 3. Decision procedure

Checks run in this order. The first failing check **rejects** the candidate with its code and no
later check runs. `value` means the candidate's value parsed per its field type.

| Step | Code | Rejects when |
|---:|---|---|
| 1 | `CANDIDATE_INVALID` | The candidate is not an object, `field` is not a string, `value` is missing or not a string/integer, `unit` or `key` is not a string, `confidence` is not a number in [0, 1], or `evidence`/`search_region` is present but not an object with integer `start` and `end`. |
| 2 | `FIELD_UNKNOWN` | `field` is not in the schema. |
| 3 | `NULL_STRING_LITERAL` | `value`, trimmed and lower-cased, is `null`, `none`, `nil` or `n/a`. |
| 4 | `TYPE_INVALID` | `value` does not parse as the field type (§4.1). |
| 5 | `RANGE_INVALID` | `value` is below `minimum` or above `maximum`. |
| 6 | `UNIT_INVALID` | The candidate's `unit` differs from the field's `unit` (both absent is a match). |
| 7 | `KEY_INVALID` | The field has `keys`, and the candidate's `key` is absent or not exactly one of them. |
| 8 | `NO_EVIDENCE` | `evidence` is absent. |
| 9 | `SPAN_INVALID` | The evidence span, or `search_region`, is not a valid span (§2.2). |
| 10 | `VALUE_NOT_IN_EVIDENCE` | No number token (§4.1) in the span equals `value`, by its value or its scaled value (for `string` fields: the whitespace-normalised value is not a substring of the whitespace-normalised span text). |
| 11 | `UNIT_NOT_IN_EVIDENCE` | The field has a unit, and no matching number token in the span has that unit at its location (§4.3). |

**Re-anchoring (steps 10–11).** When step 10 or 11 fails, `policy.reanchor` is true and the candidate
has a non-blank `evidence.text`, the implementation finds every occurrence of `evidence.text` inside
`search_region` (whitespace runs in the quote match any whitespace run in the document). If
**exactly one** occurrence other than the cited span passes steps 10 and 11, that occurrence becomes
the evidence, the decision records code `EVIDENCE_REANCHORED`, and checking continues. Otherwise
the original failure stands.

A candidate that passes every step is then **flagged**. Each flag adds its code; any flag makes the
outcome `needs_verification`, no flag makes it `admitted`.

| Code | Flags when |
|---|---|
| `NON_VERBATIM_EVIDENCE` | `evidence.text` is present and differs from the span's text after whitespace normalisation and joining of line-break hyphenation (§4.4). |
| `QUALIFIED_VALUE` | A qualifier (§4.2) applies to the value in the document and its comparator differs from the field's `comparator`. |
| `SCALE_WORD` | A scale word (§4.1) follows the value, and the candidate's `value` is the number as written, not its scaled value. |
| `KEY_NOT_AT_VALUE` | The field has `keys`, and the candidate's `key` is not a key at the value (§4.5). |
| `LOW_CONFIDENCE` | `policy.min_confidence` is set and `confidence` is below it. |
| `CONFLICTING_CANDIDATES` | Another candidate for the same non-`multiple` field, and on a keyed field the same `key`, also passed steps 1–11 with a different canonical value. Set on every such candidate. |

`EVIDENCE_REANCHORED` is informational: it never changes the outcome.

**Coverage.** For every `required` field with no candidate that is `admitted` or
`needs_verification`, the receipt lists `{"field": <name>, "code": "REQUIRED_FIELD_MISSING"}`.
Coverage is per field, not per key.

## 4. Text rules

### 4.1 Numbers

A **number token** is a maximal match of `[-−]?\d[\d,]*(\.\d+)?` that is not preceded by a letter,
digit, `.` or `,`, with one trailing `,` dropped. A leading `-` or `−` (U+2212) counts only when
it is not preceded by a letter or digit. The token has a value when its digits are either
ungrouped (`\d+`) or grouped in threes after the first group (`\d{1,3}(,\d{3})+`); otherwise it
has **no** value (`252,0000` never equals 252000 or 2520000). When tokens are read inside a span, a
token that continues past the span's end is ignored, so a span can never read a prefix of a longer
number.

A number token with a value that is followed by a **scale word** also has a **scaled value**. The
scale words are `thousand`, `million`, `billion`, `trillion`, `lakh` and `crore`, matched as whole
words, case-insensitively, after at most 2 whitespace code points. The scaled value is the value
times 10^3, 10^6, 10^9, 10^12, 10^5 or 10^7: "$1.25 billion" is 1250000000 and "4 lakh" is
400000. Like a unit, the scale word is read from the document, so it counts even past the end of
the span. A scale word with no number before it ("millions of") has no value.

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
| `gt` | more than, greater than, above, over, exceed, exceeds, exceeding, > | |
| `lt` | less than, fewer than, below, under, < | |
| `ge` | at least, minimum of, no less than, ≥ | or more, or greater, or older, or higher, or above |
| `le` | up to, maximum of, at most, no more than, ≤ | or less, or fewer, or younger, or lower, or below |
| `range` | between | the value is followed by `to`, `through`, `thru`, `-` or `–` and then another number token, or is preceded by such a connector and a number token; `and` counts as a connector only when `between` comes before the first number; one word of up to 12 characters with no digits (a unit or scale word) may stand between the first number and `to`, `through`, `thru` or `and`, so both ends of "30 mg to 45 mg" and "$1 million to $2 million" are a range |

Where two qualifiers overlap in the text, only the longer one applies: "no more than" is `le`,
not also `gt`, and "no less than" is `ge`, not also `lt`.

A negation directly before a `gt`, `lt`, `ge` or `le` qualifier in the *before* column inverts
it: `gt` becomes `le`, `le` becomes `gt`, `lt` becomes `ge`, and `ge` becomes `lt`. The
negations are `not`, `cannot` and `can't` (with `'` or `’`), optionally followed by `be`, with
only whitespace between them and the qualifier, in the same sentence. The negation may lie
outside the 40-code-point window as long as the qualifier is inside it. So "must not be more
than $7,000" and "may not exceed $19,000" are `le`, and "cannot be less than $1,200" is `ge`.
In "not required if the balance is more than $600", the `not` is not directly before the
qualifier, so the value stays `gt`.

A change is not a range. When the first number of a range pair follows `from`, and a change word
is directly before `from` (only whitespace between them), the second number is the new value and
is not a range end. The change words are increased, decreased, raised, reduced, lowered, rose,
fell, dropped, grew, changed, increase, decrease, reduction, rise, drop and change. The first
number keeps its range reading: it is the old value, and a field that takes it should be looked
at. So in "increased from $70,000 to $72,000", $72,000 is unqualified and $70,000 is a range.
"run from 7 to 8 hours" has no change word, so both numbers stay a range.

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
allowed), or when the first suffix after the token end is one of the unit's suffixes, starts
within `policy.unit_window` code points without crossing a sentence end, and is not a per-unit.
The first suffix is the match of any suffix of any unit in the table, built-in or the schema's,
that starts earliest, the longest one at a tie; a later match never counts. So `mg` is not at the
10 in "10 mcg (maximum 500 mg)", because `mcg` comes first, and `hours` is not at the 2 in
"Infuse 2 L in 4 hours". A number without a unit of its own still takes the next one: `mg` is at
the 25 in "25 or 50 mg". It is a **per-unit** when it is followed, after optional whitespace, by `/` or `per`, an
optional number, and a body-size or volume unit: `kg`, `kilogram`, `lb`, `pound`, `m2`, `m²`,
`m^2`, `square meter` or `square metre`, `mL`, `dL`, `L`, `liter` or `litre` (plurals included,
case-insensitive, not followed by a letter). So `mg` is not at the 10 in "10 mg/kg (maximum 500
mg)", nor at "1.6 mcg/kg/day", "75 mg/m2", "2 mg per kilogram" or "250 mg/5 mL". A time
denominator keeps the unit: "200 mg/day" is mg. A weight-based dose needs its own unit code, such
as `mg/kg` with the suffix `mg/kg`. A unit code not in the table and without prefixes or suffixes
is at every token (the check is vacuous).

### 4.4 Whitespace normalisation

Collapse every whitespace run to one space and trim. For the verbatim comparison only, also delete
`-` followed by a line break and optional whitespace (line-break hyphenation).

### 4.5 Keys

A **key mention** is an occurrence of one of a field's keys in the document: matched
case-insensitively, with each whitespace run in the key matching any whitespace run, and not
preceded or followed by a letter or digit. Where two mentions overlap and one contains the
other, only the longer counts. A mention is in a sentence (§4.2) when it lies wholly inside it.

The value is at its supporting number token (§3 steps 10–11), or at the start of the evidence
span for a `string` field. The **keys at the value** are the keys mentioned in the value's
sentence. When the sentence mentions none, they are the key of the nearest mention that ends at
or before the value's start, or no key when there is no such mention. The candidate's `key` must
be one of them.

There is no heading detection. A heading kept as a line of text is a mention like any other, so
in "2.2 Heart Failure\nThe starting dose is 5 mg", 5 mg is at heart failure, and so is a value
in a later sentence under that heading, until another key is mentioned. A sentence that mentions
two conditions puts its values at both. Rows of a flattened table with no sentence end between
them are one sentence, so every value in the table is at every key the table mentions, and a key
swapped within a table is not caught.

## 5. Receipt

```json
{"groundgate": "0.3",
 "document": {"id": null, "sha256": "sha256:..."},
 "schema_sha256": "sha256:...", "policy_sha256": "sha256:...",
 "decisions": [{"candidate_id": "c1", "candidate_sha256": "sha256:...", "field": "...",
                "key": null, "outcome": "admitted", "codes": [], "value": "2000", "unit": "mg",
                "evidence": {"start": 120, "end": 128}}],
 "coverage": [],
 "summary": {"admitted": 1, "needs_verification": 0, "rejected": 0},
 "receipt_sha256": "sha256:..."}
```

Decisions are sorted by `candidate_sha256`, then by input position. `codes` lists the rejecting
code, or the flag codes in the order of the table in §3, followed by `EVIDENCE_REANCHORED` when it
applies. `value` is the canonical value and `unit` the candidate's unit, each `null` when the candidate
does not provide a parseable one. `key` is the candidate's `key` when its field has `keys` and the
key is a string, otherwise `null`. `evidence` is the span the decision rests on: the re-anchored span
when re-anchoring applied, otherwise the cited span if it is valid, otherwise `null`. Coverage is
sorted by field name. `receipt_sha256` is the digest of kind `receipt` over the receipt without
its `receipt_sha256` key.

## 6. Canonical JSON and digests

Canonical JSON is RFC 8785 (JCS): keys sorted by UTF-16 code units, no insignificant whitespace,
strings escaped as ECMAScript `JSON.stringify` does, numbers serialised as ECMAScript
`Number.prototype.toString`. NaN and infinities are not permitted. Integers outside
[-(2^53-1), 2^53-1] are not permitted (they are not exactly representable).

`digest(kind, obj) = "sha256:" + hex(SHA-256("groundgate/0.3:" + kind + "\0" + JCS(obj)))`, where
the prefix is ASCII and `JCS(obj)` is UTF-8.

## 7. Non-goals for v0.3

Semantic correctness (whether the sentence describes the field), dates, arrays of records,
cross-document checks, and PDF geometry (page and bounding box) as evidence. Adapters may convert
richer evidence into spans.
