"""PDF text with word boxes, via pdfminer.six (MIT). Needs ``pip install groundgate[pdf]``.

Text a reader cannot see is not evidence. Words drawn entirely outside the page's CropBox (proof
marks, slugs, off-page junk) are dropped, and the count is reported as a warning.

Superscripts and subscripts are marked with ``^`` and ``_`` so they never fuse with the number
before them: a raised 9 after 10 reads ``10^9``, not ``109``.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, BinaryIO

from .layout import Box, Page, Word

LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
     "ﬅ": "st", "ﬆ": "st"}
)  # fmt: skip

PAGE_BREAK = "\n\f"
BLOCK_BREAK = "\n\n"
LINE_BREAK = "\n"
SCRIPT_SIZE = 0.85  # a glyph this much smaller than its neighbour, and shifted, is a script
SCRIPT_SHIFT = 0.2  # baseline shift, as a fraction of the neighbour's size

Rect = tuple[float, float, float, float]
Result = tuple[str, list[Page], list[Word], list[str]]


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


def _read(fp: BinaryIO, wanted: list[int] | None) -> Result:
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
        for bi, lines in enumerate(blocks):
            if bi:
                out.add(BLOCK_BREAK)
            for li, line_words in enumerate(lines):
                if li:
                    out.add(LINE_BREAK)
                for wi, (t, box) in enumerate(line_words):
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
