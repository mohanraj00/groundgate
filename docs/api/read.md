# groundgate.read.read()

Release: main, before 1.0.0 (spec 0.13).

`read` turns a file into the NFC text that the extractor and `admit` both read. For a PDF, it
also gives the page and the box of each word.

## Call

```text
read(path, pages=None, *, data=None, ocr=False) -> Extracted
```

| Argument | Default | What it does |
|---|---|---|
| `path` | | The file. Its suffix selects the format: `.pdf`, `.xml`, `.html`, `.htm`, `.xhtml`, `.docx`, `.xlsx`, `.txt`, `.text`, `.md` or `.markdown`. |
| `pages` | `None` | The PDF pages to read, from 1. Other formats ignore it. |
| `data` | `None` | The bytes of the file. Then `read` does not open `path`, but the suffix still selects the format. |
| `ocr` | `False` | OCR for a PDF page with no text layer and an image. Other formats ignore it. |

A PDF needs `groundgate[pdf]`. OCR needs `groundgate[ocr]` and the `tesseract` program. DOCX,
XLSX, HTML, XML and text need no extra.

## Example

```python
from groundgate.read import read

doc = read("docs/quickstart/doc.txt")
print(doc.text, end="")
print(doc.layout, doc.warnings, doc.ocr)
print(doc.completeness)
```

```text
The IRA contribution limit is $7,000. The deduction phases out above $79,000.
None () None
{'status': 'complete', 'missing': []}
```

## Result

An `Extracted` with these members:

- `text`: the NFC text. Windows line ends become `\n`.
- `layout`: a `Layout` with the pages and the word boxes, for a PDF only. Otherwise `None`.
- `warnings`: a tuple of strings, for example `doc.txt: no text was extracted`.
- `ocr`: the tesseract version when OCR read a page, otherwise `None`.
- `completeness`: `status` (`complete`, `partial` or `no_text`) and the `missing` pages.

## Errors

- `ReadError` (a `ValueError`): `x.csv: unsupported file type .csv`, `x.txt is not UTF-8`,
  `page.xml: not well-formed XML (...)`, `x.pdf: not a readable PDF (...)`, and the size and
  zip limits of a DOCX or XLSX file.
- `ReadError`: with `ocr=True`, `page N has no text layer, and OCR needs tesseract: ...` and
  the other tesseract faults.
- `ImportError`: `PDF support needs pdfminer.six: pip install 'groundgate[pdf]'`.
- `FileNotFoundError` and the other `OSError` types, when `path` cannot be opened.

## See also

- [Guide: Documents](../guide.md#documents)
- [Read documents, and DOCX and XLSX files](../howto/documents.md)
- [Read scanned PDFs](../howto/scanned-pdfs.md)
- [read_document()](read-document.md) gives the same text with its nodes.
