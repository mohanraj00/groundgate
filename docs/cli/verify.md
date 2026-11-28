# groundgate verify

Release: main, before 1.0.0 (spec 0.13).

`groundgate verify` decides the candidates again from the inputs and compares the result with a
receipt. Use it to prove that a stored receipt still matches its document, schema and candidates.

## Command

```text
groundgate verify RECEIPT DOC SCHEMA CANDIDATES [options] [--pack-dir DIR]
groundgate verify --store DIR PACKET [--pack-dir DIR]
```

| Option | Default | Effect |
|---|---|---|
| `--policy`, `--judgments`, `--references`, `--document-source` | none | The same inputs that `admit` got. |
| `--pin`, `--outline`, `--completeness`, `--doubt`, `--layout` | none | The same files that `admit` got. |
| `--pack FILE` | none | A pack that the schema names. Repeat it for each pack. |
| `--pack-dir DIR` | none | A folder of pack files. `verify` takes each pack that the receipt names by its digest. |
| `--store DIR` | none | Get the receipt and each input from the packet `PACKET`. |

Give `verify` each input that you gave `admit`. `DOC` may be `-` for standard input. With
`--store`, the packet holds each input, so the command refuses each other input option.

## Example

```bash
uv run groundgate verify receipt.json docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json
```

```text
receipt verified
```

With an empty candidate list in place of `candidates.json`, the receipt does not match:

```text
mismatch: summary differs from the re-derived receipt
mismatch: decision count differs from the re-derived receipt
```

## Result

| Exit code | Meaning |
|---|---|
| 0 | The command prints `receipt verified`. |
| 1 | The receipt does not match its inputs. Each problem is a `mismatch: ...` line on stderr. |
| 2 | Invalid input, or an input that is not in the store. |

A receipt of another spec version gives one problem, which names the release that verifies it.

## Errors

Each error exits 2. A usage error prints `groundgate: error: <message>`. An input error prints
`groundgate: <message>` (`PacketError`, `ValueError` or `OSError`).

| Message | Cause |
|---|---|
| `verify requires RECEIPT DOC SCHEMA CANDIDATES, or --store DIR PACKET` | An input is missing. |
| `with --store, verify gets each input from the packet: remove DOC SCHEMA CANDIDATES` | An input option is given with `--store`. |
| `DIR: the store folder is not there` | The `--store` folder is not there. |
| `input deleted: the text@1 object sha256:... was deleted at ..., reason: ...` | `store forget` removed an input (`InputGone`). |
| `input missing: the packet@1 object sha256:... is not in the store` | The key is not in the store, and the deleted log has no record of it (`InputGone`). |
| `the layout was extracted from a different document` | `--layout` is of another text. |

## See also

- [Review flagged facts and keep receipts](../howto/review.md), sections 5 and 8.
- [Keep pack files with receipts](../howto/keep-packs.md) shows `--pack-dir`.
- [Guide: Receipts](../guide.md#receipts) and [Guide: Command line](../guide.md#command-line).
