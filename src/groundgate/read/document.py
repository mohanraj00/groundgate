"""The document model: the text of ``read`` and a flat list of nodes (``document@1``).

>>> extracted, doc = read_document("label.html")     # doctest: +SKIP
>>> doc.of_kind("table")                              # the tables, in text order
>>> doc.at(start, end)                                # the innermost node of a cited span
>>> Document.from_dict(json.loads(raw), text)         # the loader for an object from a file

Each node is a UTF-8 byte span into the text, as SPEC §2.2 spans are. The nodes never change the
text: ``read_document`` gives the same text as ``read``. A node is information only, and
``admit`` does not import this module. docs/design/document-model.md defines the format (§4),
the basis of each node (§5), the lookups (§7) and the checks of the loader (§12).

The standard library only.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..canonical import jcs
from . import HTML_SUFFIXES, OFFICE_SUFFIXES, TEXT_SUFFIXES, Extracted, ReadError, _decode, reader
from .layout import Layout
from .nodes import MAX_DEPTH, MAX_NODES, PARENTS, Raw, chars_of_bytes, finish

__all__ = ["FORMAT", "Document", "DocumentError", "Match", "Node", "read_document"]

FORMAT = "document@1"
KINDS = tuple(PARENTS)
BASES = ("markup", "rules", "layout")
_KEY = re.compile(r"sha256:[0-9a-f]{64}")
_TOP = ("doubt", "format", "nodes", "options", "reader", "source", "text")
_COMMON = ("basis", "end", "id", "kind", "parent", "start")
_CELL = ("column", "columns", "header", "row", "rows")


class DocumentError(ValueError):
    """A ``document@1`` object breaks a rule of the format."""


@dataclass(frozen=True, slots=True)
class Node:
    """One node. ``start`` and ``end`` are UTF-8 byte offsets into the text, half-open."""

    id: int
    kind: str
    basis: str
    parent: int | None
    start: int
    end: int
    level: int | None = None  # a heading only, 1 to 6
    row: int | None = None  # a cell only: the grid position and the span of the cell
    column: int | None = None
    rows: int | None = None
    columns: int | None = None
    header: bool | None = None  # a cell only: True for a header cell, None when not known

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {name: getattr(self, name) for name in _COMMON}
        if self.kind == "heading":
            out["level"] = self.level
        elif self.kind == "cell":
            out.update({name: getattr(self, name) for name in _CELL})
        return out


@dataclass(frozen=True)
class Match:
    """An occurrence of a string: its byte span, and the innermost node that holds it."""

    start: int
    end: int
    node: Node | None


class Document:
    """A checked ``document@1`` object and its text, with the lookups of the design note §7.

    Make one with ``read_document`` or ``Document.from_dict``. Each lookup is deterministic, and
    a lookup by span costs time in proportion to the depth of the nodes, not to their number.
    """

    def __init__(self, obj: Mapping[str, Any], text: str, nodes: tuple[Node, ...]) -> None:
        self._obj = dict(obj)
        self.text = text
        self.nodes = nodes
        self._data = text.encode("utf-8")
        self._starts = [n.start for n in nodes]
        self._children: dict[int | None, list[Node]] = {}
        self._kinds: dict[str, list[Node]] = {}
        for n in nodes:
            self._children.setdefault(n.parent, []).append(n)
            self._kinds.setdefault(n.kind, []).append(n)

    @property
    def source(self) -> str:
        """The store key of the ``source@1`` object: the bytes of the file."""
        return str(self._obj["source"])

    @property
    def reader(self) -> dict[str, str]:
        return dict(self._obj["reader"])

    @property
    def options(self) -> dict[str, Any]:
        return dict(self._obj["options"])

    @property
    def doubt(self) -> list[dict[str, Any]]:
        return [dict(d) for d in self._obj["doubt"]]

    def to_dict(self) -> dict[str, Any]:
        return {**self._obj, "nodes": [n.to_dict() for n in self.nodes]}

    def to_json(self) -> bytes:
        """The canonical JSON of the object (RFC 8785), so the same reading has the same bytes."""
        return jcs(self.to_dict()).encode("utf-8")

    # Lookups (§7)

    def node(self, id: int) -> Node:
        """The node ``id``. Raises ``KeyError`` for an id that is not in the list."""
        if isinstance(id, bool) or not isinstance(id, int) or not 0 <= id < len(self.nodes):
            raise KeyError(id)
        return self.nodes[id]

    def at(self, start: int, end: int) -> Node | None:
        """The innermost node whose span holds the byte span [start, end), or None."""
        if not 0 <= start <= end <= len(self._data):
            raise ValueError(f"[{start}, {end}) is not a span of the text")
        i = bisect.bisect_right(self._starts, start) - 1
        n = self.nodes[i] if i >= 0 else None
        while n is not None:
            if n.start <= start and end <= n.end:
                return n
            n = None if n.parent is None else self.nodes[n.parent]
        return None

    def of_kind(self, kind: str) -> list[Node]:
        """The nodes of ``kind``, in text order."""
        if kind not in KINDS:
            raise ValueError(f"{kind!r} is not a node kind")
        return list(self._kinds.get(kind, ()))

    def find(self, text: str) -> list[Match]:
        """Each exact occurrence of the NFC string ``text``, with its innermost node. The bytes
        must be the same: no case folding and no whitespace rule."""
        if not text:
            raise ValueError("find needs a string that is not empty")
        if not unicodedata.is_normalized("NFC", text):
            raise ValueError("find needs an NFC string, as the text is NFC")
        needle = text.encode("utf-8")
        out = []
        at = self._data.find(needle)
        while at >= 0:
            out.append(Match(at, at + len(needle), self.at(at, at + len(needle))))
            at = self._data.find(needle, at + 1)
        return out

    def children(self, id: int) -> list[Node]:
        """The children of node ``id``, in text order."""
        return list(self._children.get(self.node(id).id, ()))

    def section(self, id: int) -> tuple[int, int]:
        """The byte span of the section of heading ``id``. It starts at the heading and ends at
        the next heading of the same level or a lower level number, or at the end of the text.
        Whitespace at the end of the span is not in it."""
        heading = self.node(id)
        if heading.kind != "heading" or heading.level is None:
            raise ValueError(f"node {id} is not a heading")
        end = len(self._data)
        for n in self._kinds["heading"]:
            if n.start > heading.start and n.level is not None and n.level <= heading.level:
                end = n.start
                break
        tail = self._data[heading.start : end].decode("utf-8")
        return heading.start, heading.start + len(tail.rstrip().encode("utf-8"))

    def cell(self, table: int, row: int, column: int) -> Node | None:
        """The cell of table ``table`` at grid position (row, column), also when a spanned cell
        covers that position. None when no cell is there."""
        if self.node(table).kind != "table":
            raise ValueError(f"node {table} is not a table")
        for r in self._children.get(table, ()):
            for c in self._children.get(r.id, ()):
                assert c.row is not None and c.column is not None
                assert c.rows is not None and c.columns is not None
                if c.row <= row < c.row + c.rows and c.column <= column < c.column + c.columns:
                    return c
        return None

    # The loader (§12)

    @classmethod
    def from_dict(cls, obj: object, text: str) -> Document:
        """Check ``obj`` against ``text`` and give the document. The object is untrusted, as it
        can come from a store or a file. Raises ``DocumentError`` at the first fault."""
        if not isinstance(text, str) or not unicodedata.is_normalized("NFC", text):
            raise DocumentError("the text must be an NFC string")
        if not isinstance(obj, Mapping):
            raise DocumentError(f"a {FORMAT} object must be a JSON object")
        _members(obj, _TOP, FORMAT)
        if obj["format"] != FORMAT:
            raise DocumentError(f"the format must be {FORMAT}")
        data = text.encode("utf-8")
        for name in ("source", "text"):
            if not isinstance(obj[name], str) or not _KEY.fullmatch(obj[name]):
                raise DocumentError(f"the member {name} is not a key such as sha256:<64 hex>")
        if obj["text"] != _text_key(data):
            raise DocumentError("the member text is not the key of this text")
        reader = obj["reader"]
        _members(reader, ("name", "version"), "reader")
        if not all(isinstance(reader[k], str) and reader[k] for k in ("name", "version")):
            raise DocumentError("the reader name and version must be strings that are not empty")
        options = obj["options"]
        _members(options, ("pages",), "options")
        pages = options["pages"]
        if pages is not None and not (
            isinstance(pages, list) and all(_integer(p) and p >= 1 for p in pages)
        ):
            raise DocumentError("the option pages must be null or a list of page numbers")
        _check_doubt(obj["doubt"], data)
        raw = obj["nodes"]
        if not isinstance(raw, list):
            raise DocumentError("the member nodes must be a list")
        if len(raw) > MAX_NODES:
            raise DocumentError(f"more than {MAX_NODES} nodes")
        nodes = tuple(_check_nodes(raw, data))
        return cls({k: obj[k] for k in _TOP if k != "nodes"}, text, nodes)


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _members(obj: object, names: Iterable[str], what: str) -> None:
    if not isinstance(obj, Mapping):
        raise DocumentError(f"{what} must be a JSON object")
    names = tuple(names)
    if set(obj) != set(names):
        extra = sorted(set(map(str, obj)) - set(names))
        missing = sorted(set(names) - set(obj))
        raise DocumentError(f"{what} has the wrong members (extra {extra}, missing {missing})")


def _text_key(data: bytes) -> str:
    from ..store import key  # the store key of text@1 (store.md §4)

    return key("text@1", data)


def _boundary(data: bytes, offset: object, what: str) -> int:
    if not _integer(offset):
        raise DocumentError(f"{what} must be an integer")
    assert isinstance(offset, int)
    if not 0 <= offset <= len(data):
        raise DocumentError(f"{what} {offset} is outside the text")
    if offset < len(data) and data[offset] & 0xC0 == 0x80:
        raise DocumentError(f"{what} {offset} is not on a character boundary")
    return offset


def _check_doubt(doubt: object, data: bytes) -> None:
    if not isinstance(doubt, list):
        raise DocumentError("the member doubt must be a list")
    last = 0
    for i, d in enumerate(doubt):
        _members(d, ("confidence", "end", "start"), f"doubt {i}")
        assert isinstance(d, Mapping)
        start = _boundary(data, d["start"], f"doubt {i} start")
        end = _boundary(data, d["end"], f"doubt {i} end")
        if not last <= start < end:
            raise DocumentError(f"doubt {i} must be a span that is not empty, in text order")
        c = d["confidence"]
        if isinstance(c, bool) or not isinstance(c, int | float) or not 0 <= c <= 1:
            raise DocumentError(f"doubt {i} confidence must be a number from 0 to 1")
        last = end


def _check_nodes(raw: list[object], data: bytes) -> Iterable[Node]:
    nodes: list[Node] = []
    chain: list[int] = []  # the previous node and the nodes above it
    last_end: dict[int | None, int] = {}
    last_start = 0
    for i, obj in enumerate(raw):
        what = f"node {i}"
        if not isinstance(obj, Mapping):
            raise DocumentError(f"{what} must be a JSON object")
        kind = obj.get("kind")
        if kind not in KINDS:
            raise DocumentError(f"{what} kind must be one of {', '.join(KINDS)}")
        extra = ("level",) if kind == "heading" else _CELL if kind == "cell" else ()
        _members(obj, _COMMON + extra, what)
        if obj["id"] != i or not _integer(obj["id"]):
            raise DocumentError(f"{what} id must be {i}, its place in the list")
        if obj["basis"] not in BASES:
            raise DocumentError(f"{what} basis must be one of {', '.join(BASES)}")
        start = _boundary(data, obj["start"], f"{what} start")
        end = _boundary(data, obj["end"], f"{what} end")
        if start > end or (start == end and kind != "cell"):
            raise DocumentError(f"{what} span is empty or reversed; only a cell can be empty")
        if start < end and (
            data[start : start + 4].decode("utf-8", "ignore")[:1].isspace()
            or data[max(start, end - 4) : end].decode("utf-8", "ignore")[-1:].isspace()
        ):
            raise DocumentError(f"{what} span starts or ends with whitespace")
        parent = obj["parent"]
        if parent is not None and not (_integer(parent) and 0 <= parent < i):
            raise DocumentError(f"{what} parent must be null or the id of a node before it")
        up = None if parent is None else nodes[parent]
        if (None if up is None else up.kind) not in PARENTS[kind]:
            allowed = sorted("null" if k is None else k for k in PARENTS[kind])
            raise DocumentError(f"{what}: a {kind} must have as parent: {', '.join(allowed)}")
        if up is not None and not (up.start <= start and end <= up.end):
            raise DocumentError(f"{what} span is not inside the span of its parent")
        # Tree order: the parent is the node before this one or a node above it. A lookup by span
        # then finds each node that holds the span above the last node that starts before it.
        while chain and chain[-1] != parent:
            chain.pop()
        if parent is not None and not chain:
            raise DocumentError(
                f"{what} is not in tree order: its parent is not above the node before it"
            )
        if len(chain) >= MAX_DEPTH:  # a lookup by span walks the parents, so the walk stays short
            raise DocumentError(f"{what} has {MAX_DEPTH} or more nodes above it")
        chain.append(i)
        if start < last_start:
            raise DocumentError(f"{what} is not in text order")
        if start < last_end.get(parent, 0):
            raise DocumentError(f"{what} overlaps the node before it with the same parent")
        last_start, last_end[parent] = start, end
        values: dict[str, Any] = {}
        if kind == "heading":
            level = obj["level"]
            if not (_integer(level) and 1 <= level <= 6):
                raise DocumentError(f"{what} level must be an integer from 1 to 6")
            values["level"] = level
        elif kind == "cell":
            for name, low in (("row", 0), ("column", 0), ("rows", 1), ("columns", 1)):
                if not (_integer(obj[name]) and obj[name] >= low):
                    raise DocumentError(f"{what} {name} must be an integer of {low} or more")
                values[name] = obj[name]
            if obj["header"] not in (True, False, None):
                raise DocumentError(f"{what} header must be true, false or null")
            values["header"] = obj["header"]
        nodes.append(Node(i, kind, obj["basis"], parent, start, end, **values))
    return nodes


# The reader


def read_document(
    path: str | Path,
    pages: Iterable[int] | None = None,
    *,
    ocr: bool = False,
    data: bytes | None = None,
) -> tuple[Extracted, Document]:
    """Read ``path`` as ``read`` does, and also give its document model. The text and the
    layout are the same as the text and the layout of ``read``.

    HTML, XML, DOCX and XLSX give ``markup`` nodes. A PDF gives ``layout`` paragraphs and
    tables, and ``rules`` tables where the page draws the rules. A text or Markdown file gives
    ``layout`` paragraphs: the blocks between blank lines. With ``ocr=True``, a scanned PDF page
    gives a ``layout`` paragraph for each paragraph of the OCR engine, and a ``doubt`` entry for
    each OCR word with a confidence below 1. A read with OCR records the tesseract version in
    ``reader``. OCR is off by default: an OCR word can be wrong, and ``admit`` does not read
    ``doubt``. If ``data`` is given, it is the bytes of the file, and ``read_document`` does not
    read the file again.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    options = {"pages": None if pages is None else list(pages)}
    source = path.read_bytes() if data is None else data
    raws: list[Raw] = []
    doubt: list[dict[str, Any]] = []
    if suffix == ".pdf":
        from ..canonical import digest, is_nfc
        from .ocr import Scan
        from .pdf import read_pdf

        scan = Scan()
        text, page_list, words, warnings = read_pdf(
            path, options["pages"], raws, data=source, scan=scan, ocr=ocr
        )
        if not is_nfc(text):  # pragma: no cover - words are normalised one by one
            raise ReadError(f"{path}: extracted text is not NFC")
        layout = Layout(digest("document", {"text": text}), tuple(page_list), tuple(words))
        extracted = Extracted(text, layout, tuple(warnings), scan.version)
        doubt = scan.doubt
        data = text.encode("utf-8")
        chars = chars_of_bytes(data, [p for r in raws for p in (r.start, r.end) if p >= 0])
        for r in raws:
            r.start = chars[r.start]
            r.end = chars[r.end] if r.end >= 0 else -1
    else:
        if suffix == ".xml":
            import xml.etree.ElementTree as ET

            from .markup import xml_nodes

            try:
                text, raws = xml_nodes(source)
            except ET.ParseError as e:
                raise ReadError(f"{path}: not well-formed XML ({e})") from e
        elif suffix in HTML_SUFFIXES:
            from .markup import html_nodes

            text, raws = html_nodes(_decode(source, path))
        elif suffix in OFFICE_SUFFIXES:
            from .office import office_nodes

            text, raws = office_nodes(source, path)
        elif suffix in TEXT_SUFFIXES:
            text = unicodedata.normalize("NFC", _decode(source, path))
            raws = _paragraphs(text)
        else:
            raise ReadError(f"{path}: unsupported file type {suffix or '(none)'}")
        empty = () if text.strip() else (f"{path.name}: no text was extracted",)
        extracted = Extracted(text, warnings=empty)
    from ..store import key

    obj = {
        "format": FORMAT,
        "source": key("source@1", source),
        "reader": reader(extracted.ocr),
        "options": options,
        "text": key("text@1", extracted.text.encode("utf-8")),
        "nodes": finish(extracted.text, raws),
        "doubt": doubt,
    }
    return extracted, Document.from_dict(obj, extracted.text)


def _paragraphs(text: str) -> list[Raw]:
    """The blocks of a text file between blank lines. A blank line holds only whitespace."""
    out: list[Raw] = []
    start: int | None = None
    pos = 0
    for line in text.split("\n"):
        if line.strip():
            if start is None:
                start = pos
        elif start is not None:
            out.append(Raw("paragraph", "layout", start, end=pos - 1))
            start = None
        pos += len(line) + 1
    if start is not None:
        out.append(Raw("paragraph", "layout", start, end=len(text)))
    return out
