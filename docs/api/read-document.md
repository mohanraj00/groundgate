# groundgate.read.document.read_document()

Release: main, before 1.0.0 (spec 0.13).

`read_document` reads a file as [read()](read.md) does, and also gives its `document@1` model:
the same text plus a flat list of nodes, such as headings, tables and cells.

## Call

```text
read_document(path, pages=None, *, ocr=False, data=None) -> tuple[Extracted, Document]
```

| Argument | Default | What it does |
|---|---|---|
| `path` | | The file. Its suffix selects the format, as for `read`. |
| `pages` | `None` | The PDF pages to read, from 1. The object records them in `options`. |
| `ocr` | `False` | OCR for a scanned PDF page. Each OCR word with a confidence below 1 gets a `doubt` entry. |
| `data` | `None` | The bytes of the file. Then `read_document` does not read `path`. |

The extras are the extras of `read`: `groundgate[pdf]` for a PDF, `groundgate[ocr]` for OCR.

## Example

```python
from groundgate.read.document import read_document

page = b"<h1>Limits</h1><table><tr><th>Item</th><th>2025</th></tr>"
page += b"<tr><td>IRA limit</td><td>$7,000</td></tr></table>"
extracted, doc = read_document("limits.html", data=page)
data = doc.text.encode("utf-8")
for node in doc.nodes:
    print(node.id, node.kind, node.parent, repr(data[node.start : node.end].decode()))
match = doc.find("$7,000")[0]
print(match.node.kind, match.node.row, match.node.column, extracted.text == doc.text)
```

```text
0 heading None 'Limits'
1 table None 'Item\t2025\nIRA limit\t$7,000'
2 row 1 'Item\t2025'
3 cell 2 'Item'
4 cell 2 '2025'
5 row 1 'IRA limit\t$7,000'
6 cell 5 'IRA limit'
7 cell 5 '$7,000'
cell 1 1 True
```

## Result

A tuple of two objects:

- `Extracted`: the same object that `read` gives.
- `Document`: `text`, `nodes`, `source` (the store key of the bytes), `reader`, `options` and
  `doubt`. Each `Node` has `id`, `kind`, `basis`, `parent`, and `start` and `end` as UTF-8 byte
  offsets. A heading has `level`. A cell has `row`, `column`, `rows`, `columns` and `header`.

The lookups are `node`, `at`, `of_kind`, `find`, `children`, `section` and `cell`.
`doc.to_json()` gives canonical JSON (RFC 8785). `Document.from_dict(obj, text)` checks a saved
object against its text. A node is information only: `admit` never reads one.

## Errors

- `ReadError`: `notes.csv: unsupported file type .csv`, `x.txt is not UTF-8`,
  `x.xml: not well-formed XML (...)`, and the PDF, OCR and zip faults of `read`.
- `ImportError`: a PDF without `groundgate[pdf]`.
- `FileNotFoundError` and the other `OSError` types, when `data` is `None` and `path` cannot be
  read. `read_document` reads the file before it checks the suffix.
- `DocumentError` (a `ValueError`): `Document.from_dict` refuses an object, for example
  `the member text is not the key of this text`.

## See also

- [Read documents, and DOCX and XLSX files](../howto/documents.md)
- [Guide: Documents](../guide.md#documents)
- [extract()](extract.md) takes a `Document` in place of the text.
