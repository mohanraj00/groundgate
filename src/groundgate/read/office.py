"""DOCX and XLSX to text with the standard library (#529). Both are zip files of XML.

The text follows the conventions of ``markup.py``: a block ends with a blank line, a table row
with a line break, and a tab goes between the cells of a row. The nodes are the ones of
docs/design/document-model.md §5.1:

- DOCX: a paragraph with a heading style or an outline level gives a heading. A numbered
  paragraph gives a list item, and adjacent items give one list. A table gives its rows and its
  cells, with ``gridSpan`` and ``vMerge`` as the span of a cell. A superscript run reads ``^``
  and a subscript run ``_``, as in HTML. A hidden run (``vanish`` on the run, its character
  style, its paragraph style or the document defaults) gives no text.
- XLSX: each sheet gives a heading with the sheet name and one table. The row and the column of
  a cell are its place in the sheet, from 0. Rich text marks superscripts and subscripts as DOCX
  does. An escape such as ``_x000D_`` reads as its character. A merged cell spans its range. A
  number reads as the sheet stores it, not as the sheet formats it. Hidden sheets, rows and
  columns give no text.

These files are untrusted input. ``_Zip`` refuses a file larger than MAX_FILE, more than
MAX_MEMBERS members, a member name outside the archive, and a total expanded size larger than
MAX_EXPANDED. ``_parse`` refuses a DOCTYPE, so no entity is declared or loaded, and an element
deeper than MAX_XML_DEPTH. An XLSX text longer than MAX_TEXT is refused, because one short
shared string can repeat in each cell. DOCX text is never longer than its XML.

A DOCX gives the text of the document after its tracked changes: deleted text, deleted table
rows and cells, and moved-from text give no text. Of the branches of ``mc:AlternateContent``,
only the first ``mc:Choice`` is read.
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
from typing import Any, TypeVar
from xml.parsers import expat

from . import ReadError
from .markup import _final, _Writer
from .nodes import MAX_COLUMNS, MAX_NODES, MAX_SPAN, Raw, span_number

MAX_FILE = 64 * 2**20  # the bytes of the zip file
MAX_MEMBERS = 10_000
MAX_EXPANDED = 256 * 2**20  # the sum of the expanded sizes of all members
MAX_XML_DEPTH = 512
MAX_TEXT = 64 * 2**20  # the code points of an XLSX text: a shared string can repeat in each cell

# The namespaces of the transitional and the strict forms of Office Open XML.
NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main": "w",
    "http://purl.oclc.org/ooxml/wordprocessingml/main": "w",
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main": "x",
    "http://purl.oclc.org/ooxml/spreadsheetml/main": "x",
    "http://schemas.openxmlformats.org/package/2006/relationships": "rel",
    "http://schemas.openxmlformats.org/markup-compatibility/2006": "mc",
}
_T = TypeVar("_T")
OFF = {"0", "false", "off"}
# The properties from before a tracked change. The reader shows the document after the changes.
_CHANGES = {
    "w:pPrChange",
    "w:rPrChange",
    "w:tblPrChange",
    "w:tblPrExChange",
    "w:trPrChange",
    "w:tcPrChange",
    "w:sectPrChange",
    "w:tblGridChange",
    "w:numberingChange",
}
_CELL_REF = re.compile(r"([A-Z]{1,3})([0-9]{1,7})")
_HEADING = re.compile(r"heading ([1-9])")
_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")  # a character in an XLSX string, as _x000D_


def _unescape(m: re.Match[str]) -> str:
    code = int(m.group(1), 16)
    return "\ufffd" if 0xD800 <= code <= 0xDFFF else chr(code)


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


class _Styles:
    """The paragraph and character styles of a DOCX file that change what ``read`` gives: the
    heading level of a paragraph style, and the ``vanish`` and ``vertAlign`` properties of each
    style. A style without a property takes it from its ``basedOn`` style."""

    def __init__(self) -> None:
        self.levels: dict[str, int] = {}
        self.vanish: dict[str, bool] = {}
        self.align: dict[str, str] = {}
        self.based_on: dict[str, str] = {}
        self.default = False
        self.default_align: str | None = None
        self.default_paragraph: str | None = None  # the style of a paragraph with no pStyle

    def hidden(self, style: str | None) -> bool | None:
        """The ``vanish`` of ``style`` and the styles it is based on, or None when none says."""
        return self._find(self.vanish, style)

    def vert_align(self, style: str | None) -> str | None:
        return self._find(self.align, style)

    def level(self, style: str | None) -> int | None:
        """The heading level of a paragraph style, or 0 for body text, or None."""
        return self._find(self.levels, style)

    def paragraph(self, style: str | None) -> str | None:
        """The style of a paragraph: its ``pStyle``, or the default paragraph style."""
        return style if style is not None else self.default_paragraph

    def _find(self, table: dict[str, _T], style: str | None) -> _T | None:
        seen: set[str] = set()
        while style is not None and style not in seen:
            if style in table:
                return table[style]
            seen.add(style)
            style = self.based_on.get(style)
        return None


def _styles(z: _Zip, document: str) -> _Styles:
    """The styles of ``document``: the heading level of each paragraph style id, from a name
    ``heading N`` or ``Title`` or from the outline level, and the hidden styles."""
    member = z.target(document, "styles")
    out = _Styles()
    if member is None:
        return out
    stack: list[str] = []
    current: list[str] = []  # the id and the type of the open style

    def start(tag: str, attrs: dict[str, str]) -> None:
        parent = stack[-1] if stack else ""
        stack.append(tag)
        if not _CHANGES.isdisjoint(stack):
            return
        if tag == "w:style":
            current[:] = [attrs.get("styleId", ""), attrs.get("type", "")]
            on = attrs.get("default", "0").lower() not in OFF
            if on and current[1] == "paragraph" and out.default_paragraph is None:
                out.default_paragraph = current[0]
        elif tag == "w:vanish" and parent == "w:rPr" and "w:rPrDefault" in stack:
            out.default = attrs.get("val", "true").lower() not in OFF
        elif tag == "w:vertAlign" and parent == "w:rPr" and "w:rPrDefault" in stack:
            out.default_align = attrs.get("val", "")
        elif not current or "w:style" not in stack:
            return
        elif tag == "w:basedOn" and parent == "w:style":
            out.based_on[current[0]] = attrs.get("val", "")
        elif tag == "w:vanish" and parent == "w:rPr" and stack[-3:-2] == ["w:style"]:
            out.vanish[current[0]] = attrs.get("val", "true").lower() not in OFF
        elif tag == "w:vertAlign" and parent == "w:rPr" and stack[-3:-2] == ["w:style"]:
            out.align[current[0]] = attrs.get("val", "")
        elif current[1] != "paragraph":
            return
        elif tag == "w:name":
            value = attrs.get("val", "").strip().lower()
            m = _HEADING.fullmatch(value)
            if m or value == "title":
                out.levels[current[0]] = min(int(m.group(1)), 6) if m else 1
        elif tag == "w:outlineLvl" and current[0] not in out.levels:
            level = _outline(attrs)
            if level is not None:
                out.levels[current[0]] = level

    def end(tag: str) -> None:
        stack.pop()
        if tag == "w:style":
            current.clear()

    _parse(z.read(member), f"{z.path}: {member}", start, end)
    return out


def _outline(attrs: dict[str, str]) -> int | None:
    """The heading level of an outline level: 0 to 8 give 1 to 6, and 9 (body text) gives 0."""
    value = attrs.get("val", "")
    if not (value.isascii() and value.isdigit() and int(value) <= 9):
        return None
    return 0 if int(value) == 9 else min(int(value) + 1, 6)


class _Table:
    def __init__(self, raw: int) -> None:
        self.raw = raw
        self.row = -1
        self.row_raw = -1
        self.column = 0
        self.header = False
        self.deleted = False  # the open row is a deleted row of tracked changes
        self.merge: dict[int, int] = {}  # column -> the cell that a vertical merge starts


class _Docx:
    """The handlers of ``word/document.xml``."""

    def __init__(self, nodes: _Nodes, styles: _Styles) -> None:
        self.n = nodes
        self.w = nodes.w
        self.styles = styles
        self.stack: list[str] = []
        # The depth inside a subtree that gives no text: ``w:moveFrom`` (the old place of moved
        # text), ``mc:Fallback``, and each ``mc:Choice`` after the first, which repeat the first.
        self.skip = 0
        self.choices: list[bool] = []  # for each open ``mc:AlternateContent``: a choice was read
        self.para: dict[str, Any] | None = None  # the outer paragraph that is open
        self.inner = 0  # paragraphs and tables inside the outer paragraph (text boxes)
        # [the cell, the open list, the paragraphs so far] of the top level and each open cell
        self.containers: list[list[int | None]] = [[None, None, 0]]
        self.tables: list[_Table] = []
        self.cells: list[int] = []
        self.deleted: list[bool] = []  # for each open cell: a deleted cell of tracked changes
        self.inner_styles: list[str | None] = []  # the style of each open text box paragraph
        self.in_text = False
        self.vanish: bool | None = None  # the direct ``vanish`` of the open run
        self.run_style: str | None = None
        self.align: str | None = None  # the direct ``vertAlign`` of the open run
        self.script: str | None = None  # the mark that the open run started
        self.scripted = False

    def start(self, tag: str, attrs: dict[str, str]) -> None:
        parent = self.stack[-1] if self.stack else ""
        self.stack.append(tag)
        if tag == "mc:Choice" and not self.skip and self.choices:
            if self.choices[-1]:
                self.skip = 1
                return
            self.choices[-1] = True
        if self.skip or tag in ("mc:Fallback", "w:moveFrom") or tag in _CHANGES:
            self.skip += 1
            return
        if tag == "mc:AlternateContent":
            self.choices.append(False)
        if tag in ("w:p", "w:tbl") and self.para is None and self.deleted and self.deleted[-1]:
            self.skip = 1  # the content of a deleted cell gives no text
            return
        if tag == "w:p":
            if self.para is not None:
                self.inner += 1
                self.inner_styles.append(None)
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
            t.row, t.column, t.header, t.deleted = t.row + 1, 0, False, False
            t.row_raw = self.n.open("row", t.raw if t.raw >= 0 else None)
        elif tag == "w:tc" and self.tables and self.tables[-1].deleted:
            self.skip = 1  # the cells of a deleted row give no text
        elif tag == "w:tc" and self.tables:
            t = self.tables[-1]
            self.w.start("td")
            members: dict[str, Any] = {"row": max(t.row, 0), "column": t.column}
            members.update(rows=1, columns=1, header=True if t.header else None)
            cell = self.n.open("cell", t.row_raw if t.row_raw >= 0 else None, members)
            self.cells.append(cell)
            self.deleted.append(False)
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
        if tag == "w:del" and parent == "w:trPr":
            t.deleted = True
            if t.row_raw >= 0:
                self.n.raws[t.row_raw].keep = False
        elif tag == "w:tblHeader" and parent == "w:trPr":
            t.header = attrs.get("val", "true").lower() not in OFF
        elif tag == "w:gridBefore" and parent == "w:trPr":
            t.column += span_number(attrs.get("val")) if attrs.get("val") else 0
        elif tag == "w:cellDel" and parent == "w:tcPr" and self.deleted:
            self.deleted[-1] = True
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
        if self.inner:  # a paragraph in a text box gives no node, but its style hides runs
            if tag == "w:pStyle" and parent == "w:pPr" and self.inner_styles:
                self.inner_styles[-1] = attrs.get("val")
                return
        elif tag == "w:pStyle" and parent == "w:pPr":
            self.para["style"] = attrs.get("val")
            return
        elif tag == "w:vanish" and parent == "w:rPr" and self.stack[-3:-2] == ["w:pPr"]:
            return  # the paragraph mark only
        elif tag == "w:outlineLvl" and parent == "w:pPr":
            self.para["outline"] = _outline(attrs)
            return
        elif tag == "w:numId" and attrs.get("val", "0") != "0":
            self.para["list"] = True
            return
        if tag == "w:r":
            self.vanish, self.run_style, self.align = None, None, None
            self.script, self.scripted = None, False
        elif tag == "w:rStyle" and parent == "w:rPr" and self.stack[-3:-2] == ["w:r"]:
            self.run_style = attrs.get("val")
        elif tag == "w:vanish" and parent == "w:rPr" and self.stack[-3:-2] == ["w:r"]:
            self.vanish = attrs.get("val", "true").lower() not in OFF
        elif tag == "w:vertAlign" and parent == "w:rPr" and self.stack[-3:-2] == ["w:r"]:
            self.align = attrs.get("val", "")
        elif parent == "w:r" and not self._hidden():
            if tag == "w:t":
                self.in_text = True
                script = self._script()
                if script and not self.scripted:
                    self.w.start(script)
                    self.script, self.scripted = script, True
            elif tag == "w:noBreakHyphen":
                self.w.text("-")
            elif tag == "w:tab":
                self.w.text(" ")
            elif tag in ("w:br", "w:cr"):
                self.w.block(1)

    def _paragraph_style(self) -> str | None:
        """The ``pStyle`` of the innermost open paragraph, in a text box or not."""
        if self.inner_styles:
            return self.inner_styles[-1]
        return self.para["style"] if self.para else None

    def _script(self) -> str | None:
        """``sup`` or ``sub`` for a run with a superscript or a subscript ``vertAlign``: its own,
        or the one of its character style, of the style of its paragraph or of the document
        defaults, in that order."""
        para = self.styles.paragraph(self._paragraph_style())
        align = self.align
        for value in (self.styles.vert_align(self.run_style), self.styles.vert_align(para)):
            align = value if align is None else align
        if align is None:
            align = self.styles.default_align
        return {"superscript": "sup", "subscript": "sub"}.get(align or "")

    def _hidden(self) -> bool:
        """The run is hidden: by its own ``vanish``, its character style, the style of its
        paragraph or the document defaults, in that order."""
        for value in (
            self.vanish,
            self.styles.hidden(self.run_style),
            self.styles.hidden(self.styles.paragraph(self._paragraph_style())),
        ):
            if value is not None:
                return value
        return self.styles.default

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
        elif tag == "mc:AlternateContent" and self.choices:
            self.choices.pop()
        elif tag == "w:r" and self.scripted and self.script:
            self.w.end(self.script)
            self.scripted = False
        elif tag in ("w:p", "w:tbl") and self.inner:
            self.inner -= 1
            if tag == "w:p" and self.inner_styles:
                self.inner_styles.pop()
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
        level = para["outline"]  # a direct outline level comes before the style
        if level is None:
            level = self.styles.level(self.styles.paragraph(para["style"]))
        level = level or None
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
        if self.deleted.pop():  # the cell is not in the document: no node, no column, no tab
            if cell >= 0:
                self.n.raws[cell].keep = False
            return
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
    reader = _Docx(nodes, _styles(z, document))
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


class _Rich:
    """The text of a string with rich text runs. A superscript run reads ``^`` and a subscript
    run ``_``, as in ``_Writer``: ``10`` and a superscript ``9`` read ``10^9``, never ``109``."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.script: str | None = None
        self.marked = False
        self.after = False

    def start(self, tag: str, parent: str, attrs: dict[str, str]) -> None:
        if tag == "x:r":
            self.script, self.marked = None, False
        elif tag == "x:vertAlign" and parent == "x:rPr":
            self.script = {"superscript": "^", "subscript": "_"}.get(attrs.get("val", ""))

    def text(self, data: str) -> None:
        if not data:
            return
        if self.script and not self.marked:
            self.parts.append(self.script)
            self.marked = True
        elif self.after and data[0].isdigit():
            self.parts.append(" ")  # "10", a superscript "9", then "5" must not read "10^95"
        self.after = False
        self.parts.append(data)

    def end(self, tag: str) -> None:
        if tag == "x:r" and self.marked:
            self.after = True

    def value(self) -> str:
        return _ESCAPE.sub(_unescape, "".join(self.parts))


def _shared_strings(z: _Zip, workbook: str) -> list[str]:
    member = z.target(workbook, "sharedStrings")
    out: list[str] = []
    if member is None:
        return out
    stack: list[str] = []
    rich = _Rich()

    def start(tag: str, attrs: dict[str, str]) -> None:
        nonlocal rich
        parent = stack[-1] if stack else ""
        stack.append(tag)
        if tag == "x:si":
            rich = _Rich()
        rich.start(tag, parent, attrs)

    def end(tag: str) -> None:
        stack.pop()
        rich.end(tag)
        if tag == "x:si":
            out.append(rich.value())

    def chars(data: str) -> None:
        if stack and stack[-1] == "x:t" and "x:rPh" not in stack:
            rich.text(data)

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
        parent = self.stack[-1] if self.stack else ""
        self.stack.append(tag)
        if self.cell is not None:
            self.cell["rich"].start(tag, parent, attrs)
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
            self.cell = {"type": attrs.get("t", "n"), "rich": _Rich()}
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
            self.cell["rich"].text(data)

    def end(self, tag: str) -> None:
        self.stack.pop()
        if self.cell is not None:
            self.cell["rich"].end(tag)
        if tag != "x:c" or self.cell is None:
            return
        cell, self.cell = self.cell, None
        value = cell["rich"].value()
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


def _budget(z: _Zip, w: _Writer, value: str) -> None:
    if w.size + len(value) > MAX_TEXT:
        raise ReadError(f"{z.path}: the text is larger than {MAX_TEXT} characters")


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
        _budget(z, w, name)
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
            _budget(z, w, value)
            w.text(value)
            nodes.close(cell)
            w.end("td")
        nodes.close(row_raw)
        w.end("tr")
        nodes.close(table)
        w.end("table")
