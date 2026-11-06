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


def _in_row(grid: _Grid, cells: list[Node], spanned: list[Node], label: Node) -> Node | None:
    """The one data cell with text after ``label`` in its row."""
    row, left = _place(label)
    for cell in spanned:
        assert cell.row is not None and cell.rows is not None
        if cell.row <= row < cell.row + cell.rows:
            return None
    after = [c for c in cells if c.row == row and _place(c)[1] > left]
    full = [c for c in after if c.start < c.end]
    if len(full) != 1:
        return None
    column = _place(full[0])[1]
    # Each cell of a row is in the list, so this walk costs no more than the list.
    if column - left > len(after) or not _whole(grid, ((row, c) for c in range(left, column + 1))):
        return None
    return full[0] if full[0].header is False else None


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
    for cell in cells:
        if cell.start < cell.end:
            texts.setdefault(_name(data[cell.start : cell.end].decode("utf-8")), []).append(cell)

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

    for name, field in schema.fields.items():
        labels = [c for n, who in names.items() if who == {name} for c in texts.get(n, ())]
        if not labels:
            continue
        if field.keys is None:
            one = _in_row(grid, cells, spanned, labels[0]) if len(labels) == 1 else None
            add(field, None, labels[0], None, one)
            continue
        wanted = [_name(k) for k in field.keys]
        for key, form in zip(field.keys, wanted, strict=True):
            headers = texts.get(form, ())
            if not headers:
                continue
            if wanted.count(form) > 1 or len(labels) * len(headers) > 1:
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
    match, and the basis of a line is always ``layout``."""
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
    return [m[0] for m in found.values() if len(m) == 1 and m[0] is not None]
