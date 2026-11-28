# gg.extractor_schema()

Release: main, before 1.0.0 (spec 0.13).

`extractor_schema` returns a JSON Schema for the structured output of a model: an object with a
`candidates` list for one groundgate schema. Give it to the model as its output format.

## Call

```text
gg.extractor_schema(schema, reference_ids=None, packs=()) -> dict
```

- `schema`: a dict or a `gg.Schema`.
- `reference_ids`: the ids of the references that you give to `admit`. With them, the schema
  permits a `reference` item with `ref` set to one of these ids. Default `None`: no reference
  item.
- `packs`: the vocabulary packs that the schema names, as pack objects.

## Example

```python
import json

import groundgate as gg

schema = json.load(open("docs/quickstart/schema.json", encoding="utf-8"))
out = gg.extractor_schema(schema)
print(out["required"], sorted(out["$defs"]))
for shape in out["properties"]["candidates"]["items"]["anyOf"]:
    print(shape["properties"]["field"], shape["properties"]["unit"], shape["properties"]["key"])
```

```text
['candidates'] ['document', 'evidence', 'external', 'knowledge']
{'const': 'ira_limit'} {'const': 'USD'} {'type': 'null'}
{'const': 'phaseout_start'} {'const': 'USD'} {'type': 'null'}
```

## Result

A dict that you can serialise with `json.dumps`. Each field of the schema has its own
candidate shape:

- `field` is the field name;
- `unit` is its unit or `null`;
- `key` is one of its keys or `null`.

Every member is required, and no object takes other members.

The schema has no `id` member and no `$schema` member. Give each candidate an id before
`admit`. A field with no keys gets no evidence role `key`, because a key item on it always
fails. The schema uses only the JSON Schema subset of the strict structured-output modes.

The schema does not check three rules of step 1 (SPEC §3):

- two items with the same role, except `field`;
- more than 8 field items;
- a blank `text`, `url` or `retrieved`.

## Errors

`extractor_schema` raises `gg.PacketError`:

- `the schema has no fields, so an extractor can send no candidate`
- `reference_ids must be a non-empty list of unique non-blank strings`
- The messages of `Schema.from_dict`, such as `schema must be an object with a 'fields' object`.

## See also

- [The extractor's output](../guide.md#the-extractors-output) in the guide.
- [`gg.candidate_schema()`](candidate-schema.md) describes one candidate.
- `groundgate schema schema.json` writes the same schema from the command line.
