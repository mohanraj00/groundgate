"""Page geometry for extracted text: which page and box each word came from.

Offsets are UTF-8 byte offsets into the extracted text, the same unit as SPEC §2.2 spans, so a
decision's evidence span maps straight to boxes on the page. Coordinates are PDF points with the
origin at the top-left of the page.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..model import PacketError

LAYOUT_VERSION = "0.1"


@dataclass(frozen=True)
class Box:
    page: int  # 1-based page number in the source file
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True)
class Word:
    start: int  # UTF-8 byte offsets into the text
    end: int
    box: Box


@dataclass(frozen=True)
class Page:
    number: int
    width: float
    height: float
    start: int  # byte range of this page's text
    end: int


@dataclass(frozen=True)
class Layout:
    document_sha256: str
    pages: tuple[Page, ...]
    words: tuple[Word, ...]

    def page_at(self, offset: int) -> int | None:
        """The page whose text contains byte ``offset``."""
        for p in self.pages:
            if p.start <= offset < p.end:
                return p.number
        return None

    def locate(self, start: int, end: int) -> list[Box]:
        """Boxes covering the words that overlap bytes [start, end), one box per line."""
        boxes: list[Box] = []
        for w in self.words:
            if w.end <= start or w.start >= end:
                continue
            b = w.box
            last = boxes[-1] if boxes else None
            if last and last.page == b.page and _same_line(last, b):
                boxes[-1] = Box(
                    b.page,
                    min(last.x0, b.x0),
                    min(last.top, b.top),
                    max(last.x1, b.x1),
                    max(last.bottom, b.bottom),
                )
            else:
                boxes.append(b)
        return boxes

    def to_dict(self) -> dict[str, Any]:
        return {
            "groundgate_layout": LAYOUT_VERSION,
            "document_sha256": self.document_sha256,
            "pages": [
                {
                    "page": p.number,
                    "width": p.width,
                    "height": p.height,
                    "start": p.start,
                    "end": p.end,
                }
                for p in self.pages
            ],
            "words": [
                [w.start, w.end, w.box.page, w.box.x0, w.box.top, w.box.x1, w.box.bottom]
                for w in self.words
            ],
        }

    @classmethod
    def from_dict(cls, d: object) -> Layout:
        if not isinstance(d, Mapping) or d.get("groundgate_layout") != LAYOUT_VERSION:
            raise PacketError(f"not a groundgate layout v{LAYOUT_VERSION} object")
        try:
            pages = tuple(
                Page(int(p["page"]), float(p["width"]), float(p["height"]), int(p["start"]),
                     int(p["end"]))
                for p in d["pages"]
            )  # fmt: skip
            words = tuple(
                Word(int(s), int(e), Box(int(pg), float(x0), float(t), float(x1), float(b)))
                for s, e, pg, x0, t, x1, b in d["words"]
            )
        except (KeyError, TypeError, ValueError) as e:
            raise PacketError(f"malformed layout: {e}") from e
        end = 0
        for p in pages:
            if not end <= p.start <= p.end:
                raise PacketError("malformed layout: pages must be in text order")
            end = p.end
        prev = 0
        for w in words:
            if not prev <= w.start < w.end <= end:
                raise PacketError("malformed layout: words must be in text order, within the pages")
            prev = w.end
        return cls(str(d["document_sha256"]), pages, words)


def _same_line(a: Box, b: Box) -> bool:
    overlap = min(a.bottom, b.bottom) - max(a.top, b.top)
    return overlap > 0.5 * min(a.bottom - a.top, b.bottom - b.top)
