# groundgate specification v0.5 (draft)

Status: draft, not released. Version string: `groundgate/0.5`. Spec 0.4 was released with
groundgate 0.4.0 and is in the `v0.4.0` tag, spec 0.3 in the `v0.3.0` tag, spec 0.2 in the `v0.2.0` tag, and spec 0.1 in the
`v0.1.0` tag. Any change to how
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
conflicting proposal). The extractor can cite more than the value: the sign, the scale, the unit,
the key and the field's own words, each at its own place (§4.6). It can also cite a reference that
the app supplies, an external source, or its own knowledge (§2.5). groundgate admits what checked
evidence supports, plus what the app's policy allows for evidence that it cannot check (§2.4), and
the receipt says which. It does **not** judge whether the text means what the field claims.
Anything it cannot prove is flagged, not silently admitted. A model's answer can enter a decision
only as a recorded judgment (§2.6), never as a call: the decision stays a function of its inputs.

## 2. Inputs

### 2.1 Document

UTF-8 text in Unicode Normalization Form C. A document that is not NFC is an **invalid packet**:
the implementation raises an error and emits no receipt. Callers normalise before extracting.

`document_sha256` is the digest (§6) of kind `document` over `{"text": <text>}`.

A packet may give the **document source**: the URL that the app got the document from, a
non-blank string, or null. It goes into the receipt, and the policy can trust external sources on
its domain (§2.4).

A packet may also carry **references**: other source texts that the app, not the extractor,
supplies. A reference can hold only the part of its source that matters.

```json
{"id": "irs-p17", "text": "...", "source": "https://www.irs.gov/publications/p17"}
```

`id` is a non-blank string, unique in the packet. `text` is a non-empty string in NFC. `source` is
a non-blank string or null (default). Other keys, or a malformed reference, make the packet
invalid. A reference's digest is of kind `reference` over `{"text": <text>}`.

### 2.2 Offsets

A **span** is `{"start": s, "end": e}`: zero-based, half-open **UTF-8 byte** offsets into the
document, or into a reference for an item from that reference. A span is valid when `0 <= s < e <= len(bytes)` and both `s` and `e` fall on character
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
  "keys": ["<key>"] | null,
  "aliases": ["<words>"] | null
}},
 "units": {"<unit code>": {"prefix": ["<surface>"], "suffix": ["<surface>"]}}}
```

Defaults: `unit` null, `comparator` `"eq"`, bounds null, `required` false, `multiple` false,
`keys` null, `aliases` null.

`keys` makes a field **keyed**: its values belong to one of several conditions, such as the
indications of a drug, and each candidate names its condition. The keys are written in the
document's words (§4.5). `keys` is null or a non-empty list of strings, no key is blank, and no
two keys are equal after whitespace normalisation (§4.4) and lower-casing; otherwise the packet is
invalid.
`aliases` are the field's names in the document's words, such as "loss from operations" for an
operating income field. A field item (§4.6) is checked against them. They follow the same rules as
`keys`: null or a non-empty list of strings, none blank, no two equal after whitespace
normalisation and lower-casing.
`units` extends and overrides the built-in table (§4.3). `schema_sha256` is the digest of kind
`schema` over the schema object **after** defaults are filled in.

### 2.4 Policy

```json
{"min_confidence": null, "unit_window": 24, "reanchor": true, "judge": null,
 "sources": {"external": {"allow": [], "other": "review"}, "knowledge": "review"}}
```

`sources` says what happens to a candidate that only evidence from outside the pinned texts
supports (§3, the outside path). groundgate cannot check such evidence, so the app decides:

- `external.allow` is a list of non-blank strings. An external item whose URL matches an entry is
  admitted. `"*"` matches every URL. `"document-domain"` matches a URL whose host equals the host
  of the document source, and nothing when the packet has no document source. Any other entry
  matches a URL that starts with it, so write the entry with its final `/`.
- `external.other` is `review` or `reject`: what happens to an external item that matches no entry.
- `knowledge` is `admit`, `review` or `reject`.

The **host** of a URL is the text after its first `://` up to the first `/`, `?` or `#`, after the
last `@`, without a `:` and port, lower-cased. A URL without `://` has no host. Defaults fill in
each member that is absent; other keys or values are invalid.

`judge` is null or names the one judge whose recorded judgments (§2.6) the decision reads, with
its thresholds:

```json
{"id": "jev", "digest": "jev-1.13.0",
 "clear": {"KEY_NOT_AT_VALUE": 0.9}, "doubt": {"field_match": 0.2}}
```

`id` and `digest` are non-blank strings. `digest` names one model version: the digest of the
weights, or the version that a hosted model reports. `clear` and `doubt` are optional and default to `{}`;
`clear` can hold only `KEY_NOT_AT_VALUE`, and `doubt` only `field_match`, each a number in [0, 1]
when present (null is invalid). Other keys
are invalid. With `judge` null, or with no threshold for a question, the decision is the same as
without judgments.

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
| `evidence` | no | The evidence items the extractor gives, as a list. One item object counts as a list that holds it. |
| `search_region` | no | Span within which re-anchoring may look (§3 step 10). Default: the whole document. |
| `confidence` | no | Number in [0, 1]. |
| `id` | no | Caller's identifier, echoed in the decision. |

Other keys are allowed and ignored by the checks (for example the proposer's name); they are covered
by `candidate_sha256`, the digest of kind `candidate` over the candidate object as given.

An **evidence item** is one piece of support for the value. Its `source` says where it comes from:

| `source` | Who supplies the text | Members | Trust |
|---|---|---|---|
| `document` (default) | the app | `role`, `start` and `end`, `text` | checked |
| `reference` | the app | `ref`, `role`, `start` and `end`, `text` | checked |
| `external` | the extractor | `url`, `retrieved`, `text` | quoted |
| `knowledge` | the extractor | `text` | stated |

- `role` is one of `value` (default), `sign`, `scale`, `unit`, `key` and `field` (§4.6).
- `ref` is the `id` of a reference in the packet. The item's offsets are in that reference.
- `start` and `end` are a span (§2.2). Give both or neither. Without them, `text` is a **quote**,
  and groundgate finds it (§4.6).
- `text` is the text that the item quotes. For `knowledge`, it is the extractor's statement, for
  example "The phase-out starts at $165,000 for married filing jointly (IRC §221)".
- `url` is the external page, and `retrieved` the date that the extractor read it, each a
  non-blank string.

```json
{"id": "c7", "field": "operating_income", "key": "2024", "value": "-105198000", "unit": "USD",
 "evidence": [{"text": "(105,198\n)"},
              {"role": "scale", "text": "(in thousands"},
              {"role": "unit", "text": "$"},
              {"role": "field", "text": "Loss from operations"},
              {"role": "key", "text": "2024"}]}
```

The **value item** is the document or reference item with role `value`. The other document and
reference items are **role items**. External and knowledge items are **outside items**.

### 2.6 Judgments

A packet may carry a list of **recorded judgments**: answers that a judge (a model, or a person)
gave about one candidate before the decision. groundgate never calls a judge.

```json
{"candidate_id": "c1", "question": "key", "judge": {"id": "jev", "digest": "jev-1.13.0"},
 "answer": "heart failure", "p": 0.97}
```

| Key | Meaning |
|---|---|
| `candidate_id` | The `id` of exactly one candidate in the packet. |
| `question` | `key`: which of the field's keys the value belongs to. `field_match`: whether the text states the value as the field. |
| `judge` | `id` and `digest`, non-blank strings. |
| `answer` | `key` only: the chosen key as a string, or null for none of the keys. |
| `p` | For `key`, the probability of the answer. For `field_match`, the probability that the text states the value as the field. A number in [0, 1]. |

The packet is **invalid** when a judgment is malformed, names an id that no candidate or more than
one candidate has, or repeats a question for one candidate.

A judgment **applies** when its `judge` equals `policy.judge`'s `id` and `digest`, the policy has
a threshold for its question, and its candidate passed (§3.3). Other judgments change nothing.

## 3. Decision procedure

Checks run in this order. The first failing check **rejects** the candidate with its code and no
later check runs. `value` means the candidate's value parsed per its field type.

| Step | Code | Rejects when |
|---:|---|---|
| 1 | `CANDIDATE_INVALID` | The candidate is malformed (below). |
| 2 | `FIELD_UNKNOWN` | `field` is not in the schema. |
| 3 | `NULL_STRING_LITERAL` | `value`, trimmed and lower-cased, is `null`, `none`, `nil` or `n/a`. |
| 4 | `TYPE_INVALID` | `value` does not parse as the field type (§4.1). |
| 5 | `RANGE_INVALID` | `value` is below `minimum` or above `maximum`. |
| 6 | `UNIT_INVALID` | The candidate's `unit` differs from the field's `unit` (both absent is a match). |
| 7 | `KEY_INVALID` | The field has `keys`, and the candidate's `key` is absent or not exactly one of them. |
| 8 | `NO_EVIDENCE` | The candidate has no value item and no outside item. |

Step 1 rejects when the candidate is not an object, `field` is not a string, `value` is missing or
not a string/integer, `unit` or `key` is not a string, `confidence` is not a number in [0, 1],
`search_region` is present but not an object with integer `start` and `end`, or `evidence` is
present but not an object or a list of objects. It also rejects when an evidence item:

- has a `source` other than the four kinds, or a `role` other than the six, or a `role` on an
  outside item;
- has a `ref` on an item that is not from a reference, or a reference item has no `ref` or a `ref`
  that names no reference in the packet;
- has only one of `start` and `end`, or one that is not an integer;
- has a `text` that is not a string, or has neither offsets nor a non-blank `text`;
- is external and lacks a non-blank `url`, `retrieved` or `text`, or is knowledge and lacks a
  non-blank `text`;
- has the same role as another document or reference item of the candidate.

A member of the candidate itself whose value is null counts as absent. Inside an evidence item, a
null member is invalid.

After step 8, a candidate with a value item takes the **checked path**. A candidate with no value
item takes the **outside path**. On the checked path, outside items change nothing, and the receipt
does not list them.

### 3.1 The checked path

The value item's **text** is the document, or its reference. The checks read that text.

| Step | Code | Rejects when |
|---:|---|---|
| 9 | `SPAN_INVALID` | The value item's span, or `search_region`, is not a valid span (§2.2). |
| 9a | `QUOTE_NOT_FOUND` | The value item is a quote, and it does not occur in the text (§4.6). |
| 10 | `VALUE_NOT_IN_EVIDENCE` | No number token (§4.1) in the span equals `value`, by its value, its scaled value or a derived value (§4.6), and no part is missing (below). For `string` fields: the whitespace-normalised value is not a substring of the whitespace-normalised span text. |
| 11 | `UNIT_NOT_IN_EVIDENCE` | The field has a unit, and no matching number token in the span has that unit at its location (§4.3). |

`search_region` limits the search for a quote and for re-anchoring in the document. It does not
apply to a reference.

**A part is missing** when no item supports a part that the value needs. Step 10 then does not
reject. The candidate continues at the first number token in the span for which one of these
holds, and the decision lists the part in `missing`:

- `sign`: the candidate has no sign item, and `value` equals the negative of a value of the token
  that step 10 tried.
- `scale`: the candidate has no scale item, the token has no scaled value, and `value` equals the
  token's value, with any sign applied, times 10^3, 10^5, 10^6, 10^7, 10^9 or 10^12.
- `sign` and `scale`: neither item is there, and `value` equals the negative of the token's value
  times one of those powers of ten.

At a token, the sign alone is tried first, then the scale alone, then both.

Step 11 does not reject at a matching token where **no unit form is next to the token**: no
prefix of a unit in the table (§4.3) ends at the token's start (whitespace between them allowed),
and no suffix of one starts within `policy.unit_window` code points after the token without
crossing a sentence end. A per-unit counts as a form here, so "75 mg/m2" still rejects a value in
mg. With a unit item, the item then supplies the unit, and it is checked at the value (§4.6).
Without one, the decision lists `unit` in `missing`. A missing part adds the flag
`PART_MISSING`, so the outcome is at best `needs_verification`.

**Re-anchoring (steps 10–11).** When step 10 or 11 fails, `policy.reanchor` is true, the value item
has offsets and a non-blank `text`, the implementation finds every occurrence of `text` inside
`search_region`, or in the whole reference (whitespace runs in the quote match any whitespace run
in the text). If **exactly one** occurrence other than the cited span passes steps 10 and 11
without a missing part, that occurrence becomes the evidence, the decision records code
`EVIDENCE_REANCHORED`, and checking continues. Otherwise the original failure stands, and a part
can still be missing at the cited span.

The value is at its supporting number token, or at the start of the evidence span for a `string`
field. The role items are then checked at the value (§4.6).

### 3.2 The outside path

On the outside path, the candidate's support is its outside items. groundgate cannot check them,
and `policy.sources` decides (§2.4).

1. An external item **holds the value** when its `text`, read as a text of its own with the whole
   text as the span, passes steps 10 and 11 without a missing part. A knowledge item always holds
   the value.
2. When no item holds the value, the candidate is rejected with `VALUE_NOT_IN_EVIDENCE`.
3. Each item that holds the value gets an **action**. An external item gets `admit` when its URL
   matches an entry of `external.allow`, and `external.other` when not. A knowledge item gets
   `knowledge`.
4. The **deciding item** is the first item, in list order, with the best action: `admit`, then
   `review`, then `reject`, and an external item before a knowledge item at the same action.
5. With `reject`, the candidate is rejected with `SOURCE_REJECTED`. With `review`, the decision
   gets the flag `EVIDENCE_QUOTED` for an external deciding item, or `EVIDENCE_STATED` for a
   knowledge item. With `admit`, it records `ADMITTED_BY_POLICY`.

When the deciding item is external, the flags `QUALIFIED_VALUE`, `SCALE_WORD` and
`KEY_NOT_AT_VALUE` read its text as the text. When it is knowledge, they do not apply.
`NON_VERBATIM_EVIDENCE` and the role flags do not apply on the outside path.

### 3.3 Flags

A candidate that passes every step is then **flagged**. Each flag adds its code; any flag makes the
outcome `needs_verification`, no flag makes it `admitted`. A candidate **passed** when it was not
rejected by steps 1–11 or on the outside path.

| Code | Flags when |
|---|---|
| `NON_VERBATIM_EVIDENCE` | The value item has offsets and a `text` that differs from the span's text after whitespace normalisation and joining of line-break hyphenation (§4.4). |
| `QUALIFIED_VALUE` | A qualifier (§4.2) applies to the value in the text and its comparator differs from the field's `comparator`. |
| `SCALE_WORD` | A scale word (§4.1) follows the value, and the candidate's `value` is the number as written, not its scaled value. |
| `PART_MISSING` | The decision lists a part in `missing` (§3.1). |
| `SIGN_CITATION_INVALID` | The sign item fails its check (§4.6). |
| `SCALE_CITATION_INVALID` | The scale item fails its check. |
| `UNIT_CITATION_INVALID` | The unit item fails its check. |
| `FIELD_CITATION_INVALID` | The field item fails its check. |
| `KEY_NOT_AT_VALUE` | The field has `keys`, and the candidate's `key` is not a key at the value (§4.5), and a passing key item does not put it there. |
| `KEY_CITATION_INVALID` | The key item fails its check. |
| `EVIDENCE_QUOTED` | On the outside path, the deciding item is external, with the action `review`. |
| `EVIDENCE_STATED` | On the outside path, the deciding item is knowledge, with the action `review`. |
| `LOW_CONFIDENCE` | `policy.min_confidence` is set and `confidence` is below it. |
| `CONFLICTING_CANDIDATES` | Another candidate for the same non-`multiple` field, and on a keyed field the same `key`, also passed with a different canonical value. Set on every such candidate. |
| `MODEL_DOUBT` | An applying judgment doubts the value (step 12). |

`EVIDENCE_REANCHORED`, `VALUE_DERIVED`, `KEY_CITED`, `ADMITTED_BY_POLICY` and `MODEL_CLEARED` are
informational: they never change the outcome. `VALUE_DERIVED` says that the value is a derived
value (§4.6), not the number as written or its scaled value. A passing role item never removes a
flag other than `KEY_NOT_AT_VALUE`, so it never admits a candidate that another check flags.

When the field has `keys`, the decision lists `key` in `missing` when it gets `KEY_NOT_AT_VALUE`
and the candidate has no key item. This adds no `PART_MISSING`, because `KEY_NOT_AT_VALUE` is
already a flag.

**Recorded judgments (step 12).** After the flags, each applying judgment (§2.6) acts on its
candidate. A judgment never overturns a rejection, and never admits a candidate that has another
flag.

- `key`, on a candidate flagged `KEY_NOT_AT_VALUE`, with `p` at or above
  `clear.KEY_NOT_AT_VALUE`: when `answer` is the candidate's `key`, the flag is removed and the
  decision records `MODEL_CLEARED`; otherwise the decision gets `MODEL_DOUBT` and the flag stays.
  On a candidate whose key item removed that flag (`KEY_CITED`, §4.6), a `key` judgment at that
  probability with another `answer` adds `MODEL_DOUBT`. Any other `key` judgment changes nothing,
  and the receipt still lists it.
- `field_match`, with `p` below `doubt.field_match`: the decision gets `MODEL_DOUBT`.

The outcome then follows the flags that are left, as above. When `MODEL_CLEARED` removes
`KEY_NOT_AT_VALUE`, `key` stays in `missing`.

**Coverage.** For every `required` field with no candidate that is `admitted` or
`needs_verification`, the receipt lists `{"field": <name>, "code": "REQUIRED_FIELD_MISSING"}`.
Coverage is per field, not per key.

## 4. Text rules

### 4.1 Numbers

In the rules that make a value, a digit, and `\d`, is an ASCII digit, `0` to `9`. Other digits,
such as the Devanagari `२`, are not digits there, so `२०००` is not a number token and a candidate
value written in them is invalid. They wait for a locale input (#60). In the rules that only stop
a reading or add a flag (the per-unit check of §4.3, the range checks of §4.2 and the join before
a code in §4.2), `\d` is any Unicode decimal digit (general category Nd), so a number in other
digits can block a value but never make one. A **letter or number** is a character of Unicode
general category L or N.

A **number token** is a maximal match of `[-−]?\d[\d,]*(\.\d+)?` that is not preceded by a letter
or number, `.` or `,`, with one trailing `,` dropped. The match is no token when a number
character (general category N) other than `0` to `9` follows it, directly or after one `.` or `,`,
so ASCII digits next to other digits, as in `2,०००`, are no token. A leading `-`
or `−` (U+2212) counts only when it is not preceded by a letter or number. The token has a value when its digits are either
ungrouped (`\d+`), grouped in threes after the first group (`\d{1,3}(,\d{3})+`), or grouped the
Indian way, the last three digits and then pairs (`\d{1,2}(,\d{2})*,\d{3}`, so `2,00,000` is
200000 and `1,00,00,000` is 10000000); otherwise it has **no** value (`252,0000` never equals
252000 or 2520000, and `1,23,456,789` mixes the two groupings). The value is the digits without
the commas, so a string valid under both groupings, such as `25,000`, has one value. When tokens are read inside a span, a
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

A qualifier applies when it appears between the value and the nearest of: the previous number
token, the start of the sentence, or 40 code points before the value (qualifiers *before*); or
between the value and the nearest of the next number token, the end of the sentence, or 40 code
points after it (qualifiers *after*). Sentences end at `.` or `;` followed by whitespace (a line
break counts), at `•`, or at a blank line (two line breaks with only spaces, tabs or carriage
returns between them). For the qualifier window only, a `.` that ends a listed abbreviation, as a
whole word, does not end a sentence when the first character after the whitespace is a lowercase
letter, a digit, `$`, `€`, `£` or `₹`, and the whitespace holds no blank line. Two of them also
join before any other character, when the whitespace holds no blank line: `u.s.` always, and `no.`
or `nos.` when the next word holds a digit or starts with two uppercase letters A to Z. So for
qualifiers "up to Rs. 50,000", "from 6 p.m. to 8 p.m.", "in the U.S. Tax Court" and "Docket No.
DEA-1086" are one sentence each, and "No. The fee" and "2 lb. (Heart failure" are two each. A wider qualifier window can only add a flag. Key scope (§4.5)
and the unit search (§4.3) still end the sentence at every such dot, because there a join would let
a key or unit of one sentence reach a value in the next. The abbreviations, case-insensitive: a.m.,
p.m., approx., ca., cf., e.g., i.e., etc., vs., viz., no., nos., p., pp., para., fig., figs., vol.,
rs., u.s., u.k., dr., mr., mrs., ms., jr., sr., st., inc., co., corp., ltd., est., min., max., hr.,
hrs., mo., mos., yr., yrs., wk., wks., wt., oz., lb. and lbs. Matching is case-insensitive on whole
words. `from` is deliberately absent: "from 7 to 8" is already a range through its connector, and
"up from $236,000" is not a qualifier.

| Comparator | Before the value | After the value |
|---|---|---|
| `approx` | approximately, approx, about, around, nearly, roughly, generally, ~, ≈ | |
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
stands before `from` in the same phrase, the second number is the new value and is not a range
end. The change word and `from` are in the same phrase when one of these is true:

- only whitespace stands between them, as in "increased from";
- at most six words stand between them, separated only by whitespace, and the first of them is
  a determiner, or `in`, `of` or `to` followed by a determiner, as in "reducing the annual fee
  from" or "an increase in the late fee from". The determiners are the, a, an, its, their, this,
  that, these and those. Every other word between them is made of letters, with `-`, `'` or `’`
  allowed between two letters, and is not one of these: about, above, across, after, among, at,
  before, below, between, by, during, for, from, in, into, on, over, per, since, through, to,
  under, until, with, within, range, ranges, ranged, ranging, vary, varies, varied, varying.

So a digit, punctuation, a preposition or a range word between them ends the phrase, and so
does a missing determiner: in "increased body weight from 20 to 40 kg", `increased` describes
the weight, and 40 stays a range end.

The change words are increase, increases, increased, increasing, decrease, decreases, decreased,
decreasing, raise, raises, raised, raising, reduce, reduces, reduced, reducing, reduction,
reductions, lowers, lowered, lowering, rise, rises, rose, risen, rising, fall, falls, fell,
fallen, falling, drop, drops, dropped, dropping, grow, grows, grew, grown, growing, change,
changes, changed, changing, decline, declines, declined, declining, adjust, adjusts, adjusted,
adjusting, adjustment, adjustments, revise, revises, revised, revising, revision and revisions.
`lower` is not one: it is also an adjective, as in "lower doses from 2 to 4 mg". The first number
keeps its range reading: it is the old value, and a field that takes it should be looked at. So
in "increased from $70,000 to $72,000", $72,000 is unqualified and $70,000 is a range. "run from
7 to 8 hours" has no change word, so both numbers stay a range.

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
sentence, except in a table sentence (below). When the sentence mentions none, they are the key
of the nearest mention that ends at or before the value's start, or no key when there is no such
mention or when a label line lies wholly between the end of that mention and the start of the
value's sentence. The candidate's `key` must be one of them.

A **label line** is a line with a blank line (§4.2) or the start of the text before it and a
blank line after it. It holds at most 12 words (runs of non-whitespace) and no `.` or `;`
followed by whitespace, where its own line break counts, so it does not end with `.` or `;`. Such a line names what follows in its own words,
such as "Treatment of DVT and PE:" or "Adults", and a short form of a condition is not a key
mention. So the key of an earlier heading does not reach past it, and a value under it goes to
review.

There is no other heading detection. A heading kept as a line of text is a mention like any
other, so in "2.2 Heart Failure\n\nThe starting dose is 5 mg", 5 mg is at heart failure, and so
is a value in a later sentence under that heading, until another key is mentioned or a label line
comes. A sentence that mentions
two conditions puts its values at both.

Rows of a flattened table with no sentence end between them are one sentence. A **table
sentence** is a sentence that holds 3 or more line breaks and mentions 2 or more keys of the
field. In a table sentence, the keys at a value are the keys mentioned on the value's own line
(from the line break before it, or the start of the sentence, to the line break after it, or the
end of the sentence), and no key when that line mentions none. So a table with one row on each
line keeps its row keys, and a table flattened to one cell on each line sends its keyed values to
review. The nearest earlier mention does not apply inside a table sentence.

A key item (§4.6) can put the key at the value in a table. This is the **column rule**. It
applies when the keys at the value are none, the candidate has a passing field item at the row
(§4.6), and a passing key item. Let the **header** be the longest run of key mentions of the field
that holds the key item's mention, where only whitespace stands between two mentions of the run.
The key item's mention is the n-th of the header. The column rule puts the key at the value when
all of these hold:

1. The header ends before the field item starts.
2. No key mention of the field lies between the end of the header and the start of the field item.
3. Between the end of the field item and the value, the **cells** are the number tokens and the
   lone dashes (`-`, `–` or `—` with whitespace or a line end on both sides). The value's token is
   the n-th cell from the field item.

So a cell that shows a dash for zero still counts, and a second header between the two moves the
value out of the rule.

### 4.6 Evidence items

**Finding an item.** An item with offsets is at its span, which must be valid in its text. An item
without offsets is a quote. Its **occurrences** are the matches of its `text` in its text, where
each whitespace run in the quote matches any whitespace run.

- For the value item, the occurrences are those inside `search_region` (document only). The first
  occurrence where steps 10 and 11 pass without a missing part is the evidence. When there is no
  such occurrence, the evidence is the first occurrence, and steps 10 and 11 run there. When there
  is no occurrence, step 9a rejects.
- For a role item, the occurrence is the one that holds the value's token; else the last one that
  ends at or before the value; else the first one after the value.

A role item **fails** its check when it is not found, when its span is not valid, when its `text`
is not verbatim-equal to the span's text (as `NON_VERBATIM_EVIDENCE` compares them), or when its
`source` and `ref` differ from those of the value item. On a `string` field, every role item other
than a key or field item fails. Otherwise it passes when its role's check holds:

| Role | Passes when |
|---|---|
| `sign` | The item holds **brackets around the value**: a `(` before the token with only whitespace and prefixes of the field's unit between them, and a `)` after it with only whitespace between them. Or it holds a **loss word** (`loss`, `losses`, `deficit`, `deficits`), ends at or before the token in the value's sentence (§4.5), and from the start of the item to the token there is no number token, no line break, no tab and no **gain word** (`income`, `gain`, `gains`, `profit`, `profits`, `earnings`). Each word is matched whole and case-insensitively. |
| `scale` | The item holds a scale word (§4.1), also with a final `s` (`thousands`), ends at or before the token, and no other scale word lies between its end and the token. |
| `unit` | The item holds a prefix or suffix of the field's unit as a whole (§4.3), ends at or before the token, and no unit form is next to the token (§3.1). |
| `field` | The field has `aliases`, the item holds a mention of one of them (matched as key mentions are, §4.5), and the item ends at or before the token. Then either no letter (general category L) lies between the item's end and the token (the item is at the **row**), or the item is in the value's sentence with no number token between its end and the token. |
| `key` | The item holds a key mention of the candidate's `key`. |

The scale and the sign of a token are its **parts**. A token is **negative** when the candidate
has a sign item, or when brackets enclose it in the text, as the sign check reads them. The token's **derived values**
are its value, and its scaled value if it has one. When the candidate has a scale item whose text
holds a scale word, a token with no scaled value also has its value times the first such word's
factor. When the token is negative, each of these also has its negative (minus its absolute
value). A failing sign or scale item still gives its part: the decision then has the item's
flag.

A field item without `aliases` is not checked: it changes nothing. A key item that passes puts its
key at the value only by the column rule (§4.5). The decision records `KEY_CITED` when that removed
`KEY_NOT_AT_VALUE`. A recorded `key` judgment that applies, at or above `clear.KEY_NOT_AT_VALUE`,
and names another key adds `MODEL_DOUBT` to a decision with `KEY_CITED`.

## 5. Receipt

```json
{"groundgate": "0.5",
 "document": {"id": null, "sha256": "sha256:...", "source": null},
 "references": [],
 "schema_sha256": "sha256:...", "policy_sha256": "sha256:...",
 "decisions": [{"candidate_id": "c1", "candidate_sha256": "sha256:...", "field": "...",
                "key": null, "outcome": "admitted", "codes": [], "value": "2000", "unit": "mg",
                "source": "document", "ref": null, "url": null,
                "evidence": {"start": 120, "end": 128}, "parts": [], "missing": []}],
 "coverage": [],
 "judgments": [],
 "summary": {"admitted": 1, "needs_verification": 0, "rejected": 0},
 "receipt_sha256": "sha256:..."}
```

`document.source` is the document source, or null. `references` lists each reference as
`{"id", "sha256", "source"}`, sorted by `id`.

Decisions are sorted by `candidate_sha256`, then by input position. `codes` lists the rejecting
code, or the flag codes in the order of the table in §3.3, followed by `EVIDENCE_REANCHORED`,
`VALUE_DERIVED`, `KEY_CITED`, `ADMITTED_BY_POLICY` and then `MODEL_CLEARED` when they apply.
`value` is the canonical value and `unit` the candidate's unit, each `null` when the candidate does
not provide a parseable one. `key` is the candidate's `key` when its field has `keys` and the key
is a string, otherwise `null`.

- `source` is the kind of the item that the decision rests on: the value item's on the checked
  path, the deciding item's on the outside path, otherwise `null`. `ref` is the value item's `ref`
  for a reference, and `url` the deciding item's URL for an external item, otherwise `null`.
- `evidence` is the value span that the decision rests on: the re-anchored span when re-anchoring
  applied, the found occurrence for a quote, otherwise the cited span if it is valid, otherwise
  `null`. It is in the value item's text.
- `parts` lists each role item of a candidate that reached the role checks, as
  `{"role", "start", "end", "passed"}`, in the role order `sign`, `scale`, `unit`, `field`, `key`.
  `start` and `end` are the item's span, or null when it was not found. A field item without
  `aliases` is listed with `passed` false.
- `missing` lists the missing parts in the order `sign`, `scale`, `unit`, `key`.

Coverage is sorted by field name. `judgments` lists each judgment that applied, as
`{"candidate_sha256", "question", "answer", "p"}` (`answer` only for `key`), sorted by
`candidate_sha256`, then by input position of the candidate, then by question; the judge is in the
policy. `receipt_sha256` is the digest of kind `receipt` over the receipt without its
`receipt_sha256` key.

## 6. Canonical JSON and digests

Canonical JSON is RFC 8785 (JCS): keys sorted by UTF-16 code units, no insignificant whitespace,
strings escaped as ECMAScript `JSON.stringify` does, numbers serialised as ECMAScript
`Number.prototype.toString`. NaN and infinities are not permitted. Integers outside
[-(2^53-1), 2^53-1] are not permitted (they are not exactly representable).

`digest(kind, obj) = "sha256:" + hex(SHA-256("groundgate/0.5:" + kind + "\0" + JCS(obj)))`, where
the prefix is ASCII and `JCS(obj)` is UTF-8.

## 7. Non-goals for v0.5

Semantic correctness (whether the sentence describes the field) by groundgate itself: a recorded
`field_match` judgment can only add doubt, and a field item checks only the field's own aliases.
Calling a model, fetching a URL, dates, arrays of records, arithmetic over several numbers, the
subject of the document (groundgate assumes one subject per document), and PDF geometry (page and
bounding box) as evidence. Adapters may convert richer evidence into spans.
