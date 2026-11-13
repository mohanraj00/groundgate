"""Places: the page and the box of each word of a document (SPEC §4.15, #614).

A reader gives the places of a PDF. With them, the receipt gives a locator for each decision
whose value span is in the document: the page and the box of the cited words. The places change
no outcome and no code.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from typing import Any

from .canonical import Offsets
from .model import PacketError

MAX_PLACES = 2_000_000  # the entries of one places list
MAX_PAGE = 1_000_000
MAX_COORDINATE = 2**31 - 1  # hundredths of a PDF point
SCALE = 100  # one PDF point is this many units

Locator = tuple[int, tuple[int, int, int, int]]  # the page, and x0, y0, x1, y1


def _int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def check_places(raw: object, offsets: Offsets) -> list[list[int]]:
    """The places list of the packet (SPEC §4.15), or ``PacketError``. Each entry is
    ``[start, end, page, x0, y0, x1, y1]`` with integers only."""
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise PacketError("places must be a list")
    if len(raw) > MAX_PLACES:
        raise PacketError(f"places has more than {MAX_PLACES} entries")
    size = offsets.byte_length
    out: list[list[int]] = []
    last = 0
    for n, entry in enumerate(raw):
        where = f"places {n}"
        if isinstance(entry, (str, bytes)) or not isinstance(entry, Sequence) or len(entry) != 7:
            raise PacketError(f"{where} must be a list of 7 integers")
        start, end, page, x0, y0, x1, y1 = entry
        if not (_int(start, 0, size) and _int(end, 0, size) and start < end):
            raise PacketError(f"{where} must be a valid span of the document")
        if offsets.to_char(start) is None or offsets.to_char(end) is None:
            raise PacketError(f"{where} must be a valid span of the document")
        if start < last:
            raise PacketError(f"{where} must start at or after the end of the entry before it")
        last = end
        if not _int(page, 1, MAX_PAGE):
            raise PacketError(f"{where} must have a page number from 1 to {MAX_PAGE}")
        if not all(_int(v, 0, MAX_COORDINATE) for v in (x0, y0, x1, y1)) or x0 > x1 or y0 > y1:
            raise PacketError(
                f"{where} must have a box of integers with x0 <= x1 and y0 <= y1, in hundredths "
                "of a point"
            )
        out.append([start, end, page, x0, y0, x1, y1])
    return out


class Places:
    """The checked places of a document, for ``locate``."""

    def __init__(self, places: list[list[int]]) -> None:
        self.places = places
        self._ends = [p[1] for p in places]  # in order, because no two entries overlap

    def locate(self, start: int, end: int) -> Locator | None:
        """The locator of the byte span [start, end): the page of its first word, and the box
        that covers each word of the span on that page. None when no word overlaps the span."""
        i = bisect.bisect_right(self._ends, start)  # the first entry that ends after start
        page: int | None = None
        box: list[int] = []
        while i < len(self.places) and self.places[i][0] < end:
            _, _, p, x0, y0, x1, y1 = self.places[i]
            if page is None:
                page, box = p, [x0, y0, x1, y1]
            elif p == page:
                box = [min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1)]
            i += 1
        return None if page is None else (page, (box[0], box[1], box[2], box[3]))


def layout_places(layout: Any) -> list[list[int]]:
    """The places of a ``groundgate.read`` layout: each word with its box in hundredths of a
    point, rounded half to even. A word that starts before the end of the word before it is
    left out, so the list has no overlap."""
    out: list[list[int]] = []
    last = 0
    for w in layout.words:
        if w.start < last or w.start >= w.end:
            continue
        b = w.box
        x0, y0, x1, y1 = (round(v * SCALE) for v in (b.x0, b.top, b.x1, b.bottom))
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        if min(x0, y0) < 0 or max(x1, y1) > MAX_COORDINATE or not 1 <= b.page <= MAX_PAGE:
            continue  # a word outside the page area has no place
        out.append([w.start, w.end, b.page, x0, y0, x1, y1])
        last = w.end
    return out
