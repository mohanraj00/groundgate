# gg.feedback_message()

Release: main, before 1.0.0 (spec 0.13).

`feedback_message` builds a text for the extractor from one decision. The text says what to
cite in a new answer. It returns `None` when a new answer cannot fix the decision.

## Call

```text
gg.feedback_message(decision, candidate, schema, text=None, references=None, packs=())
    -> str | None
```

- `decision`: one `gg.Decision` from a receipt.
- `candidate`: the candidate that the decision decided. Its digest must be
  `decision.candidate_sha256`.
- `schema`, `packs`: the same schema and packs that you gave to `admit`.
- `text`, `references`: the document text and the references that you gave to `admit`. A
  missing key with `KEY_NOT_AT_VALUE` needs them to find the table row of the value.

## Example

```python
import groundgate as gg

text = "Amounts (in thousands)\n\nRevenue 5"
schema = {"fields": {"revenue": {"type": "integer", "unit": "USD", "aliases": ["Revenue"]}}}
candidate = {
    "id": "c1",
    "field": "revenue",
    "value": "5000",
    "unit": "USD",
    "evidence": [{"text": "5"}],
}
decision = gg.admit(text, schema, [candidate]).decisions[0]
print(decision.outcome, decision.codes, decision.missing)
print(gg.feedback_message(decision, candidate, schema, text=text))
```

```text
needs_verification ('PART_MISSING',) ('scale', 'unit')
Field "revenue": you gave the value "5000" with value "5".
- PART_MISSING: The value needs a sign, a scale or a unit that no evidence item supports.
- Cite the scale with a "scale" item.
- Cite the unit with a "unit" item.
- Also cite the words that name the field with a "field" item.
```

## Result

A string. The first line gives the value and its quotes. Then each reason code that is not
informational, each missing part and each part that failed gets one line. Send it to the extractor
with the next request.

`feedback_message` returns `None` in these cases:

- The decision is `admitted`.
- A code of the decision is not one that a new citation can fix, such as
  `VALUE_NOT_IN_EVIDENCE`.
- A unit or a key is missing, and the field has no `aliases`.

## Errors

- `ValueError("candidate digest does not match the decision")`: the candidate is not the one
  that the decision decided.
- `gg.PacketError("give the packs to Schema.from_dict when the schema is a Schema")`: you gave
  a `gg.Schema` and also `packs`.
- The messages of `Schema.from_dict` for an invalid schema dict.

## See also

- [Run extraction and evidence repairs](../howto/feedback.md) shows a feedback loop.
- [Python API](../guide.md#python-api) in the guide.
