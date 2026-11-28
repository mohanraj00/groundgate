# groundgate admit

Release: main, before 1.0.0 (spec 0.13).

`groundgate admit` decides each candidate against the document and writes a receipt. It has a
single-document mode and a batch mode for a folder of documents.

## Command

```text
groundgate admit DOC SCHEMA CANDIDATES [--document-id ID] [-o FILE] [--store DIR [--reading KEY]]
groundgate admit --docs DIR --candidates DIR --schema FILE --out DIR [--store DIR]
```

Both modes take `--policy FILE`, `--references FILE`, `--document-source URL`, `--pack FILE`
(once for each pack), `--judgments` and `--doubt`. `DOC` may be `-` for standard input.

| Option | Mode | Effect |
|---|---|---|
| `--document-id ID` | single | The document id in the receipt. Default: `null`. |
| `-o`, `--output FILE` | single | Write the receipt here. Default: stdout, or no receipt with `--store`. |
| `--judgments FILE` | both | Recorded judgments (SPEC §2.6). In batch mode, a folder of `<doc>.json`. |
| `--doubt FILE` | both | A doubt list, or the `document@1` model from `read --document`. In batch mode, a folder of `<doc>.json`. |
| `--pin`, `--outline`, `--completeness FILE` | single | The source pin, the headings for passage fields, and the completeness of the reading. |
| `--layout FILE` | single | The layout from `read`: each decision gets its page and box. |
| `--store DIR` | both | Write the inputs, the receipt and a packet to the store. |
| `--reading KEY`, `--locate` | single | With `--store`: the reading key from `read --store`, and the boxes from its layout. |

In batch mode, `--docs` holds `<doc>.txt` files and `--candidates` holds one `<doc>.json` array
for each document. Write `[]` for a document with no candidates. The document id is `<doc>`.

## Example

```bash
uv run groundgate admit docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json -o receipt.json
```

The command prints nothing. The receipt has 90 lines. Its summary is:

```text
  "summary": {
    "admitted": 1,
    "needs_verification": 1,
    "rejected": 1
  },
```

In batch mode, `docs/` holds `ira.txt` and `cands/` holds `ira.json`:

```bash
uv run groundgate admit --docs docs --candidates cands --schema docs/quickstart/schema.json --out out
```

```text
| Outcome | Total |
|---|---:|
| admitted | 1 |
| needs_verification | 1 |
| rejected | 1 |

| Code | Total |
|---|---:|
| QUALIFIED_VALUE | 1 |
| VALUE_NOT_IN_EVIDENCE | 1 |
```

## Result

In single mode, the command prints the receipt, or writes it to `-o`. With `--store`, it prints
the packet key. In batch mode, `out/<doc>.json` is the receipt of each document. `out/summary.json`
has a `documents` object keyed by `<doc>` and a `totals` object. Each has `outcomes` counts and
`codes` counts. With `--store`, each document entry also has a `packet` member with its packet key.

`admit` exits 0 when it writes a receipt, whatever the outcomes are. It exits 2 for invalid input.

## Errors

Each error exits 2. A usage error prints `groundgate: error: <message>`. An input error prints
`groundgate: <message>` (`PacketError`, `ValueError` or `OSError`). A batch input error stops the
run before it writes a receipt or a packet.

| Message | Cause |
|---|---|
| `admit requires DOC SCHEMA CANDIDATES, or the batch options` | A positional input is missing. |
| `batch admit requires --docs, --candidates, --schema and --out` | One batch option is missing. |
| `batch admit cannot use positional inputs, --output or --document-id` | The two modes are mixed. |
| `--reading needs --store` | `--reading` without `--store`. |
| `DIR: no .txt documents` | The `--docs` folder has no `.txt` file. |
| `cands/other.json is not there; write [] for a document with no candidates` | A document has no candidate file. |
| `summary.txt: summary.json is reserved for the batch summary` | A document is named `summary`. |
| `--out must not be the same folder as --store: DIR` | `--out` is the store folder. |
| `the layout was extracted from a different document` | `--layout` is of another text. |

## See also

- [Check your own model's extractions](../howto/own-model.md) and
  [Review flagged facts and keep receipts](../howto/review.md).
- [Guide: Command line](../guide.md#command-line) gives the batch rules, and
  [Guide: Decisions](../guide.md#decisions) gives the outcomes and codes.
