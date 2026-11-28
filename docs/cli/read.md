# groundgate read

Release: main, before 1.0.0 (spec 0.13).

`groundgate read` turns a PDF, HTML, XML, DOCX, XLSX or text file into NFC text. The extractor
and `admit` both read this text, so the evidence spans of a receipt point into it.

## Command

```text
groundgate read FILE [-o FILE] [--pages RANGES] [--layout FILE] [--completeness FILE]
                     [--document FILE] [--ocr] [--store DIR]
```

| Option | Default | Effect |
|---|---|---|
| `-o`, `--output FILE` | stdout | Write the text to this file. |
| `--pages RANGES` | all pages | PDF pages to read, for example `1-12,15`. Other formats ignore it. |
| `--layout FILE` | none | Also write the page and word boxes as JSON. PDF only. |
| `--completeness FILE` | none | Also write the completeness of the reading as JSON (SPEC §4.16). |
| `--document FILE` | none | Also write `document@1`: the text key and the nodes, such as headings and tables. |
| `--ocr` | off | OCR a PDF page with no text layer. Needs `groundgate[ocr]` and the `tesseract` program. |
| `--store DIR` | none | Write the source, the text, the layout and a reading to the store, and print the reading key. |

The suffix of `FILE` selects the format: `.pdf`, `.xml`, `.html`, `.htm`, `.xhtml`, `.docx`,
`.xlsx`, or `.txt`, `.text`, `.md` and `.markdown` for text. A PDF needs `groundgate[pdf]`.

## Example

```bash
uv run groundgate read docs/quickstart/doc.txt -o doc.txt --completeness completeness.json
cat completeness.json
```

```text
{"status": "complete", "missing": []}
```

With `--store`, the command prints the reading key. Give that key to `admit --reading`:

```bash
uv run groundgate read --store store docs/quickstart/doc.txt -o doc.txt
```

```text
sha256:b1f92ae34a5012a39c67767dabde61b763267bfc8392942f7521b9895934c430
```

## Result

Without `-o` and `--store`, the command prints the text. With `--store`, it prints the reading
key, and `-o` writes the text. A reader warning goes to stderr as `groundgate: warning: ...`. The
command exits 0.

## Errors

Each error prints `groundgate: <message>` on stderr and exits 2.

| Message | Cause |
|---|---|
| `FILE: unsupported file type .json` | The suffix is not a known format (`ReadError`). |
| `FILE is not UTF-8` | A text file does not decode as UTF-8 (`ReadError`). |
| `FILE: not a readable PDF (...)` | The PDF reader cannot parse the file (`ReadError`). |
| `PDF support needs pdfminer.six: pip install 'groundgate[pdf]'` | The `[pdf]` extra is not installed (`ImportError`). |
| `--layout needs a PDF` | `--layout` with a file that is not a PDF. |
| `argument --pages: bad page range '3-1'` | A range is not `N` or `N-M` with 1 <= N <= M <= 100000 (usage error). |

## See also

- [Read documents, and DOCX and XLSX files](../howto/documents.md) shows `--document` and the nodes.
- [Read scanned PDFs](../howto/scanned-pdfs.md) shows `--ocr`.
- [Guide: Documents](../guide.md#documents) and [Guide: Command line](../guide.md#command-line).
