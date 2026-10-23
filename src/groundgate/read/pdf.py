"""PDF text with word boxes, via pdfminer.six (MIT). Needs ``pip install groundgate[pdf]``.

Text a reader cannot see is not evidence. Words drawn entirely outside the page's CropBox (proof
marks, slugs, off-page junk) are dropped, and the count is reported as a warning.

Superscripts and subscripts are marked with ``^`` and ``_`` so they never fuse with the number
before them: a raised 9 after 10 reads ``10^9``, not ``109``.

A table is written one row on each line, with a tab between two cells, as the HTML path writes
table cells (#230). pdfminer gives each column of a table as its own text box, so ``_tables``
rebuilds the rows from the height of the text lines. A table of text cells, such as questions
beside their answers, has no number to find its rows. When the page draws the rules of such a
table, ``grid`` gives its cells, and each row of cells is one line (#332). Prose keeps
pdfminer's lines.

The same PDF always gives the same text. pdfminer breaks a tie between two equally distant text
boxes by ``id()``, a memory address, so the reading order could change from run to run (#30).
While groundgate reads a PDF, pdfminer's layout code gets a stable ``id()`` instead.
"""

from __future__ import annotations

import contextlib
import itertools
import threading
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any, BinaryIO

from .grid import RULE_WIDTH, Grid, Rule, grids
from .layout import Box, Page, Word, _same_line
from .nodes import PageNodes, Raw

LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
     "ﬅ": "st", "ﬆ": "st"}
)  # fmt: skip

PAGE_BREAK = "\n\f"
BLOCK_BREAK = "\n\n"
LINE_BREAK = "\n"
CELL_BREAK = "\t"
SCRIPT_SIZE = 0.85  # a glyph this much smaller than its neighbour, and shifted, is a script
SCRIPT_SHIFT = 0.2  # baseline shift, as a fraction of the neighbour's size

Rect = tuple[float, float, float, float]
Result = tuple[str, list[Page], list[Word], list[str]]
Line = list[tuple[str, Box]]  # the words of one pdfminer text line
Row = list[Line]  # the cells of one output line, left to right
Key = tuple[int, int]  # a text line: its block and its line in the block

CELL_GAP = 0.65  # a gap between two words this many times the word's height starts a new cell
HEADING_WORDS = 4  # a row with no number joins a table when each of its parts is this short
GRID_ROWS = 200  # more disagreeing rows than this give no grid, so the scan stays bounded
COLUMN_HEADING_WORDS = 8  # a column heading above a table, such as a spanning heading
LISTED_LINES = 3  # two cells side by side with this many lines each, line for line, are lists
SPACE = 0.25  # the width of a space, as a part of the word's height
HEADER_BAND = 36.0  # PDF points from the visible page top, independent of page size (#265)
DASHES = frozenset("-\u2013\u2014\u2212")  # hyphen, en dash, em dash, minus
NUMBER_CHARS = frozenset("0123456789,.$€£¥₹%()") | DASHES  # with the signs of the built-in units


class _Builder:
    """Accumulates text while tracking its UTF-8 byte length."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.size = 0

    def add(self, s: str) -> tuple[int, int]:
        start = self.size
        self.parts.append(s)
        self.size += len(s.encode("utf-8"))
        return start, self.size

    def text(self) -> str:
        return "".join(self.parts)


def _rules(obj: Any) -> Iterator[Rect]:
    """The bbox of each straight line and rectangle that the page draws, also inside a figure.

    A stroked rectangle gives its four sides. A filled rectangle counts only when it is thin, as
    a rule drawn as a rectangle is: a wider fill, such as a shaded cell, is no rule.
    """
    from pdfminer.layout import LTFigure, LTLine, LTRect

    for child in obj:
        if isinstance(child, LTFigure):
            yield from _rules(child)
        elif isinstance(child, LTRect):
            x0, y0, x1, y1 = child.bbox
            if min(x1 - x0, y1 - y0) <= RULE_WIDTH:
                yield x0, y0, x1, y1
            elif child.stroke:
                yield from ((x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1))
        elif isinstance(child, LTLine):
            yield child.bbox


def _text_boxes(obj: Any) -> Iterator[Any]:
    from pdfminer.layout import LTFigure, LTTextBox

    for child in obj:
        if isinstance(child, LTTextBox):
            yield child
        elif isinstance(child, LTFigure):
            yield from _text_boxes(child)  # text drawn inside a form XObject


def _script(ch: Any, base: Any) -> str:
    """'^' or '_' when glyph ``ch`` is a superscript or subscript relative to ``base``."""
    if base is None or ch.size >= SCRIPT_SIZE * base.size:
        return ""
    shift = SCRIPT_SHIFT * base.size
    if ch.y0 > base.y0 + shift:
        return "^"
    if ch.y0 < base.y0 - shift:
        return "_"
    return ""


def _words(line: Any) -> Iterator[tuple[str, Rect]]:
    """(text, bbox) for each run of non-space glyphs in a text line."""
    from pdfminer.layout import LTChar

    text: list[str] = []
    boxes: list[Rect] = []
    base = None  # the last full-size glyph in this word
    in_script = ""
    for obj in line:
        t = obj.get_text()
        if not (isinstance(obj, LTChar) and t.strip()):
            if text:
                yield "".join(text), _union(boxes)
            text, boxes, base, in_script = [], [], None, ""
            continue
        mark = _script(obj, base)
        if mark and mark != in_script:
            text.append(mark)
        elif not mark:
            if in_script and t[0].isdigit():
                text.append(" ")  # "10^9 5" must not read as "10^95"
            base = obj
        in_script = mark
        text.append(t)
        boxes.append(obj.bbox)
    if text:
        yield "".join(text), _union(boxes)


def _union(boxes: list[Rect]) -> Rect:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _visible(page: Any) -> Rect:
    """The page's CropBox, in the coordinates pdfminer gives its layout objects."""
    from pdfminer.utils import apply_matrix_rect

    x0, y0, x1, y1 = page.mediabox
    rotate = page.rotate % 360
    if rotate == 90:
        ctm = (0, -1, 1, 0, -y0, x1)
    elif rotate == 180:
        ctm = (-1, 0, 0, -1, x1, y1)
    elif rotate == 270:
        ctm = (0, 1, -1, 0, y1, -x0)
    else:
        ctm = (1, 0, 0, 1, -x0, -y0)  # the same transform PDFPageInterpreter applies
    cx0, cy0, cx1, cy1 = apply_matrix_rect(ctm, page.cropbox)
    return min(cx0, cx1), min(cy0, cy1), max(cx0, cx1), max(cy0, cy1)


def read_pdf(
    path: str | Path, pages: Iterable[int] | None = None, nodes: list[Raw] | None = None
) -> Result:
    """Text, pages, words and warnings for a PDF. ``pages`` are 1-based page numbers. If
    ``nodes`` is a list, it gets the nodes of the document model, with byte offsets."""
    try:
        from pdfminer.pdftypes import PDFException
        from pdfminer.psexceptions import PSException
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise ImportError("PDF support needs pdfminer.six: pip install 'groundgate[pdf]'") from e
    from . import ReadError

    wanted = None
    if pages is not None:
        wanted = sorted(set(pages))
        if not wanted or wanted[0] < 1:
            raise ReadError("pages must be 1-based page numbers")
    try:
        with open(path, "rb") as fp:
            return _read(fp, wanted, nodes)
    except (PDFException, PSException) as e:
        raise ReadError(f"{path}: not a readable PDF ({type(e).__name__}: {e})") from e


_LAYOUT_LOCK = threading.Lock()


@contextlib.contextmanager
def _stable_ids() -> Iterator[None]:
    """pdfminer.layout's ``id()`` becomes a number given in the order objects are first seen.

    ``group_textboxes`` keeps box pairs in a heap of ``(skip, distance, id(a), id(b), a, b)``, so
    pairs at the same distance were ordered by memory address. The numbers keep every object
    distinct, which is all the heap and its ``done`` set need. One read at a time holds the lock.
    """
    from pdfminer import layout

    seq = itertools.count()

    def stable_id(obj: object) -> int:
        n = getattr(obj, "_groundgate_seq", None)
        if not isinstance(n, int):
            n = next(seq)
            setattr(obj, "_groundgate_seq", n)  # noqa: B010  (LT objects have no such attribute)
        return n

    with _LAYOUT_LOCK:
        setattr(layout, "id", stable_id)  # noqa: B010  (shadows the builtin in that module only)
        try:
            yield
        finally:
            delattr(layout, "id")


def _read(fp: BinaryIO, wanted: list[int] | None, nodes: list[Raw] | None = None) -> Result:
    with _stable_ids():
        return _read_pages(fp, wanted, nodes)


def _read_pages(fp: BinaryIO, wanted: list[int] | None, nodes: list[Raw] | None = None) -> Result:
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage

    manager = PDFResourceManager(caching=True)
    device = PDFPageAggregator(manager, laparams=LAParams(all_texts=True))
    interpreter = PDFPageInterpreter(manager, device)
    index = None if wanted is None else [p - 1 for p in wanted]
    out = _Builder()
    page_list: list[Page] = []
    words: list[Word] = []
    warnings: list[str] = []
    marks = None if nodes is None else PageNodes(nodes)
    for i, pdf_page in enumerate(PDFPage.get_pages(fp, index)):
        number = wanted[i] if wanted is not None else i + 1  # get_pages keeps document order
        interpreter.process_page(pdf_page)
        vx0, vy0, vx1, vy1 = _visible(pdf_page)
        if page_list:
            out.add(PAGE_BREAK)
        start = out.size
        hidden = 0
        blocks = []
        for text_box in _text_boxes(device.get_result()):
            lines = []
            for line in text_box:
                line_words = []
                for t, (x0, y0, x1, y1) in _words(line):
                    if x1 <= vx0 or x0 >= vx1 or y1 <= vy0 or y0 >= vy1:
                        hidden += 1
                        continue
                    box = Box(number, round(x0 - vx0, 2), round(vy1 - y1, 2),
                              round(x1 - vx0, 2), round(vy1 - y0, 2))  # fmt: skip
                    line_words.append((unicodedata.normalize("NFC", t.translate(LIGATURES)), box))
                if line_words:
                    lines.append(line_words)
            if lines:
                blocks.append(lines)
        rules: list[Rule] = []
        for x0, y0, x1, y1 in _rules(device.get_result()):
            if not (x1 >= vx0 and x0 <= vx1 and y1 >= vy0 and y0 <= vy1):
                continue  # a rule a reader cannot see (or with no position) draws no cell
            x0, y0, x1, y1 = max(x0, vx0), max(y0, vy0), min(x1, vx1), min(y1, vy1)
            rules.append((x0 - vx0, vy1 - y1, x1 - vx0, vy1 - y0))
        kinds: list[str | None] = []
        for bi, rows in enumerate(_tables(blocks, grids(rules), kinds)):
            if bi:
                out.add(BLOCK_BREAK)
            if marks:
                marks.block(kinds[bi], out.size)
            for ri, cells in enumerate(rows):
                if ri:
                    out.add(LINE_BREAK)
                if marks:
                    marks.start_row(out.size)
                for ci, cell in enumerate(cells):
                    if ci:
                        out.add(CELL_BREAK)
                    if marks:
                        marks.start_cell(out.size)
                    for wi, (t, box) in enumerate(cell):
                        if wi:
                            out.add(" ")
                        ws, we = out.add(t)
                        words.append(Word(ws, we, box))
                    if marks:
                        marks.end_cell(out.size)
                if marks:
                    marks.end_row(out.size)
            if marks:
                marks.end_block(out.size)
        page_list.append(Page(number, round(vx1 - vx0, 2), round(vy1 - vy0, 2), start, out.size))
        if hidden:
            warnings.append(f"page {number}: dropped {hidden} words drawn outside the visible page")
        if out.size == start:
            warnings.append(
                f"page {number} has no text layer; OCR the PDF first (for example with ocrmypdf)"
            )
    if not page_list:
        warnings.append("no pages were extracted")
    elif wanted is not None and len(page_list) < len(wanted):
        warnings.append(f"the PDF has fewer pages than requested ({len(page_list)} extracted)")
    return out.text(), page_list, words, warnings


def _span(line: Line) -> Box:
    boxes = [b for _, b in line]
    return Box(boxes[0].page, min(b.x0 for b in boxes), min(b.top for b in boxes),
               max(b.x1 for b in boxes), max(b.bottom for b in boxes))  # fmt: skip


def _cells(line: Line) -> list[Line]:
    """A text line cut where the gap between two words is CELL_GAP times the height or more."""
    cells = [[line[0]]]
    for (_, a), word in itertools.pairwise(line):
        if word[1].x0 - a.x1 >= CELL_GAP * (a.bottom - a.top):
            cells.append([])
        cells[-1].append(word)
    return cells


def _number_cell(line: Line) -> bool:
    """A text line of only numbers, currency signs, brackets and dashes, such as "$ (1,234)"."""
    chars = set("".join(t for t, _ in line))
    return chars <= NUMBER_CHARS and any(c.isdigit() or c in DASHES for c in chars)


def _tables(
    blocks: list[list[Line]], ruled: Sequence[Grid] = (), kinds: list[str | None] | None = None
) -> list[list[Row]]:
    """The page's output blocks. pdfminer gives a table as one text box for each column, so its
    rows are rebuilt here: the text lines at the same height become one row, with a tab between
    two cells. Other text keeps pdfminer's boxes and lines.

    A **table row** has two or more text lines side by side, with no overlap, and one of them is a
    number cell. In a table row, and in a row of only number cells in a table, a gap between two
    words of CELL_GAP times their height or more also starts a cell. Two table rows are in one table
    when each row between them is a table row, a heading row (lines side by side, each of
    HEADING_WORDS words or fewer), only number cells, or ends before the first number cell of both,
    as a heading in the label column does. A line of prose across the number columns ends the table.
    A table has two or more table rows: one number beside text, such as a page number beside a
    running head or a number in one of two columns of prose, is no table. A table also takes its
    column headings: the rows of two or more lines side by side above it, where each line after the
    first has COLUMN_HEADING_WORDS words or fewer. No row below a table joins it, so a table never
    takes the rows of the next. Above it, the walk goes past lines in the label column, and stops at
    a line across the edge of its first number cell or at a row of lines side by side that is no
    column heading, such as two columns of prose. A row whose top is less than HEADER_BAND points
    from the visible page top is never a table row, and the walk stops at it (#265). The row stays
    in ordinary text, also when it holds a page number or a year. A heading
    in the label column above the first table row joins only when a column heading is above it.
    The table is written where pdfminer gives the first of its lines, one row on each line.

    The number columns of a table come from its widest rows when their spans agree. The widest rows
    with a label set them when the table has any, or a strict majority of those rows that agree (two
    majorities with different columns give none), and a full row of only number cells joins them
    only when it fits. A full row keeps its tabs only when its number cells fit the columns, and the
    text before its first number is one label. A number cell before the first number cell of every
    labeled row, such as a year as a row label, is a label and no column. A text cell after the
    label that overlaps a text cell of another labeled row, such as a column of "n/a", is a column
    cell. The nearest column heading row with more cells than the columns gives the columns when
    each column is under one of its cells, because every row can leave a column blank; the heading
    then starts with an empty label slot. A short row uses these columns: each number cell must
    overlap exactly one column, and each later text cell must be inside exactly one column, in
    increasing order. Skipped columns get empty cells (#266). A row with a label and only text cells
    after it, such as "n/a", is placed the same way. Above the first table row, such a row is placed
    only when it fits, because it can be a column heading. A full row of only number cells, such as
    a row of year headings, starts with an empty label slot, so each cell keeps its column position,
    and it must fit the columns too. A table with no label column gets no label slot in any row. If
    the grid or a cell is ambiguous, the row is written without tabs. An ambiguous row of only
    number cells and currency signs also has two blank lines on either side, a key-scope barrier in
    spec 0.9, so it cannot reuse a prior field label as a column hint (#278).
    """
    rows, span, plan = _plan(blocks)

    def number(key: Key) -> bool:
        return _number_cell(blocks[key[0]][key[1]])

    region: dict[Key, int] = {}
    tables: list[list[Row]] = []
    for n, (first, group) in enumerate(plan):
        grouped = [[cell for bi, li in rows[ri] for cell in _cells(blocks[bi][li])] for ri in group]
        # a number left of the first number cell of every labeled row is a row label, such as a year
        edge = min(
            (
                _span(next(c for c in cells if _number_cell(c))).x0
                for cells in grouped
                if cells and not _number_cell(cells[0]) and any(map(_number_cell, cells))
            ),
            default=None,
        )

        texts = _text_columns(grouped)
        numbered = [
            [
                cell
                for cell in cells[_label_number(cells, edge) :]
                if _number_cell(cell) or id(cell) in texts
            ]
            for cells in grouped
        ]
        widest = max(map(len, numbered), default=0)
        full = [
            (num, cells) for num, cells in zip(numbered, grouped, strict=True) if len(num) == widest
        ]
        # labeled rows set the grid when there are any; a row of only numbers joins it if it fits
        with_label = [
            num
            for num, cells in zip(numbered, grouped, strict=True)
            if num and (not _number_cell(cells[0]) or _label_number(cells, edge))
        ]
        most = max(map(len, with_label), default=0)
        basis = [num for num in with_label if len(num) == most]
        columns = _grid(basis) if basis else _number_columns([num for num, _ in full])
        if basis and columns:
            fits = [
                num
                for num in numbered
                if len(num) == most and len(_fill_empty_cells(num, columns)) > 1
            ]
            columns = _number_columns(fits) or columns
        # a column heading can show a column that every row leaves blank
        right = max((_span(c[0]).x1 for c in grouped if c and not _number_cell(c[0])), default=0)
        heading = -1  # the row of the heading that gives the columns
        for ri in reversed(range(first, group[0])):  # the nearest heading first
            cells = [
                c for bi, li in rows[ri] for c in _cells(blocks[bi][li]) if _span(c).x1 > right
            ]
            if (wide := _heading_columns(cells, columns)) != columns:
                heading, columns = ri, wide
                break
        width = max(widest, len(columns))
        tables.append([])
        for ri in range(first, group[-1] + 1):
            row = rows[ri]
            lines = [blocks[bi][li] for bi, li in row]
            isolated = False
            if (_side_by_side(row, span) and any(map(number, row))) or all(map(number, row)):
                cells = [cell for line in lines for cell in _cells(line)]
                labeled = _label_number(cells, edge)
                numeric_only = not labeled and all(map(_number_cell, cells))
                if labeled:
                    placed = _fill_empty_cells(cells[1:], columns)
                    lines = (
                        [cells[0] + placed[0], *placed[1:]] if len(placed) > 1 else _plain(cells)
                    )
                elif sum(map(_number_cell, cells)) < width:
                    lines = _fill_empty_cells(cells, columns)
                elif numeric_only:
                    placed = _fill_empty_cells(cells, columns)
                    isolated = len(placed) == 1
                    lines = placed if isolated else [[], *cells]
                else:  # a full row with a label keeps its tabs when its numbers fit the columns
                    numbers = [cell for cell in cells if _number_cell(cell)]
                    aligned = len(_fill_empty_cells(numbers, columns)) > 1
                    at = next(i for i, cell in enumerate(cells) if _number_cell(cell))
                    if not aligned or not all(map(_number_cell, cells[at:])):
                        lines = _plain(cells)
                    else:  # the text before the first number is one label
                        lines = [[word for cell in cells[:at] for word in cell], *cells[at:]]
                # a lone currency sign, such as "$", does not make the row a labeled row
                signs = all(set("".join(t for t, _ in cell)) <= NUMBER_CHARS for cell in cells)
                isolated = isolated or (not labeled and signs and len(lines) == 1)
            elif columns and _side_by_side(row, span):
                cells = [cell for line in lines for cell in _cells(line)]
                if ri == heading:  # the heading that gave the columns
                    lines = _fill_empty_cells(cells, columns)
                elif _span(cells[0]).x1 <= columns[0][0]:  # a label, then text cells in the columns
                    placed = _fill_empty_cells(cells, columns)
                    if ri > group[0] or len(placed) > 1:  # a heading that does not fit stays
                        lines = placed
            if not with_label and len(lines) > 1 and not lines[0]:
                lines = lines[1:]  # a table with no label column gets no label slot
            if isolated:
                tables[n].extend([[], [], lines, [], []])
            else:
                tables[n].append(lines)
            region.update((key, n) for key in row)
    found_by_layout = len(tables)
    for grid in ruled:  # a table with numbers keeps its rows (#332)
        found = _ruled_rows(blocks, grid, region.keys())
        if found is not None:
            region.update((key, len(tables)) for key in found[0])
            tables.append(found[1])
    out: list[list[Row]] = []
    done: set[int] = set()
    for bi, block in enumerate(blocks):
        prose: list[Row] = []
        for li, line in enumerate(block):
            table = region.get((bi, li))
            if table is None:
                prose.append([line])
                continue
            if prose:
                out.append(prose)
                prose = []
            if table not in done:
                done.add(table)
                out.append(tables[table])
                if kinds is not None:
                    kinds.extend([None] * (len(out) - 1 - len(kinds)))
                    kinds.append("layout" if table < found_by_layout else "rules")
        if prose:
            out.append(prose)
    if kinds is not None:
        kinds.extend([None] * (len(out) - len(kinds)))
    return out


def _ruled_rows(
    blocks: list[list[Line]], grid: Grid, taken: Iterable[Key]
) -> tuple[list[Key], list[Row]] | None:
    """The text lines in a ruled table and its output rows, or None to write the text as before.

    Each word in the table must be in exactly one cell, and each text line that has a word in the
    table must have all its words in it. The words of one cell are one slot: its lines top to
    bottom, joined with one space. A row is the cells that start at the same rule, left to right,
    with an empty slot for an empty cell. A tall cell is in the row where it starts. In the rows
    below it, its slot is empty, so each cell keeps its column. A row of one cell, such as a
    framed note, keeps its lines and gets no tab. A table needs two or more rows with two or more
    cells that hold words, and no line of a table with numbers. A row of two cells that are lists
    side by side (``_listed``) makes the table ambiguous.
    """
    x0, top, x1, bottom = grid.box
    taken = set(taken)
    keys: list[Key] = []
    words: dict[int, list[tuple[Key, int]]] = {}
    for bi, block in enumerate(blocks):
        for li, line in enumerate(block):
            inside = [
                x0 <= (b.x0 + b.x1) / 2 <= x1 and top <= (b.top + b.bottom) / 2 <= bottom
                for _, b in line
            ]
            if not any(inside):
                continue
            if not all(inside) or (bi, li) in taken:
                return None
            for wi, (_, box) in enumerate(line):
                cell = grid.cell_of(box)
                if cell is None:
                    return None
                words.setdefault(cell, []).append(((bi, li), wi))
            keys.append((bi, li))
    table: list[Row] = []
    full = 0
    for r in range(len(grid.starts)):
        cells = grid.slots(r)
        lines = [
            _cell_lines(blocks, words.get(n, [])) if grid.cells[n].row == r else [] for n in cells
        ]
        if not any(lines):
            continue
        if len(cells) == 1:
            table.extend([line] for line in lines[0])
            continue
        if _listed(lines, [(grid.cells[n].x0, grid.cells[n].x1) for n in cells]):
            return None
        full += sum(map(bool, lines)) >= 2
        table.append([[word for line in cell for word in line] for cell in lines])
    if full < 2:
        return None
    return keys, table


def _listed(cells: list[list[Line]], walls: list[tuple[float, float]]) -> bool:
    """Whether a row holds two cells that are lists side by side: rows that the page draws no
    rule between, such as names beside their counts.

    Both cells have LISTED_LINES or more lines, as many lines as the other, and each line at the
    height of a line of the other. Also, no line of either cell ends where it must: the first word
    of the next line fits on it, inside the cell's walls less the cell's left padding. Text that
    wraps in a cell ends a line only where the next word does not fit.
    """

    def broken(cell: list[Line], x0: float, x1: float) -> bool:
        right = x1 - max(0.0, min(_span(line).x0 for line in cell) - x0)
        for line, after in itertools.pairwise(cell):
            word = after[0][1]
            space = SPACE * (word.bottom - word.top)
            if _span(line).x1 + space + (word.x1 - word.x0) > right:
                return False  # the next word does not fit: the line wraps
        return True

    tall = [
        (cell, x0, x1) for cell, (x0, x1) in zip(cells, walls, strict=True)
        if len(cell) >= LISTED_LINES
    ]  # fmt: skip
    return any(
        len(a) == len(b)
        and all(_same_line(_span(x), _span(y)) for x, y in zip(a, b, strict=True))
        and broken(a, a0, a1)
        and broken(b, b0, b1)
        for (a, a0, a1), (b, b0, b1) in itertools.combinations(tall, 2)
    )


def _cell_lines(blocks: list[list[Line]], at: list[tuple[Key, int]]) -> list[Line]:
    """The words of one cell as its visual lines, top to bottom, each left to right."""
    parts: dict[Key, Line] = {}
    for (bi, li), wi in at:
        parts.setdefault((bi, li), []).append(blocks[bi][li][wi])
    lines: list[Line] = []
    for part in sorted(parts.values(), key=lambda p: (_span(p).top, _span(p).x0)):
        if lines and _same_line(_span(lines[-1]), _span(part)):
            lines[-1] = sorted([*lines[-1], *part], key=lambda w: w[1].x0)
        else:
            lines.append(part)
    return lines


def _label_number(cells: Row, edge: float | None) -> bool:
    """Whether the row starts with a number cell that ends before ``edge``, the first number cell
    of the labeled rows, such as a year as a row label."""
    return (
        edge is not None
        and len(cells) > 1
        and _number_cell(cells[0])
        and _span(cells[0]).x1 <= edge
    )


def _grid(rows: list[Row]) -> list[tuple[float, float]]:
    """The number columns of the labeled rows. If they disagree, the columns of a strict majority
    of rows whose cells each overlap the cells of one of them, so one row off the grid does not
    remove the grid of the others. Two majorities with different columns give no grid, and so do
    more than GRID_ROWS rows, because each row is compared with each other row."""
    columns = _number_columns(rows)
    if columns or not 3 <= len(rows) <= GRID_ROWS:
        return columns
    spans = [[(box.x0, box.x1) for box in map(_span, row)] for row in rows]
    grids = set()
    for one in spans:
        same = [
            row
            for row, other in zip(rows, spans, strict=True)
            if all(a0 < b1 and b0 < a1 for (a0, a1), (b0, b1) in zip(one, other, strict=True))
        ]
        if 2 * len(same) > len(rows) and (columns := _number_columns(same)):
            grids.add(tuple(columns))
    return list(grids.pop()) if len(grids) == 1 else []  # competing majorities give no grid


def _text_columns(rows: list[Row]) -> set[int]:
    """The ids of the text cells, such as "n/a", that form a column of a labeled number row.

    A text cell after the label is in a column when a chain of overlaps joins it to a text cell of
    another such row. A text cell with no partner, such as "Restated", stays with the label.
    """
    cells = sorted(
        ((_span(cell), n, cell) for n, row in enumerate(rows)
         if row and not _number_cell(row[0]) and any(map(_number_cell, row))
         for cell in row[1:] if not _number_cell(cell)),
        key=lambda item: item[0].x0,
    )  # fmt: skip
    groups: list[list[tuple[int, Line]]] = []
    right = 0.0
    for box, n, cell in cells:
        if not groups or box.x0 >= right:
            groups.append([])
            right = box.x1
        groups[-1].append((n, cell))
        right = max(right, box.x1)
    found: set[int] = set()
    for group in groups:
        if len({n for n, _ in group}) > 1:
            found.update(id(cell) for _, cell in group)
    return found


def _heading_columns(cells: Row, columns: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The columns of a heading row with more cells than the columns, when each heading cell
    holds at most one column and every column is under one heading cell. Otherwise the columns."""
    if not columns or len(cells) <= len(columns):
        return columns
    spans = [_span(cell) for cell in cells]
    held = [[c for c in columns if c[0] < box.x1 and box.x0 < c[1]] for box in spans]
    if any(len(h) > 1 for h in held) or sum(map(len, held)) != len(columns):
        return columns
    wide = [
        (min([box.x0, *(c[0] for c in h)]), max([box.x1, *(c[1] for c in h)]))
        for box, h in zip(spans, held, strict=True)
    ]
    return wide if all(a[1] <= b[0] for a, b in itertools.pairwise(wide)) else columns


def _plain(row: Row) -> Row:
    """All the words of a row on one line, with no tabs."""
    return [[word for cell in row for word in cell]]


def _number_columns(rows: list[Row]) -> list[tuple[float, float]]:
    """The union of each widest-row column, only when those rows share a compatible grid.

    Each column must have a common horizontal overlap across its rows, and the resulting
    column bands must not overlap. A page with unrelated grids cannot supply a safe position.
    """
    if not rows:
        return []
    columns = []
    for cells in zip(*rows, strict=True):
        spans = [_span(cell) for cell in cells]
        if max(b.x0 for b in spans) >= min(b.x1 for b in spans):
            return []
        columns.append((min(b.x0 for b in spans), max(b.x1 for b in spans)))
    if any(a[1] > b[0] for a, b in itertools.pairwise(columns)):
        return []
    return columns


def _fill_empty_cells(row: Row, columns: list[tuple[float, float]]) -> Row:
    """Place a short row in an agreed grid, or retain all its words on one line without tabs.

    A text cell before the first column is the label. A later text cell, such as "n/a", takes a
    column only when it is fully inside that column, so a long label that crosses into the number
    columns is ambiguous.
    """
    fallback = _plain(row)
    if not columns:
        return fallback
    labels: Line = []
    placed: dict[int, Line] = {}
    previous = -1
    for cell in row:
        box = _span(cell)
        if not _number_cell(cell):
            if not placed and box.x1 <= columns[0][0]:
                labels.extend(cell)
                continue
            hits = [n for n, (x0, x1) in enumerate(columns) if x0 <= box.x0 and box.x1 <= x1]
        else:
            hits = [n for n, (x0, x1) in enumerate(columns) if box.x0 < x1 and box.x1 > x0]
        if len(hits) != 1 or hits[0] <= previous:
            return fallback
        previous = hits[0]
        placed[previous] = cell
    cells = [placed.get(n, []) for n in range(len(columns))]
    return [labels, *cells]


def _side_by_side(row: list[Key], span: dict[Key, Box]) -> bool:
    return len(row) > 1 and all(span[a].x1 <= span[b].x0 + 0.5 for a, b in itertools.pairwise(row))


def _plan(
    blocks: list[list[Line]],
) -> tuple[list[list[Key]], dict[Key, Box], list[tuple[int, list[int]]]]:
    """The tables of _tables: the page's rows of text lines, left to right, the span of each line,
    and for each table the row where it starts (its first column heading, if any) and its table
    rows."""
    span = {
        (bi, li): _span(line) for bi, block in enumerate(blocks) for li, line in enumerate(block)
    }
    rows: list[list[Key]] = []
    for key in sorted(span, key=lambda k: (span[k].top, span[k].x0)):
        if rows and _same_line(span[rows[-1][0]], span[key]):
            rows[-1].append(key)
        else:
            rows.append([key])
    for row in rows:
        row.sort(key=lambda k: span[k].x0)

    def number(key: Key) -> bool:
        return _number_cell(blocks[key[0]][key[1]])

    def side_by_side(row: list[Key]) -> bool:
        return _side_by_side(row, span)

    def in_band(row: list[Key]) -> bool:
        return min(span[k].top for k in row) < HEADER_BAND

    def table_row(row: list[Key]) -> bool:
        return not in_band(row) and side_by_side(row) and any(map(number, row))

    def heading(row: list[Key]) -> bool:
        return side_by_side(row) and all(len(blocks[bi][li]) <= HEADING_WORDS for bi, li in row)

    def column_heading(row: list[Key]) -> bool:  # the first part may be a long title or label
        return side_by_side(row) and all(
            len(blocks[bi][li]) <= COLUMN_HEADING_WORDS for bi, li in row[1:]
        )

    def first_number(row: list[Key]) -> float:
        return min(span[k].x0 for k in row if number(k))

    groups: list[list[int]] = []
    for i, row in enumerate(rows):
        if not table_row(row):
            continue
        if groups:
            prev = groups[-1][-1]
            edge = min(first_number(rows[prev]), first_number(row)) + 0.5
            if all(
                table_row(rows[r])
                or heading(rows[r])
                or all(number(k) for k in rows[r])
                or all(span[k].x1 <= edge for k in rows[r])
                for r in range(prev + 1, i)
            ):
                groups[-1].append(i)
                continue
        groups.append([i])
    groups = [group for group in groups if len(group) > 1]
    taken: set[int] = set()
    plan: list[tuple[int, list[int]]] = []
    for group in groups:
        first, last = group[0], group[-1]
        edge = first_number(rows[first]) + 0.5
        above = first - 1
        while above >= 0 and above not in taken:
            if in_band(rows[above]):
                break
            if column_heading(rows[above]):
                first = above
            elif (
                side_by_side(rows[above])
                or span[rows[above][0]].x0 < edge < span[rows[above][0]].x1
            ):
                break
            above -= 1
        taken.update(range(first, last + 1))
        plan.append((first, group))
    return rows, span, plan
