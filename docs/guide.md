# Guide

groundgate takes these inputs and returns a receipt:

- a **document**: the text the facts came from;
- a **schema**: the fields you want, with their types and units;
- **candidates**: the facts an extractor proposed, each with its evidence: quotes or spans in the
  document or in a reference, or an outside source;
- a **policy** (optional): a few knobs, with defaults;
- **references**, a **document source** and **judgments** (optional): other source texts that you
  trust, the document's URL, and a judge's recorded answers.

Every candidate gets one decision, with reason codes:

| Outcome | What the app does |
|---|---|
| `admitted` | Store the fact. |
| `needs_verification` | Send it to a person, with its evidence and codes. |
| `rejected` | Do not store it. The codes say why. | [SPEC.md](../SPEC.md) is the normative version of everything below; this page is the
working summary.

## Documents

The document is a Python `str` in Unicode NFC. Anything else is an invalid packet: `admit`
raises `PacketError` and writes no receipt. If your text came from somewhere else, normalise it
before you extract, so the extractor's offsets and groundgate's agree:

```python
import unicodedata

text = unicodedata.normalize("NFC", text)
```

To get text from a file, use `groundgate.extract.extract(path, pages=None)` or
`groundgate extract` on the command line. It reads PDF (with `groundgate[pdf]`), HTML, XML and
plain text and returns an `Extracted` with `text` (NFC), `layout` (PDFs only) and `warnings`. It
drops text a reader can't see, and for PDFs records the page and box of every word so the report
can show page numbers.

## Schema

```json
{"fields": {
   "max_daily_dose": {"type": "number", "unit": "mg", "comparator": "le", "required": true},
   "tablet_strengths": {"type": "number", "unit": "mg", "multiple": true},
   "pediatric_min_age": {"type": "integer", "unit": "years", "minimum": "0"}
 },
 "units": {"inHg": {"suffix": ["inches Hg", "inHg"]}}}
```

| Key | Default | Meaning |
|---|---|---|
| `type` | `"number"` | `number`, `integer` or `string`. |
| `unit` | `null` | The unit code the value must carry: in the candidate, and next to the value in the text or in a `unit` item. |
| `comparator` | `"eq"` | What the field means relative to the number: `eq`, `gt`, `ge`, `lt`, `le`, `approx`, `range`. A qualifier in the text that implies a different comparator flags `QUALIFIED_VALUE`. |
| `minimum`, `maximum` | `null` | Bounds, as decimal strings or integers. Outside them is `RANGE_INVALID`. |
| `required` | `false` | A required field with nothing admitted or flagged is listed in the receipt's `coverage`. |
| `multiple` | `false` | The field holds a list, so different values don't conflict. |
| `keys` | `null` | The conditions a value can belong to, in the document's words. Each candidate names one as `key`. |
| `aliases` | `null` | The field's names in the document's words, such as "loss from operations". A field item is checked against them (spec 0.5). |

The comparator is how a field says "up to" is fine. `max_daily_dose` above is `le`, so "up to
4,000 mg" admits; an `eq` field citing the same text is flagged.

**Units.** The built-in table covers `USD`, `EUR`, `GBP`, `INR`, `%`, `mg`, `mcg`, `g`, `kg`,
`mL`, `L`, and `minutes` through `years`. A unit is found when a prefix (`$`) ends at the number,
or a suffix (`mg`, `dollars`) starts within `unit_window` code points after it, in the same
sentence. The whole suffix must be in that sentence, so a suffix that holds `. ` (such as
`in. Hg`) never matches. Only the first suffix of any known unit counts, so in "10 mcg (maximum
500 mg)" the 10 is mcg, never mg. `units` in the schema adds codes or replaces built-in ones. A code with no surfaces
matches everywhere, so the unit check becomes a no-op for it.

**Keys.** A label gives a different starting dose per indication. Declare them on the field and
send one candidate per indication:

```json
{"fields": {"starting_dose": {"unit": "mg", "keys": ["hypertension", "heart failure"]}}}
```

A candidate for `starting_dose` without a `key`, or with one not in the list, is rejected
`KEY_INVALID`. groundgate then reads which key the text puts at the value: the keys its sentence
mentions, or else the nearest one mentioned before it, such as the heading "2.2 Heart Failure".
When that is not the candidate's key, the fact is flagged `KEY_NOT_AT_VALUE`. Two candidates only
conflict when they share a key. The receipt echoes the key. A short label line such as "Notes:"
between the heading and the value stops the heading's key, and in a table sentence only the
value's own line counts. So a right key under a label line, or in a table with one cell on each
line, goes to review.

## Candidates

```json
{"id": "c1", "field": "max_daily_dose", "value": "4000", "unit": "mg",
 "evidence": [{"start": 120, "end": 128, "text": "4,000 mg"}],
 "confidence": 0.93, "proposer": "gemini-3.6-flash"}
```

- `value` is a string, or a JSON integer. Write decimals as strings (`"0.5"`), never as floats.
- `evidence` is a list of evidence items (below). One item object also works, as in spec 0.4.
- `search_region` limits where groundgate looks for a quote and where re-anchoring may look. It
  defaults to the whole document.
- `key` names the condition on a keyed field. On other fields it is ignored.
- `start` and `end` in an evidence item are UTF-8 byte offsets, end exclusive. For a Python
  index `i`, the offset is `len(text[:i].encode())`.
- Any other key (a proposer name, a chunk id) is kept, ignored by the checks, and covered by the
  candidate's hash.

`gg.candidate_schema()` returns a JSON Schema for one candidate, the file
[`candidate.schema.json`](../src/groundgate/candidate.schema.json) in the package. It describes
every candidate that step 1 accepts. For a model's structured output, use
[`gg.extractor_schema`](#the-extractors-output) instead. groundgate does not validate with
either schema: step 1 is the definition. The schema does not check three things: a
`ref` that names no reference, two document or reference items with the same role, and an integer
written with a fraction (`2.0`).

### Evidence items

Spec 0.5. A right value often needs more than one place in the text. In a 10-K table,
`-105198000` for operating income in 2024 needs the bracketed `(105,198)`, the header "(in
thousands", the `$` at the top of the column, the row "Loss from operations" and the "2024" column.
The extractor cites each part as one item:

```json
"evidence": [{"text": "(105,198\n)"},
             {"role": "scale", "text": "(in thousands"},
             {"role": "unit", "text": "$"},
             {"role": "field", "text": "Loss from operations"},
             {"role": "key", "text": "2024"}]
```

An item from the document has a `role` and either a byte span (`start`, `end`, optional `text`)
or only `text`. With only `text`, the item is a quote, and groundgate finds it. For the value item,
groundgate takes the first occurrence that holds the value with its unit, else the first
occurrence. For a role item, it takes the occurrence that holds the value, else the last one
before it, else the first one after it. A quote that does not occur rejects the fact with
`QUOTE_NOT_FOUND`.

| Role | What it supports | What groundgate checks |
|---|---|---|
| `value` (default) | The number as written. | The value is there, as in spec 0.4. |
| `sign` | A negative value. | Brackets around the number, or a loss word ("loss", "deficit") at most 4 words before it in the same sentence, with no "no", "not" or "without" directly before it, and no number, line break, tab or gain word ("income", "profit") between it and the number. |
| `scale` | A value in thousands or millions. | "in thousands" or "in millions" before the value, with no other scale word between. |
| `unit` | A unit that is not next to the number, such as the `$` at the top of a column. | The field item passes, the item holds a form of the field's unit before the value, and no unit form, not even the field's own, is next to the number. |
| `field` | The field's own words. | The item holds one of the field's `aliases`, on the value's row or in its sentence. |
| `key` | The key, such as a column header. | The item holds a mention of the key. In a table, the key is at the value when it is the n-th key of its header and the value is the n-th cell after the field item (the column rule). A dash or a `$` with no number counts as a cell. A footnote number after the row label stops the rule. When only spaces stand between the row label and its first number, the rule stops after the first column. A tab after the label, as `groundgate extract` writes HTML tables, keeps it. |

groundgate computes the value from the parts. The extractor does not state the steps. On a field
with a unit, brackets that enclose the number make it negative with no item. When the value needs a sign, a scale or a
unit that no item supports, the fact goes to review with `PART_MISSING`, and the decision lists
the part in `missing`. An item that fails its check flags the fact (`SIGN_CITATION_INVALID` and so
on). groundgate never swaps in a part that it found itself.

### Evidence from outside the document

Some right values are not in the document. An item can come from three other sources:

| `source` | Who supplies the text | Members | groundgate can check it |
|---|---|---|---|
| `reference` | the app | `ref` (the id of a reference in the packet), then as a document item | yes, like the document |
| `external` | the extractor | `url`, `retrieved` (a date), `text` (the quoted passage) | only that the quote holds the value |
| `knowledge` | the extractor | `text` (its statement) | no |

A reference is a source text that you pass to `admit` as `references`, such as a tax table. It can
hold only the part that matters. Each reference has a unique non-blank `id`, a non-empty NFC
`text` and an optional `source` (its URL), and no other members. `search_region` does not apply
to a reference.

A candidate with no value item takes the outside path: the policy's `sources` decide what happens
to it (below). A candidate with a value item takes the checked path, and its outside items change
nothing and are not in the receipt. The receipt says which source a decision rests on.

### The extractor's output

`gg.extractor_schema(schema)` returns a JSON Schema for a model's structured output: an object
with a `candidates` list. Give it to the model as its output format, then pass the list to
`admit`. `groundgate schema schema.json` writes the same schema.

```python
output_format = gg.extractor_schema(schema)
out = your_model(instructions, text, output_format)
receipt = gg.admit(text, schema, out["candidates"])
```

With references, give their ids to the schema and the same references to `admit`:

```python
references = [{"id": "tax-table", "text": table_text, "source": "https://www.irs.gov/..."}]
output_format = gg.extractor_schema(schema, [r["id"] for r in references])
out = your_model(instructions, text, references, output_format)
receipt = gg.admit(text, schema, out["candidates"], references=references)
```

- Each field of your schema has its own candidate shape. `field` is the field's name, `unit` its
  unit code or `null`, and `key` one of its keys on a keyed field, else `null`. So the model cannot send a field, a
  unit or a key that the schema does not have.
- An item has no offsets. A model cannot count UTF-8 bytes, so it quotes, and groundgate finds the
  quote.
- A reference item is in the schema only when you give the reference ids.
- The schema uses only `$schema`, `type`, `properties`, `required`, `additionalProperties`, `items`, `const`,
  `enum`, `anyOf`, `$defs`, `$ref` and `description`. Every member is required, and no object
  takes other members. This is the subset that the strict structured-output modes take.
- Two step 1 rules stay outside the schema: two items with the same role, and a blank `text`,
  `url` or `retrieved`. Step 1 rejects such a candidate with `CANDIDATE_INVALID`.

The schema gives the shape. These instructions tell the model what to put in it:

```text
Extract the fields from the text. Give "value" as the fact is, as a plain number without $,
commas or a unit, with its sign and scale: a number in brackets, or a loss, is negative, and a
table "in thousands" multiplies its numbers by 1000.

Give the evidence as quotes, each copied verbatim from the text:
- role "value": the number as written, such as "(12,040)";
- role "sign": the brackets or the loss word that make the value negative, when the value quote
  does not hold them;
- role "scale": the words that scale the number, such as "(in thousands)";
- role "unit": the unit or $ sign when it is not next to the number, such as the $ at the top of
  a table column;
- role "field": the words that name the field, such as a table row label;
- role "key": the words that name the key, such as a table column heading.
Leave out each role that the value does not need.

If no text states a value, but you know it, give a "knowledge" item that states the value and
its basis, or an "external" item with the URL of a page that states it, the date that you read
the page, and a quote from it.
```

For example, for a field `operating_income` [USD] with keys `2025` and `2024` and the alias "Loss
from operations", this table (with tabs between cells, as `groundgate extract` writes HTML tables):

```text
CONSOLIDATED STATEMENTS OF OPERATIONS
(in thousands)

	2025	2024
Revenue	$ 412,300	$ 388,950
Loss from operations	(12,040)	(9,775)
```

gives this candidate for 2025, and one like it for 2024. Both are admitted, with `VALUE_DERIVED`
and `KEY_CITED`:

```json
{"field": "operating_income", "value": "-12040000", "unit": "USD", "key": "2025",
 "evidence": [{"source": "document", "role": "value", "text": "(12,040)"},
              {"source": "document", "role": "scale", "text": "(in thousands)"},
              {"source": "document", "role": "unit", "text": "$"},
              {"source": "document", "role": "field", "text": "Loss from operations"},
              {"source": "document", "role": "key", "text": "2025"}]}
```

## Policy

| Key | Default | Meaning |
|---|---|---|
| `min_confidence` | `null` | Below this, a candidate is flagged `LOW_CONFIDENCE`. |
| `unit_window` | `24` | How far after a number a unit suffix may start, in code points. |
| `reanchor` | `true` | When the value item's span misses the value, and exactly one other occurrence of its `text` holds the value with its unit, move the evidence there (`EVIDENCE_REANCHORED`). Only an item with offsets and `text` re-anchors. |
| `judge` | `null` | The one judge whose recorded judgments apply, and its thresholds. See [Recorded judgments](#recorded-judgments). |
| `sources` | review | What happens to a value that only external or knowledge evidence supports. See below. |

```json
{"sources": {"external": {"allow": ["document-domain", "https://www.law.cornell.edu/"],
                          "other": "review"},
             "knowledge": "review"}}
```

groundgate cannot check evidence from outside the pinned texts, so you decide. An external item
whose URL matches an `allow` entry is admitted with `ADMITTED_BY_POLICY`. `"*"` matches every URL,
`"document-domain"` matches the host of the document source (`document_source=` in `admit`), and
any other entry is a URL prefix, so end it with `/`. Other external items get `other`: `review`
(`EVIDENCE_QUOTED`) or `reject` (`SOURCE_REJECTED`). Knowledge items get `knowledge`: `admit`,
`review` (`EVIDENCE_STATED`) or `reject`. The defaults send both to review, so nothing from outside
the document is admitted unless you say so (ADR
[0001](adr/0001-admit-by-policy.md)).

### Recorded judgments

Spec 0.4, experimental. groundgate never calls a model. A judge, such as a small typed-decision model,
answers questions about candidates before the decision, and you pass its answers as `judgments`:

```python
policy = {
    "judge": {
        "id": "jev",
        "digest": "jev-1.13.0",
        "clear": {"KEY_NOT_AT_VALUE": 0.9},
        "doubt": {"field_match": 0.2},
    }
}
judgments = [
    {
        "candidate_id": "c7",
        "question": "key",
        "judge": {"id": "jev", "digest": "jev-1.13.0"},
        "answer": "heart failure",
        "p": 0.97,
    },
    {
        "candidate_id": "c9",
        "question": "field_match",
        "judge": {"id": "jev", "digest": "jev-1.13.0"},
        "p": 0.04,
    },
]
receipt = gg.admit(text, schema, candidates, policy, judgments=judgments)
```

- A `key` judgment on a candidate flagged `KEY_NOT_AT_VALUE` clears the flag when it chooses the
  candidate's key with `p` at or above `clear.KEY_NOT_AT_VALUE` (`MODEL_CLEARED`). Another key
  or none at that `p` adds `MODEL_DOUBT`, also to a decision with `KEY_CITED`.
- A `field_match` judgment with `p` below `doubt.field_match` adds `MODEL_DOUBT`, so the value
  goes to review.
- Only judgments of the policy's judge and model version apply. A judgment never overturns a
  rejection, and never admits a candidate that has another flag.

The thresholds belong to one model and one kind of document. groundgate ships none: measure
yours with `groundgate-calibrate` ([#112](https://github.com/mohanraj00/groundgate/issues/112)).

## Decisions

Checks run in a fixed order and the first failure rejects:

`CANDIDATE_INVALID`, `FIELD_UNKNOWN`, `NULL_STRING_LITERAL`, `TYPE_INVALID`, `RANGE_INVALID`,
`UNIT_INVALID`, `KEY_INVALID`, `NO_EVIDENCE`, `SPAN_INVALID`, `QUOTE_NOT_FOUND`,
`VALUE_NOT_IN_EVIDENCE`, `UNIT_NOT_IN_EVIDENCE`, and on the outside path `SOURCE_REJECTED`.

A fact that passes them all is checked for flags. Any flag makes it `needs_verification`:

`NON_VERBATIM_EVIDENCE`, `QUALIFIED_VALUE`, `SCALE_WORD`, `PART_MISSING`, `SIGN_CITATION_INVALID`,
`SCALE_CITATION_INVALID`, `UNIT_CITATION_INVALID`, `FIELD_CITATION_INVALID`, `KEY_NOT_AT_VALUE`,
`KEY_CITATION_INVALID`, `EVIDENCE_QUOTED`, `EVIDENCE_STATED`, `LOW_CONFIDENCE`,
`CONFLICTING_CANDIDATES`, and `MODEL_DOUBT` from a recorded judgment. `EVIDENCE_REANCHORED`,
`VALUE_DERIVED`, `KEY_CITED`, `ADMITTED_BY_POLICY` and `MODEL_CLEARED` only inform.

`CONFLICTING_CANDIDATES` is set on every candidate for a single-valued field (and key) when two
of them passed the checks with different values. groundgate never picks between them. That is also why
it helps to send several proposers' candidates through one `admit` call: disagreement becomes a
flag. It only helps when they disagree.

A decision carries `candidate_id`, `candidate_sha256`, `field`, `key`, `outcome`, `codes`, the
canonical `value`, the candidate's `unit`, the `source` it rests on (with `ref` or `url`), the
value's `evidence` span (the re-anchored one, if it moved, or null on the outside path), the
`parts` (each role item's span and whether it passed), and the `missing` parts. These are two
decisions from the [table example](#the-key-span) below. The first cites its scale, row and
column, and the second cites nothing but the value:

```json
{"candidate_id": 1, "field": "sales", "key": "south", "outcome": "admitted",
 "codes": ["VALUE_DERIVED", "KEY_CITED"], "value": "35000", "unit": "USD",
 "source": "document", "ref": null, "url": null, "evidence": {"start": 65, "end": 67},
 "parts": [{"role": "scale", "start": 16, "end": 29, "passed": true},
           {"role": "field", "start": 46, "end": 53, "passed": true},
           {"role": "key", "start": 39, "end": 44, "passed": true}],
 "missing": [], "candidate_sha256": "sha256:4e8d5970..."}
{"candidate_id": 2, "field": "sales", "key": "south", "outcome": "needs_verification",
 "codes": ["PART_MISSING", "KEY_NOT_AT_VALUE"], "value": "35000", "unit": "USD",
 "source": "document", "ref": null, "url": null, "evidence": {"start": 65, "end": 67},
 "parts": [], "missing": ["scale", "key"], "candidate_sha256": "sha256:9dd86267..."}
```

`missing` lists the parts in the order `sign`, `scale`, `unit`, `key`. It lists `key` when the
fact has `KEY_NOT_AT_VALUE` and no key item, which adds no `PART_MISSING`. A judgment that clears
the key flag leaves `key` in `missing`.

**Feedback to the extractor.** `groundgate.codes.DESCRIPTIONS` maps each code to one sentence. An
app can send a fact's codes, their sentences and `missing` back to its extractor, ask for the
missing parts or better evidence, and decide again. Whether to do this is the app's choice.

## How values are read

SPEC §4 has the exact rules. This is what they mean for your documents.

**Numbers.** groundgate reads numbers written with the ASCII digits 0 to 9 (spec 0.3):

| Written | Read as |
|---|---|
| `7000`, `-5`, `−5` | digits with no groups, and an optional minus sign |
| `7,000`, `1,234.5` | groups of three with a comma, and a dot before the decimals |
| `2,00,000`, `1,00,00,000` | Indian grouping: the last three digits, then pairs (spec 0.3) |

These have no value, so a candidate that cites only them is rejected `VALUE_NOT_IN_EVIDENCE`:

| Written | Why |
|---|---|
| `1.234,56`, `0,5` | a comma is the decimal mark |
| `1 234`, `1'234` | a space or an apostrophe separates the groups, so `1 234` is two numbers |
| `five`, `1/2`, `1.5e3` | a number word, a fraction or an exponent |
| `252,0000`, `1,23,456,789` | the groups are malformed, or they mix the two groupings |
| `२०००`, `٢٠٠٠` | the digits are not ASCII digits. A candidate `value` written in them is rejected `TYPE_INVALID`. |

These rules are for English text. Other number formats need locale packs, which are a design and
not yet code ([design/locale-packs.md](design/locale-packs.md)).

A span never reads part of a longer number. A span on `500 mg` inside `1,500 mg` does not hold 500,
and a span that stops at `29.` inside `29.97` does not hold 29.

**Scale words.** `thousand`, `million`, `billion`, `trillion`, `lakh` and `crore` after a number
multiply it. Send the scaled value. For "$1.25 billion", `"1250000000"` admits and `"1.25"` is
flagged `SCALE_WORD`.

**Qualifiers.** groundgate looks for a qualifier in the same sentence, up to 40 code points before
and after the value, and not past the next number. Each qualifier implies a comparator. When that
comparator is not the field's, the fact is flagged `QUALIFIED_VALUE`. Some of the words:

| Comparator | For example |
|---|---|
| `approx` | about, approximately, around, nearly |
| `gt`, `lt` | more than, above, exceeds; less than, below, under |
| `ge`, `le` | at least, or more; up to, at most, or less |
| `range` | between; a second number after `to`, `through` or `-` |

A negation directly before the word inverts it, so "may not exceed $19,000" is `le`. A change is
not a range: in "increased from $70,000 to $72,000", $72,000 is the new value and has no
qualifier. The full lists are in SPEC §4.2.

**Sentence ends.** A sentence ends at `.` or `;` before whitespace, at `•`, and at a blank line.
The qualifier window, the unit search and the key scope stop there. In spec 0.3, the dot of a
listed abbreviation such as `approx.`, `Rs.`, `p.m.` or `U.S.` does not end the sentence for the
qualifier window when a lowercase letter, a digit or a currency sign comes next. So "up to Rs.
50,000" is qualified. The unit search and the key scope still stop at that dot.

**Strings.** A `string` field matches when its value is in the span text. Whitespace runs count
as one space on both sides. Case counts.

## When a fact is rejected or flagged

Rejections, in the order of the checks:

| Code | Usual cause | What to do |
|---|---|---|
| `CANDIDATE_INVALID` | A decimal is sent as a JSON float, such as `0.5`, or an evidence item is malformed. | Send the value as a string: `"0.5"`. Use `gg.extractor_schema` as the model's output format. |
| `FIELD_UNKNOWN` | The field name is not in the schema. | Send the name as the schema writes it. |
| `NULL_STRING_LITERAL` | The extractor sent `"null"`, `"none"`, `"nil"` or `"n/a"` for a value that is not there. | Leave the field out instead. |
| `TYPE_INVALID` | The value does not parse as the field's type, such as `"7,000 USD"` or `"7.5"` for an integer. | Send the plain number, without commas or a unit. |
| `RANGE_INVALID` | The value is outside the field's `minimum` or `maximum`. | Check the value, or the bounds. |
| `UNIT_INVALID` | The candidate's `unit` is not the field's unit code. | Send the field's unit code. |
| `KEY_INVALID` | The candidate's `key` is not written exactly as one of the field's `keys`. | Send the key as the schema writes it. |
| `NO_EVIDENCE` | No value item and no outside item, such as a LangExtract extraction that did not align. | Ask for a quote of the value. |
| `SPAN_INVALID` or `VALUE_NOT_IN_EVIDENCE` | Character offsets are sent as byte offsets, and the text has a character outside ASCII before the span. | Convert the offsets (see [Candidates](#candidates)), or send only the value item's `text`, and groundgate finds the quote. |
| `QUOTE_NOT_FOUND` | The extractor changed the quote of the value, or cited the wrong reference. | Ask for the text copied exactly, from the text that it cites. |
| `VALUE_NOT_IN_EVIDENCE` | The value is not in the cited text, or the text writes the number in a form that groundgate does not read (see above). | A person checks the fact. |
| `UNIT_NOT_IN_EVIDENCE` | Another unit is next to the number, such as mcg for an mg field, or a per-unit such as mg/kg. | Check the field's unit. For a per-unit, give the field its own code, such as `mg/kg`. |
| `SOURCE_REJECTED` | Only outside evidence supports the value, and the policy rejects it. | Ask for a quote from the document or a reference. |

Flags send the fact to a person:

| Code | Usual cause | What to do |
|---|---|---|
| `NON_VERBATIM_EVIDENCE` | The extractor changed the quote. | A person compares the quote with the text at the span. |
| `QUALIFIED_VALUE` | The text says "up to" and the field is `eq`. | If the field is a limit, set its `comparator`. If not, a person checks the fact. |
| `SCALE_WORD` | The value is sent as written, without its scale word. | Send the scaled value. |
| `PART_MISSING` | The value needs a sign, a scale or a unit that no item supports. A unit is missing when no unit form is next to the number: the text writes a surface that is not in the table, or the suffix is past `unit_window` or a sentence end. `missing` names the part. | Ask the extractor for those items, or add the unit's surfaces in the schema's `units`. |
| `SIGN_CITATION_INVALID`, `SCALE_CITATION_INVALID`, `UNIT_CITATION_INVALID` | The item does not hold its part at the value (see [Evidence items](#evidence-items)). A unit item also fails when the field item fails, or when a unit is already next to the number. | A person checks the fact. |
| `FIELD_CITATION_INVALID` | The item holds none of the field's `aliases`, or it is not on the value's row or in its sentence. | Give the field `aliases` in the document's words. |
| `KEY_NOT_AT_VALUE` | The value is under a different condition in the text, or a label line or a table cell stands between the key and the value. | In a table, ask the extractor for a `field` item and a `key` item, and give the field `aliases`. Otherwise a person checks the fact. |
| `KEY_CITATION_INVALID` | The key item does not hold a mention of the key, or is not in the value's text. | A person checks the fact. |
| `EVIDENCE_QUOTED`, `EVIDENCE_STATED` | Only outside evidence supports the value. | Check the source. If you trust it, add the URL prefix to `sources.external.allow`, or set `sources.knowledge` to `admit`. |
| `LOW_CONFIDENCE` | The extractor's `confidence` is below `min_confidence`. | A person checks the fact. |
| `CONFLICTING_CANDIDATES` | Two proposers read different values. | A person picks one. groundgate never picks. |
| `MODEL_DOUBT` | A recorded judgment of the policy's judge doubts the value or its key. | A person checks the fact. |

`REQUIRED_FIELD_MISSING` is a coverage finding, not a decision: no candidate of a required field
was admitted or flagged.

## Python API

```python
import groundgate as gg

receipt = gg.admit(
    text,
    schema,
    candidates,
    policy=None,
    document_id=None,
    judgments=None,
    *,
    references=None,
    document_source=None,
)
receipt.decisions  # tuple of gg.Decision
receipt.coverage  # tuple of (field, "REQUIRED_FIELD_MISSING")
receipt.references  # tuple of (id, sha256, source)
receipt.to_dict()  # the JSON receipt, including receipt_sha256

receipt_dict = receipt.to_dict()  # or the stored JSON
check = gg.verify(
    receipt_dict,
    text,
    schema,
    candidates,
    policy=None,
    judgments=None,
    *,
    references=None,
    document_source=None,
)
check.ok, check.problems  # True, () when the receipt re-derives exactly
```

`references` and `document_source` are keyword-only. `schema` and `policy` can be dicts or
`gg.Schema` / `gg.Policy`. Invalid inputs raise `gg.PacketError`. In Python, `Decision.evidence`
and `Part.span` are `(start, end)` tuples, and `to_dict()` writes them as `{"start", "end"}`.
`gg.candidate_schema()` and `gg.extractor_schema(schema, reference_ids=None)` return the JSON
Schemas of [Candidates](#candidates) and [The extractor's output](#the-extractors-output). `gg.digest(kind, obj)` and `gg.jcs(obj)` are the hashing primitives, if you
need to compute a candidate's hash yourself.

### LangExtract

```python
from groundgate.adapters.langextract import admit_document, to_candidates

receipt = admit_document(
    result,
    schema,
    policy=None,
    document_id=None,
    judgments=None,
    references=None,
    document_source=None,
)
```

Every argument after `policy` is keyword-only. Other keyword arguments (`fields=`,
`value_attribute=` and the others below) go to `to_candidates`. `document_id` defaults to the
id that you gave LangExtract, and each candidate's id is the index of its extraction.

`result` is an `lx.data.AnnotatedDocument`, or a dict from the JSONL LangExtract writes.
LangExtract is never imported. Per extraction:

- `field` is the `extraction_class`, renamed through `fields={"class": "field"}` if you pass it;
- `value` is the `value` attribute (`value_attribute=` to change it), or the `extraction_text`;
- `unit` is the `unit` attribute (`unit_attribute=`);
- `key` is the `key` attribute (`key_attribute=`);
- `evidence` is a list. The first item is the value item: the `char_interval`, converted to
  bytes, with the `extraction_text` as its text.

These attributes add evidence items:

| Attribute | Evidence item |
|---|---|
| `sign_text`, `scale_text`, `unit_text`, `key_text`, `field_text` | A quote with the role `sign`, `scale`, `unit`, `key` or `field`. |
| `source_url`, `source_retrieved`, `source_quote` | One `external` item. All three must hold text. |
| `knowledge` | One `knowledge` item. |

A quote has no offsets. groundgate finds it near the value and writes the span to the receipt.
The adapter skips an attribute that is blank or not a string. If your prompt uses other names,
map them: `attributes={"key_text": "row_label"}`.

If LangExtract could not align an extraction, it has no value item. With outside items, the
evidence is those items, and your policy decides. Without them, the extraction is rejected
`NO_EVIDENCE`. `to_candidates` returns the candidates without admitting them, so you can merge
several models' output into one call.

#### The key span

A model cannot count characters, so ask it for the words, and groundgate finds them. Add this to
the prompt for keyed fields, and give `key_text` in the examples:

```text
When words before the value name its key, such as a heading, a table row or column label, or a
bullet, also give "key_text" in the attributes: those words copied verbatim from the text, the
nearest ones before the value. Leave "key_text" out when no words before the value name its key.
```

A cited key puts the key at a table value only by the column rule. That rule also needs the row
label, so ask for `field_text` too, and give the field its `aliases`. In this made-up table, the
first two extractions cite the scale, the row and the column. The third cites nothing:

```python
from groundgate.adapters.langextract import admit_document

text = "Sales by region (in thousands)\n\nNorth\n\nSouth\n\nWidgets\n\n$\n\n40\n\n$\n\n35"
schema = {
    "fields": {
        "sales": {
            "type": "integer",
            "unit": "USD",
            "keys": ["north", "south"],
            "aliases": ["widgets"],
            "multiple": True,
        }
    }
}


def extraction(quote, value, key, **texts):  # what LangExtract returns for one value
    start = text.index(quote)
    return {
        "extraction_class": "sales",
        "extraction_text": quote,
        "char_interval": {"start_pos": start, "end_pos": start + len(quote)},
        "attributes": {"value": value, "unit": "USD", "key": key, **texts},
    }


cited = {"scale_text": "(in thousands", "field_text": "Widgets"}
result = {
    "text": text,
    "extractions": [
        extraction("40", "40000", "north", key_text="North", **cited),
        extraction("35", "35000", "south", key_text="South", **cited),
        extraction("35", "35000", "south"),
    ],
}
for d in sorted(admit_document(result, schema).decisions, key=lambda d: d.candidate_id):
    print(f"{d.outcome:<19} {d.key:<6} {d.value:<6} {' '.join(d.codes)}".rstrip())
```

```text
admitted            north  40000  VALUE_DERIVED KEY_CITED
admitted            south  35000  VALUE_DERIVED KEY_CITED
needs_verification  south  35000  PART_MISSING KEY_NOT_AT_VALUE
```

The third value misses its scale and its key, so a person checks it.

### Report

```python
from groundgate.report import render

html = render(receipt_dict, text, candidates, schema=schema, policy=policy, judgments=judgments)
```

With `schema` (and `policy`, `judgments`, `references` and `document_source`, if you used them),
the page re-derives the receipt first and says whether it matched. `layout=` and `title=` are optional. The page is one self-contained HTML file with no scripts.

## Command line

```bash
groundgate extract FILE [--pages 1-3,7] [-o doc.txt] [--layout layout.json]
groundgate admit   DOC SCHEMA CANDIDATES [--policy P] [--judgments J] [--document-id ID] [-o receipt.json]
groundgate verify  RECEIPT DOC SCHEMA CANDIDATES [--policy P] [--judgments J]
groundgate report  RECEIPT DOC SCHEMA CANDIDATES [--policy P] [--judgments J] [--layout L] [--title T] [-o report.html]
groundgate schema  SCHEMA [--references R] [-o extractor.schema.json]
```

`admit`, `verify` and `report` also take `--references R` and `--document-source URL`. `schema`
writes the extractor schema, with the ids of the references in `R` as its refs. `DOC` may be `-`
for standard input. Exit codes: 0 success, 1 the receipt does not match its
inputs, 2 invalid input.

## Receipts

A receipt holds the spec version, the document's id, SHA-256 and source, each reference's id,
SHA-256 and source, the SHA-256 of the schema and policy, one decision per candidate, the coverage
findings, the judgments that applied, a summary and its own hash. Hashes are over RFC 8785
canonical JSON with a `groundgate/<spec version>:<kind>` prefix, so a receipt made in one language
verifies in another. `verify` recomputes everything from the inputs. Any change to the document,
its source, a reference, the schema, the policy, a judgment, a candidate or a decision shows up as
a problem.

**Versions.** A receipt names the spec version it was decided under, and `verify` accepts only the
version it implements. A groundgate that implements spec 0.5 reports a 0.4 receipt as one problem
and checks nothing more. So pin the groundgate version where you keep receipts. To verify an old
receipt, install the release for its spec version in a separate environment, for example
`pip install groundgate==0.2.0` for spec 0.2.
