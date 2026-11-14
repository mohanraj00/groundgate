"""Passages: a citable section of a document (SPEC §4.17, #638).

A reader gives the outline: the headings of the document, each with a level. A passage is the
section of one heading. The gate admits a passage only when the cited span is exactly that
section and the heading has the label that the candidate gives.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence

from .canonical import Offsets
from .fold import fold_text
from .model import PacketError

MAX_OUTLINE = 1_000_000  # the entries of one outline
MAX_LEVEL = 6


def check_outline(raw: object, offsets: Offsets) -> list[dict[str, int]]:
    """The outline of the packet (SPEC §4.17), or ``PacketError``."""
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise PacketError("outline must be a list")
    if len(raw) > MAX_OUTLINE:
        raise PacketError(f"outline has more than {MAX_OUTLINE} entries")
    size = offsets.byte_length
    out: list[dict[str, int]] = []
    last = 0
    for n, entry in enumerate(raw):
        where = f"outline {n}"
        if not isinstance(entry, Mapping) or set(entry) != {"start", "end", "level"}:
            raise PacketError(f"{where} must be an object with start, end and level")
        start, end, level = entry["start"], entry["end"], entry["level"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= size:
            raise PacketError(f"{where} must be a valid span of the document")
        if offsets.to_char(start) is None or offsets.to_char(end) is None:
            raise PacketError(f"{where} must be a valid span of the document")
        if start < last:
            raise PacketError(f"{where} must start at or after the end of the entry before it")
        last = end
        if type(level) is not int or not 1 <= level <= MAX_LEVEL:
            raise PacketError(f"{where} must have a level from 1 to {MAX_LEVEL}")
        out.append({"start": start, "end": end, "level": level})
    return out


def document_outline(document: object) -> list[dict[str, int]]:
    """The outline of a ``document@1`` model of ``read_document``: its heading nodes."""
    headings = document.of_kind("heading")  # type: ignore[attr-defined]
    return [{"start": n.start, "end": n.end, "level": n.level} for n in headings]


def label_words(text: str) -> list[str]:
    """The words of a heading or of a label (SPEC §4.17): split at whitespace, without the
    marks at the start and at the end of a word, each letter folded."""
    words = (w.lstrip("§(").rstrip(".:)") for w in text.split())
    return [fold_text(w) for w in words if w]


def has_label(heading: str, label: str) -> bool:
    """True when the heading has the label: the words of the label are the words of the
    heading that start at its first word or at its second word."""
    want, have = label_words(label), label_words(heading)
    return bool(want) and any(have[i : i + len(want)] == want for i in (0, 1))


class Outline:
    """The headings of a document, for the passage checks. Offsets are UTF-8 bytes."""

    def __init__(self, text: str, offsets: Offsets, entries: Sequence[Mapping[str, int]]) -> None:
        self._text = text
        self._offsets = offsets
        self._entries = list(entries)
        self._starts = [e["start"] for e in self._entries]
        # the limit of each section: the start of the next entry that is not below it
        self._limits = [offsets.byte_length] * len(self._entries)
        open_: list[int] = []
        for i, e in enumerate(self._entries):
            while open_ and self._entries[open_[-1]]["level"] >= e["level"]:
                self._limits[open_.pop()] = e["start"]
            open_.append(i)

    def heading(self, start: int) -> int | None:
        """The index of the entry that starts at ``start``, or None."""
        i = bisect.bisect_left(self._starts, start)
        return i if i < len(self._starts) and self._starts[i] == start else None

    def text(self, index: int) -> str:
        e = self._entries[index]
        a, b = self._offsets.to_char(e["start"]), self._offsets.to_char(e["end"])
        assert a is not None and b is not None  # check_outline made each span valid
        return self._text[a:b]

    def section_end(self, index: int) -> int:
        """The end of the section of entry ``index``: after the last character that is not
        whitespace before its limit."""
        end = self._offsets.to_char(self._limits[index])
        assert end is not None  # a limit is the start of an entry or the end of the text
        while end and self._text[end - 1].isspace():
            end -= 1
        return self._offsets.to_bytes(end)
