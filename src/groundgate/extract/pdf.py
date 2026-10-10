"""PDF text with word boxes, via pdfminer.six (MIT). Needs ``pip install groundgate[pdf]``.

Text a reader cannot see is not evidence. Words drawn entirely outside the page's CropBox (proof
marks, slugs, off-page junk) are dropped, and the count is reported as a warning.

Superscripts and subscripts are marked with ``^`` and ``_`` so they never fuse with the number
before them: a raised 9 after 10 reads ``10^9``, not ``109``.

A table is written one row on each line, with a tab between two cells, as the HTML path writes
table cells (#230). pdfminer gives each column of a table as its own text box, so ``_tables``
rebuilds the rows from the height of the text lines. Prose keeps pdfminer's lines.

The same PDF always gives the same text. pdfminer breaks a tie between two equally distant text
boxes by ``id()``, a memory address, so the reading order could change from run to run (#30).
While groundgate reads a PDF, pdfminer's layout code gets a stable ``id()`` instead.
"""

from __future__ import annotations

import contextlib
import itertools
import threading
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, BinaryIO

from .layout import Box, Page, Word, _same_line

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

CELL_GAP = 0.65  # a gap between two words this many times the word's height starts a new cell
HEADING_WORDS = 4  # a row with no number joins a table when each of its parts is this short
DASHES = frozenset("-\u2013\u2014\u2212")  # hyphen, en dash, em dash, minus
NUMBER_CHARS = frozenset("0123456789,.$€£¥%()") | DASHES


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


def extract_pdf(path: str | Path, pages: Iterable[int] | None = None) -> Result:
    """Text, pages, words and warnings for a PDF. ``pages`` are 1-based page numbers."""
    try:
        from pdfminer.pdftypes import PDFException
        from pdfminer.psexceptions import PSException
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise ImportError("PDF support needs pdfminer.six: pip install 'groundgate[pdf]'") from e
    from . import ExtractError

    wanted = None
    if pages is not None:
        wanted = sorted(set(pages))
        if not wanted or wanted[0] < 1:
            raise ExtractError("pages must be 1-based page numbers")
    try:
        with open(path, "rb") as fp:
            return _read(fp, wanted)
    except (PDFException, PSException) as e:
        raise ExtractError(f"{path}: not a readable PDF ({type(e).__name__}: {e})") from e


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


def _read(fp: BinaryIO, wanted: list[int] | None) -> Result:
    with _stable_ids():
        return _read_pages(fp, wanted)


def _read_pages(fp: BinaryIO, wanted: list[int] | None) -> Result:
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
        for bi, rows in enumerate(_tables(blocks)):
            if bi:
                out.add(BLOCK_BREAK)
            for ri, cells in enumerate(rows):
                if ri:
                    out.add(LINE_BREAK)
                for ci, cell in enumerate(cells):
                    if ci:
                        out.add(CELL_BREAK)
                    for wi, (t, box) in enumerate(cell):
                        if wi:
                            out.add(" ")
                        ws, we = out.add(t)
                        words.append(Word(ws, we, box))
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
    return chars <= NUMBER_CHARS and (any(c.isdigit() for c in chars) or chars <= DASHES)


def _tables(blocks: list[list[Line]]) -> list[list[Row]]:
    """The page's output blocks. pdfminer gives a table as one text box for each column, so its
    rows are rebuilt here: the text lines at the same height become one row, with a tab between
    two cells. Other text keeps pdfminer's boxes and lines.

    A **table row** has two or more text lines side by side, with no overlap, and one of them is
    a number cell. In a table row, a gap between two words of CELL_GAP times their height or more
    also starts a cell. Two table rows are in one table when each row between them is a table
    row, a heading row (lines side by side, each of HEADING_WORDS words or fewer), only number
    cells, or ends before the first number cell of both, as a heading in the label column does.
    A line of prose across the number columns ends the table. A table has two or more table
    rows: one number beside text, such as a page number beside a running head or a number in one
    of two columns of prose, is no table. A table also takes the rows of two or more lines side
    by side above it, up to a line across the edge of its first number cell, and those just below
    it, such as its column headings. A heading in the label column above the first table row
    joins only when such a row is above it. The table is written where pdfminer gives the first of
    its lines, one row on each line.
    """
    Key = tuple[int, int]  # block, line
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
        return len(row) > 1 and all(
            span[a].x1 <= span[b].x0 + 0.5 for a, b in itertools.pairwise(row)
        )

    def table_row(row: list[Key]) -> bool:
        return side_by_side(row) and any(map(number, row))

    def heading(row: list[Key]) -> bool:
        return side_by_side(row) and all(len(blocks[bi][li]) <= HEADING_WORDS for bi, li in row)

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
    region: dict[Key, int] = {}
    tables: list[list[Row]] = []
    for n, group in enumerate(groups):
        first, last = group[0], group[-1]
        edge = first_number(rows[first]) + 0.5
        above = first - 1
        while above >= 0 and rows[above][0] not in region:
            if side_by_side(rows[above]):
                first = above
            elif span[rows[above][0]].x0 < edge < span[rows[above][0]].x1:
                break
            above -= 1
        while last + 1 < len(rows) and side_by_side(rows[last + 1]):
            last += 1
        tables.append([])
        for row in rows[first : last + 1]:
            lines = [blocks[bi][li] for bi, li in row]
            if table_row(row):
                lines = [cell for line in lines for cell in _cells(line)]
            tables[n].append(lines)
            region.update((key, n) for key in row)
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
        if prose:
            out.append(prose)
    return out
