# groundgate.adapters.langextract.to_candidates()

Release: main, before 1.0.0 (spec 0.13).

`to_candidates` turns each extraction of a LangExtract result into one groundgate candidate. It
does not admit them, so you can merge the output of several models into one `admit` call.

## Call

```text
to_candidates(document, *, fields=None, value_attribute="value", unit_attribute="unit",
              key_attribute="key", attributes=None) -> list[dict]
```

- `document`: an `lx.data.AnnotatedDocument`, or a dict from the JSONL that LangExtract
  writes. The adapter reads `text`, `extractions`, and for each extraction
  `extraction_class`, `extraction_text`, `char_interval` (`start_pos`, `end_pos`),
  `alignment_status` and `attributes`.
- `fields`: renames an `extraction_class` to a field name, for example `{"limit": "ira_limit"}`.
- `value_attribute`, `unit_attribute`, `key_attribute`: the attributes that give the value,
  the unit and the key.
- `attributes`: renames an evidence attribute, for example `{"key_text": "row_label"}`.

The evidence attributes are `sign_text`, `scale_text`, `unit_text`, `key_text`, `field_text`,
`source_url`, `source_retrieved`, `source_quote` and `knowledge`.

## Example

The `[langextract]` extra is not needed. LangExtract is never imported, so the example uses
small stand-in objects with the same attributes.

```python
import json
from types import SimpleNamespace as Obj

from groundgate.adapters.langextract import to_candidates

text = "The IRA contribution limit is $7,000. The deduction phases out above $79,000.\n"
start = text.index("$7,000")
extraction = Obj(
    extraction_class="ira_limit",
    extraction_text="$7,000",
    char_interval=Obj(start_pos=start, end_pos=start + 6),
    alignment_status="match_exact",
    attributes={"value": "7000", "unit": "USD", "field_text": "IRA contribution limit"},
)
document = Obj(text=text, extractions=[extraction])
print(json.dumps(to_candidates(document)))
```

```text
[{"id": 0, "field": "ira_limit", "value": "7000", "extraction_class": "ira_limit", "alignment_status": "match_exact", "unit": "USD", "evidence": [{"start": 30, "end": 36, "text": "$7,000"}, {"role": "field", "text": "IRA contribution limit"}]}]
```

## Result

A list of candidate dicts, one for each extraction, in order. `id` is the index of the
extraction. The first evidence item is the value item: the `char_interval` as UTF-8 byte
offsets, with the `extraction_text`. A role attribute gives a quote with no offsets, and
groundgate finds it near the value. An extraction with no `char_interval` has no value item. Its
evidence is the outside items, or it has no evidence and `admit` rejects it `NO_EVIDENCE`.
`extraction_class` and `alignment_status` are for the report only.

## Errors

- `PacketError`: `the LangExtract document has no text`.
- `PacketError`: `the LangExtract document text is not NFC; ...`. Normalize the text before
  you call LangExtract.
- `PacketError`: `extraction 0 has a char_interval outside the document text`.
- `ValueError`: `unknown evidence attributes [...]; use names from (...)`, for a bad key in
  `attributes`.

## See also

- [Guide: LangExtract](../guide.md#langextract)
- [admit_document()](admit-document.md) admits the candidates in one call.
