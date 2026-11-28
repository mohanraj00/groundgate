# groundgate pack list

Release: main, before 1.0.0 (spec 0.13).

`groundgate pack list` lists the built-in packs of the wheel and the status of each pack. Use it
to see which packs a schema can name, and whether a pack has a measured route.

## Command

```text
groundgate pack list [--json]
```

| Option | Default | Effect |
|---|---|---|
| `--json` | off | Print the list as JSON, not as a table. |

The list holds each built-in pack other than the base pack `en`. The base pack is part of the core.

## Example

```bash
uv run groundgate pack list
```

```text
id	version	type	status
annual-reports	1.0.0	kind	example
benefit-summaries	1.0.0	kind	example
component-datasheets	1.0.0	kind	example
electronics	1.0.0	vocabulary	example
finance	1.0.0	vocabulary	example
us-10k	1.0.0	kind	example
us-government-reports	1.0.0	kind	example
```

## Result

The table has one tab-separated line for each pack, sorted by id, then by version. The status is
`example` when the pack has no measured row, and `measured` when it has one or more. Under a
measured pack, each measured row is on an indented line with its `kind`, `field`, `code`,
`documents`, `bound` and `results`.

With `--json`, the command prints a JSON list. Each entry has `id`, `version`, `type`, `status`
and `measured`. The `measured` member holds the measured rows, and it is `[]` for an example pack.

The command exits 0.

## Errors

The command has no input, so it has no input error. A usage error, such as `pack` with no step,
exits 2.

## See also

- [Guide: Python API](../guide.md#python-api) gives the built-in packs, the kind packs and their
  templates.
- [Keep pack files with receipts](../howto/keep-packs.md) shows how to keep your own packs.
