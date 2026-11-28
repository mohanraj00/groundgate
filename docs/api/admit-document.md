# groundgate.adapters.langextract.admit_document()

Release: main, before 1.0.0 (spec 0.13).

`admit_document` admits every extraction of one LangExtract result. LangExtract checks that each
quote is in the source. It does not check the typed value in the attributes: groundgate does.

## Call

```text
admit_document(document, schema, policy=None, *, document_id=None, judgments=None,
               references=None, document_source=None, **options) -> Receipt
```

- `document`: an `lx.data.AnnotatedDocument`, or a dict from the JSONL that LangExtract writes.
- `schema`, `policy`: as for `admit`.
- `document_id`: `None` takes the id that you gave LangExtract (`document_id` of a dict, or
  `_document_id` of an object). An id that LangExtract made itself is random, so the adapter
  leaves it out and the receipt stays the same from run to run.
- `judgments`, `references`, `document_source`: go to `admit`.
- `options`: go to [to_candidates()](to-candidates.md): `fields`, `value_attribute`,
  `unit_attribute`, `key_attribute` and `attributes`.

## Example

The `[langextract]` extra is not needed. This example gives the dict form that LangExtract
writes to JSONL.

```python
from groundgate.adapters.langextract import admit_document

text = "The IRA contribution limit is $7,000. The deduction phases out above $79,000.\n"
schema = {
    "fields": {
        "ira_limit": {"type": "integer", "unit": "USD"},
        "phaseout_start": {"type": "integer", "unit": "USD"},
    }
}


def extraction(field, quote, value):
    start = text.index(quote)
    return {
        "extraction_class": field,
        "extraction_text": quote,
        "char_interval": {"start_pos": start, "end_pos": start + len(quote)},
        "attributes": {"value": value, "unit": "USD"},
    }


result = {
    "document_id": "irs-590a",
    "text": text,
    "extractions": [
        extraction("ira_limit", "$7,000", "7000"),
        extraction("ira_limit", "$7,000", "70000"),
        extraction("phaseout_start", "$79,000", "79000"),
    ],
}
receipt = admit_document(result, schema)
print(receipt.to_dict()["document"]["id"])
for d in sorted(receipt.decisions, key=lambda d: d.candidate_id):
    print(f"{d.candidate_id} {d.field} {d.value} {d.outcome} {' '.join(d.codes)}".rstrip())
```

```text
irs-590a
0 ira_limit 7000 admitted
1 ira_limit 70000 rejected VALUE_NOT_IN_EVIDENCE
2 phaseout_start 79000 needs_verification QUALIFIED_VALUE
```

## Result

The `Receipt` of `admit`: one decision for each extraction. `candidate_id` is the index of the
extraction. To render or verify the receipt, take the candidates again with
`to_candidates(result)`.

## Errors

- `PacketError`: the faults of `to_candidates`, such as `the LangExtract document has no text`
  or a text that is not NFC.
- `PacketError`: an invalid schema, policy or other input that `admit` refuses.
- `ValueError`: `unknown evidence attributes [...]`, for a bad key in `attributes`.
- `TypeError`: an option name that `to_candidates` does not take.

## See also

- [Guide: LangExtract](../guide.md#langextract)
- [to_candidates()](to-candidates.md)
