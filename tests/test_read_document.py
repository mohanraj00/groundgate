"""The document model: document@1, its loader and its lookups (#507)."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import test_read
from test_read_grid import QUESTIONS, _rules

from groundgate.cli import main
from groundgate.read import read
from groundgate.read.document import Document, DocumentError, read_document
from groundgate.read.nodes import MAX_DEPTH, MAX_NODES
from groundgate.store import key

from pdfgen import make_pdf

ROOT = Path(__file__).parent.parent
TABLE_CASES = json.loads((ROOT / "tests/fixtures/pdf_table_cases.json").read_text())["cases"]


def _fixtures(tmp_path: Path) -> list[tuple[Path, list[int] | None]]:
    """Each test fixture of the reader as a file: the HTML and XML cases of test_read, the hand
    written PDF tables, a ruled PDF table, the PDF of test_read and the example files."""
    out: list[tuple[Path, list[int] | None]] = []
    for test, suffix in ((test_read.test_html, ".html"), (test_read.test_xml, ".xml")):
        for i, (source, _) in enumerate(test.pytestmark[0].args[1]):
            path = tmp_path / f"case{i}{suffix}"
            path.write_text(source, encoding="utf-8")
            out.append((path, None))
    for case in TABLE_CASES:
        if "page" in case:
            path = tmp_path / f"{case['id']}.pdf"
            path.write_bytes(make_pdf([[tuple(line) for line in case["page"]]]))
            out.append((path, None))
    ruled = tmp_path / "ruled.pdf"
    ruled.write_bytes(
        make_pdf([QUESTIONS], drawings=[_rules([72, 250, 540], [720, 700, 660, 620, 580])])
    )
    out.append((ruled, None))
    label = tmp_path / "label.pdf"
    label.write_bytes(
        make_pdf([[(72, 720, "Dosage"), (72, 690, "Start at 500 mg.")], [(72, 720, "Café")]])
    )
    out += [(label, None), (label, [2])]
    out += [(ROOT / "examples/irs-590a/document.txt", None)]
    out += [(ROOT / "examples/irs-590a/report.html", None)]
    out += [(path, pages) for path, pages, _ in test_read._pinned_bench_texts()]
    return out


def test_the_text_bytes_do_not_change_on_each_fixture(tmp_path: Path) -> None:
    fixtures = _fixtures(tmp_path)
    assert len(fixtures) > 20
    for path, pages in fixtures:
        extracted, doc = read_document(path, pages)
        assert extracted == read(path, pages), path.name
        assert doc.text == extracted.text


def test_two_reads_give_the_same_bytes_and_the_loader_takes_them(tmp_path: Path) -> None:
    for path, pages in _fixtures(tmp_path):
        extracted, doc = read_document(path, pages)
        again = read_document(path, pages)[1]
        assert doc.to_json() == again.to_json(), path.name
        loaded = Document.from_dict(json.loads(doc.to_json()), extracted.text)
        assert loaded.nodes == doc.nodes


def _nodes(doc: Document) -> list[tuple[Any, ...]]:
    data = doc.text.encode()
    return [(n.kind, n.basis, n.parent, data[n.start : n.end].decode()) for n in doc.nodes]


def _doc(tmp_path: Path, name: str, body: str | bytes) -> Document:
    path = tmp_path / name
    if isinstance(body, str):
        path.write_text(body, encoding="utf-8")
    else:
        path.write_bytes(body)
    return read_document(path)[1]


HTML = (
    "<h1>Dosage</h1><p>Take <b>one</b> pill.</p><ul><li>a<li>b</ul>"
    "<table><tr><th>Dose</th><th>Max</th></tr>"
    "<tr><td rowspan=2>500 mg</td><td></td></tr><tr><td>x</td></tr></table>"
    "<h2>Storage</h2><p>Cafe\u0301 is dry"
)


def test_html_nodes(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "a.html", HTML)
    assert (
        doc.text
        == "Dosage\n\nTake one pill.\n\na\nb\n\nDose\tMax\n500 mg\nx\n\nStorage\n\nCafé is dry"
    )
    assert _nodes(doc) == [
        ("heading", "markup", None, "Dosage"),
        ("paragraph", "markup", None, "Take one pill."),
        ("list", "markup", None, "a\nb"),
        ("item", "markup", 2, "a"),
        ("item", "markup", 2, "b"),
        ("table", "markup", None, "Dose\tMax\n500 mg\nx"),
        ("row", "markup", 5, "Dose\tMax"),
        ("cell", "markup", 6, "Dose"),
        ("cell", "markup", 6, "Max"),
        ("row", "markup", 5, "500 mg"),
        ("cell", "markup", 9, "500 mg"),
        ("cell", "markup", 9, ""),
        ("row", "markup", 5, "x"),
        ("cell", "markup", 12, "x"),
        ("heading", "markup", None, "Storage"),
        ("paragraph", "markup", None, "Café is dry"),
    ]
    cells = doc.of_kind("cell")
    assert [(c.row, c.column, c.rows, c.columns, c.header) for c in cells] == [
        (0, 0, 1, 1, True),
        (0, 1, 1, 1, True),
        (1, 0, 2, 1, False),
        (1, 1, 1, 1, False),
        (2, 1, 1, 1, False),
    ]
    assert doc.node(0).level == 1 and doc.node(14).level == 2
    assert cells[3].start == cells[3].end == doc.node(9).end  # an empty cell at its row's end


def test_html_blocks_with_blocks_inside_are_no_paragraph(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        "b.html",
        "<div><p>One</p><div>Two</div></div><table><tr><td><p>In a cell</p></td></tr></table>"
        "<h3><p>Heading text</p></h3><p>Open<p>Next</p><span hidden><p>no</p></span>",
    )
    assert _nodes(doc) == [
        ("paragraph", "markup", None, "One"),
        ("paragraph", "markup", None, "Two"),
        ("table", "markup", None, "In a cell"),
        ("row", "markup", 2, "In a cell"),
        ("cell", "markup", 3, "In a cell"),
        ("paragraph", "markup", 4, "In a cell"),
        ("heading", "markup", None, "Heading text"),
        ("paragraph", "markup", None, "Open"),
        ("paragraph", "markup", None, "Next"),
    ]


def test_html_colspan_and_rowspan_give_grid_positions(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        "c.html",
        "<table><tr><td colspan=2>a</td><td rowspan=3>b</td><td>c</td></tr>"
        "<tr><td>d</td><td>e</td><td>f</td></tr><tr><td colspan=x>g</td></tr></table>",
    )
    table = doc.of_kind("table")[0].id
    got = {
        doc.text.encode()[c.start : c.end].decode(): (c.row, c.column, c.rows, c.columns)
        for c in doc.of_kind("cell")
    }
    assert got == {
        "a": (0, 0, 1, 2),
        "b": (0, 2, 3, 1),
        "c": (0, 3, 1, 1),
        "d": (1, 0, 1, 1),
        "e": (1, 1, 1, 1),
        "f": (1, 3, 1, 1),
        "g": (2, 0, 1, 1),
    }
    data = doc.text.encode()

    def at(row: int, column: int) -> str | None:
        cell = doc.cell(table, row, column)
        return None if cell is None else data[cell.start : cell.end].decode()

    assert [at(0, 1), at(2, 2), at(1, 3), at(2, 3), at(9, 0)] == ["a", "b", "f", None, None]


def test_xhtml_empty_cells_and_spans_with_leading_zeros(tmp_path: Path) -> None:
    source = (
        "<table><tr><td/><td>x</td></tr>"
        '<tr><td colspan="000002">A</td><td>B</td></tr></table>'
    )  # review of #521
    path = tmp_path / "x.xhtml"
    path.write_text(source, encoding="utf-8")
    extracted, doc = read_document(path)
    assert extracted == read(path)
    data = doc.text.encode()
    cells = [
        (data[c.start : c.end].decode(), c.row, c.column, c.columns) for c in doc.of_kind("cell")
    ]
    assert cells == [("", 0, 0, 1), ("x", 0, 1, 1), ("A", 1, 0, 2), ("B", 1, 2, 1)]
    table = doc.of_kind("table")[0].id
    b = doc.cell(table, 1, 2)
    assert b is not None and data[b.start : b.end] == b"B"


def test_spl_headings_take_the_depth_of_their_section(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        "spl.xml",
        '<document xmlns="urn:hl7-org:v3"><title>Label</title><section><title>Dosage</title>'
        "<text><paragraph>Take it.</paragraph><list><item>one</item><item>two</item></list>"
        "<table><tbody><tr><td>Dose</td><td>5 mg</td></tr></tbody></table></text>"
        "<section><title>Children</title></section></section>"
        "<section><title>Storage</title></section></document>",
    )
    assert [(n.kind, n.level) for n in doc.of_kind("heading")] == [
        ("heading", 1),
        ("heading", 1),
        ("heading", 2),
        ("heading", 1),
    ]
    assert [n.kind for n in doc.nodes] == [
        "heading", "heading", "paragraph", "list", "item", "item", "table", "row", "cell", "cell",
        "heading", "heading",
    ]  # fmt: skip
    dosage = doc.of_kind("heading")[1].id
    start, end = doc.section(dosage)
    assert doc.text.encode()[start:end].decode().endswith("Children")


def test_other_xml_gives_paragraphs_and_no_lists(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "o.xml", "<r><title>T</title><list><item>a</item></list><p>x</p></r>")
    assert _nodes(doc) == [
        ("paragraph", "markup", None, "T"),
        ("paragraph", "markup", None, "a"),
        ("paragraph", "markup", None, "x"),
    ]


def test_text_files_give_paragraphs_between_blank_lines(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "t.md", "# Not a heading\nline two\n \n\n  para two  \n")
    assert _nodes(doc) == [
        ("paragraph", "layout", None, "# Not a heading\nline two"),
        ("paragraph", "layout", None, "para two"),
    ]


def test_pdf_blocks_tables_and_ruled_tables(tmp_path: Path) -> None:
    case = next(c for c in TABLE_CASES if "page" in c and c.get("expected_table_rows"))
    path = tmp_path / "t.pdf"
    path.write_bytes(make_pdf([[tuple(line) for line in case["page"]]]))
    doc = read_document(path)[1]
    data = doc.text.encode()
    rows = [
        [data[c.start : c.end].decode() for c in doc.children(r.id)]
        for r in doc.of_kind("row")
        if r.basis == "layout"
    ]
    for row in case["expected_table_rows"]:
        assert [cell for cell in row] in rows
    assert all(c.header is None and c.rows == c.columns == 1 for c in doc.of_kind("cell"))

    ruled = tmp_path / "ruled.pdf"
    ruled.write_bytes(
        make_pdf([QUESTIONS], drawings=[_rules([72, 250, 540], [720, 700, 660, 620, 580])])
    )
    doc = read_document(ruled)[1]
    data = doc.text.encode()
    assert {n.basis for n in doc.of_kind("table")} == {"rules"}
    assert [data[c.start : c.end].decode() for c in doc.children(doc.of_kind("row")[1].id)] == [
        "What is the overall deductible?",
        "$500 individual / $1,000 family",
    ]


def test_pdf_prose_is_layout_paragraphs(tmp_path: Path) -> None:
    path = tmp_path / "p.pdf"
    path.write_bytes(make_pdf([[(72, 720, "Dosage"), (72, 600, "Take 5 mg.")], [(72, 720, "x")]]))
    doc = read_document(path)[1]
    assert _nodes(doc) == [
        ("paragraph", "layout", None, "Dosage"),
        ("paragraph", "layout", None, "Take 5 mg."),
        ("paragraph", "layout", None, "x"),
    ]


def test_lookups(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "a.html", HTML)
    data = doc.text.encode()
    at = data.index(b"500 mg")
    cell = doc.at(at, at + 3)
    assert cell is not None and cell.kind == "cell" and cell.row == 1
    assert doc.at(0, len(data)) is None
    assert doc.at(at, at) == cell
    with pytest.raises(ValueError):
        doc.at(5, 2)
    found = doc.find("Café")
    assert [(m.start, m.node and m.node.kind) for m in found] == [
        (data.index("Café".encode()), "paragraph")
    ]
    assert [(m.node and m.node.id) for m in doc.find("x")] == [8, 13]  # "Max" and "x"
    assert doc.find("cafe") == []
    with pytest.raises(ValueError, match="NFC"):
        doc.find("Cafe\u0301")
    assert [n.kind for n in doc.children(5)] == ["row", "row", "row"]
    assert doc.section(0) == (0, len(data))  # "Storage" is a lower heading, so it is inside
    assert doc.section(14) == (doc.node(14).start, len(data))
    two = _doc(tmp_path, "two.html", "<h2>A</h2><p>x</p><h3>B</h3><h2>C</h2>")
    assert two.section(0) == (0, two.text.encode().index(b"\n\nC"))
    with pytest.raises(ValueError, match="not a heading"):
        doc.section(1)
    with pytest.raises(KeyError):
        doc.node(len(doc.nodes))
    with pytest.raises(ValueError, match="not a table"):
        doc.cell(0, 0, 0)
    assert len(doc.of_kind("item")) == 2
    with pytest.raises(ValueError):
        doc.of_kind("section")


GOOD_TEXT = "Dose\t5 mg"
GOOD_NODES = [
    {"id": 0, "kind": "table", "basis": "markup", "parent": None, "start": 0, "end": 9},
    {"id": 1, "kind": "row", "basis": "markup", "parent": 0, "start": 0, "end": 9},
    {"id": 2, "kind": "cell", "basis": "markup", "parent": 1, "start": 0, "end": 4,
     "row": 0, "column": 0, "rows": 1, "columns": 1, "header": None},
    {"id": 3, "kind": "cell", "basis": "markup", "parent": 1, "start": 5, "end": 9,
     "row": 0, "column": 1, "rows": 1, "columns": 1, "header": False},
]  # fmt: skip


def _good() -> tuple[dict[str, Any], str]:
    doc = Document.from_dict(
        {
            "format": "document@1",
            "source": "sha256:" + "0" * 64,
            "reader": {"name": "groundgate.read", "version": "0.13.0"},
            "options": {"pages": None},
            "text": key("text@1", GOOD_TEXT.encode()),
            "nodes": GOOD_NODES,
            "doubt": [{"start": 5, "end": 9, "confidence": 0.5}],
        },
        GOOD_TEXT,
    )
    return doc.to_dict(), GOOD_TEXT


def _set(path: str, value: Any) -> Any:
    def change(obj: dict[str, Any]) -> None:
        *head, last = path.split(".")
        for part in head:
            obj = obj[int(part)] if part.isdigit() else obj[part]  # type: ignore[assignment]
        if value is DELETE:
            del obj[last]  # type: ignore[arg-type]
        elif isinstance(obj, list):
            obj[int(last)] = value
        else:
            obj[last] = value

    return change


DELETE = object()
FAULTS: list[tuple[str, Any, str]] = [
    ("format", "document@2", "format must be"),
    ("extra", 1, "wrong members"),
    ("doubt", DELETE, "wrong members"),
    ("source", "sha256:" + "0" * 63, "not a key"),
    ("text", "sha256:" + "1" * 64, "not the key of this text"),
    ("reader.name", "", "not empty"),
    ("reader.extra", "x", "wrong members"),
    ("options.pages", [0], "page numbers"),
    ("options.pages", [True], "page numbers"),
    ("doubt", {}, "must be a list"),
    ("doubt.0.confidence", 2, "from 0 to 1"),
    ("doubt.0.start", 9, "not empty"),
    ("nodes", {}, "must be a list"),
    ("nodes.0", [], "JSON object"),
    ("nodes.0.kind", "section", "kind must be"),
    ("nodes.0.level", 1, "wrong members"),
    ("nodes.2.header", DELETE, "wrong members"),
    ("nodes.1.id", 7, "id must be 1"),
    ("nodes.1.id", True, "id must be 1"),
    ("nodes.0.basis", "model", "basis must be"),
    ("nodes.0.end", 10, "outside the text"),
    ("nodes.0.end", 9.0, "must be an integer"),
    ("nodes.0.start", -1, "outside the text"),
    ("nodes.2.end", 5, "whitespace"),
    ("nodes.1.start", 9, "empty or reversed"),
    ("nodes.1.parent", 1, "id of a node before it"),
    ("nodes.1.parent", None, "a row must have as parent: table"),
    ("nodes.2.parent", 0, "a cell must have as parent: row"),
    ("nodes.0.parent", 0, "id of a node before it"),
    ("nodes.3.start", 0, "overlaps"),
    ("nodes.2.row", -1, "row must be an integer of 0 or more"),
    ("nodes.2.rows", 0, "rows must be an integer of 1 or more"),
    ("nodes.2.header", "yes", "header must be"),
]


@pytest.mark.parametrize(("path", "value", "error"), FAULTS, ids=[f[0] for f in FAULTS])
def test_the_loader_refuses_each_fault(path: str, value: Any, error: str) -> None:
    obj, text = _good()
    Document.from_dict(obj, text)
    bad = copy.deepcopy(obj)
    _set(path, value)(bad)
    with pytest.raises(DocumentError, match=error):
        Document.from_dict(bad, text)


def test_the_loader_refuses_more_faults() -> None:
    obj, text = _good()
    with pytest.raises(DocumentError, match="NFC"):
        Document.from_dict(obj, "Cafe\u0301")
    with pytest.raises(DocumentError, match="JSON object"):
        Document.from_dict([], text)
    bad = copy.deepcopy(obj)  # a node outside its parent
    bad["nodes"][0]["end"] = 4
    with pytest.raises(DocumentError, match="inside the span of its parent"):
        Document.from_dict(bad, text)
    bad = copy.deepcopy(obj)
    paragraph = {**obj["nodes"][0], "kind": "paragraph"}
    bad["nodes"] = [{**paragraph, "start": 5, "end": 9}, {**paragraph, "id": 1, "end": 4}]
    with pytest.raises(DocumentError, match="not in text order"):
        Document.from_dict(bad, text)
    multi = "é x"
    bad = copy.deepcopy(obj)
    bad["text"] = key("text@1", multi.encode())
    bad["nodes"] = [{**obj["nodes"][0], "start": 1, "end": 4}]
    bad["doubt"] = []
    with pytest.raises(DocumentError, match="character boundary"):
        Document.from_dict(bad, multi)
    bad["nodes"] = [{**obj["nodes"][0], "kind": "paragraph", "start": 0, "end": 2}]
    bad["nodes"].append({**bad["nodes"][0], "id": 1, "start": 0, "end": 4})
    with pytest.raises(DocumentError, match="overlaps"):
        Document.from_dict(bad, multi)
    bad = copy.deepcopy(obj)
    node = obj["nodes"][0]
    bad["nodes"] = [{**node, "id": i, "kind": "paragraph"} for i in range(MAX_NODES + 1)]
    with pytest.raises(DocumentError, match="more than"):
        Document.from_dict(bad, text)


def test_the_loader_refuses_a_deep_chain_of_nodes() -> None:
    """A lookup by span walks the parents of a node, so the loader limits their number (#521)."""
    text = "x"
    chain: list[dict[str, Any]] = []
    for i in range(MAX_DEPTH + 1):
        kind = ("table", "row", "cell")[i % 3]
        node: dict[str, Any] = {"id": i, "kind": kind, "basis": "markup", "start": 0, "end": 1}
        node["parent"] = i - 1 if i else None
        if kind == "cell":
            node.update(row=0, column=0, rows=1, columns=1, header=None)
        chain.append(node)
    obj = {
        "format": "document@1",
        "source": "sha256:" + "0" * 64,
        "reader": {"name": "groundgate.read", "version": "0.13.0"},
        "options": {"pages": None},
        "text": key("text@1", text.encode()),
        "nodes": chain[:MAX_DEPTH],
        "doubt": [],
    }
    assert len(Document.from_dict(obj, text).nodes) == MAX_DEPTH
    obj["nodes"] = chain
    with pytest.raises(DocumentError, match="nodes above it"):
        Document.from_dict(obj, text)


def test_a_reader_stops_at_the_node_limit(tmp_path: Path) -> None:
    path = tmp_path / "many.html"
    path.write_text("<p>x" * (MAX_NODES + 10), encoding="utf-8")
    extracted, doc = read_document(path)
    assert extracted == read(path)
    assert len(doc.nodes) == MAX_NODES  # a next <p> closes each paragraph before the stop


def test_a_reader_stops_at_its_limits_and_the_text_stays(tmp_path: Path) -> None:
    deep = "<div>" * 300 + "x" + "</div>" * 300 + "<p>after</p>"
    path = tmp_path / "deep.html"
    path.write_text(deep, encoding="utf-8")
    extracted, doc = read_document(path)
    assert extracted == read(path)
    assert doc.nodes == ()  # no span ends in the wrong place after the stop
    wide = "<table><tr>" + "<td colspan=99999 rowspan=99999>a</td>" * 5000 + "</tr></table>"
    path.write_text(wide + "<p>b</p>", encoding="utf-8")
    extracted, doc = read_document(path)
    assert extracted == read(path)
    assert all(c.rows <= 1000 and c.columns <= 1000 for c in doc.of_kind("cell"))


def test_cli_read_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "a.html").write_text(HTML, encoding="utf-8")
    out = tmp_path / "doc.json"
    assert main(["read", str(tmp_path / "a.html"), "--document", str(out)]) == 0
    text = capsys.readouterr().out
    assert text == read(tmp_path / "a.html").text
    doc = Document.from_dict(json.loads(out.read_bytes()), text)
    assert out.read_bytes() == doc.to_json()
    assert doc.reader["name"] == "groundgate.read" and doc.options == {"pages": None}
    store = ["read", str(tmp_path / "a.html"), "--document", str(out), "--store", str(tmp_path)]
    assert main(store) == 2
    assert "--store" in capsys.readouterr().err


def test_admit_and_the_core_rules_do_not_import_the_document_model() -> None:
    code = (
        "import sys, groundgate, groundgate.admit, groundgate.text, groundgate.model, "
        "groundgate.canonical, groundgate.codes, groundgate.fold, groundgate.pack;"
        "print(sorted(m for m in sys.modules if m.startswith('groundgate.read')));"
        "import groundgate.read;"
        "print('groundgate.read.document' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.split("\n")[:2] == ["[]", "False"]
