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
import unicodedata
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from ..read.document import Document, Node
from ..read.nodes import MAX_SPAN

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


def _dash(c: str) -> bool:
    return c in ("-", _MINUS) or unicodedata.category(c) == "Pd"


def _value(field: Field, text: str) -> str | None:
    """The value in ``text``. A number field needs exactly one number with no brackets, no
    colon, and no letter before the number. In "N/A, Cost: 5" the 5 is the value of Cost.
    A dash or a minus outside the number can be a sign, as in "-$5", so it gives nothing."""
    if field.type == "string":
        return text
    found = _NUMBER.search(text)
    if found is None or ":" in text or any(c.isalpha() for c in text[: found.start()]):
        return None
    rest = text[: found.start()] + text[found.end() :]
    if any(c.isnumeric() or c in "()" or _dash(c) for c in rest):
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


class _Runs:
    """For each place of the grid, the first column of its run of places to the left and the
    first row of its run of places above. The pass also keeps the last header cell of each run
    up to the place, and a cell with a null header counts as a header there, because it can be
    one. One pass over the grid gives all of them, so a check of a path costs no walk."""

    def __init__(self, grid: _Grid) -> None:
        self.left: dict[tuple[int, int], int] = {}
        self.top: dict[tuple[int, int], int] = {}
        self.head_column: dict[tuple[int, int], int] = {}  # -1 when the run has no header
        self.head_row: dict[tuple[int, int], int] = {}
        for row, column in sorted(grid):
            self.left[row, column] = self.left.get((row, column - 1), column)
            last = self.head_column.get((row, column - 1), -1)
            head = grid[row, column].header is not False
            self.head_column[row, column] = column if head else last
        for row, column in sorted(grid, key=lambda p: (p[1], p[0])):
            self.top[row, column] = self.top.get((row - 1, column), row)
            last = self.head_row.get((row - 1, column), -1)
            head = grid[row, column].header is not False
            self.head_row[row, column] = row if head else last

    def across(self, row: int, left: int, column: int) -> bool:
        """True if the grid holds each place of ``row`` from ``left`` to ``column``."""
        return self.left.get((row, column), column + 1) <= left

    def down(self, column: int, top: int, row: int) -> bool:
        """True if the grid holds each place of ``column`` from ``top`` to ``row``."""
        return self.top.get((row, column), row + 1) <= top


def _at_header(grid: _Grid, runs: _Runs, label: Node, header: Node) -> Node | None:
    """The value cell at the row of ``label`` and the column of ``header``."""
    row, left = _place(label)
    top, column = _place(header)
    if header.header is not True or column <= left or row <= top:
        return None
    # The grid has no spanned cell, so a spanned cell on either path is a gap in the path.
    if not (runs.across(row, left, column) and runs.down(column, top, row)):
        return None
    # A header cell between the header and the value starts a new header: in "Item | 2024;
    # Cost | 5; Item | 2023; Revenue | 4", the 4 is under 2023. A header cell between the
    # label and the value is not clear either.
    if runs.head_row[row - 1, column] != top or runs.head_column[row, column - 1] > left:
        return None
    # A value with a null header can be a row header, as a ``th`` with the scope ``row``.
    value = grid[row, column]
    return value if value.header is False else None


class _Row:
    """The cells of one row, in the order of their column."""

    def __init__(self, cells: list[Node]) -> None:
        cells.sort(key=lambda c: _place(c)[1])
        self.full = [c for c in cells if c.start < c.end]
        self.full_columns = [_place(c)[1] for c in self.full]


def _in_row(runs: _Runs, row_of: _Row, label: Node) -> Node | None:
    """The one data cell with text after ``label`` in its row."""
    row, left = _place(label)
    # A bisect on the sorted columns, so a row with many labels costs no more than its cells.
    first = bisect_right(row_of.full_columns, left)
    if len(row_of.full) - first != 1:
        return None
    value = row_of.full[first]
    column = _place(value)[1]
    # An empty cell has no text, so the row text does not show a header cell between them.
    if not runs.across(row, left, column) or runs.head_column[row, column - 1] > left:
        return None
    return value if value.header is False else None


def _covers_a_place(grid: _Grid, spanned: list[Node]) -> bool:
    """True if a cell in ``spanned`` covers a place of ``grid``. A loaded object can say this.

    A sweep over the rows with a Fenwick tree over the columns counts the places in each
    rectangle, so a large span costs no walk of its area."""
    columns = sorted({c for _, c in grid})
    points = sorted(grid)
    # (row, sign, cell, first index, index after the last): the places above ``row`` in the
    # columns of the cell. The two queries of a cell give the places of the cell together.
    queries: list[tuple[int, int, int, int, int]] = []
    for at, cell in enumerate(spanned):
        top, left = _place(cell)
        low = bisect_left(columns, left)
        high = bisect_left(columns, left + (cell.columns or 1))
        if low < high:
            queries.append((top, -1, at, low, high))
            queries.append((top + (cell.rows or 1), 1, at, low, high))
    tree = [0] * (len(columns) + 1)

    def count(index: int) -> int:  # the added places in the first ``index`` columns
        total = 0
        while index > 0:
            total += tree[index]
            index -= index & -index
        return total

    places = [0] * len(spanned)
    added = 0
    for row, sign, at, low, high in sorted(queries):
        while added < len(points) and points[added][0] < row:
            index = bisect_left(columns, points[added][1]) + 1
            while index <= len(columns):
                tree[index] += 1
                index += index & -index
            added += 1
        places[at] += sign * (count(high) - count(low))
    return any(places)


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


def _cells_hold_the_text(data: bytes, table: Node, rows: list[tuple[Node, list[Node]]]) -> bool:
    """True if the cells hold all the text of the table. A byte outside the cells must be
    whitespace, from the start of the table to its end. A loaded object can leave out a cell,
    or a row, and its text then shifts the cells after it."""
    at = table.start
    for row, held in rows:
        if row.start < at or data[at : row.start].strip():
            return False
        at = row.start
        for cell in held:
            if cell.start < at or data[at : cell.start].strip():
                return False
            at = cell.end
        if row.end < at or data[at : row.end].strip():
            return False
        at = row.end
    return table.end >= at and not data[at : table.end].strip()


def _table(
    document: Document,
    table: Node,
    data: bytes,
    names: dict[str, set[str]],
    keys_of: dict[str, dict[str, list[str]]],
    nested: set[int],
    found: _Found,
    schema: Schema,
) -> None:
    cells: list[Node] = []
    last = -1
    row_cells: list[tuple[Node, list[Node]]] = []
    for row in document.children(table.id):
        held = [c for c in document.children(row.id) if c.kind == "cell"]
        row_cells.append((row, held))
        # A loaded object can give the cells any place. The places must follow the text: one
        # row for each row node, rows in the order of the nodes, columns in the order of the
        # cells. Else a swap of two values gives each the header of the other.
        places = [_place(c) for c in held]
        if any(r != places[0][0] for r, _ in places) or (places and places[0][0] <= last):
            return
        if any(a[1] >= b[1] for a, b in pairwise(places)):
            return
        if places:
            last = places[0][0]
        cells.extend(held)
    if any(c.id in nested for c in cells):
        return  # the text of a cell with a table is not one label, header or value
    if not _cells_hold_the_text(data, table, row_cells):
        return
    single = [c for c in cells if not _spanned(c)]
    grid = {_place(c): c for c in single}
    if len(grid) != len(single):
        return  # two cells at one place: a loaded object can say this, and no cell is clear
    spanned = [c for c in cells if _spanned(c)]
    if any(c.rows == MAX_SPAN and _place(c)[0] + MAX_SPAN <= last for c in spanned):
        return  # the reader caps a span at MAX_SPAN rows, and the source span can go past it
    if _covers_a_place(grid, spanned):
        return  # a spanned cell over a place of the grid: no path through it is clear
    runs = _Runs(grid)
    texts: dict[str, list[Node]] = {}
    for cell in cells:
        if cell.start < cell.end:
            form = _name(data[cell.start : cell.end].decode("utf-8"))
            texts.setdefault(form, []).append(cell)

    def add(
        field: Field, key: str | None, label: Node, header: Node | None, value: Node | None
    ) -> None:
        target = found.setdefault((field.name, key), [])
        if value is None or value.start == value.end:
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
    # A label is the row label only if no cell comes before it in its row: in "Cost | Revenue |
    # 5", "Revenue" is a data cell of the row of "Cost", also when no field names "Cost". An
    # empty cell counts too, because the text of the row does not show it.
    label_rows = [_place(c)[0] for held in found_labels.values() for c in held]
    least = _least_columns(cells, label_rows)
    covered = _least_columns(spanned, label_rows)  # the rows that a spanned cell covers
    by_row: dict[int, list[Node]] = {}
    for cell in cells:
        by_row.setdefault(_place(cell)[0], []).append(cell)
    rows = {row: _Row(held) for row, held in by_row.items()}
    # A header is a column header only in a row of headers. The document keeps no scope, so in
    # "Cost | <th scope=row>2024</th> | 5" the 2024 can be a row header for Cost alone.
    head_rows = {
        row
        for row, held in by_row.items()
        if all(c.header is True for c in held if c.start < c.end)
    }
    for name, labels in found_labels.items():
        field = schema.fields[name]
        inner = any(least[_place(c)[0]] < _place(c)[1] for c in labels)
        if field.keys is None:
            one = None
            if len(labels) == 1 and not inner and _place(labels[0])[0] not in covered:
                one = _in_row(runs, rows[_place(labels[0])[0]], labels[0])
            add(field, None, labels[0], None, one)
            continue
        # Scan the smaller of the cell texts and the keys, so a large key list costs a table
        # no more than its cells.
        forms = keys_of.get(name, {})
        matched = (
            [f for f in forms if f in texts]
            if len(forms) < len(texts)
            else [f for f in texts if f in forms]
        )
        for form in matched:
            keys, headers = forms[form], texts[form]
            if (
                inner
                or len(keys) > 1
                or len(labels) * len(headers) > 1
                or _place(headers[0])[0] not in head_rows
            ):
                for key in keys:
                    found.setdefault((name, key), []).append(None)
                continue
            value = _at_header(grid, runs, labels[0], headers[0])
            add(field, keys[0], labels[0], headers[0], value)


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
        if colon < 0:
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
        # In "Revenue: N/A, Cost: 5" the 5 is the value of Cost. A second colon can be a second
        # label; _value refuses a letter before a number. A refused line still counts as a
        # match, so a second line of the same field does not become the only match.
        # A tab can split the line into cells that the text does not mark. The line still counts.
        target = found.setdefault((field.name, None), [])
        if ":" in text or b"\t" in line:
            target.append(None)
            continue
        places = {"value": value, "field": label}
        bases = {"value": "layout", "field": "layout"}
        target.append(_candidate(field, None, text, places, bases))


def propose(text: str, document: Document | None, schema: Schema) -> list[Json]:
    """The candidates of the reader, with no ``id`` and no ``proposer``: the runner sets them.

    Each candidate has the extra member ``basis``, the basis of each cell that it cites by role.
    ``admit`` ignores this member (SPEC §2.5). A plain text has no cells, so only its lines can
    match, and the basis of a line is always ``layout``. The candidates are in the order of
    their field name, then in the order of the keys of the field."""
    names: dict[str, set[str]] = {}
    keys_of: dict[str, dict[str, list[str]]] = {}  # field -> key form -> keys, in schema order
    for name, field in schema.fields.items():
        for alias in field.aliases or ():
            names.setdefault(_name(alias), set()).add(name)
        for key in field.keys or ():
            keys_of.setdefault(name, {}).setdefault(_name(key), []).append(key)
    data = text.encode("utf-8")
    found: _Found = {}
    tables = [] if document is None else document.of_kind("table")
    if document is not None:
        nested = _nested(document)
        for table in tables:
            _table(document, table, data, names, keys_of, nested, found, schema)
    _lines(data, tables, names, found, schema)

    # Sort by field name, not by schema order: a saved schema is canonical JSON, so its fields
    # load in sorted order, and replay must give the same candidate IDs (#510). The keys of a
    # field are a list, so the key order is the schema order, in all tables.
    # The rank of each key, so the sort costs no scan of the keys for each candidate.
    ranks: dict[str, dict[str, int]] = {}
    for name, field in schema.fields.items():
        for rank, key in enumerate(field.keys or ()):
            ranks.setdefault(name, {}).setdefault(key, rank)

    def place(item: tuple[tuple[str, str | None], list[Json | None]]) -> tuple[str, int]:
        (name, key), _ = item
        return name, -1 if key is None else ranks[name][key]

    ordered = sorted(found.items(), key=place)
    return [m[0] for _, m in ordered if len(m) == 1 and m[0] is not None]
