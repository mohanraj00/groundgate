# Read documents, and DOCX and XLSX files

`groundgate read` turns a file into the text that the extractor and `admit` both read. With
`--document`, it also writes `document@1`: the same text plus a list of nodes, such as the
headings, the tables and the cells. This page shows how to read a file with its nodes, what the
nodes hold, and how to give them to `extract`. The workbook and the numbers are made up.

The [guide](../guide.md) lists each format that `read` takes. The format of `document@1` is in
the [design note](../design/document-model.md).

## 1. Read a file with its nodes

`read` takes PDF, HTML, XML, DOCX, XLSX and plain text. DOCX and XLSX need no extra package:
the reader uses the standard library only (#529). The workbook below has one sheet with a
small statement. The code writes the file, as your app gets it from a user.

```python
import json
import tempfile
import zipfile
from pathlib import Path

import groundgate as gg
from groundgate.read.document import Document, read_document

X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"


def rels(target, kind):
    return (
        f'<Relationships xmlns="{P}"><Relationship Id="rId1" Type="{R}/{kind}" '
        f'Target="{target}"/></Relationships>'
    )


def cell(ref, value):
    if isinstance(value, str):
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    return f'<c r="{ref}"><v>{value}</v></c>'


rows = [
    ["(in thousands)"],
    [None, "2025", "2024"],
    ["Net sales", 84210, 79605],
    ["Cost of sales", 61930, 58114],
]
sheet = "".join(
    f'<row r="{r + 1}">'
    + "".join(cell(f"{'ABC'[c]}{r + 1}", v) for c, v in enumerate(row) if v is not None)
    + "</row>"
    for r, row in enumerate(rows)
)
members = {
    "_rels/.rels": rels("xl/workbook.xml", "officeDocument"),
    "xl/workbook.xml": (
        f'<workbook xmlns="{X}" xmlns:r="{R}"><sheets>'
        '<sheet name="Operations" sheetId="1" r:id="rId1"/></sheets></workbook>'
    ),
    "xl/_rels/workbook.xml.rels": rels("worksheets/sheet1.xml", "worksheet"),
    "xl/worksheets/sheet1.xml": (
        f'<worksheet xmlns="{X}"><sheetData>{sheet}</sheetData></worksheet>'
    ),
}
work = Path(tempfile.mkdtemp())
with zipfile.ZipFile(work / "statement.xlsx", "w") as z:
    for name, xml in members.items():
        z.writestr(name, xml)

extracted, doc = read_document(work / "statement.xlsx")
print(doc.text.replace("\t", "\\t"))
```

The output shows each tab as `\t`:

```text
Operations

(in thousands)
2025\t2024
Net sales\t84210\t79605
Cost of sales\t61930\t58114
```

`read_document` gives the same `Extracted` as `groundgate.read.read`, and also the `Document`.
The text is the same text that `read` gives: the nodes never change it. On the command line, one
command writes both:

```bash
groundgate read statement.xlsx -o doc.txt --document doc.json
```

`doc.txt` holds the text, and `doc.json` holds `document@1` as canonical JSON (RFC 8785). So the
same reading gives the same bytes.

## 2. What document@1 holds

The object has seven members:

| Member | What it holds |
|---|---|
| `format` | `document@1` |
| `source` | The store key of the bytes of the file |
| `text` | The store key of the text, so the nodes name the one text they belong to |
| `reader` | The name and the version of the reader. A read with OCR names tesseract too. |
| `options` | The options of the read: `pages` |
| `doubt` | The spans of OCR words with a confidence below 1. See [Read scanned PDFs](scanned-pdfs.md). |
| `nodes` | The nodes, in text order |

Each node is a UTF-8 byte span into the text. A node has a `kind`: `heading`, `paragraph`,
`list`, `item`, `table`, `row` or `cell`. It has a `parent`, the id of the node that holds it,
and a `basis`: `markup` for HTML, XML, DOCX and XLSX, `layout` for PDF blocks and tables, OCR
paragraphs and text files, and `rules` for a PDF table with drawn rules. A heading also has a
`level`. A cell also has its grid place: `row`, `column`, `rows`, `columns` and `header`.

```python
data = doc.text.encode("utf-8")
for node in doc.nodes:
    where = f" row {node.row} column {node.column}" if node.kind == "cell" else ""
    print(node.id, node.kind, node.parent, repr(data[node.start : node.end].decode()) + where)
```

```text
0 heading None 'Operations'
1 table None '(in thousands)\n2025\t2024\nNet sales\t84210\t79605\nCost of sales\t61930\t58114'
2 row 1 '(in thousands)'
3 cell 2 '(in thousands)' row 0 column 0
4 row 1 '2025\t2024'
5 cell 4 '2025' row 1 column 1
6 cell 4 '2024' row 1 column 2
7 row 1 'Net sales\t84210\t79605'
8 cell 7 'Net sales' row 2 column 0
9 cell 7 '84210' row 2 column 1
10 cell 7 '79605' row 2 column 2
11 row 1 'Cost of sales\t61930\t58114'
12 cell 11 'Cost of sales' row 3 column 0
13 cell 11 '61930' row 3 column 1
14 cell 11 '58114' row 3 column 2
```

The sheet name is a heading of level 1, and the sheet is one table. The row and the column of a
cell are its place in the sheet, from 0. Cell A2 is empty, so row 1 has no cell at column 0,
and its text has no tab before `2025`. The grid place still puts `2025` in column 1.

The `Document` has lookups: `node`, `at`, `of_kind`, `find`, `children`, `section` and `cell`.
`find` gives each exact occurrence of a string with the innermost node that holds it. `cell`
gives the cell at a grid place of a table:

```python
for match in doc.find("79605"):
    print(match.start, match.end, match.node.kind, match.node.row, match.node.column)
print(doc.cell(1, 1, 2).id)
```

```text
53 58 cell 2 2
6
```

To use a `doc.json` again, load it with `Document.from_dict` and the text. The loader checks
the object against the text, because a file or a store can hold anything. It raises
`DocumentError` at the first fault, for example a `text` key of another text.

```python
(work / "doc.json").write_bytes(doc.to_json())
again = Document.from_dict(json.loads((work / "doc.json").read_text()), doc.text)
print(len(again.nodes), again.to_dict()["format"])
```

```text
15 document@1
```

## 3. Give the document to extract

`admit` never reads a node. It reads the text and the spans that the candidates cite, as for
any other text. The nodes help the extractor: give the `Document` to `extract` in place of the
text.

- The runner packs whole nodes into the chunks that it sends, so a table stays with its header
  rows and the headings above it.
- The runner puts a marker such as `⟦9⟧` before the text of each cell in the prompt. A reply can
  then cite the cell as `{"source": "document", "role": "value", "node": 9}`, with no quote.
- The runner finds the span of the cell and gives `admit` only offsets. The marker is not in
  the text that `admit` checks.

The client below is a fixed example, as in [Run extraction and evidence repairs](feedback.md).
It reads the cell ids from the markers in the region text, and cites each part as a node.
The region text holds a row such as `⟦8⟧Net sales\t⟦9⟧84210\t⟦10⟧79605`, with `\t` for a
tab.

```python
import re

from groundgate.extract import extract

schema = {
    "fields": {"net_sales": {"type": "integer", "keys": ["2025", "2024"], "aliases": ["net sales"]}}
}


def client(prompt):
    request = json.loads(prompt.split("\n", 1)[1])
    marked = request["sources"][0]["text"]
    ids = {text: int(n) for n, text in re.findall(r"⟦(\d+)⟧([^\t\n]+)", marked)}

    def item(role, text):
        return {"source": "document", "role": role, "node": ids[text]}

    candidate = {
        "field": "net_sales",
        "value": "84210000",
        "unit": None,
        "key": "2025",
        "evidence": [
            item("value", "84210"),
            item("scale", "(in thousands)"),
            item("field", "Net sales"),
            item("key", "2025"),
        ],
    }
    return json.dumps({"candidates": [candidate], "not_found": []})


result = extract(doc, schema, client=client, model_id="fixed-example-1")
for d in result.receipt.decisions:
    print(d.field, d.key, d.value, d.outcome, " ".join(d.codes))
```

```text
net_sales 2025 84210000 admitted VALUE_DERIVED KEY_CITED
```

The scale item cites the cell `(in thousands)`, and the value is the cell `84210` times 1,000.
The run record keeps the key of the document and the document itself, so a replay uses the
same nodes.

## 4. DOCX and XLSX files

A DOCX or XLSX file is a zip file of XML. The reader writes the text with the rules of HTML: a
blank line after a block, a line break after a table row, and a tab between two cells.

In a DOCX file:

- A paragraph with a heading style or an outline level is a heading. A numbered paragraph is a
  list item, and adjacent items make one list.
- A table gives its rows and its cells. A merged cell (`gridSpan`, `vMerge`) spans its columns
  and rows.
- A superscript reads `^1` and a subscript `_2`, as in HTML.
- Hidden text gives no text.
- The text is the text after the tracked changes. Deleted text, deleted rows and cells, and
  moved-from text give no text.

In an XLSX file:

- Each sheet gives a heading with the sheet name and one table.
- A number reads as the sheet stores it, not as the sheet shows it. A cell that shows `84,210`
  reads `84210`.
- A merged cell spans its range.
- Hidden sheets, rows and columns give no text.

The second rule of the XLSX list is important for the extractor. The value quote must be the
stored number, as the text has it. Show the extractor the text of `read`, not the sheet as a
program shows it. Then the quotes match.

The reader refuses a file larger than 64 MiB, more than 10,000 members in the zip, a member name
outside the archive, and more than 256 MiB of expanded XML. It refuses a DOCTYPE too, so no XML
entity is loaded. These files are untrusted input.

## Checklist

- Read the file with `groundgate read FILE -o doc.txt --document doc.json`, or with
  `read_document` in Python.
- Give the extractor and `admit` the same text, the text of `read`.
- Give the `Document` to `extract`, so a reply can cite a cell by its node.
- Load a saved `doc.json` with `Document.from_dict`, which checks it against the text.
- For a scanned PDF, read [Read scanned PDFs](scanned-pdfs.md).
