# gg.candidate_schema()

Release: main, before 1.0.0 (spec 0.13).

`candidate_schema` returns the JSON Schema of one candidate (SPEC §2.5). It is the file
`candidate.schema.json` in the package. Use it to check candidates in your own code.

## Call

```text
gg.candidate_schema() -> dict
```

The function takes no arguments.

## Example

```python
import groundgate as gg

schema = gg.candidate_schema()
print(schema["title"])
print(schema["required"])
print(list(schema["properties"]))
```

```text
groundgate candidate, spec 0.13
['field', 'value']
['id', 'field', 'value', 'unit', 'key', 'proposer', 'evidence', 'search_region', 'confidence']
```

## Result

A new dict for each call, a JSON Schema of draft 2020-12. It describes each candidate that step
1 of SPEC §3 accepts. groundgate does not validate with this schema: step 1 is the definition.

The schema does not check four things:

- a `ref` that names no reference;
- two document or reference items with the same role other than `field`;
- more than 8 field items;
- an integer written with a fraction, such as `2.0`.

For the structured output of a model, use [`gg.extractor_schema()`](extractor-schema.md). It
gives each field of your schema its own candidate shape.

## Errors

`candidate_schema` raises no groundgate error.

## See also

- [Candidates](../guide.md#candidates) in the guide.
- [`gg.admit()`](admit.md) rejects a malformed candidate with `CANDIDATE_INVALID`.
