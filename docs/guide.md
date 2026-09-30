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

The comparator is how a field says "up to" is fine. `max_daily_dose` above is `le`, so "up to
4,000 mg" admits; an `eq` field citing the same text is flagged.

**Units.** The built-in table covers `USD`, `EUR`, `GBP`, `INR`, `%`, `mg`, `mcg`, `g`, `kg`,
`mL`, `L`, and `minutes` through `years`. A unit is found when a prefix (`$`) ends at the number,
or a suffix (`mg`, `dollars`) starts within `unit_window` code points after it, in the same
sentence. `units` in the schema adds codes or replaces built-in ones. A code with no surfaces
matches everywhere, so the unit check becomes a no-op for it.

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
`UNIT_INVALID`, `NO_EVIDENCE`, `SPAN_INVALID`, `VALUE_NOT_IN_EVIDENCE`, `UNIT_NOT_IN_EVIDENCE`.

A fact that passes them all is checked for flags. Any flag makes it `needs_verification`:

`NON_VERBATIM_EVIDENCE`, `QUALIFIED_VALUE`, `SCALE_WORD`, `LOW_CONFIDENCE`,
`CONFLICTING_CANDIDATES`.

`CONFLICTING_CANDIDATES` is set on every candidate for a single-valued field when two of them
passed the checks with different values. groundgate never picks between them. That is also why
it helps to send several proposers' candidates through one `admit` call: disagreement becomes a
flag. It only helps when they disagree.

A decision carries `candidate_id`, `candidate_sha256`, `field`, `outcome`, `codes`, the canonical
`value`, the candidate's `unit`, and the `evidence` span the decision rests on (the re-anchored
one, if it moved).

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
`groundgate/0.1:<kind>` prefix, so a receipt made in one language verifies in another.
`verify` recomputes everything from the inputs; any change to the document, schema, policy, a
candidate or a decision shows up as a problem.
