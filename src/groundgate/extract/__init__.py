"""Turn a source file into the NFC text groundgate admits against, plus page geometry for PDFs.

>>> doc = extract("label.pdf")          # doctest: +SKIP
>>> doc.text                            # what the extractor and groundgate both read
>>> doc.layout.locate(start, end)       # page boxes for a decision's evidence span

Supported: PDF with a text layer (``groundgate[pdf]``), HTML, XML (including DailyMed SPL),
and plain text. Scanned PDFs need OCR first.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..canonical import digest, is_nfc
from .layout import Box, Layout, Page, Word
from .markup import html_text, xml_text

__all__ = ["Box", "ExtractError", "Extracted", "Layout", "Page", "Word", "extract"]

TEXT_SUFFIXES = {".txt", ".text", ".md", ".markdown"}
HTML_SUFFIXES = {".html", ".htm", ".xhtml"}


class ExtractError(ValueError):
    """The file cannot be turned into text."""


@dataclass(frozen=True)
class Extracted:
    text: str
    layout: Layout | None = None  # PDFs only
    warnings: tuple[str, ...] = ()


def _decode(data: bytes, path: Path) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ExtractError(f"{path} is not UTF-8") from e
    return text.replace("\r\n", "\n").replace("\r", "\n")


def extract(path: str | Path, pages: Iterable[int] | None = None) -> Extracted:
    """Extract ``path``. ``pages`` (1-based) selects PDF pages; other formats ignore it."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from .pdf import extract_pdf

        text, page_list, words, warnings = extract_pdf(path, pages)
        if not is_nfc(text):  # pragma: no cover - words are normalised one by one
            raise ExtractError(f"{path}: extracted text is not NFC")
        layout = Layout(digest("document", {"text": text}), tuple(page_list), tuple(words))
        return Extracted(text, layout, tuple(warnings))
    data = path.read_bytes()
    if suffix == ".xml":
        import xml.etree.ElementTree as ET

        try:
            text = xml_text(data)
        except ET.ParseError as e:
            raise ExtractError(f"{path}: not well-formed XML ({e})") from e
    elif suffix in HTML_SUFFIXES:
        text = html_text(_decode(data, path))
    elif suffix in TEXT_SUFFIXES:
        text = _decode(data, path)
    else:
        raise ExtractError(f"{path}: unsupported file type {suffix or '(none)'}")
    empty = () if text.strip() else (f"{path.name}: no text was extracted",)
    return Extracted(unicodedata.normalize("NFC", text), warnings=empty)
