# groundgate report

Release: main, before 1.0.0 (spec 0.13).

`groundgate report` verifies a receipt, then renders an HTML review page for it. A person uses
the page to check each flagged value against the cited text.

## Command

```text
groundgate report RECEIPT DOC SCHEMA CANDIDATES [options] [--layout FILE] [--title TEXT] [-o FILE]
groundgate report --store DIR PACKET [--layout FILE] [--title TEXT] [-o FILE]
```

| Option | Default | Effect |
|---|---|---|
| `--policy`, `--judgments`, `--references`, `--document-source` | none | The same inputs that `admit` got. |
| `--pin`, `--outline`, `--completeness`, `--doubt`, `--pack FILE` | none | The same files that `admit` got. |
| `--pack-dir DIR` | none | A folder of pack files, found by the digests in the receipt. |
| `--layout FILE` | none | The layout JSON from `read`. The page then shows page numbers. |
| `--title TEXT` | see below | The page title. |
| `-o`, `--output FILE` | stdout | Write the HTML to this file. |
| `--store DIR` | none | Get the receipt, each input and the layout of the packet `PACKET`. |

The default title is the document id of the receipt. If the id is `null`, the title is the file
name of `DOC`. With `--store`, the command takes the layout of the reading that the packet names,
unless you give `--layout`.

## Example

```bash
uv run groundgate report receipt.json docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json -o report.html
```

The command prints nothing. `report.html` is one HTML file of about 9.5 KB with no scripts. Its
title is `doc.txt`.

## Result

| Exit code | Meaning |
|---|---|
| 0 | The receipt matches, and the command writes the page. |
| 1 | The receipt does not match. The command writes no page. |
| 2 | Invalid input, or an input that is not in the store. |

When the receipt does not match, stderr has each problem and one more line:

```text
mismatch: summary differs from the re-derived receipt
mismatch: decision count differs from the re-derived receipt
groundgate: not rendering a receipt that does not match
```

## Errors

Each error exits 2. A usage error prints `groundgate: error: <message>`. An input error prints
`groundgate: <message>` (`PacketError`, `ValueError` or `OSError`).

| Message | Cause |
|---|---|
| `report requires RECEIPT DOC SCHEMA CANDIDATES, or --store DIR PACKET` | An input is missing. |
| `with --store, report gets each input from the packet: remove ...` | An input option is given with `--store`. |
| `the layout was extracted from a different document` | The layout is of another text. |
| `input deleted: ...` or `input missing: ...` | An input of the packet is not in the store (`InputGone`). |

## See also

- [Review flagged facts and keep receipts](../howto/review.md), sections 2 and 3.
- [Guide: Report](../guide.md#report) gives `render` in Python.
- [Guide: Command line](../guide.md#command-line).
