# groundgate schema

Release: main, before 1.0.0 (spec 0.13).

`groundgate schema` writes the JSON Schema for the output of an extractor. Give it to a model as
its structured output format, so that each candidate has the shape that `admit` reads.

## Command

```text
groundgate schema SCHEMA [--references FILE] [--pack FILE]... [-o FILE]
```

| Option | Default | Effect |
|---|---|---|
| `SCHEMA` | required | The groundgate schema JSON. |
| `--references FILE` | none | A JSON array of references. Their ids become the allowed `ref` values. |
| `--pack FILE` | none | A vocabulary pack that the schema names (SPEC §4.8). Repeat it for each pack. |
| `-o`, `--output FILE` | stdout | Write the JSON Schema to this file. |

## Example

```bash
uv run groundgate schema docs/quickstart/schema.json
```

```text
{
  "type": "object",
  "properties": {
    "candidates": {
      "type": "array",
      "items": {
        "anyOf": [
          {
            "type": "object",
            "properties": {
              "field": {
                "const": "ira_limit"
              },
...
```

The output has 166 lines. The rest has the item for `phaseout_start` and the `$defs` of the
three evidence kinds: `document`, `external` and `knowledge`.

## Result

The command prints one JSON object: a `candidates` array, with one item shape for each field of
the schema. Each item requires `field`, `value`, `unit`, `key` and `evidence`. The command exits 0.

## Errors

Each error prints `groundgate: <message>` on stderr and exits 2.

| Message | Cause |
|---|---|
| `field 'x' has unknown type 'float'` | The schema is invalid (`PacketError`). Each schema rule has its own message. |
| `references must be a list of objects` | The `--references` file is not a JSON list of objects (`PacketError`). |
| `duplicate JSON key 'fields'` | A JSON file repeats a key (`ValueError`). |
| `[Errno 2] No such file or directory: ...` | A file is not there (`OSError`). |

## See also

- [Check a schema](schema-check.md) finds the settings that make a check fail every time.
- [Check your own model's extractions](../howto/own-model.md) gives the schema to a model.
- [Guide: The extractor's output](../guide.md#the-extractors-output) and
  [Guide: Command line](../guide.md#command-line).
