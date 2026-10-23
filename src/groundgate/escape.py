"""One escape form for each character that is not printable in a CLI message (#448)."""

from __future__ import annotations


def escape(text: str) -> str:
    """``text`` with each character that is not printable as an escape of a fixed length:
    ``\\u`` and 4 hex digits up to U+FFFF, ``\\U`` and 8 hex digits above it. A reader can
    then tell where each escape ends."""
    return "".join(c if c.isprintable() else _one(ord(c)) for c in text)


def _one(o: int) -> str:
    return f"\\u{o:04x}" if o <= 0xFFFF else f"\\U{o:08x}"
