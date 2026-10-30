"""DOCX and XLSX to text with the standard library (#529). Both are zip files of XML.

The text follows the conventions of ``markup.py``: a block ends with a blank line, a table row
with a line break, and a tab goes between the cells of a row. The nodes are the ones of
docs/design/document-model.md §5.1:

- DOCX: a paragraph with a heading style or an outline level gives a heading. A numbered
  paragraph gives a list item, and adjacent items give one list. A table gives its rows and its
  cells, with ``gridSpan`` and ``vMerge`` as the span of a cell. A superscript run reads ``^``
  and a subscript run ``_``, as in HTML. Hidden runs (``vanish``) give no text.
- XLSX: each sheet gives a heading with the sheet name and one table. The row and the column of
  a cell are its place in the sheet, from 0. A merged cell spans its range. A number reads as
  the sheet stores it, not as the sheet formats it. Hidden sheets, rows and columns give no text.

These files are untrusted input. ``_Zip`` refuses a file larger than MAX_FILE, more than
MAX_MEMBERS members, a member name outside the archive, and a total expanded size larger than
MAX_EXPANDED. ``_parse`` refuses a DOCTYPE, so no entity is declared or loaded, and an element
deeper than MAX_XML_DEPTH.
"""

from __future__ import annotations

import bisect
import io
import posixpath
import re
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.parsers import expat

from . import ReadError
from .markup import _final, _Writer
from .nodes import MAX_COLUMNS, MAX_NODES, MAX_SPAN, Raw, span_number

MAX_FILE = 64 * 2**20  # the bytes of the zip file
MAX_MEMBERS = 10_000
MAX_EXPANDED = 256 * 2**20  # the sum of the expanded sizes of all members
MAX_XML_DEPTH = 512

# The namespaces of the transitional and the strict forms of Office Open XML.
NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main": "w",
    "http://purl.oclc.org/ooxml/wordprocessingml/main": "w",
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main": "x",
    "http://purl.oclc.org/ooxml/spreadsheetml/main": "x",
    "http://schemas.openxmlformats.org/package/2006/relationships": "rel",
    "http://schemas.openxmlformats.org/markup-compatibility/2006": "mc",
}
OFF = {"0", "false", "off"}
_CELL_REF = re.compile(r"([A-Z]{1,3})([0-9]{1,7})")
_HEADING = re.compile(r"heading ([1-9])")


class _Zip:
    """A zip file that passed the checks of the module docstring."""

    def __init__(self, data: bytes, path: Path) -> None:
        self.path = path
        if len(data) > MAX_FILE:
            raise ReadError(f"{path}: the file is larger than {MAX_FILE} bytes")
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
            infos = self.zip.infolist()
        except (zipfile.BadZipFile, ValueError, EOFError) as e:
            raise ReadError(f"{path}: not a zip file ({e})") from e
        if len(infos) > MAX_MEMBERS:
            raise ReadError(f"{path}: the zip file has more than {MAX_MEMBERS} members")
        names: set[str] = set()
        for info in infos:
            parts = re.split(r"[/\\]", info.filename)
            if info.filename.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
                raise ReadError(f"{path}: the member {info.filename!r} is outside the archive")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ReadError(f"{path}: the member {info.filename!r} has an unknown compression")
            if info.filename in names:
                raise ReadError(f"{path}: the member {info.filename!r} occurs two times")
            names.add(info.filename)
        if sum(info.file_size for info in infos) > MAX_EXPANDED:
            raise ReadError(f"{path}: the expanded size is larger than {MAX_EXPANDED} bytes")
        self.names = names
        self.left = MAX_EXPANDED

    def read(self, name: str) -> bytes:
        """The bytes of a member. The read stops at the bytes that are left of MAX_EXPANDED, so
        a member never expands past its limit, whatever size its header gives."""
        if name not in self.names:
            raise ReadError(f"{self.path}: the member {name!r} is not in the file")
        try:
            with self.zip.open(name) as f:
                data = f.read(self.left + 1)
        except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError) as e:
            raise ReadError(f"{self.path}: cannot read the member {name!r} ({e})") from e
        if len(data) > self.left:
            raise ReadError(f"{self.path}: the expanded size is larger than {MAX_EXPANDED} bytes")
        self.left -= len(data)
        return data

    def related(self, part: str) -> dict[str, tuple[str, str]]:
        """The relationships of ``part`` ("" for the package): the id, then the type and the
        member name of the target. An external target is left out."""
        folder, name = posixpath.split(part)
        rels = posixpath.join(folder, "_rels", name + ".rels")
        out: dict[str, tuple[str, str]] = {}
        if rels not in self.names:
            return out

        def start(tag: str, attrs: dict[str, str]) -> None:
            if tag != "rel:Relationship" or attrs.get("TargetMode") == "External":
                return
            target = attrs.get("Target", "")
            target = target[1:] if target.startswith("/") else posixpath.join(folder, target)
            out[attrs.get("Id", "")] = (attrs.get("Type", ""), posixpath.normpath(target))

        _parse(self.read(rels), f"{self.path}: {rels}", start)
        return out

    def target(self, part: str, kind: str) -> str | None:
        """The member of the first relationship of ``part`` whose type ends with ``/kind``."""
        for rel_type, member in self.related(part).values():
            if rel_type.endswith("/" + kind):
                return member
        return None


def _parse(
    data: bytes,
    what: str,
    start: Callable[[str, dict[str, str]], None],
    end: Callable[[str], None] | None = None,
    chars: Callable[[str], None] | None = None,
) -> None:
    """Parse ``data`` with expat and call the handlers. A tag reads ``w:p``: the prefix of its
    namespace in NAMESPACES, or ``?`` for another namespace. An attribute has its local name."""
    p = expat.ParserCreate(namespace_separator=" ")
    p.buffer_text = True
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    depth = 0

    def refuse(*_: object) -> int:
        raise ReadError(f"{what}: XML with a DOCTYPE or an entity is not read")

    def name(raw: str) -> str:
        uri, _, local = raw.rpartition(" ")
        return f"{NAMESPACES.get(uri, '?')}:{local}" if uri else local

    def on_start(tag: str, attrs: dict[str, str]) -> None:
        nonlocal depth
        depth += 1
        if depth > MAX_XML_DEPTH:
            raise ReadError(f"{what}: XML deeper than {MAX_XML_DEPTH} elements is not read")
        start(name(tag), {k.rpartition(" ")[2]: v for k, v in attrs.items()})

    def on_end(tag: str) -> None:
        nonlocal depth
        depth -= 1
        if end is not None:
            end(name(tag))

    p.StartDoctypeDeclHandler = refuse
    p.EntityDeclHandler = refuse
    p.ExternalEntityRefHandler = refuse
    p.StartElementHandler = on_start
    p.EndElementHandler = on_end
    if chars is not None:
        p.CharacterDataHandler = chars
    try:
        p.Parse(data, True)
    except expat.ExpatError as e:
        raise ReadError(f"{what}: not well-formed XML ({e})") from e


class _Nodes:
    """The raw nodes of one reader. After MAX_NODES nodes, no node opens or closes, so
    ``finish`` drops each open node, as ``Tracker`` does."""

    def __init__(self, w: _Writer) -> None:
        self.w = w
        self.raws: list[Raw] = []

    def open(self, kind: str, parent: int | None, members: dict[str, Any] | None = None) -> int:
        if len(self.raws) >= MAX_NODES:
            return -1
        self.raws.append(Raw(kind, "markup", self.w.size, parent, members=members))
        return len(self.raws) - 1

    def close(self, i: int) -> None:
        if i >= 0 and len(self.raws) < MAX_NODES:
            self.raws[i].end = self.w.size


def office_nodes(data: bytes, path: Path) -> tuple[str, list[Raw]]:
    """The NFC text of a DOCX or an XLSX file and its nodes, with code point offsets."""
    z = _Zip(data, path)
    w = _Writer()
    nodes = _Nodes(w)
    if path.suffix.lower() == ".docx":
        _docx(z, nodes)
    else:
        _xlsx(z, nodes)
    return _final(w, nodes.raws)


def _main(z: _Zip, kind: str) -> str:
    main = z.target("", "officeDocument")
    if main is None:
        raise ReadError(f"{z.path}: the file has no main part ({kind})")
    return main


# DOCX


def _heading_styles(z: _Zip, document: str) -> dict[str, int]:
    """The heading level of each paragraph style id: from a name ``heading N`` or ``Title``,
    or from the outline level of the style."""
    styles = z.target(document, "styles")
    out: dict[str, int] = {}
    if styles is None:
        return out
    current: list[str] = []

    def start(tag: str, attrs: dict[str, str]) -> None:
        if tag == "w:style":
            current[:] = [attrs.get("styleId", "")] if attrs.get("type") == "paragraph" else []
        elif current and tag == "w:name":
            value = attrs.get("val", "").strip().lower()
            m = _HEADING.fullmatch(value)
            if m or value == "title":
                out[current[0]] = min(int(m.group(1)), 6) if m else 1
        elif current and tag == "w:outlineLvl" and current[0] not in out:
            level = _outline(attrs)
            if level is not None:
                out[current[0]] = level

    _parse(z.read(styles), f"{z.path}: {styles}", start)
    return out


def _outline(attrs: dict[str, str]) -> int | None:
    value = attrs.get("val", "")
    return (
        min(int(value) + 1, 6) if value.isascii() and value.isdigit() and int(value) < 9 else None
    )


class _Table:
    def __init__(self, raw: int) -> None:
        self.raw = raw
        self.row = -1
        self.row_raw = -1
        self.column = 0
        self.header = False
        self.merge: dict[int, int] = {}  # column -> the cell that a vertical merge starts


class _Docx:
    """The handlers of ``word/document.xml``."""

    def __init__(self, nodes: _Nodes, styles: dict[str, int]) -> None:
        self.n = nodes
        self.w = nodes.w
        self.styles = styles
        self.stack: list[str] = []
        self.skip = 0  # the depth inside ``mc:Fallback``, which repeats the ``mc:Choice``
        self.para: dict[str, Any] | None = None  # the outer paragraph that is open
        self.inner = 0  # paragraphs and tables inside the outer paragraph (text boxes)
        # [the cell, the open list, the paragraphs so far] of the top level and each open cell
        self.containers: list[list[int | None]] = [[None, None, 0]]
        self.tables: list[_Table] = []
        self.cells: list[int] = []
        self.in_text = False
        self.hidden = False
        self.script: str | None = None
        self.scripted = False

    def start(self, tag: str, attrs: dict[str, str]) -> None:
        parent = self.stack[-1] if self.stack else ""
        self.stack.append(tag)
        if self.skip or tag == "mc:Fallback":
            self.skip += 1
            return
        if tag == "w:p":
            if self.para is not None:
                self.inner += 1
                self.w.block(1)
            else:
                self._break()
                self.para = {"start": self.w.size, "style": None, "outline": None, "list": False}
        elif tag == "w:tbl":
            if self.para is not None:
                self.inner += 1
                return
            self.containers[-1][1] = None
            self.w.start("table")
            self.tables.append(_Table(self.n.open("table", self.containers[-1][0])))
        elif tag in ("w:tr", "w:tc") and self.para is not None:
            self.w.block(1)
        elif tag == "w:tr" and self.tables:
            t = self.tables[-1]
            self.w.start("tr")
            t.row, t.column, t.header = t.row + 1, 0, False
            t.row_raw = self.n.open("row", t.raw if t.raw >= 0 else None)
        elif tag == "w:tc" and self.tables:
            t = self.tables[-1]
            self.w.start("td")
            members: dict[str, Any] = {"row": max(t.row, 0), "column": t.column}
            members.update(rows=1, columns=1, header=True if t.header else None)
            cell = self.n.open("cell", t.row_raw if t.row_raw >= 0 else None, members)
            self.cells.append(cell)
            self.containers.append([cell if cell >= 0 else None, None, 0])
        elif self.para is None and self.tables:
            self._table_property(tag, parent, attrs)
        elif self.para is not None:
            self._paragraph_property(tag, parent, attrs)

    def _break(self) -> None:
        """Start a paragraph. A paragraph in a cell starts on a new line, so the cells of a row
        stay on one line, as HTML ``td`` cells do."""
        container = self.containers[-1]
        if len(self.containers) == 1:
            self.w.start("p")
        elif container[2]:
            self.w.block(1)
        container[2] = (container[2] or 0) + 1

    def _table_property(self, tag: str, parent: str, attrs: dict[str, str]) -> None:
        t = self.tables[-1]
        if tag == "w:tblHeader" and parent == "w:trPr":
            t.header = attrs.get("val", "true").lower() not in OFF
        elif tag == "w:gridBefore" and parent == "w:trPr":
            t.column += span_number(attrs.get("val")) if attrs.get("val") else 0
        elif tag in ("w:gridSpan", "w:vMerge") and parent == "w:tcPr" and self.cells:
            cell = self.cells[-1]
            if cell < 0:
                return
            members = self.n.raws[cell].members
            assert members is not None
            if tag == "w:gridSpan":
                members["columns"] = span_number(attrs.get("val"))
            elif attrs.get("val") == "restart":
                t.merge[members["column"]] = cell
            else:  # a cell that continues the merge above it
                above = t.merge.get(members["column"], -1)
                if above >= 0:
                    above_members = self.n.raws[above].members
                    assert above_members is not None
                    above_members["rows"] = min(above_members["rows"] + 1, MAX_SPAN)
                members["merged"] = True

    def _paragraph_property(self, tag: str, parent: str, attrs: dict[str, str]) -> None:
        assert self.para is not None
        if self.inner:  # the properties of a paragraph in a text box give no node
            pass
        elif tag == "w:pStyle" and parent == "w:pPr":
            self.para["style"] = attrs.get("val")
            return
        elif tag == "w:outlineLvl" and parent == "w:pPr":
            self.para["outline"] = _outline(attrs)
            return
        elif tag == "w:numId" and attrs.get("val", "0") != "0":
            self.para["list"] = True
            return
        if tag == "w:r":
            self.hidden, self.script, self.scripted = False, None, False
        elif tag == "w:vanish" and parent == "w:rPr" and self.stack[-3:-2] == ["w:r"]:
            self.hidden = attrs.get("val", "true").lower() not in OFF
        elif tag == "w:vertAlign" and parent == "w:rPr" and self.stack[-3:-2] == ["w:r"]:
            align = attrs.get("val")
            self.script = (
                "sup" if align == "superscript" else "sub" if align == "subscript" else None
            )
        elif parent == "w:r" and not self.hidden:
            if tag == "w:t":
                self.in_text = True
                if self.script and not self.scripted:
                    self.w.start(self.script)
                    self.scripted = True
            elif tag == "w:tab":
                self.w.text(" ")
            elif tag in ("w:br", "w:cr"):
                self.w.block(1)

    def chars(self, data: str) -> None:
        if self.in_text and not self.skip:
            self.w.text(data)

    def end(self, tag: str) -> None:
        self.stack.pop()
        if self.skip:
            self.skip -= 1
            return
        if tag == "w:t":
            self.in_text = False
        elif tag == "w:r" and self.scripted and self.script:
            self.w.end(self.script)
            self.scripted = False
        elif tag in ("w:p", "w:tbl") and self.inner:
            self.inner -= 1
            self.w.block(1)
        elif tag == "w:p" and self.para is not None:
            self._paragraph()
        elif self.para is not None or not self.tables:
            return
        elif tag == "w:tc" and self.cells:
            self._cell()
        elif tag == "w:tr":
            self.n.close(self.tables[-1].row_raw)
            self.w.end("tr")
        elif tag == "w:tbl":
            self.n.close(self.tables.pop().raw)
            self.w.end("table")

    def _paragraph(self) -> None:
        assert self.para is not None
        para, self.para = self.para, None
        container = self.containers[-1]
        level = self.styles.get(para["style"] or "") or para["outline"]
        before = len(self.n.raws)
        if level is not None or not para["list"]:
            container[1] = None
            kind = "heading" if level is not None else "paragraph"
            i = self.n.open(kind, container[0], {"level": level} if level is not None else None)
        else:
            if container[1] is None:
                opened = self.n.open("list", container[0])
                container[1] = opened if opened >= 0 else None
            i = self.n.open("item", container[1])
        for raw in self.n.raws[before:]:
            raw.start = para["start"]
        self.n.close(i)
        if container[1] is not None:
            self.n.close(container[1])
        if len(self.containers) == 1:
            self.w.end("p")

    def _cell(self) -> None:
        t = self.tables[-1]
        cell = self.cells.pop()
        self.containers.pop()
        columns = 1
        if cell >= 0:
            raw = self.n.raws[cell]
            assert raw.members is not None
            columns = raw.members["columns"]
            if raw.members.pop("merged", False) or t.column + columns > MAX_COLUMNS:
                raw.keep = False
            elif t.merge.get(raw.members["column"]) not in (None, cell):
                del t.merge[raw.members["column"]]
            self.n.close(cell)
        t.column += columns
        self.w.end("td")


def _docx(z: _Zip, nodes: _Nodes) -> None:
    document = _main(z, "word/document.xml")
    reader = _Docx(nodes, _heading_styles(z, document))
    _parse(z.read(document), f"{z.path}: {document}", reader.start, reader.end, reader.chars)


# XLSX


def _cell_place(ref: str | None) -> tuple[int, int] | None:
    """The row and the column of a reference such as ``B3``, from 0."""
    m = _CELL_REF.fullmatch(ref or "")
    if m is None:
        return None
    column = 0
    for ch in m.group(1):
        column = column * 26 + ord(ch) - 64
    row = int(m.group(2))
    if not (1 <= row <= 2**20 and 1 <= column <= MAX_COLUMNS):
        return None
    return row - 1, column - 1


def _shared_strings(z: _Zip, workbook: str) -> list[str]:
    member = z.target(workbook, "sharedStrings")
    out: list[str] = []
    if member is None:
        return out
    stack: list[str] = []
    parts: list[str] = []

    def start(tag: str, attrs: dict[str, str]) -> None:
        stack.append(tag)
        if tag == "x:si":
            parts.clear()

    def end(tag: str) -> None:
        stack.pop()
        if tag == "x:si":
            out.append("".join(parts))

    def chars(data: str) -> None:
        if stack and stack[-1] == "x:t" and "x:rPh" not in stack:
            parts.append(data)

    _parse(z.read(member), f"{z.path}: {member}", start, end, chars)
    return out


class _Sheet:
    """The handlers of one worksheet. ``cells`` maps (row, column) to the value."""

    def __init__(self, shared: list[str]) -> None:
        self.shared = shared
        self.cells: dict[tuple[int, int], str] = {}
        self.merges: list[tuple[int, int, int, int]] = []
        self.hidden_columns: list[tuple[int, int]] = []  # first and last, from 0
        self.stack: list[str] = []
        self.row = -1
        self.row_hidden = False
        self.column = -1
        self.cell: dict[str, Any] | None = None

    def start(self, tag: str, attrs: dict[str, str]) -> None:
        self.stack.append(tag)
        if tag == "x:row":
            r = attrs.get("r", "")
            self.row = (
                int(r) - 1 if r.isascii() and r.isdigit() and 0 < int(r) <= 2**20 else self.row + 1
            )
            self.row_hidden = attrs.get("hidden", "0").lower() not in OFF
            self.column = -1
        elif tag == "x:c":
            place = _cell_place(attrs.get("r"))
            row, column = place if place else (max(self.row, 0), self.column + 1)
            self.row, self.column = row, column
            self.cell = {"type": attrs.get("t", "n"), "parts": []}
        elif tag == "x:col" and attrs.get("hidden", "0").lower() not in OFF:
            low, high = attrs.get("min", ""), attrs.get("max", "")
            if low.isascii() and low.isdigit() and high.isascii() and high.isdigit():
                self.hidden_columns.append((int(low) - 1, int(high) - 1))
        elif tag == "x:mergeCell":
            first, _, last = attrs.get("ref", "").partition(":")
            a, b = _cell_place(first), _cell_place(last)
            if a and b and a <= b and a[1] <= b[1]:
                self.merges.append((*a, *b))

    def chars(self, data: str) -> None:
        if self.cell is None or "x:rPh" in self.stack:
            return
        tag = self.stack[-1]
        if (tag == "x:v" and self.stack[-2:-1] == ["x:c"]) or (
            tag == "x:t" and "x:is" in self.stack
        ):
            self.cell["parts"].append(data)

    def end(self, tag: str) -> None:
        self.stack.pop()
        if tag != "x:c" or self.cell is None:
            return
        cell, self.cell = self.cell, None
        value = "".join(cell["parts"])
        if cell["type"] == "s":
            index = value.strip()
            ok = index.isascii() and index.isdigit() and int(index) < len(self.shared)
            value = self.shared[int(index)] if ok else ""
        elif cell["type"] == "b":
            value = {"0": "FALSE", "1": "TRUE"}.get(value.strip(), value)
        if value.strip() and not self.row_hidden:
            self.cells.setdefault((self.row, self.column), value)


def _ranges(ranges: list[tuple[int, int]]) -> Callable[[int], bool]:
    """A test for a number in one of ``ranges``. The cost of a test is log(len(ranges))."""
    starts: list[int] = []
    ends: list[int] = []
    for a, b in sorted(ranges):
        if starts and a <= ends[-1] + 1:
            ends[-1] = max(ends[-1], b)
        elif a <= b:
            starts.append(a)
            ends.append(b)

    def test(n: int) -> bool:
        i = bisect.bisect_right(starts, n) - 1
        return i >= 0 and n <= ends[i]

    return test


def _sheets(z: _Zip, workbook: str) -> list[tuple[str, str]]:
    """The name and the member of each sheet that is not hidden, in workbook order."""
    rels = z.related(workbook)
    out: list[tuple[str, str]] = []

    def start(tag: str, attrs: dict[str, str]) -> None:
        if tag == "x:sheet" and attrs.get("state", "visible") == "visible":
            rel = rels.get(attrs.get("id", ""))
            if rel is not None and rel[0].endswith("/worksheet"):
                out.append((attrs.get("name", ""), rel[1]))

    _parse(z.read(workbook), f"{z.path}: {workbook}", start)
    return out


def _xlsx(z: _Zip, nodes: _Nodes) -> None:
    workbook = _main(z, "xl/workbook.xml")
    shared = _shared_strings(z, workbook)
    w = nodes.w
    for name, member in _sheets(z, workbook):
        sheet = _Sheet(shared)
        _parse(z.read(member), f"{z.path}: {member}", sheet.start, sheet.end, sheet.chars)
        spans: dict[tuple[int, int], tuple[int, int]] = {}
        for r0, c0, r1, c1 in sheet.merges:
            spans.setdefault((r0, c0), (min(r1 - r0 + 1, MAX_SPAN), min(c1 - c0 + 1, MAX_SPAN)))
        hidden = _ranges(sheet.hidden_columns)
        cells = sorted(
            (place, value) for place, value in sheet.cells.items() if not hidden(place[1])
        )
        if not cells:
            continue
        w.start("h1")
        heading = nodes.open("heading", None, {"level": 1})
        w.text(name)
        nodes.close(heading)
        w.end("h1")
        w.start("table")
        table = nodes.open("table", None)
        row_raw, last_row = -1, -1
        for (row, column), value in cells:
            if row != last_row:
                if last_row >= 0:
                    nodes.close(row_raw)
                    w.end("tr")
                w.start("tr")
                row_raw, last_row = nodes.open("row", table if table >= 0 else None), row
            rows, columns = spans.get((row, column), (1, 1))
            members = {"row": row, "column": column, "rows": rows, "columns": columns}
            w.start("td")
            cell = nodes.open("cell", row_raw if row_raw >= 0 else None, members | {"header": None})
            w.text(value)
            nodes.close(cell)
            w.end("td")
        nodes.close(row_raw)
        w.end("tr")
        nodes.close(table)
        w.end("table")
