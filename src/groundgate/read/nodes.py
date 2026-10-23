"""The nodes of ``document@1`` while a reader builds them (docs/design/document-model.md §4).

A reader records each node as a ``Raw`` with code point offsets into its text. ``finish`` then
trims the whitespace at the two ends of each span, drops each node that breaks a rule of §4.2,
and gives the nodes with UTF-8 byte offsets. A node is information only: a dropped node never
changes the text.
"""

from __future__ import annotations

import bisect
import itertools
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

MAX_NODES = 2**17  # the loader refuses more; a reader stops at this number (#521)
MAX_DEPTH = 256  # open elements, and the depth of a node; a reader stops deeper than this
MAX_SPAN = 1000  # a larger rowspan or colspan counts as this number
GRID_BUDGET = 4_000_000  # grid steps for the table cells of one document
MAX_COLUMNS = 2**14  # a table wider than this stops the reader

# The kinds that each kind can have as parent (§4.2 rule 4). None is the top level.
PARENTS: dict[str, frozenset[str | None]] = {
    "heading": frozenset({None, "cell", "item"}),
    "paragraph": frozenset({None, "cell", "item"}),
    "list": frozenset({None, "cell", "item"}),
    "table": frozenset({None, "cell", "item"}),
    "item": frozenset({"list"}),
    "row": frozenset({"table"}),
    "cell": frozenset({"row"}),
}


@dataclass(slots=True)
class Raw:
    """A node while a reader builds it. ``end`` is -1 until the node closes."""

    kind: str
    basis: str
    start: int
    parent: int | None = None
    end: int = -1
    keep: bool = True
    members: dict[str, Any] | None = None  # the level of a heading, the grid place of a cell


class Tracker:
    """The open elements of a markup reader, and the nodes that they give.

    ``position`` gives the current length of the text that the writer collected. A role is
    ``heading``, ``block``, ``list``, ``item``, ``table``, ``row`` or ``cell``. A ``block`` is a
    paragraph only when no other node opens inside it.
    """

    def __init__(self, position: Any) -> None:
        self.position = position
        self.nodes: list[Raw] = []
        self.stack: list[tuple[str, int]] = []  # (tag, index into nodes)
        self.inner: set[int] = set()  # blocks with a node inside
        self.tables: dict[int, _Grid] = {}
        self.budget = GRID_BUDGET
        self.stopped = False

    def open(self, tag: str, role: str, basis: str, members: dict[str, Any] | None = None) -> None:
        if self.stopped:
            return
        if len(self.stack) >= MAX_DEPTH or len(self.nodes) >= MAX_NODES:
            self.stopped = True  # the open nodes never close, so ``finish`` drops them
            return
        parent = self.stack[-1][1] if self.stack else None
        if parent is not None and self.nodes[parent].kind == "block":
            self.inner.add(parent)
        node = Raw(role, basis, self.position(), parent, members=dict(members) if members else None)
        n = len(self.nodes)
        if role == "table":
            self.tables[n] = _Grid()
        elif role == "row":
            table = self._nearest("table")
            if table is not None:
                self.tables[table].next_row()
        elif role == "cell":
            self._place(node)
        self.nodes.append(node)
        self.stack.append((tag, n))

    def _nearest(self, role: str) -> int | None:
        for _, n in reversed(self.stack):
            if self.nodes[n].kind == role:
                return n
            if self.nodes[n].kind == "table":
                return None
        return None

    def _place(self, node: Raw) -> None:
        members = node.members = node.members or {}
        rows, columns = members.pop("rows", 1), members.pop("columns", 1)
        table = self._nearest("table") if self._nearest("row") is not None else None
        if table is None:
            node.keep = False
            return
        grid = self.tables[table]
        row, column, cost = grid.place(rows, columns)
        self.budget -= cost
        if self.budget < 0 or column + columns > MAX_COLUMNS:
            self.stopped = True
            node.keep = False
            return
        members.update(row=row, column=column, rows=rows, columns=columns)

    def close(self, tag: str) -> None:
        """Close the innermost open ``tag`` and each element above it. An end tag with no open
        element is ignored. After a stop, nothing closes, so no span ends in the wrong place."""
        if self.stopped or not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            t, n = self.stack.pop()
            self.nodes[n].end = self.position()
            if t == tag:
                return

    def close_any(self, tags: Iterable[str], scope: Iterable[str]) -> None:
        """Close the innermost open element of ``tags`` when no element of ``scope`` is above
        it."""
        tags, scope = set(tags), set(scope)
        for tag, _ in reversed(self.stack):
            if tag in tags:
                self.close(tag)
                return
            if tag in scope:
                return

    def done(self) -> list[Raw]:
        """The nodes. At the end of the text, each open element closes. After a stop, each open
        element stays open, so ``finish`` drops it."""
        while self.stack and not self.stopped:
            self.close(self.stack[-1][0])
        for n, node in enumerate(self.nodes):
            if node.kind == "block":
                node.kind = "paragraph"
                node.keep = node.keep and n not in self.inner
        return self.nodes


class _Grid:
    """The grid positions of one table, after spanned cells (§4.2 rule 5)."""

    def __init__(self) -> None:
        self.row = -1
        self.column = 0
        self.taken: dict[int, int] = {}  # column -> the last row that a spanned cell covers

    def next_row(self) -> None:
        self.row += 1
        self.column = 0

    def place(self, rows: int, columns: int) -> tuple[int, int, int]:
        row = max(self.row, 0)
        column, cost = self.column, columns if rows > 1 else 1
        while self.taken.get(column, -1) >= row and column <= MAX_COLUMNS:
            column += 1
            cost += 1
        if rows > 1 and column + columns <= MAX_COLUMNS:
            for c in range(column, column + columns):
                self.taken[c] = max(self.taken.get(c, -1), row + rows - 1)
        self.column = column + columns
        return row, column, cost


def span_number(value: str | None) -> int:
    """The number of a ``rowspan`` or ``colspan`` attribute, 1 to MAX_SPAN. A value that is not
    a positive integer counts as 1."""
    text = (value or "").strip()
    if not text.isascii() or not text.isdigit():
        return 1
    digits = text.lstrip("0")  # "0002" is 2; the cap applies to the value, not to the string
    return max(1, min(int(digits[:5] or "0"), MAX_SPAN))


class PageNodes:
    """The nodes of the PDF text layer, with byte offsets (``read/pdf.py``). A block of prose is
    a paragraph. A table block gives a table, its rows and its cells. ``kind`` is ``None`` for
    prose, ``layout`` for a table from ``_tables`` and ``rules`` for a ruled table."""

    def __init__(self, sink: list[Raw]) -> None:
        self.sink = sink
        self.kind: str | None = None
        self.table = self.row = -1
        self.rows = self.column = 0

    def block(self, kind: str | None, at: int) -> None:
        self.kind = kind
        self.table = len(self.sink)
        self.rows = 0
        self.sink.append(Raw("paragraph" if kind is None else "table", kind or "layout", at))

    def start_row(self, at: int) -> None:
        if self.kind is not None:
            self.row, self.column = len(self.sink), 0
            self.sink.append(Raw("row", self.kind, at, self.table))

    def start_cell(self, at: int) -> None:
        if self.kind is not None:
            members = {"row": self.rows, "column": self.column, "rows": 1, "columns": 1}
            self.sink.append(Raw("cell", self.kind, at, self.row, members=members))
            self.column += 1

    def end_cell(self, at: int) -> None:
        if self.kind is not None:
            self.sink[-1].end = at

    def end_row(self, at: int) -> None:
        if self.kind is not None:
            self.sink[self.row].end = at
            if self.column:
                self.rows += 1
            else:
                self.sink[self.row].keep = False

    def end_block(self, at: int) -> None:
        self.sink[self.table].end = at


def chars_of_bytes(data: bytes, positions: Iterable[int]) -> dict[int, int]:
    """The code point offset of each byte offset in ``positions``."""
    out: dict[int, int] = {}
    last_byte = last_char = 0
    for b in sorted(set(positions)):
        last_char += len(data[last_byte:b].decode("utf-8", "replace"))
        last_byte = b
        out[b] = last_char
    return out


def bytes_of_chars(text: str, positions: Iterable[int]) -> dict[int, int]:
    """The UTF-8 byte offset of each code point offset in ``positions``."""
    out: dict[int, int] = {}
    last_char = last_byte = 0
    for c in sorted(set(positions)):
        last_byte += len(text[last_char:c].encode("utf-8"))
        last_char = c
        out[c] = last_byte
    return out


def nfc_map(pre: str, positions: Iterable[int]) -> dict[int, int] | None:
    """The offset in ``NFC(pre)`` of each offset in ``pre``, or None when a composition crosses
    one of the offsets."""
    cuts = sorted(set(positions) | {0, len(pre)})
    if unicodedata.is_normalized("NFC", pre):
        return {c: c for c in cuts}
    out: dict[int, int] = {}
    pieces: list[str] = []
    size = 0
    for a, b in itertools.pairwise(cuts):
        out[a] = size
        piece = unicodedata.normalize("NFC", pre[a:b])
        pieces.append(piece)
        size += len(piece)
    out[cuts[-1]] = size
    if "".join(pieces) != unicodedata.normalize("NFC", pre):
        return None
    return out


class Kept:
    """The parts of a writer's raw text that ``_Writer.result`` keeps, and the offset in the
    result of each raw offset. ``result`` takes the spaces and tabs at the end of each line, and
    the line breaks at the two ends of the text. Adjacent kept parts are one run."""

    def __init__(self, raw: str) -> None:
        starts: list[int] = []
        ends: list[int] = []

        def keep(a: int, b: int) -> None:
            if a == b:
                return
            if ends and ends[-1] == a:
                ends[-1] = b
            else:
                starts.append(a)
                ends.append(b)

        first = len(raw) - len(raw.lstrip(" \t\n"))  # blank lines at the start go
        first = raw.rfind("\n", 0, first) + 1 if first else 0
        pos = first
        while pos <= len(raw):
            stop = raw.find("\n", pos)
            stop = len(raw) if stop < 0 else stop
            line_end = pos + len(raw[pos:stop].rstrip(" \t"))
            keep(pos, line_end)
            if stop < len(raw):
                keep(stop, stop + 1)  # the line break
            pos = stop + 1
        # the line breaks (and the blank lines) at the end go
        while ends and raw[ends[-1] - 1] == "\n":
            ends[-1] -= 1
            if ends[-1] == starts[-1]:
                starts.pop()
                ends.pop()
        self.starts, self.ends = starts, ends
        self.before: list[int] = []
        size = 0
        for a, b in zip(starts, ends, strict=True):
            self.before.append(size)
            size += b - a
        self.size = size

    def __call__(self, p: int) -> int:
        i = bisect.bisect_right(self.starts, p) - 1
        if i < 0:
            return 0
        a, b = self.starts[i], self.ends[i]
        return self.before[i] + min(p - a, b - a)


def finish(text: str, raws: list[Raw]) -> list[dict[str, Any]]:
    """The node objects of ``raws``, whose offsets are code points into ``text``.

    Each span loses the whitespace at its two ends. A node is dropped when it did not close, when
    its span is empty (an empty cell keeps a zero-width span inside its row), or when it breaks
    the order, the nesting or the parent kinds of §4.2. The children of a dropped node get the
    nearest node above it as parent. The first MAX_NODES nodes stay.
    """
    for raw in raws:  # trim each span in place; a node that did not close goes
        s, e = raw.start, raw.end
        if not raw.keep or e < s:
            raw.keep = False
            continue
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        raw.start, raw.end = s, e
    ids: dict[int, int] = {}  # raw index -> node id
    kept: list[Raw] = []
    parents: list[int | None] = []  # the parent id of each kept node
    last_end: dict[int | None, int] = {}  # the end of the last child of each parent id
    last_start = 0
    for n, raw in enumerate(raws):
        if not raw.keep or len(kept) >= MAX_NODES:
            continue
        up = raw.parent
        while up is not None and up not in ids:
            up = raws[up].parent
        parent = None if up is None else ids[up]
        if parent is None:
            parent_kind, lo, hi = None, 0, len(text)
        else:
            above = kept[parent]
            parent_kind, lo, hi = above.kind, above.start, above.end
        if parent_kind not in PARENTS[raw.kind]:
            continue
        s, e = raw.start, raw.end
        if s == e:
            if raw.kind != "cell":
                continue
            s = e = min(max(s, lo), hi)
        if not (lo <= s and e <= hi and s >= last_start and s >= last_end.get(parent, 0)):
            continue
        raw.start, raw.end = s, e
        ids[n] = len(kept)
        kept.append(raw)
        parents.append(parent)
        last_end[parent] = e
        last_start = s
    del ids, last_end
    offsets = bytes_of_chars(text, [p for raw in kept for p in (raw.start, raw.end)])
    out = []
    for i, raw in enumerate(kept):
        node: dict[str, Any] = {
            "id": i,
            "kind": raw.kind,
            "basis": raw.basis,
            "parent": parents[i],
            "start": offsets[raw.start],
            "end": offsets[raw.end],
        }
        members = raw.members or {}
        if raw.kind == "heading":
            node["level"] = members["level"]
        elif raw.kind == "cell":
            node.update({k: members[k] for k in ("row", "column", "rows", "columns")})
            node["header"] = members.get("header")
        out.append(node)
    return out
