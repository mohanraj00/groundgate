"""The structure reader: a proposer with no model (docs/design/document-model.md §8).

The reader finds a value in two ways. A table cell is the cell at the row of a label and the
column of a header. A ``label: value`` line is a line outside tables with one label and one value.
The labels come from the schema ``aliases``, and the headers come from the schema ``keys``. No
reader gives form fields yet, so this module reads none.

The reader is not part of a decision. It reads cells by their grid position, and ``admit`` checks
the result on the text (SPEC §4.5, §4.6). So this module imports nothing from ``groundgate.text``
or ``groundgate.admit``: a shared selection would repeat its own errors in the check.

If a value is not clear, the reader proposes nothing for the field and key. A wrong row is worse
than no row.
"""

from __future__ import annotations

import heapq
import re
from bisect import bisect_right
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ..read.document import Document, Node

if TYPE_CHECKING:
    from ..model import Field, Schema

Json = dict[str, Any]
# A match is a candidate, or None for a match with no clear value. Two matches give no candidate.
_Found = dict[tuple[str, str | None], list[Json | None]]
_Grid = dict[tuple[int, int], Node]

_MINUS = chr(0x2212)
_NUMBER = re.compile(rf"(?<![\w.,])[-{_MINUS}]?[0-9][0-9,]*(?:\.[0-9]+)?")


def _name(text: str) -> str:
    """The form in which a cell or a line matches a label or a header."""
    return " ".join(text.split()).casefold().removesuffix(":").rstrip()


def _value(field: Field, text: str) -> str | None:
    """The value in ``text``. A number field needs exactly one number with no brackets."""
    if field.type == "string":
        return text
    found = _NUMBER.search(text)
    if found is None:
        return None
    rest = text[: found.start()] + text[found.end() :]
    if any(c.isnumeric() or c in "()" for c in rest):
        return None
    return found.group().replace(",", "").replace(_MINUS, "-")


def _trim(data: bytes, start: int, end: int) -> tuple[int, int]:
    """The span without whitespace at its start or its end."""
    text = data[start:end].decode("utf-8")
    left = len(text) - len(text.lstrip())
    return start + len(text[:left].encode("utf-8")), end - len(
        text[len(text.rstrip()) :].encode("utf-8")
    )


def _item(role: str, start: int, end: int) -> Json:
    return {"source": "document", "role": role, "start": start, "end": end}


def _place(cell: Node) -> tuple[int, int]:
    assert cell.row is not None and cell.column is not None
    return cell.row, cell.column


def _spanned(cell: Node) -> bool:
    return cell.rows != 1 or cell.columns != 1


def _whole(grid: _Grid, places: Iterable[tuple[int, int]]) -> bool:
    return all(place in grid for place in places)


def _at_header(grid: _Grid, count: int, label: Node, header: Node) -> Node | None:
    """The value cell at the row of ``label`` and the column of ``header``."""
    row, left = _place(label)
    top, column = _place(header)
    # A path longer than the cells of the table holds a gap, so it stops before the walk.
    if header.header is not True or column <= left or row <= top:
        return None
    if column - left + row - top > count:
        return None
    # The grid has no spanned cell, so a spanned cell on either path is a gap in the path.
    across = ((row, c) for c in range(left, column + 1))
    down = ((r, column) for r in range(top, row + 1))
    if not (_whole(grid, across) and _whole(grid, down)):
        return None
    value = grid[row, column]
    return None if value.header is True else value


class _Row:
    """The cells of one row, in the order of their column."""

    def __init__(self, cells: list[Node]) -> None:
        cells.sort(key=lambda c: _place(c)[1])
        self.columns = [_place(c)[1] for c in cells]
        self.full = [c for c in cells if c.start < c.end]
        self.full_columns = [_place(c)[1] for c in self.full]


def _in_row(grid: _Grid, row_of: _Row, label: Node) -> Node | None:
    """The one data cell with text after ``label`` in its row."""
    row, left = _place(label)
    # A bisect on the sorted columns, so a row with many labels costs no more than its cells.
    after = len(row_of.columns) - bisect_right(row_of.columns, left)
    first = bisect_right(row_of.full_columns, left)
    if len(row_of.full) - first != 1:
        return None
    value = row_of.full[first]
    column = _place(value)[1]
    # One cell with text follows the label, so the walks of a row cover each cell once at most.
    if column - left > after or not _whole(grid, ((row, c) for c in range(left, column + 1))):
        return None
    return value if value.header is False else None


def _least_columns(blockers: list[Node], rows: Iterable[int]) -> dict[int, int]:
    """For each row in ``rows``, the least column of a cell in ``blockers`` that covers the row."""
    order = sorted(blockers, key=lambda c: _place(c)[0])
    active: list[tuple[int, int]] = []  # (column, the first row after the cell)
    least: dict[int, int] = {}
    at = 0
    for row in sorted(set(rows)):
        while at < len(order) and _place(order[at])[0] <= row:
            top, column = _place(order[at])
            heapq.heappush(active, (column, top + (order[at].rows or 1)))
            at += 1
        while active and active[0][1] <= row:
            heapq.heappop(active)
        if active:
            least[row] = active[0][0]
    return least


def _candidate(
    field: Field, key: str | None, text: str, places: dict[str, tuple[int, int]], bases: Json
) -> Json | None:
    value = _value(field, text)
    if value is None:
        return None
    return {
        "field": field.name,
        "value": value,
        "unit": field.unit,
        "key": key,
        "evidence": [_item(role, *span) for role, span in places.items()],
        "basis": bases,
    }


def _nested(document: Document) -> set[int]:
    """The ids of the cells that hold a table. The text of such a cell is not one value."""
    out: set[int] = set()
    seen: set[int] = set()
    for table in document.of_kind("table"):
        at = table.parent
        while at is not None and at not in seen:
            seen.add(at)
            node = document.node(at)
            if node.kind == "cell":
                out.add(at)
            at = node.parent
    return out


def _table(
    document: Document,
    table: Node,
    data: bytes,
    names: dict[str, set[str]],
    nested: set[int],
    found: _Found,
    schema: Schema,
) -> None:
    cells = [
        cell
        for row in document.children(table.id)
        for cell in document.children(row.id)
        if cell.kind == "cell"
    ]
    single = [c for c in cells if not _spanned(c)]
    grid = {_place(c): c for c in single}
    if len(grid) != len(single):
        return  # two cells at one place: a loaded object can say this, and no cell is clear
    spanned = [c for c in cells if _spanned(c)]
    texts: dict[str, list[Node]] = {}
    blockers: list[Node] = []
    for cell in cells:
        if cell.start < cell.end:
            form = _name(data[cell.start : cell.end].decode("utf-8"))
            texts.setdefault(form, []).append(cell)
            if cell.header is True or form in names:
                blockers.append(cell)

    def add(
        field: Field, key: str | None, label: Node, header: Node | None, value: Node | None
    ) -> None:
        target = found.setdefault((field.name, key), [])
        if value is None or value.start == value.end or value.id in nested:
            target.append(None)
            return
        places = {"value": (value.start, value.end), "field": (label.start, label.end)}
        bases = {"value": value.basis, "field": label.basis}
        if header is not None:
            places["key"] = (header.start, header.end)
            bases["key"] = header.basis
        text = data[value.start : value.end].decode("utf-8")
        target.append(_candidate(field, key, text, places, bases))

    # Look up each cell text once: a scan of every alias for each table costs fields x aliases.
    found_labels: dict[str, list[Node]] = {}
    for form, held in texts.items():
        who = names.get(form)
        if who is not None and len(who) == 1:
            found_labels.setdefault(next(iter(who)), []).extend(held)
    # A label is the row label only if no header and no other label comes before it in its row:
    # in "Cost | Revenue | 5", "Revenue" is a data cell of the row of "Cost".
    label_rows = [_place(c)[0] for held in found_labels.values() for c in held]
    least = _least_columns(blockers, label_rows)
    covered = _least_columns(spanned, label_rows)  # the rows that a spanned cell covers
    by_row: dict[int, list[Node]] = {}
    for cell in cells:
        by_row.setdefault(_place(cell)[0], []).append(cell)
    rows = {row: _Row(held) for row, held in by_row.items()}
    for name, labels in found_labels.items():
        field = schema.fields[name]
        inner = any(least[_place(c)[0]] < _place(c)[1] for c in labels)
        if field.keys is None:
            one = None
            if len(labels) == 1 and not inner and _place(labels[0])[0] not in covered:
                one = _in_row(grid, rows[_place(labels[0])[0]], labels[0])
            add(field, None, labels[0], None, one)
            continue
        wanted = [_name(k) for k in field.keys]
        for key, form in zip(field.keys, wanted, strict=True):
            headers = texts.get(form, ())
            if not headers:
                continue
            if inner or wanted.count(form) > 1 or len(labels) * len(headers) > 1:
                found.setdefault((name, key), []).append(None)
                continue
            value = _at_header(grid, len(cells), labels[0], headers[0])
            add(field, key, labels[0], headers[0], value)


def _lines(
    data: bytes, tables: list[Node], names: dict[str, set[str]], found: _Found, schema: Schema
) -> None:
    starts = [t.start for t in tables]
    ends: list[int] = []
    for table in tables:  # the largest end so far: a table can hold a table
        ends.append(max(table.end, ends[-1]) if ends else table.end)
    at = 0
    for line in data.split(b"\n"):
        start, at = at, at + len(line) + 1
        colon = line.find(b":")
        if colon < 0 or b"\t" in line:
            continue
        before = bisect_right(starts, start + len(line)) - 1
        if before >= 0 and ends[before] > start:
            continue
        who = names.get(_name(line[:colon].decode("utf-8")))
        if who is None or len(who) != 1:
            continue
        field = schema.fields[next(iter(who))]
        if field.keys is not None:
            continue
        label = _trim(data, start, start + colon)
        value = _trim(data, start + colon + 1, start + len(line))
        if value[0] == value[1]:
            continue
        text = data[value[0] : value[1]].decode("utf-8")
        places = {"value": value, "field": label}
        bases = {"value": "layout", "field": "layout"}
        found.setdefault((field.name, None), []).append(
            _candidate(field, None, text, places, bases)
        )


def propose(text: str, document: Document | None, schema: Schema) -> list[Json]:
    """The candidates of the reader, with no ``id`` and no ``proposer``: the runner sets them.

    Each candidate has the extra member ``basis``, the basis of each cell that it cites by role.
    ``admit`` ignores this member (SPEC §2.5). A plain text has no cells, so only its lines can
    match, and the basis of a line is always ``layout``. The candidates are in the order of
    their field name, then in the order of the keys of the field."""
    names: dict[str, set[str]] = {}
    for name, field in schema.fields.items():
        for alias in field.aliases or ():
            names.setdefault(_name(alias), set()).add(name)
    data = text.encode("utf-8")
    found: _Found = {}
    tables = [] if document is None else document.of_kind("table")
    if document is not None:
        nested = _nested(document)
        for table in tables:
            _table(document, table, data, names, nested, found, schema)
    _lines(data, tables, names, found, schema)

    # Sort by field name, not by schema order: a saved schema is canonical JSON, so its fields
    # load in sorted order, and replay must give the same candidate IDs (#510). The keys of a
    # field are a list, so the key order is the schema order, in all tables.
    def place(item: tuple[tuple[str, str | None], list[Json | None]]) -> tuple[str, int]:
        (name, key), _ = item
        keys = schema.fields[name].keys
        return name, -1 if key is None or keys is None else keys.index(key)

    ordered = sorted(found.items(), key=place)
    return [m[0] for _, m in ordered if len(m) == 1 and m[0] is not None]
