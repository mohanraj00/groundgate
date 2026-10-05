# Guide

groundgate takes four inputs and returns a receipt:

- a **document**: the text the facts came from;
- a **schema**: the fields you want, with their types and units;
- **candidates**: the facts an extractor proposed, each citing a span of the document;
- a **policy** (optional): a few knobs, with defaults.

Every candidate gets one decision: `admitted`, `needs_verification` or `rejected`, with reason
codes. [SPEC.md](../SPEC.md) is the normative version of everything below; this page is the
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
plain text, returns NFC text, drops text a reader can't see, and for PDFs records the page and
box of every word so the report can show page numbers.

## Schema

```json
{"fields": {
   "max_daily_dose": {"type": "number", "unit": "mg", "comparator": "le", "required": true},
   "tablet_strengths": {"type": "number", "unit": "mg", "multiple": true},
   "pediatric_min_age": {"type": "integer", "unit": "years", "minimum": "0"}
 },
 "units": {"inHg": {"suffix": ["inches Hg", "in. Hg"]}}}
```

| Key | Default | Meaning |
|---|---|---|
| `type` | `"number"` | `number`, `integer` or `string`. |
| `unit` | `null` | The unit code the value must carry, in the candidate and in the text. |
| `comparator` | `"eq"` | What the field means relative to the number: `eq`, `gt`, `ge`, `lt`, `le`, `approx`, `range`. A qualifier in the text that implies a different comparator flags `QUALIFIED_VALUE`. |
| `minimum`, `maximum` | `null` | Bounds, as decimal strings or integers. Outside them is `RANGE_INVALID`. |
| `required` | `false` | A required field with nothing admitted or flagged is listed in the receipt's `coverage`. |
| `multiple` | `false` | The field holds a list, so different values don't conflict. |
| `keys` | `null` | The conditions a value can belong to, in the document's words. Each candidate names one as `key`. |

The comparator is how a field says "up to" is fine. `max_daily_dose` above is `le`, so "up to
4,000 mg" admits; an `eq` field citing the same text is flagged.

**Units.** The built-in table covers `USD`, `EUR`, `GBP`, `INR`, `%`, `mg`, `mcg`, `g`, `kg`,
`mL`, `L`, and `minutes` through `years`. A unit is found when a prefix (`$`) ends at the number,
or a suffix (`mg`, `dollars`) starts within `unit_window` code points after it, in the same
sentence. Only the first suffix of any known unit counts, so in "10 mcg (maximum 500 mg)" the 10
is mcg, never mg. `units` in the schema adds codes or replaces built-in ones. A code with no surfaces
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
conflict when they share a key. The receipt echoes the key. Rows of a flattened table share one
sentence, so a key swapped inside a table is not caught.

## Candidates

```json
{"id": "c1", "field": "max_daily_dose", "value": "4000", "unit": "mg",
 "evidence": {"start": 120, "end": 128, "text": "4,000 mg"},
 "confidence": 0.93, "proposer": "gemini-3.6-flash"}
```

- `value` is a string, or a JSON integer. Write decimals as strings (`"0.5"`), never as floats.
- `evidence` is a **UTF-8 byte** span, half-open. `text` is what the extractor quoted; when it
  differs from the text at the span, the fact is flagged `NON_VERBATIM_EVIDENCE`.
- `search_region` limits where re-anchoring may look. It defaults to the whole document.
- `key` names the condition on a keyed field. On other fields it is ignored.
- Any other key (a proposer name, a chunk id) is kept, ignored by the checks, and covered by the
  candidate's hash.

Most extractors give character offsets. Convert them before you build candidates:

```python
start_byte = len(text[:start_char].encode("utf-8"))
```

The LangExtract adapter does this for you.

## Policy

| Key | Default | Meaning |
|---|---|---|
| `min_confidence` | `null` | Below this, a candidate is flagged `LOW_CONFIDENCE`. |
| `unit_window` | `24` | How far after a number a unit suffix may start, in code points. |
| `reanchor` | `true` | When the cited span misses the value but the quote occurs exactly once elsewhere with the right value and unit, move the evidence there (`EVIDENCE_REANCHORED`). |

## Decisions

Checks run in a fixed order and the first failure rejects:

`CANDIDATE_INVALID`, `FIELD_UNKNOWN`, `NULL_STRING_LITERAL`, `TYPE_INVALID`, `RANGE_INVALID`,
`UNIT_INVALID`, `KEY_INVALID`, `NO_EVIDENCE`, `SPAN_INVALID`, `VALUE_NOT_IN_EVIDENCE`,
`UNIT_NOT_IN_EVIDENCE`.

A fact that passes them all is checked for flags. Any flag makes it `needs_verification`:

`NON_VERBATIM_EVIDENCE`, `QUALIFIED_VALUE`, `SCALE_WORD`, `KEY_NOT_AT_VALUE`, `LOW_CONFIDENCE`,
`CONFLICTING_CANDIDATES`.

`CONFLICTING_CANDIDATES` is set on every candidate for a single-valued field (and key) when two
of them passed the checks with different values. groundgate never picks between them. That is also why
it helps to send several proposers' candidates through one `admit` call: disagreement becomes a
flag. It only helps when they disagree.

A decision carries `candidate_id`, `candidate_sha256`, `field`, `key`, `outcome`, `codes`, the
canonical `value`, the candidate's `unit`, and the `evidence` span the decision rests on (the re-anchored
one, if it moved).

## How values are read

SPEC §4 has the exact rules. This is what they mean for your documents.

**Numbers.** groundgate reads numbers written with ASCII digits, `0` to `9` (spec 0.3):

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
| `२०००`, `2,०००` | other digits, such as Devanagari, wait for a locale input (#60), and ASCII digits next to them are no number |

A candidate value written in other digits, such as `"२०००"`, is `CANDIDATE_INVALID`.

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

| Code | Usual cause | What to do |
|---|---|---|
| `CANDIDATE_INVALID` | A decimal is sent as a JSON float, such as `0.5`. | Send it as a string: `"0.5"`. |
| `SPAN_INVALID` or `VALUE_NOT_IN_EVIDENCE` | Character offsets are sent as byte offsets, and the text has a character outside ASCII before the span. | Convert the offsets (see [Candidates](#candidates)). Send `evidence.text` too, so that re-anchoring can find the quote. |
| `VALUE_NOT_IN_EVIDENCE` | The text writes the number in a form that groundgate does not read (see above). | A person checks the fact. |
| `UNIT_NOT_IN_EVIDENCE` | The unit is not in the table, starts after `unit_window`, is past a sentence end, or is a per-unit such as `mg/kg`. | Add the unit's surfaces in the schema's `units`, or give the field its own code, such as `mg/kg`. |
| `KEY_INVALID` | The candidate's `key` is not written exactly as one of the field's `keys`. | Send the key as the schema writes it. |
| `QUALIFIED_VALUE` | The text says "up to" and the field is `eq`. | If the field is a limit, set its `comparator`. If not, a person checks the fact. |
| `SCALE_WORD` | The value is sent as written, without its scale word. | Send the scaled value. |
| `KEY_NOT_AT_VALUE` | The value is under a different condition in the text. | A person checks the fact. Inside a flattened table every key is at every value, so this flag cannot find a swap there. |
| `CONFLICTING_CANDIDATES` | Two proposers read different values. | A person picks one. groundgate never picks. |
| `NON_VERBATIM_EVIDENCE` | The extractor changed the quote. | A person compares the quote with the text at the span. |

## Python API

```python
import groundgate as gg

receipt = gg.admit(text, schema, candidates, policy=None, document_id=None)
receipt.decisions  # tuple of gg.Decision
receipt.coverage  # tuple of (field, "REQUIRED_FIELD_MISSING")
receipt.to_dict()  # the JSON receipt, including receipt_sha256

check = gg.verify(receipt_dict, text, schema, candidates, policy=None)
check.ok, check.problems  # True, () when the receipt re-derives exactly
```

`schema` and `policy` can be dicts or `gg.Schema` / `gg.Policy`. Invalid inputs raise
`gg.PacketError`. `gg.digest(kind, obj)` and `gg.jcs(obj)` are the hashing primitives, if you
need to compute a candidate's hash yourself.

### LangExtract

```python
from groundgate.adapters.langextract import admit_document, to_candidates

receipt = admit_document(result, schema)
```

`result` is an `lx.data.AnnotatedDocument`, or a dict from the JSONL LangExtract writes.
LangExtract is never imported. Per extraction:

- `field` is the `extraction_class`, renamed through `fields={"class": "field"}` if you pass it;
- `value` is the `value` attribute (`value_attribute=` to change it), or the `extraction_text`;
- `unit` is the `unit` attribute (`unit_attribute=`);
- `evidence` is the `char_interval`, converted to bytes, quoting the `extraction_text`.

An extraction LangExtract could not align has no interval and is rejected `NO_EVIDENCE`.
`to_candidates` returns the candidates without admitting them, so you can merge several models'
output into one call.

### Report

```python
from groundgate.report import render

html = render(receipt_dict, text, candidates, schema=schema, layout=None, title=None)
```

With `schema` (and `policy`, if you used one), the page re-derives the receipt first and says
whether it matched. The page is one self-contained HTML file with no scripts.

## Command line

```bash
groundgate extract FILE [--pages 1-3,7] [-o doc.txt] [--layout layout.json]
groundgate admit   DOC SCHEMA CANDIDATES [--policy P] [--document-id ID] [-o receipt.json]
groundgate verify  RECEIPT DOC SCHEMA CANDIDATES [--policy P]
groundgate report  RECEIPT DOC SCHEMA CANDIDATES [--policy P] [--layout L] [--title T] [-o report.html]
```

`DOC` may be `-` for standard input. Exit codes: 0 success, 1 the receipt does not match its
inputs, 2 invalid input.

## Receipts

A receipt holds the SHA-256 of the document, schema and policy, one decision per candidate, the
coverage findings, a summary and its own hash. Hashes are over RFC 8785 canonical JSON with a
`groundgate/<spec version>:<kind>` prefix, so a receipt made in one language verifies in another.
`verify` recomputes everything from the inputs; any change to the document, schema, policy, a
candidate or a decision shows up as a problem.

**Versions.** A receipt names the spec version it was decided under, and `verify` accepts only the
version it implements. A groundgate that implements spec 0.3 reports a 0.2 receipt as one problem
and checks nothing more. So pin the groundgate version where you keep receipts. To verify an old
receipt, install the release for its spec version in a separate environment, for example
`pip install groundgate==0.2.0` for spec 0.2.
