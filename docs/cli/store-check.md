# groundgate store check

Release: main, before 1.0.0 (spec 0.13).

`groundgate store check` checks each object, each log chain and each packet of a store folder.
With `--repair`, it also cuts a torn last line from a log.

## Command

```text
groundgate store check --store DIR [--repair]
```

| Option | Default | Effect |
|---|---|---|
| `--store DIR` | required | The store folder. The folder must exist. |
| `--repair` | off | Cut a torn last line of a log, and print the line. |

The check reads the bytes of each object against its key, the chain of each log, and the
inputs that each packet names. For a packet with a source pin, it compares the source bytes of
its reading with the `source_sha256` of the pin.

## Example

```bash
uv run groundgate admit --store store docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json > /dev/null
uv run groundgate store check --store store
```

```text
checked 5 objects and 0 logs: 0 findings
```

## Result

The command prints these lines, in this order:

- `cut from LOG: TEXT` for each line that `--repair` cut.
- `input deleted: KIND KEY` for each input that `store forget` removed. This is not a finding.
- `not checked: the run record KEY, because its text is not in the store`.
- `finding: ...` for each problem.
- `checked N objects and M logs: K findings`.

An answer log with a torn last line gives a finding. `--repair` cuts the line:

```text
cut from logs/answers/6526a101.../303789f3....jsonl: {"torn": 1
checked 8 objects and 2 logs: 0 findings
```

This output is shortened: the real paths have the full digests, and the `input deleted` lines
of that store are left out.

Exit codes: 0 no finding, 1 one or more findings, 2 invalid input or a store error.

## Errors

| Exit | Message | Cause |
|---|---|---|
| 1 | `finding: ...` | The store has a problem, for example `LOG has a torn last line: it has no line break`. |
| 2 | `groundgate: nostore: the store folder is not there` | The `--store` folder does not exist. The command does not make a folder. |

A `StoreError` or an `OSError` gives exit 2 with the message after `groundgate:`.

## See also

- [The store note](../design/store.md), sections 7 and 8, gives the folder format, the logs and
  the torn write.
- [Guide: Store](../guide.md#store) gives the store contract.
- [groundgate store forget](store-forget.md) removes the document data of a packet.
