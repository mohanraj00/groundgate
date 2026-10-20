# groundgate specification v0.10 (draft)

Status: draft, not released. Version string: `groundgate/0.10`. Spec 0.9 is the spec of
groundgate 0.9.0, from commit 23095bf. Spec 0.8 is in the `v0.8.0` tag, spec 0.7 in the
`v0.7.0` tag, spec 0.6 in the `v0.6.0` tag, spec 0.5 in the `v0.5.0` tag, spec 0.4 in the
`v0.4.0` tag, spec 0.3 in the `v0.3.0` tag, spec 0.2 in the `v0.2.0` tag, and spec 0.1 in the
`v0.1.0` tag. Any change to how
a candidate is decided is a new version with a new version string. An implementation conforms if
it produces the outcome, codes and missing parts of every decision, the parts and the evidence
units where a vector gives them, the coverage findings, and the relation results where a vector
gives them, in every vector
under `conformance/vectors/`, and refuses every packet under `conformance/invalid/` with no
receipt.

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
the receipt says which. The app can also state relations between fields, such as a total and its
parts, and a relation that fails sends its values to a person (§3.4). groundgate does **not**
judge whether the text means what the field claims.
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

A packet may also carry **packs**: the vocabulary packs and kind packs that the schema names
(§2.3, §4.8, §4.9), and the vocabulary packs that those kind packs need, as pack objects. Each
given pack must pass the checks of §4.8 and §4.9, or the packet is invalid.

### 2.2 Offsets

A **span** is `{"start": s, "end": e}`: zero-based, half-open **UTF-8 byte** offsets into the
document, or into a reference for an item from that reference. A span is valid when `0 <= s < e <= len(bytes)` and both `s` and `e` fall on character
boundaries. Heuristic windows in §4 are measured in Unicode code points.

### 2.3 Schema

```text
{"fields": {"<name>": {
  "type": "number" | "integer" | "string",
  "unit": "<unit code>" | null,
  "comparator": "eq" | "gt" | "ge" | "lt" | "le" | "approx" | "range",
  "minimum": "<decimal>" | null,
  "maximum": "<decimal>" | null,
  "required": false,
  "multiple": false,
  "keys": ["<key>"] | null,
  "aliases": ["<words>"] | null,
  "description": "<text>",
  "template": "<pack id>/<field name>"
}},
 "units": {"<unit code>": {"prefix": ["<surface>"], "suffix": ["<surface>"]}},
 "relations": [{"id": "<name>", "total": "<field>",
                "parts": [{"field": "<field>", "factor": "<decimal>"}],
                "tolerance": "<decimal>"}],
 "packs": [{"id": "<pack id>", "version": "<version>", "sha256": "sha256:..."}]}
```

Defaults: `type` `"number"`, `unit` null, `comparator` `"eq"`, bounds null, `required` false, `multiple` false,
`keys` null, `aliases` null.

`description` is optional; when present, it must be a non-blank string, with no length limit.
It has no effect on a decision, but is part of the schema digest.

`keys` makes a field **keyed**: its values belong to one of several conditions, such as the
indications of a drug, and each candidate names its condition. The keys are written in the
document's words (§4.5). `keys` is null or a non-empty list of strings, no key is blank, and no
two keys are equal after whitespace normalisation (§4.4) and the fold of each letter (§4);
otherwise the packet is invalid.
`aliases` are the field's names in the document's words, such as "loss from operations" for an
operating income field. A field item (§4.6) is checked against them. They follow the same rules as
`keys`: null or a non-empty list of strings, none blank, no two equal after whitespace
normalisation (§4.4) and the fold of each letter (§4).
`units` extends and overrides the built-in table (§4.3). Each unit is an object with only
`prefix` and `suffix`, each a list of non-empty strings; an absent list is empty.
`packs` names each vocabulary pack and kind pack that the packet reads besides the base pack
(§4.8, §4.9), by `id` and `version`. The schema does not have to name a vocabulary pack that a
named kind pack needs. An entry can also give `sha256`: then the given pack must have that digest. This
pin is optional. The schema never names the base pack, because it always applies. The schema
names a built-in pack such as `finance` (§4.8) the same way, but the packet never gives it: the
implementation holds it. The packet is
invalid when an entry has other keys, an entry names the base pack, two entries name one id
differently, a named pack is not given or built in, a named built-in pack has a version that is
not built in, a given pack is neither named nor needed, or a pin differs. The pack
table of §4.3 and the word lists of §4 are then the union of §4.8, and `units` still extends
and overrides that table.
`template` (spec 0.10, #335) takes a field template of a kind pack (§4.9). It is
`<pack id>/<field name>`, and the schema must name that kind pack in `packs`. The template fills
each of its members that the field does not give, before the defaults. A member that the field
gives wins, also `aliases`: the template does not add to the field's aliases. The packet is
invalid (L10) when `template` is not a string with a `/`, its pack is not a kind pack that the
schema names, the pack has no template of that name, or the field and the template both give a
`type` or both give a `unit` and the two differ. Null is a unit here, so a field with `"unit":
null` and a template in USD is invalid.
`schema_sha256` is the digest of kind `schema` over the schema object **after** templates and
defaults are filled in. Each field that takes a template keeps its `template` member. With packs,
the schema object holds `packs` as `{"id", "version", "sha256"}`, sorted by `id`, with the digest
of each given pack, also of each pack that a kind pack needs. So a changed pack changes
`schema_sha256`. With no pack, the schema object holds no `packs`.

`relations` (spec 0.10, #321) is a list of relations between fields, which step 13 checks (§3.4).
A relation is an object with only these members:

- `id`: a non-blank string. No two relations have the same `id`.
- `total`: the name of a field in the schema.
- `parts`: a non-empty list of objects with only `field`, the name of a field in the schema, and
  `factor`. `factor` is a decimal string or an integer that reads as a number (§4.1), as a bound
  is, and it is not zero. The default is `"1"`. A factor of `"-1"` subtracts the part. A factor
  such as `"0.001"` changes the unit of the part, for example from mg to g.
- `tolerance`: a decimal string or an integer that reads as a number, not negative, in the unit of
  the total. The default is `"0"`.

The packet is also invalid when `relations` is not a list, a relation breaks the rules above, or:

- a field of the relation has the type `string`, or `multiple` true;
- the total is also a part, or two parts name the same field;
- the field of a part has a `unit` other than the unit of the total's field, and the part gives no
  `factor`. Null counts as a unit here, so a part without a unit under a total in USD needs a
  factor;
- some fields of the relation have `keys`, and others do not.

After defaults, each part has its `factor` and each relation its `tolerance`. A schema with no
relations, or with an empty list, has no `relations` member after defaults, so its digest does not
change.

The packet is invalid when the schema is not an object with a `fields` object, has keys other
than `fields`, `units`, `relations` and `packs`, or a field is not an object, has other keys, has a `type` or
`comparator` not listed above, a `unit` that is not a string or null, a bound that is not a
decimal string or an integer that reads as a number (§4.1, so `"1,000"` is accepted), or a
`required` or `multiple` that is not a boolean.

### 2.4 Policy

```json
{"min_confidence": null, "unit_window": 24, "reanchor": true, "judge": null,
 "sources": {"external": {"allow": [], "other": "review"}, "knowledge": "review"}}
```

`sources` says what happens to a candidate that only evidence from outside the pinned texts
supports (§3.2). groundgate cannot check such evidence, so the app decides:

- `external.allow` is a list of non-blank strings. An external item whose URL matches an entry is
  admitted. `"*"` matches every URL. `"document-domain"` matches a URL whose host equals the host
  of the document source, and nothing when the packet has no document source. Any other entry
  matches a URL that starts with it, so write the entry with its final `/`.
- `external.other` is `review` or `reject`: what happens to an external item that matches no entry.
- `knowledge` is `admit`, `review` or `reject`.

The **host** of a URL is the text after its first `://` up to the first `/`, `\`, `?` or `#`, after the
last `@`, without a `:` and port, lower-cased. A host that starts with `[` (an IPv6 literal)
ends at its `]` and keeps its colons. A URL without `://` has no host, and a document source
without `://` has no host either, so `"document-domain"` then matches nothing.

`min_confidence` is null or a number in [0, 1], `unit_window` a non-negative integer, and
`reanchor` a boolean. Defaults fill in each member of the policy and of `sources` that is absent;
other keys or values make the packet invalid.

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
| `search_region` | no | Span of the document within which quotes are found and re-anchoring may look (§3.1, §4.6). Default: the whole document. |
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

`candidate.schema.json` in the package (`candidate_schema()` in the reference implementation) is
a JSON Schema for one candidate. Step 1 is the definition: the schema does not check that a `ref`
names a reference in the packet, that two document or reference items other than field items have
different roles, that a candidate cites at most 8 field items, or that an integer has no fraction
(`2.0`).

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
| 4 | `TYPE_INVALID` | `value` does not parse as the field type (§4.1). For a `string` field: `value` is not a string, or is blank after whitespace normalisation (§4.4). |
| 5 | `RANGE_INVALID` | `value` is below `minimum` or above `maximum`. |
| 6 | `UNIT_INVALID` | The candidate's `unit` differs from the field's `unit` (both absent is a match). |
| 7 | `KEY_INVALID` | The field has `keys`, and the candidate's `key` is absent or not exactly one of them. |
| 8 | `NO_EVIDENCE` | The candidate has no value item and no outside item. |

Step 1 rejects when the candidate is not an object, `field` is not a string, `value` is missing or
not a string/integer, `unit` or `key` is not a string, `confidence` is not a number in [0, 1],
`search_region` is present but not an object with integer `start` and `end`, or `evidence` is
present but not an object or a list of objects. It also rejects when an evidence item:

- has a `source` other than the four kinds, or a `role` other than the six;
- is an outside item with a `role`, `start` or `end`, or a document or reference item with a `url`
  or `retrieved`;
- has a `ref` on an item that is not from a reference, or a reference item has no `ref` or a `ref`
  that names no reference in the packet;
- has only one of `start` and `end`, or one that is not an integer;
- has a `text` that is not a string, or has neither offsets nor a non-blank `text`;
- is external and lacks a non-blank `url`, `retrieved` or `text`, or is knowledge and lacks a
  non-blank `text`;
- has the same role as another document or reference item of the candidate, and that role is not
  `field`. A candidate can cite several field items, such as a row label and a column header
  (#300), but not more than 8. A ninth field item makes the candidate invalid, so that the work
  of one candidate stays bounded.

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
| 10 | `VALUE_NOT_IN_EVIDENCE` | No number token (§4.1) in the span equals `value` by one of its derived values (§4.6), and no part is missing (below). For `string` fields: the whitespace-normalised value is not a substring of the whitespace-normalised span text. |
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
- `scale`, from a heading: the candidate has no scale item, the token has no scaled value, the
  field's unit is not `%`, a heading scale reaches the token (§4.1), and the value matches the
  token without a scale. This is added to the parts above.

At a token, the sign alone is tried first, then the scale alone, then both.

Step 11 does not reject at a matching token where **no unit form is next to the token**: no
prefix of a unit in the table (§4.3) ends at the token's start (whitespace between them allowed),
and no suffix of one starts within `policy.unit_window` code points after the token without
crossing a sentence end. A per-unit counts as a form here, so "75 mg/m2" still rejects a value in
mg. With a unit item, the item then supplies the unit, and it is checked at the value (§4.6).
Without one, the decision lists `unit` in `missing`, unless the field check passes (§4.6) and
a form of the field's unit is at a unit place of the value, as a unit item there would
be: then the unit is not missing (#249). A heading unit (§4.3) makes the unit present only
through a unit item that holds it. A missing part adds the flag `PART_MISSING`, so the
outcome is at best `needs_verification`. At a token with a heading conflict (§4.3), no unit
form, unit place or unit item makes the unit present (spec 0.10, #365).

**Re-anchoring (steps 10–11).** When steps 10 and 11 do not pass at the cited span without a
missing part, `policy.reanchor` is true, and the value item has offsets and a non-blank `text`, the implementation finds every occurrence of `text` inside
`search_region`, or in the whole reference (whitespace runs in the quote match any whitespace run
in the text). If **exactly one** occurrence other than the cited span passes steps 10 and 11
without a missing part, that occurrence becomes the evidence, the decision records code
`EVIDENCE_REANCHORED`, and checking continues. Otherwise steps 10 and 11 run at the cited span,
where a part can be missing. So a cited span that passes only with a missing part still moves to
the one other occurrence that passes without one. At the cited span, a unit form at a unit place
can make the unit present (step 11); at another occurrence it does not, as in the choice of a
quote occurrence (§4.6, #249).

The value is at its supporting number token. For a `string` field, it is at the first occurrence
of the value in the evidence span, where a whitespace run in the value matches any whitespace run
in the text (#140). The role items are then checked at the value (§4.6).

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
`NON_VERBATIM_EVIDENCE`, `VALUE_DERIVED` and the role flags do not apply on the outside path.

### 3.3 Flags

A candidate that passes every step is then **flagged**. Each flag adds its code; any flag makes the
outcome `needs_verification`, no flag makes it `admitted`. A candidate **passed** when it was not
rejected by steps 1–11 or on the outside path.

| Code | Flags when |
|---|---|
| `NON_VERBATIM_EVIDENCE` | The value item has offsets and a `text` that differs from the span's text after whitespace normalisation and joining of line-break hyphenation (§4.4). |
| `QUALIFIED_VALUE` | A qualifier (§4.2) applies to the value in the text and its comparator differs from the field's `comparator`. Not on a `string` field. |
| `SCALE_WORD` | A scale word or a scale suffix (§4.1) follows the value, and the candidate's `value` is the number as written, not its scaled value. Not on a `string` field. |
| `PART_MISSING` | The decision lists a part in `missing` (§3.1). |
| `SIGN_CITATION_INVALID` | The sign item fails its check (§4.6). |
| `SCALE_CITATION_INVALID` | The scale item fails its check. |
| `UNIT_CITATION_INVALID` | The unit item fails its check. |
| `FIELD_CITATION_INVALID` | The field has `aliases`, the candidate has field items, and none of them passes its check (§4.6). |
| `KEY_NOT_AT_VALUE` | The field has `keys`, and the candidate's `key` is not a key at the value (§4.5), and a passing key item does not put it there. |
| `KEY_CITATION_INVALID` | The key item fails its check. |
| `EVIDENCE_QUOTED` | On the outside path, the deciding item is external, with the action `review`. |
| `EVIDENCE_STATED` | On the outside path, the deciding item is knowledge, with the action `review`. |
| `LOW_CONFIDENCE` | `policy.min_confidence` is set and `confidence` is below it. |
| `CONFLICTING_CANDIDATES` | Another candidate for the same non-`multiple` field, and on a keyed field the same `key`, also passed with a different canonical value. Set on every such candidate. |
| `RELATION_FAILED` | A relation that names the candidate's field fails at the candidate's key (step 13, §3.4). |
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
`KEY_NOT_AT_VALUE`, `key` stays in `missing`. Step 13 (§3.4) runs after this step and can add
`RELATION_FAILED`.

**Coverage.** For every `required` field with no candidate that is `admitted` or
`needs_verification`, the receipt lists `{"field": <name>, "code": "REQUIRED_FIELD_MISSING"}`.
Coverage is per field, not per key.

### 3.4 Relations (step 13)

A relation (§2.3) says that the total equals the sum of its parts, each part times its factor. So
it checks a sum, a difference, a scale and a unit change across fields. Step 13 reads only the
values of the candidates that passed. It does not read the text again, and it never rejects.

Each relation is checked once for each **relation key**: null when its fields have no `keys`, and
otherwise each key that every field of the relation lists, compared as exact strings.

1. The relation **applies** at a relation key when each of its fields has at least one candidate
   that passed (§3.3) with that `key`, and the candidates of each field that passed with that key
   have one canonical value. On fields without `keys`, every candidate that passed counts. When
   the relation does not apply, it changes nothing. So a field with no value that passed, or with
   two values (`CONFLICTING_CANDIDATES`), stops the relation at that key.
2. Let T be the value of the total, and P and f the value and the factor of each part. The
   **difference** is T minus the sum of f × P over the parts.
3. The **allowance** is the relation's `tolerance`, plus half of the place of T, plus half of |f|
   times the place of P for each part. The place of a field's value is the smallest place of the
   candidates of that field that passed with the key (below).
4. The relation **holds** when the absolute value of the difference is at most the allowance.
   Otherwise it **fails**: each candidate that passed with the key, of each field of the
   relation, gets the flag `RELATION_FAILED`.

The arithmetic is exact, with no rounding. A field can be in several relations. A candidate gets
the flag once, when one or more of them fail.

The **place** of a candidate's value is one unit of its last written digit. On the checked path,
it is the place of the supporting number token (§3.1): 1 for a token with no `.`, or 10^-d for a
token with d digits after the `.`. When the token's value is not 0, this is multiplied by |value|
divided by |token value|, so a scale that the value takes from a scale word, a scale suffix, a
scale item or a missing scale (§3.1) also scales the place. On the outside path, the place is that
of the last digit of the canonical value. So "$1,250" with a scale item "(in thousands" and the
value 1250000 has the place 1000, "$1.25 billion" with the value 1250000000 has the place
10000000, and a knowledge item with the value 3.3 has the place 0.1. A total and its parts that a
document rounds to thousands can then differ by up to 500 for each value, and the relation still
holds.

A relation that holds admits nothing: it removes no flag and adds no code. A relation that fails
does not show which value is wrong, so all of its values go to review.

## 4. Text rules

**Case (spec 0.10, #356).** A rule of this section that matches case-insensitively compares the
word and the text letter by letter, by the **fold** of each letter. The fold of `ſ` (U+017F) is
`s`. The fold of `ı` (U+0131) and of `İ` (U+0130) is `i`. The fold of the Kelvin sign `K`
(U+212A) is `k`. The fold of each other letter is its Unicode lowercase mapping with no locale,
when that mapping is one code point. Otherwise the fold is the letter itself. Two letters match
when they have the same fold. So `THOUSAND`, `thouſand`, `bİllion` and `mıllıon` are scale words,
and "(ın thousands)" is a heading scale. `µ` (U+00B5) and `μ` (U+03BC) have different folds, and
so do `ς` (U+03C2) and `σ` (U+03C3). A character with no case matches only itself, or as the rule
says, as a whitespace run or a dash does. A match covers as many code points in the text as in
the word.

The rule applies to these words:

- the scale words, their final `s`, and the `in` of a heading scale (§4.1)
- the abbreviations, the qualifiers, the negations, the range connectors, `between` and `and`,
  and each word of a change phrase, `from` included (§4.2)
- the per-units, and the `in`, the scale word, its final `s`, the `of` and the names of a
  currency statement (§4.3)
- keys and aliases (§4.5, §4.6)
- the loss words, the gain words and the negations of a sign item (§4.6)

A form whose cases are listed matches only as listed: the scale suffixes and the currency scales
(§4.1), and the codes of a currency statement (§4.3). The prefixes and suffixes of the unit table
(§4.3) match exactly.

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
number. The `000` of a currency scale (below) is no token, so `£000` and `£'000` are never an
amount of zero (spec 0.10, #313).

A number token with a value that is followed by a **scale word** also has a **scaled value**. The
scale words are `thousand`, `million`, `billion`, `trillion`, `lakh` and `crore`, matched as whole
words, case-insensitively, after at most 2 whitespace code points. The scaled value is the value
times 10^3, 10^6, 10^9, 10^12, 10^5 or 10^7: "$1.25 billion" is 1250000000 and "4 lakh" is
400000. Like a unit, the scale word is read from the document, so it counts even past the end of
the span. A scale word with no number before it ("millions of") has no value. Case-insensitive
here is the rule at the start of §4. It also applies to the final `s` of a heading scale, a scale
item and a currency statement. So `THOUSAND`, `thouſand` (with U+017F), `bİllion` (U+0130) and
`mıllıon` (U+0131) are scale words (spec 0.10, #350, #356).

A **currency sign** is `$`, `€`, `£` or `₹`, the signs that §4.2 also lists. A number token with a
value also has a scaled value when a currency sign stands directly before it and a **scale
suffix** stands directly after it: `k` or `K` (10^3), `m` or `M` (10^6), or `bn`, `Bn` or `BN`
(10^9), with no letter or number directly after the suffix (spec 0.10, #301). So `€70,471m` is
70471000000, `£32.7bn` is 32700000000 and `$250k` is 250000. Nothing can stand between the sign,
the number and the suffix. A bare `m` can be a unit (metres), so `70 m` and `5m`, with no
currency sign, have no scaled value. `£5 m`, with a space before the `m`, and `£ 9m`, with a space
after the sign, have no scaled value either: the rule is strict, and a candidate with the scaled
value of such a number misses its scale (§3.1). `£5mm` has no scaled value, because a letter
follows the `m`.

A **currency scale** is a currency sign directly followed by `k`, `K`, `m`, `M`, `bn`, `Bn`, `BN`,
`'000`, `’000` or `000` (10^3), with no letter or number directly after it, such as `£m`, `$bn`,
`£'000` or `£000` in a column header. After a bare `000`, a `,` or a `.` and then a digit also
stop the form. So `£000s`, `£0001`, `£000,000` and `£000.5` are no currency scale, and `£ 000`,
with a space after the sign, is none either (spec 0.10, #313).

A **heading scale** is `in`, whitespace and a scale word (also with a final `s`) on a line that
holds no tab, such as "(in thousands)". A currency scale on any line, with or without a tab, is
also a heading scale, such as the header row `\t£m\t£m` (spec 0.10). It reaches the lines after it
that hold a tab, not its own line: blank lines
may stand between the heading and the first of them, and the first line after that holds no tab
ends the table. So it reaches a token on such a line. A line with spaces between its cells, as
from a plain-text table, holds no tab, so no heading scale reaches it (#152).

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
words, letter by letter by the rule at the start of §4, so `U.ſ.` is the abbreviation `u.s.`
(#350, #356).
`from` is deliberately absent: "from 7 to 8" is already a range through its connector, and
"up from $236,000" is not a qualifier.

| Comparator | Before the value | After the value |
|---|---|---|
| `approx` | approximately, approx, about, around, nearly, roughly, generally, ~, ≈ | |
| `gt` | more than, greater than, above, over, exceed, exceeds, exceeding, > | |
| `lt` | less than, fewer than, below, under, < | |
| `ge` | at least, minimum of, no less than, ≥ | or more, or greater, or older, or higher, or above |
| `le` | up to, maximum of, at most, no more than, ≤ | or less, or fewer, or younger, or lower, or below |
| `range` | between | the value is followed by `to`, `through`, `thru`, `-` or `–` and then another number token, or is preceded by such a connector and a number token; between a connector and the next number token stand optional whitespace and then at most 4 characters that are not whitespace, such as `$`, so "30 to $45" is a range and "30 to US $ 45" is not; `and` counts as a connector when `between` stands before the first number in the same sentence (§4.5) with only whitespace and at most six words between them, each word a run of letters and combining marks (general categories L and M) of any length that starts with a letter, and each `between` of the sentence is tried, or when `between`, optional whitespace and at most 4 characters that are not whitespace stand directly before the first number; so "between the ages of 18 and 65" and "between $18 and $65" are ranges, and "between the minimum and maximum permitted adult ages 18 and 65" (seven words) is not; one word of up to 12 characters with no digits (a unit or scale word) may stand between the first number and `to`, `through`, `thru` or `and`, so both ends of "30 mg to 45 mg" and "$1 million to $2 million" are a range |

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
within `policy.unit_window` code points, lies wholly inside the token's sentence, and is not a
per-unit. A prefix that starts with a letter or digit does not count when a letter or digit
stands directly before it. A suffix match that starts with an ASCII letter or digit does not count
after another ASCII letter or digit of the text after the token, and one that ends with an ASCII
letter or digit does not count before one. So `Rs` is not at the 500 in "MRs 500", `g` is not at
the 5 in "5 grams", and `mg` is at the 500 in "500mg".
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
as `mg/kg` with the suffix `mg/kg`. A unit code with no prefixes and no suffixes, because it is
not in the table or because the schema gives it empty lists, is at every token (the check is
vacuous).

**Heading units (spec 0.10, #315).** A **heading unit** is a currency header or a currency
statement.

A **currency header** is a currency scale (§4.1) on any line. Its **form** is its currency sign
with the letters directly before it, as `£` in `£m`, `US$` in `US$000` and `HK$` in `HK$'000`.

A **currency statement** is `in`, whitespace, optionally a scale word (also with a final `s`),
whitespace, `of` and whitespace, and then a currency name of the table below, all on one line
that holds no tab. Examples are "presented in Australian dollars" and "(in millions of Canadian
dollars". Each word is matched whole and case-insensitively, and a whitespace run matches any
whitespace run on that line. Each name also matches in the singular. Each code also matches as a name of its row, in
capitals only.

| Code | Currency names | Sign |
|---|---|---|
| `USD` | `US dollars`, `U.S. dollars`, `United States dollars` | `$` |
| `AUD` | `Australian dollars` | `$` |
| `CAD` | `Canadian dollars` | `$` |
| `HKD` | `Hong Kong dollars` | `$` |
| `NZD` | `New Zealand dollars` | `$` |
| `SGD` | `Singapore dollars` | `$` |
| `EUR` | `euros` | `€` |
| `GBP` | `pounds sterling`, `sterling` | `£` |
| `INR` | `Indian rupees` | `₹` |
| `LKR` | `Sri Lankan rupees` | |

A heading unit **reaches** a token as a heading scale does (§4.1).

A heading unit **allows** unit codes. A currency statement allows the code of its name. A currency
header whose form is a lone sign allows the codes of that sign in the table above, and each unit
that has the sign as a prefix in the unit table. A currency header with a longer form allows each
unit that has the form as a prefix in the unit table. It is **unknown** when no unit has that
prefix, as `HK$` is when the schema gives no unit with it. An unknown header allows no code and
is skipped below. A `$` with a letter directly before it is never read as a lone `$`.

The **heading currency** of a token is the field's unit when both of these hold:

1. Each heading unit that reaches the token, other than an unknown header, allows the field's
   unit.
2. A currency statement reaches the token, or a currency header reaches it whose form is a
   prefix of the field's unit in the unit table.

So `$m` under "presented in Australian dollars" gives `AUD`. `$m` alone gives `USD` by its
built-in prefix, and never `CAD`. `$m` under a statement of another currency, or two statements
of two currencies, give no heading currency. groundgate never chooses between them.

**Heading conflict (spec 0.10, #365).** A **currency unit** is a code of the currency table
above, or a unit with a prefix in the unit table that ends with a currency sign (§4.1). A token
has a **heading conflict** when the field's unit is a currency unit, and a heading unit that
reaches the token, other than an unknown header, does not allow the field's unit. When two
heading units that reach a token do not agree, one of them does not allow the field's unit, so
the token has a heading conflict.

At a token with a heading conflict, the field's unit is never present:

- A form of the field's unit next to the token does not put the unit at the token (step 11).
  Step 11 then reads the token as a token with no unit form next to it. A form of another unit
  next to the token still rejects the candidate, as before.
- A form at a unit place of the value does not make the unit present (§3.1, #249).
- A unit item fails its check (§4.6).

So the decision lists `unit` in `missing` and gets `PART_MISSING`, or it gets
`UNIT_CITATION_INVALID` when the candidate has a unit item. The outcome is at best
`needs_verification`. A heading conflict never rejects a candidate.

A heading conflict does not change which occurrence of a quote is the evidence (§4.6), and it
does not change if re-anchoring moves the evidence (§3.1). These choices are made as if no
heading unit reaches the token. Then the heading conflict applies at the evidence. The outside
path (§3.2) does not read the heading conflict.

So under "presented in Australian dollars" and `$m`, a value in `USD` goes to review, and a value
in `AUD` can be admitted. Under "presented in US dollars" and `$m`, a value in `USD` can be
admitted. A value in `%` in that table has no heading conflict, because `%` is not a currency
unit.

### 4.4 Whitespace normalisation

Collapse every whitespace run to one space and trim. For the verbatim comparison only, also delete
`-` followed by a line break and optional whitespace (line-break hyphenation).

A **line break** in this specification is U+000A. A carriage return (U+000D) is whitespace, not a
line break.

### 4.5 Keys

A **key mention** is an occurrence of one of a field's keys in the document: matched
case-insensitively, with each whitespace run in the key matching any whitespace run, each dash
in the key matching any dash, and not preceded or followed by a letter or digit. The **dashes**
are `-` (U+002D), `‐` (U+2010), `‑` (U+2011), `‒` (U+2012) and `–` (U+2013) (spec 0.10, #317).
A dash in the key that stands between two letters (general category L) also matches a dash,
then optional spaces and carriage returns, one line break, and optional spaces and carriage
returns. So "Out–of–pocket" and "out-of-\npocket" are mentions of "out-of-pocket". The minus
sign `−` (U+2212) and the em dash `—` (U+2014) are not dashes here, and each matches only
itself: a minus is the sign of a number (§4.1). A whitespace run in the key never matches a
dash, and a dash never matches a whitespace run, so "out of pocket" is no mention of
"out-of-pocket". A line break inside a word that has no dash in the key does not join it.
Where two mentions overlap and one contains the other, only the longer counts. A mention is in
a sentence (§4.2) when it lies wholly inside it.

The value is at its supporting number token (§3 steps 10–11), or, for a `string` field, at its
first occurrence in the evidence span (§3.1). On the outside path, the evidence span is the deciding
item's whole text. The **keys at the value** are the keys mentioned in the value's
sentence, except in a table sentence (below). When the sentence mentions none, they are the key
of the nearest mention that ends at or before the value's start, or no key when there is no such
mention or when a label line lies wholly between the end of that mention and the start of the
value's sentence. A label line does not stop that key when no page break (`\f`) stands between
the mention and the value, the value's line holds a tab before the value, and each line after
the mention's line, up to and including the value's line, holds at most one number token after
its first tab: a table with one number column under a title such as "As of September 30, 2025"
(#250). The candidate's `key` must be one of them.

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
sentence** is a sentence that mentions 2 or more keys of the field and holds 3 or more
line breaks, or a sentence with a key mention in a separate header before the value.
A separate header line must mention at least 2 distinct keys, and either hold a tab or be made
only of key mentions and whitespace. A run of
separate key-only lines also counts as a header. So does a run of at least two distinct keys
with only whitespace and no key break between them, if any line touched by the run holds a tab.
An optional label before the run or a non-key slot after it does not make that run prose.
A **mixed header block** also counts: at least two key-bearing physical lines that together
mention at least two distinct keys, with a tab on at least one of those lines. At most one blank
line may separate successive key-bearing lines. A line without tabs must contain only key
mentions and whitespace. A tabbed line may have a label or non-key text, but a number token
outside its key mentions ends the block. This recognizes a trailing non-key slot even when it
interrupts the whitespace-only run between keys. This covers short tables with one data row.
In a table sentence, the keys at a value are the keys mentioned on the value's own line
(from the line break before it, or the start of the sentence, to the line break after it, or the
end of the sentence), and no key when that line mentions none. So a table with one row on each
line keeps its row keys, and a table flattened to one cell on each line sends its keyed values to
review. The nearest earlier mention does not apply inside a table sentence.

Two adjacent blank lines are a **key break** (spec 0.9): three line breaks with only spaces,
tabs or carriage returns between them. A key break stops an earlier key mention from reaching
a value by the nearest-mention rule, and stops the column rule from using an earlier header.
A key on the value's own line still applies. A reader can isolate an unaligned numeric-only row
with two blank lines on both sides. One blank line between separate cells keeps the column rule.

A nearest mention on a tabbed line with at least two distinct keys does not act as a prose
heading. Neither does a mention in a header made only of keys and whitespace. Here that header
is a run of key mentions with only whitespace and no key break between them, and only whitespace
on the first line before the run and on the last line after it. A run touching a tabbed line
is also a header when it has a label before its first key or non-key text after its last key.
A mention in a mixed header block cannot act as a prose heading either. A value below such a
header needs the column rule, even after one blank line ends the header's sentence.

A key item (§4.6) can put the key at the value in a table. This is the **column rule**. It
applies when the keys at the value are none, the candidate has a passing field item at the row
(§4.6), and a passing key item. With several such field items, the rules below read the first
one in list order (#300). Let the **header** be the longest run of key mentions of the field
that holds the key item's mention, where only whitespace and no key break stands between two
mentions of the run.
The key item's mention is the n-th of the header. The column rule puts the key at the value when
all of these hold:

1. The header ends before the field item starts. If its first key lies on a line with tabs,
   it starts in that line's first data slot. The slot before the first tab is a data slot when
   it holds exactly one key mention and whitespace, and otherwise is the row label. A first
   slot that holds a key plus other text, or several keys, is ambiguous and stops the rule.
   Only spaces and carriage returns may stand before the key in that first data slot. A leading
   unknown or empty header slot therefore stops the column rule instead of shifting the known keys.
   If any line of the header run holds a tab, all its key mentions must lie on one physical line,
   with exactly one tab between each adjacent pair. An empty slot between keys, several keys in
   one slot, or a mix of tabbed and separate-line header cells stops the rule. A mixed header
   block stops the rule even when non-key text splits its key mentions into separate runs.
   A non-key column after a one-line run does not change the known keys' ordinals.
2. No key mention of the field lies between the end of the header and the start of the field item,
   and no key break lies between the end of the header and the value.
3. No number token lies on the field item's line, after the field item and before the value, with
   no tab between the end of the field item and the start of the token. This stops the rule at a
   footnote marker, such as the `1` in "Sales (1)". It also stops the rule after the first column
   when only spaces stand between the field item and the row's first number token. A tab after
   the field item, as `groundgate read` writes HTML and PDF tables, or cells on their own
   lines, keep the rule.
4. When the field item and value are on the same line, a tab stands between the item's end
   and the value. A row kept as plain text cannot take a column key, including its first number.
   A field followed by cells on separate lines keeps the column rule.
5. Between the end of the field item and the value, the **cells** are the number tokens, the lone
   dashes (`-`, `–` or `—` with whitespace or a line end on both sides in the text), the
   **empty unit cells**, and the **empty tab slots** below. An empty unit cell is a prefix of the
   field's unit with whitespace or a line end on both sides, where the next character after the
   whitespace is not the start of a number token or `(`, and comes before the value. Each
   occurrence counts, also where two overlap, as `a a` twice in `a a a` (spec 0.7). An empty tab
   slot is the text after a tab and before the next tab or line end on that same line, when it
   holds only spaces and carriage returns, or nothing. It counts once, also at the end of a line.
   The text before the first tab is the row label, even when it is empty. A prefix-only slot
   immediately before a number keeps the existing numeric cell count. A slot that holds only a
   prefix of the field's unit, followed on its line by a slot that is empty or holds a lone dash,
   is not a cell: the next slot holds the cell of that column, as in `$\t\t$\t200` (spec 0.9).
   The value's token is the n-th cell from the field item.
6. Each tabbed line crossed from the field item through the value must be unambiguous. Read its
   slots after the first tab. Each slot must hold exactly one cell, or hold only a prefix of the
   field's unit that is not itself a cell. More than one cell in a slot, a cell that crosses a
   tab, or a nonempty slot with no cell or unit prefix makes the line ambiguous. An ambiguous
   line cannot supply a column key, including at its first number. An item on the value's own
   line that names its key still applies by the ordinary key rule.

So a cell that shows a dash for zero, or a `$` with no number, still counts, and a second header
between the two moves the value out of the rule.

### 4.6 Evidence items

**Finding an item.** An item with offsets is at its span, which must be valid in its text. An item
without offsets is a quote. Its **occurrences** are the matches of its `text` in its text, where
each whitespace run in the quote matches any whitespace run.

The quote is trimmed of whitespace at both ends first.

- For the value item, the occurrences are those inside `search_region` (document only). When the
  candidate has a field item and the field has `aliases`, only the occurrences where the field
  check passes (below) count, if there is one, with the token that steps 10 and 11 find there when a part
  may be missing (#249); otherwise all of them count. Of those, the first where steps 10 and 11
  pass without a missing part is the evidence. Here a unit form at a unit place does not make the
  unit present (step 11): an occurrence with the unit next to the value comes first. When there
  is no such occurrence, the evidence is the first of those, and steps 10 and 11 run there. When
  there is no occurrence, step 9a rejects.
- For a role item, the occurrence is the one that holds the value's token, or, for a `string`
  field, the value's first occurrence in the evidence span; else, for a unit item,
  the last one that ends at or before the value at a unit place of the value (below), where
  occurrences that overlap count too, as `$$` twice in `$$$`; else the
  last one that ends at or before the value; else the first one after the value.

An item's **text** is its `text`, or, when it has offsets and no `text`, the text at its span in
its own source (the document or its reference).

A role item **fails** its check when it is not found, when its span is not valid, when its `text`
is not verbatim-equal to the span's text (as `NON_VERBATIM_EVIDENCE` compares them), or when its
`source` and `ref` differ from those of the value item. On a `string` field, every role item other
than a key or field item fails. Otherwise it passes when its role's check holds:

| Role | Passes when |
|---|---|
| `sign` | The item holds **brackets around the value**: a `(` before the token with only whitespace and prefixes of the field's unit between them, and a `)` after it with only whitespace between them. Or it holds a **loss word** (a `sign.loss` word of the packs that the packet reads; the base pack gives none, and the built-in pack `finance` of §4.8 gives `loss`, `losses`, `deficit`, `deficits`) with no negation (`no`, `not`, `without`) directly before it, only whitespace between, and at most 4 words (runs of letters) between the loss word and the token. A loss-word item ends at or before the token in the value's sentence (§4.5), and from the start of the item to the token there is no number token, no line break, no tab and no **gain word** (`income`, `gain`, `gains`, `profit`, `profits`, `earnings`). Each word is matched whole and case-insensitively. |
| `scale` | The item holds `in`, whitespace and a scale word (§4.1), also with a final `s`, as in "(in thousands", or it holds a currency scale (§4.1), as in "£m" (spec 0.10). It ends at or before the token. No scale word, also with a final `s`, lies between its end and the token, and no currency scale with a power of ten other than the item's scale (below) lies there. So the second `£m` of the header row `\t£m\t£m` does not stop an item on the first. |
| `unit` | The item holds a prefix or suffix of the field's unit as a whole (with no letter or digit directly before a form that starts with one, and none directly after a form that ends with one). Then either the field's unit is at the token (§4.3), so the item repeats it, or the field check passes (below), the item ends at or before the token, no unit form is next to the token (§3.1), and the item is at a unit place of the value (below). Or the item holds a heading unit (§4.3) that reaches the token, the field check passes, the item ends at or before the token, no unit form is next to the token, and the token's heading currency is the field's unit (spec 0.10). In each case, the token has no heading conflict (§4.3, spec 0.10, #365). |
| `field` | The field has `aliases`, the item holds a mention of one of them (matched as key mentions are, §4.5, in the whole text, so a mention inside a longer mention does not count), and the item ends at or before the token. Then one of these holds: no letter (general category L) lies between the item's end and the token (the item is at the **row**); the item is a **label cell** for the token (below); or the item is in the value's sentence with no number token between its end and the token, and the token is not after the end of a label slot that holds the item. |
| `key` | The item holds a key mention of the candidate's `key` (a mention of the whole text, §4.5). |

**Several field items.** A candidate can cite more than one field item, for example the row label
and the column header of a table cell (#300). Each field item is checked on its own, as the table
says. The **field check** passes when one of them passes. A unit item, a unit at a unit place
(§3.1) and the choice of a quote occurrence read the field check. The decision gets
`FIELD_CITATION_INVALID` only when no field item passes. A candidate with one field item passes
the field check when that item passes.

**Label cells.** On a line that holds a tab, the **label slot** is the text from the start of the
line to the first tab, and the **answer slot** is the text after the first tab, up to the next
tab or the end of the line. A reader writes a table row this way, so a question cell and its
answer cell read "What is the overall deductible?\tIn-Network: Individual $850". A field item
that lies wholly in a label slot is a label cell for a token in the answer slot of the same
line when all of these hold (spec 0.10, #316):

1. No number token lies between the end of the item and the token.
2. At most 4 words stand in the answer slot before the token. A word is a run of non-whitespace,
   and the run that holds the token does not count.
3. No sentence end (§4.2) lies in the answer slot before the token.
4. No mention of an alias of a field of the schema lies in the answer slot before the token.

A field item in a label slot reaches a token after that slot only at the row or as a label
cell. The sentence rule does not carry it into a later slot or onto a later line, because a tab
and a line break do not end a sentence, and the next cell or row can hold another value. A
label cell is not at the row, so the column rule (§4.5) does not use it. A line with no tab has
no label slot, and its field items keep the sentence rule.

The scale and the sign of a token are its **parts**. A token is **negative** when the candidate
has a sign item, or, on a field with a unit, when brackets enclose it in the text, as the sign
check reads them. The token's **derived values**
are its value, and its scaled value if it has one. When the candidate has a scale item whose text
holds a scale word (also with a final `s`) or a currency scale, the item's **scale** is the factor
of the first of them in that text. A token with no scaled value then has only its value times the
item's scale: the number as written is not a derived value (#242). When the token
is negative, each of these also has its negative (minus its absolute value). A failing sign or
scale item still gives its part: the decision then has the item's flag.

**Unit places.** A unit item that the field's unit at the token does not repeat must hold a form
of the unit (as a whole) at a **unit place** of the value, one of these (#164):

1. **Line**: the form is on the value's line. Or it is a prefix that ends, with only whitespace
   between, at the `(` of brackets around the value (as the sign check reads them).
2. **Caption**: the form is on a line that holds no tab and no number token, and that line
   reaches the value's line. After it, blank lines may stand, then lines that are not blank and
   each hold a tab or no number token, up to the value's line, which holds a tab.
3. **Column**: the form's line and the value's line hold a tab, neither line is ambiguous under
   the column rule (§4.5, rule 6), and each line between them is not blank and holds a tab or no
   number token. The **cells of a line** are the cells of the column rule (§4.5, rule 5) after
   the first tab of the line. For an empty cell at the end of the line,
   the next character is the first one after the line end that is not whitespace. The form is a
   prefix that ends at the start of the n-th cell of its line, or a suffix that starts after the
   end of the n-th cell, with only whitespace between them. The value's token is the n-th cell
   of its line. A cell ends at the end of the longest number token, dash or empty cell that
   starts at its start. An empty tab slot cannot be a unit form's source cell: a unit in an
   earlier slot does not supply that blank column.

The place is that of the form, not of the item: an item that starts on a caption and holds a `$`
on a table line is at the place of that `$`.

So a `$` on the first row of a table applies to the same column in the rows below it, up to a
blank line or a line with a number and no tab. It also applies to a row of counts in that column
when the field check passes there. In a table with one cell on each line, a unit item on another
line than the value fails.

A field item without `aliases` is not checked: it adds no flag, and it does not pass, so a unit
item of that candidate fails unless the field's unit is at the token. A key item that passes puts its
key at the value only by the column rule (§4.5). The decision records `KEY_CITED` when that removed
`KEY_NOT_AT_VALUE`. A recorded `key` judgment that applies, at or above `clear.KEY_NOT_AT_VALUE`,
and names another key adds `MODEL_DOUBT` to a decision with `KEY_CITED`.

### 4.7 The base vocabulary pack

The word lists of §3 and §4 are data in one file, the base vocabulary pack `en` 1.0.0:
[`src/groundgate/packs/en/1.0.0.json`](src/groundgate/packs/en/1.0.0.json). Its lists are the scale
words and suffixes, the currency signs and scales, the unit table, the per-units, the qualifier
words and their negations, the range words, the change words, the abbreviations, the gain words, the
negations before a loss word, the currency names of a currency statement (§4.3), and the null
literals. It gives no loss word of §4.6: the built-in pack `finance` gives them (§4.8). The rules of §4 read each list as plain words,
never as patterns, with the fixed rules of §4: whole words, the same case rules and the same
windows.

The digest of the base pack is

`pack_sha256 = "sha256:" + hex(SHA-256("groundgate-pack/1:" + type + "\0" + JCS(pack)))`

where `type` is `vocabulary` and JCS is §6. The prefix names the pack format, not the spec
version. For this spec version the base pack is `en` 1.0.0, with the digest
`sha256:8ee2f5c367baa29969759e3ed3ec5acf39f412a8b4b6afbda6477c1cde7fdeae`.
An implementation loads a base pack with this digest, and refuses to run with another one. The base
pack applies to every packet, and the receipt does not name it: the spec version names it.

The digest reads the pack **after defaults**: each absent list is empty, `description` is `""`,
`status` is `[]`, and a currency of `heading_units` with no `sign` has the sign null.

### 4.8 Vocabulary packs

An app can give its own vocabulary packs (§2.1). A pack only adds words to the base pack: the
format has no member that removes, replaces or turns off a word, a check or a limit. A vocabulary
pack is one JSON object in format 1:

| Member | Meaning |
|---|---|
| `groundgate_pack` | The pack format, `1`. |
| `type` | `"vocabulary"`. |
| `id` | Lowercase letters and digits, with single `-` between them, at most 64 characters. The id of an app's own pack holds `-x-` and a name, for example `words-x-myapp`. |
| `version` | `MAJOR.MINOR.PATCH`, each a non-negative integer with no leading zero. |
| `description` | Optional text. It is in the digest and has no effect on a decision. |
| `status` | Optional rows `{"kind", "field", "code", "status", "documents", "bound", "limit", "results"}`, with `status` `draft` or `measured`. |
| the lists | The word lists of the base pack. Each one is optional. |

The lists have the shape of the base pack: `scale.words`, `scale.suffixes` and `scale.currency`
are objects from a word to a power of ten; `units` is an object from a unit code to
`{"prefixes", "suffixes"}`; `qualifiers.before` and `qualifiers.after` are objects from a
comparator (`approx`, `gt`, `lt`, `ge`, `le`, `range`) to phrases; `heading_units` is an object
from a code of three capitals to `{"names", "sign"}`; every other list is a list of words. A pack
other than the base pack cannot give `qualifiers.negations`, `ranges.pair`, `changes.words`,
`changes.determiners`, `sentence.join_always` or `sentence.join_before_code`: a word there
cancels a flag for every field.

A word is plain text, never a pattern. The rules of §4 escape it and read it with their fixed
rules: whole words, the same case rules and the same windows. A list with no word matches
nothing.

The packet is invalid when a given pack fails one of these checks:

| Check | The packet is invalid with |
|---|---|
| L1 closed format | a member that the format does not list, a `groundgate_pack` other than `1`, or a `type` other than `vocabulary` or `kind` (§4.9) |
| L2 data only | a value that is not a string, an integer in [-(2^53), 2^53], null, a list or an object; a boolean or a number with a fraction is not data |
| L3 words | a word that is not NFC, is blank, has whitespace at an end, holds a line break or a tab, or has more than 64 code points; a scale word, a null literal or an abbreviation that is not in lowercase; an abbreviation with no dot at its end; a currency sign that is not one code point other than a letter, a number, a separator or a control character |
| L4 size | a pack file of more than 1 MiB, before it is parsed; a JSON nesting depth of more than 8, where the pack object has depth 1; more than 256 KiB as canonical JSON; a list or an object of more than 2,000 entries |
| L5 add only | a list that only the base pack can give |
| L6 no conflict | after the union: a phrase in two comparator lists; a scale word or form with two powers; a power other than 3, 5, 6, 7, 9 or 12; a scale suffix that is also a unit suffix in one of its cases; a unit form under two unit codes; a loss word that is also a gain word; a qualifier phrase from a pack that holds a phrase of another comparator, or is held in one; a currency name under two codes; two signs for one currency |
| L7 ids and versions | an id or a version with the wrong form; a given pack with the id of a built-in pack; an app's own id with no `-x-`; one id in two versions; two copies of one id and version with two digests |
| L8 status | a malformed row; a `measured` row in a pack that is not built in |
| L11 digest | nothing to refuse: the implementation computes each digest, and never reads one from a pack |
| L12 no text | a member that holds document text, a span, a value or an evidence item. L1 refuses each one. |

L6 compares two words after whitespace normalisation and the fold of each letter (§4). A
qualifier phrase holds another phrase when the other phrase matches in it by the rule of §4.

The qualifier rule of L6 keeps the reading of the base. §4.2 applies the longer of two qualifiers
that overlap. So a pack phrase "less than or equal to" as `le` hides the base phrase "less than"
as `lt`, and a pack phrase "more" as `lt` sits in the base phrase "more than" as `gt`. Both are
invalid.

A **built-in pack** ships with the implementation, like the base pack, but applies only when the
schema or a kind pack names it (§2.3, §4.9). The packet never gives it, and L7 refuses a given pack
with its id. An implementation loads a built-in pack with its digest, and refuses to run with another
one. The receipt names it in `packs` with its digest, as it names a given pack. These are the
built-in packs of this spec version. Each file is `src/groundgate/packs/<id>/<version>.json`.

| Id | Version | Type | Needs | Digest |
|---|---|---|---|---|
| `finance` | `1.0.0` | vocabulary | | `sha256:822c91124cbd23f29e683873975d4f3f85f2207dbbb02ca3664f0ef74848162b` |
| `electronics` | `1.0.0` | vocabulary | | `sha256:af8570f97b8e06fcceae56949a6e3b5ffab4992413cf8b6f474b6239989dbc5b` |
| `us-10k` | `1.0.0` | kind | `finance` | `sha256:ea4115fd9215c89b78369cd1291cf8482cb185602e037c076a8c17c8edbab102` |
| `us-government-reports` | `1.0.0` | kind | `finance` | `sha256:604297bba0b9543fae9d3099eaa6a810f2bdb0fcd0cf5f527d6903b374e44974` |
| `annual-reports` | `1.0.0` | kind | `finance` | `sha256:ca2433ec6dd249581310c977b29a54b4c70aa65acd3561701285a2f4ccf150e7` |
| `component-datasheets` | `1.0.0` | kind | `electronics` | `sha256:3b0ac7d8b1dff0f25a33078c668739086b027704e75b7d4deba9a6ebf9c27538` |
| `benefit-summaries` | `1.0.0` | kind | | `sha256:a01109e7c7a72e248012161d8fe16b1937a77e09c328a6cdcbfd0e9d41ebe3d2` |

No built-in pack has a status row, so each route that it gives is `draft`. `electronics` gives
the unit forms of `C`, `V` and `mA` (§4.3). The kind packs give field templates (§4.9) and no
words.

`finance` gives the loss words of §4.6. A loss word only helps to admit a value: without `finance`, a sign item that holds
only a loss word fails, and the decision goes to review. The currency names of a currency
statement (§4.3) stay in the base pack, because they can stop an admit.

The union takes the base pack, then the other packs that the packet reads. Two words are one entry when they are
equal. In each list, the words of the base keep their order, and the words that the packs add
follow, longest first, then by code point. So the order of the packs never changes a match.

### 4.9 Kind packs

A kind pack (spec 0.10, #335) gives knowledge about one kind of document: field templates, and
the vocabulary packs that the kind needs. It holds no words. A word goes in a vocabulary pack,
and the kind pack names that pack in `needs`. A kind pack is one JSON object in format 1 with the
members `groundgate_pack`, `type` (`"kind"`), `id`, `version`, `description` and `status` of
§4.8, and these:

| Member | Meaning |
|---|---|
| `needs` | Optional. A list of `{"id", "version"}`: the vocabulary packs that the kind needs. |
| `fields` | Optional. An object from a field name to a template. A template holds only `type`, `unit`, `comparator`, `aliases` and `description`, with the rules of §2.3. |

After defaults, an absent `needs` is `[]` and an absent `fields` is `{}`. The digest is the digest
of §4.7 with the type `kind`. A template has no defaults of its own: a field fills them after it
takes the template (§2.3). So L9 checks only the members that a template gives. A template with
no `type` is valid, and the field that takes it gives the type or gets the default `number`.

The packet reads each vocabulary pack that the schema names, and each pack in the `needs` of each
kind pack that the schema names. The packet must give each one. A pack that is named twice in one
version is read once. A `needs` entry has no pin. To pin a needed pack, the schema names it in
`packs` with its `sha256` (§2.3). The union of §4.8 takes the vocabulary packs only.

The checks L1, L2, L3, L7, L8, L11 and L12 of §4.8 apply to a kind pack, and L4 applies with one
more limit. The packet is also invalid when a kind pack fails one of these checks:

| Check | The packet is invalid with |
|---|---|
| L4 size | more than 200 field templates |
| L7 ids and versions | a `needs` entry with an id or a version of the wrong form; a `needs` entry and the schema, or two `needs` entries, that name one id in two versions |
| L9 kind pack | a `needs` that is not a list of objects with only `id` and `version`; a `needs` entry that names the base pack, the pack itself, an id twice, a kind pack or a pack that is not given or built in; a `fields` that is not an object; a template member other than the five above; a template that breaks a rule of §2.3 |
| L10 schema | a `template` that breaks a rule of §2.3, or a field that breaks a rule of §2.3 after it takes its template |

## 5. Receipt

```json
{"groundgate": "0.10",
 "document": {"id": null, "sha256": "sha256:...", "source": null},
 "references": [],
 "packs": [],
 "schema_sha256": "sha256:...", "policy_sha256": "sha256:...",
 "decisions": [{"candidate_id": "c1", "candidate_sha256": "sha256:...", "field": "...",
                "key": null, "outcome": "admitted", "codes": [], "value": "2000", "unit": "mg",
                "source": "document", "ref": null, "url": null,
                "evidence": {"start": 120, "end": 128}, "parts": [], "missing": [],
                "packs": []}],
 "coverage": [],
 "judgments": [],
 "summary": {"admitted": 1, "needs_verification": 0, "rejected": 0},
 "receipt_sha256": "sha256:..."}
```

`document.source` is the document source, or null. `references` lists each reference as
`{"id", "sha256", "source"}`, sorted by `id`. `packs` lists each pack that the schema names, and
each pack that a named kind pack needs, as `{"id", "type", "version", "sha256"}`, sorted by `id`.
`type` is `vocabulary` or `kind`. It lists a named built-in pack such as `finance`, but never the
base pack.

Decisions are sorted by `candidate_sha256`, then by input position. `codes` lists the rejecting
code, or the flag codes in the order of the table in §3.3, followed by `EVIDENCE_REANCHORED`,
`VALUE_DERIVED`, `KEY_CITED`, `ADMITTED_BY_POLICY` and then `MODEL_CLEARED` when they apply.
`value` is the canonical value and `unit` the candidate's unit, each `null` when the candidate does
not provide a parseable one. `key` is the candidate's `key` when its field has `keys` and the key
is a string, otherwise `null`.

- `source` is the kind of the item that the decision rests on: the value item's on the checked
  path from step 9 on, the deciding item's on the outside path, and for a candidate rejected
  before step 9, the value item's when its evidence is well-formed and has one; otherwise
  `null`. `ref` is the
  value item's `ref` for a reference, and `url` the deciding item's URL for an external item, otherwise `null`.
- `evidence` is the value span that the decision rests on: the re-anchored span when re-anchoring
  applied, the found occurrence for a quote, otherwise the cited span if it is valid, otherwise
  `null`. It is in the value item's text.
- `parts` lists each role item of a candidate that reached the role checks, as
  `{"role", "start", "end", "passed"}`, in the role order `sign`, `scale`, `unit`, `field`, `key`.
  `start` and `end` are the item's span in the value's text: the found occurrence of a quote, or
  the item's offsets when they are valid there. They are null when the item is not in that text.
  Each field item is listed, in its order in the evidence list. A field item without `aliases` is
  listed with `passed` false.
- `missing` lists the missing parts in the order `sign`, `scale`, `unit`, `key`.
- `packs` lists the ids, sorted, of each pack in the receipt's `packs` that adds a word that
  occurs in the document, in a reference or in a string of the candidate, and of the kind pack
  that gave the template of the candidate's field (§2.3). Both sides are compared
  with the fold of `ſ`, `ı`, `İ` and `K` from §4 and then casefolded, with each whitespace run as
  one space. A word that the base pack gives in the same
  list is not an added word. The list can name a pack that did not change the outcome; it never
  leaves out a pack that changed it.
- `evidence_units` names the units that groundgate finds for the value's token when the unit
  check does not pass (spec 0.10, #362). A decision has this member only when it has a number
  token and one of these holds: its `codes` hold `UNIT_NOT_IN_EVIDENCE`, its `codes` hold
  `UNIT_CITATION_INVALID`, or its `missing` holds `unit`. Other decisions do not have the
  member. The member is a report. It never changes the outcome, the codes or `missing`, and
  groundgate never converts a value.

  ```json
  "evidence_units": {"token": {"start": 64, "end": 69}, "next": [], "per": false,
                     "headers": [{"form": "$", "allows": ["AUD", "CAD", "HKD", "NZD", "SGD", "USD"]}],
                     "statements": ["AUD"], "currency": ["AUD"]}
  ```

  - `token` is the span of the token in the value item's text, in UTF-8 bytes, as `evidence` is.
    For `UNIT_NOT_IN_EVIDENCE` it is the first number token in the `evidence` span that step 10
    matches when a part can be missing (§3.1). Otherwise it is the token that the value is at
    (§3.1).
  - `next` lists each code of the unit table (§4.3, built-in and the schema's) that has a form
    next to the token. A form is next to the token when a prefix of the code ends at the token
    start, or when the first suffix after the token is a suffix of the code, as §4.3 reads
    prefixes and the first suffix. A per-unit counts here. A code with no prefixes and no
    suffixes is never in the list.
  - `per` is true when the suffix of `next` is a per-unit (§4.3). Otherwise it is false. So
    "75 mg/m2" gives `"next": ["mg"], "per": true`.
  - `headers` lists each form of a currency header that reaches the token (§4.3), one time for
    each reported form, as `{"form", "allows"}`. `allows` lists the codes that the header allows.
    It is empty for an unknown header. A form is reported as it is in the text when its length
    is at most the limit: the length of the longest prefix in the unit table, plus 8 code
    points. The unit table is the built-in table with the schema's `units` (§4.3). A longer form
    is **cut** to its last code points, up to the limit, so that it keeps its sign, and its
    entry has the member `"cut": true`. Only a cut form has `cut`. If two forms give the same
    reported form, they have one entry, and it has `cut` when one of them is cut. A cut form is
    always unknown, because each prefix of the unit table is within the limit. With the
    built-in table the limit is 11 (`US$` and `Rs.` have 3), so `ABCDEFGHIJKLMNOPQRST$m` gives
    `{"form": "KLMNOPQRST$", "allows": [], "cut": true}`.
  - `statements` lists the code of each currency statement that reaches the token, one time for
    each code.
  - `currency` lists each code X for which the heading currency of the token is X when the
    field's unit is X (§4.3). X is a code of the unit table or of the currency table of §4.3.

  The lists are sorted in code point order, and `headers` by `form`. When groundgate finds no
  unit, each list is empty. When the heading units do not agree, `headers` and `statements` name
  them, and `currency` is empty. groundgate never chooses between them. `currency` holds two
  codes when the schema gives one prefix to two units, as `$` to `CAD` and to `USD`. groundgate
  does not choose then either.

Coverage is sorted by field name. `judgments` lists each judgment that applied, as
`{"candidate_sha256", "question", "answer", "p"}` (`answer` only for `key`), sorted by
`candidate_sha256`, then by input position of the candidate, then by question; the judge is in the
policy.

When the schema has relations, the receipt has a member `relations`: each relation that applied
at a relation key (§3.4), as `{"id", "key", "holds", "difference", "allowance"}`, sorted by `id`,
then by `key` in code point order. `key` is null for a relation over fields without `keys`.
`holds` is a boolean. `difference` and `allowance` are canonical decimals (§4.1). A relation that
did not apply is not listed, so the list can be empty. A receipt of a schema without relations
has no `relations` member. `receipt_sha256` is the digest of kind `receipt` over the receipt without its
`receipt_sha256` key.

## 6. Canonical JSON and digests

Canonical JSON is RFC 8785 (JCS): keys sorted by UTF-16 code units, no insignificant whitespace,
strings escaped as ECMAScript `JSON.stringify` does, numbers serialised as ECMAScript
`Number.prototype.toString`. NaN and infinities are not permitted. Integers outside
[-(2^53-1), 2^53-1] are not permitted (they are not exactly representable).

`digest(kind, obj) = "sha256:" + hex(SHA-256("groundgate/0.10:" + kind + "\0" + JCS(obj)))`, where
the prefix is ASCII and `JCS(obj)` is UTF-8.

## 7. Non-goals for v0.10

Semantic correctness (whether the sentence describes the field) by groundgate itself: a recorded
`field_match` judgment can only add doubt, and a field item checks only the field's own aliases.
Calling a model, fetching a URL, dates, arrays of records, arithmetic over several numbers (a
relation of §3.4 is the one exception, and it never admits a value), the
subject of the document (groundgate assumes one subject per document), and PDF geometry (page and
bounding box) as evidence. Adapters may convert richer evidence into spans. Number formats other
than English and Indian grouping, and digits other than 0 to 9 (#60).
