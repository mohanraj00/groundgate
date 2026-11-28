# groundgate schema check

Release: main, before 1.0.0 (spec 0.13).

`groundgate schema check` finds the settings of a valid schema that make a check fail every
time, or pass for the wrong key or field. Run it in CI before you give the schema to `admit`.

## Command

```text
groundgate schema check SCHEMA [--pack FILE]...
```

| Option | Default | Effect |
|---|---|---|
| `SCHEMA` | required | The groundgate schema JSON. |
| `--pack FILE` | none | A vocabulary pack that the schema names (SPEC §4.8). Repeat it for each pack. |

The check prints one line for each of these settings:

- a field with a `unit` and no `aliases`;
- a field whose `unit` has no forms;
- a field with `keys` and no `aliases`;
- a key in an alias of the same field;
- an alias on two fields, or an alias in a longer alias of another field;
- a `minimum` above the `maximum` on a number or integer field.

## Example

```bash
uv run groundgate schema check docs/quickstart/schema.json
echo "exit $?"
```

```text
field 'ira_limit' has a unit and no aliases: a unit item passes only for a unit next to the number
field 'phaseout_start' has a unit and no aliases: a unit item passes only for a unit next to the number
exit 1
```

Give each field its aliases, for example `"aliases": ["contribution limit"]` and
`"aliases": ["phases out above"]`. The check then prints nothing and exits 0.

## Result

| Exit code | Meaning |
|---|---|
| 0 | No finding. The command prints nothing. |
| 1 | One or more findings, one line each. |
| 2 | The schema is invalid, or a file cannot be read. |

`admit` does not run this check, and a finding does not change a receipt.

## Errors

Each error prints `groundgate: <message>` on stderr and exits 2.

| Message | Cause |
|---|---|
| `field 'x' has unknown type 'float'` | The schema is invalid (`PacketError`). Each schema rule has its own message. |
| `duplicate JSON key 'fields'` | The JSON file repeats a key (`ValueError`). |
| `[Errno 2] No such file or directory: ...` | A file is not there (`OSError`). |

## See also

- [Schema reference: Check a schema](../schema.md#check-a-schema) explains each finding.
- [groundgate schema](schema.md) writes the schema for the extractor.
- [Guide: Command line](../guide.md#command-line).
