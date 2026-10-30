"""Turn a source file into the NFC text groundgate admits against, plus page geometry for PDFs.

>>> doc = read("label.pdf")             # doctest: +SKIP
>>> doc.text                            # what the extractor and groundgate both read
>>> doc.layout.locate(start, end)       # page boxes for a decision's evidence span

Supported: PDF with a text layer (``groundgate[pdf]``), HTML, XML (including DailyMed SPL),
DOCX and XLSX (``read/office.py``, the standard library only), and plain text. With
``ocr=True``, a scanned PDF page gets OCR with the ``tesseract`` program and ``groundgate[ocr]``
(``read/ocr.py``). OCR is off by default: an OCR word can be wrong, and ``admit`` does not read
``doubt``.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..canonical import digest, is_nfc
from .layout import Box, Layout, Page, Word
from .markup import html_text, xml_text

__all__ = ["READER", "Box", "Extracted", "Layout", "Page", "ReadError", "Word", "read", "reader"]

READER = "groundgate.read"

TEXT_SUFFIXES = {".txt", ".text", ".md", ".markdown"}
HTML_SUFFIXES = {".html", ".htm", ".xhtml"}
OFFICE_SUFFIXES = {".docx", ".xlsx"}


class ReadError(ValueError):
    """The file cannot be turned into text."""


@dataclass(frozen=True)
class Extracted:
    text: str
    layout: Layout | None = None  # PDFs only
    warnings: tuple[str, ...] = ()
    ocr: str | None = None  # the tesseract version, when OCR read a page


def reader(ocr: str | None = None) -> dict[str, str]:
    """The reader that a reading records. A read with OCR names the tesseract version too, so
    a new tesseract version gives a new reading key."""
    from .. import __version__

    if ocr is None:
        return {"name": READER, "version": __version__}
    return {"name": f"{READER}+tesseract", "version": f"{__version__}+tesseract.{ocr}"}


def _decode(data: bytes, path: Path) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ReadError(f"{path} is not UTF-8") from e
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read(
    path: str | Path,
    pages: Iterable[int] | None = None,
    *,
    data: bytes | None = None,
    ocr: bool = False,
) -> Extracted:
    """Extract ``path``. ``pages`` (1-based) selects PDF pages; other formats ignore it.

    If ``data`` is given, ``read`` extracts those bytes and does not open ``path``. The suffix
    of ``path`` still selects the format, and errors still name ``path``. If ``ocr`` is True, a
    PDF page with no text layer and an image gets OCR. Other formats ignore it."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from .ocr import Scan
        from .pdf import read_pdf

        scan = Scan()
        text, page_list, words, warnings = read_pdf(path, pages, data=data, scan=scan, ocr=ocr)
        if not is_nfc(text):  # pragma: no cover - words are normalised one by one
            raise ReadError(f"{path}: extracted text is not NFC")
        layout = Layout(digest("document", {"text": text}), tuple(page_list), tuple(words))
        return Extracted(text, layout, tuple(warnings), scan.version)
    if data is None:
        data = path.read_bytes()
    if suffix == ".xml":
        import xml.etree.ElementTree as ET

        try:
            text = xml_text(data)
        except ET.ParseError as e:
            raise ReadError(f"{path}: not well-formed XML ({e})") from e
    elif suffix in HTML_SUFFIXES:
        text = html_text(_decode(data, path))
    elif suffix in OFFICE_SUFFIXES:
        from .office import office_nodes

        text, _ = office_nodes(data, path)
    elif suffix in TEXT_SUFFIXES:
        text = _decode(data, path)
    else:
        raise ReadError(f"{path}: unsupported file type {suffix or '(none)'}")
    empty = () if text.strip() else (f"{path.name}: no text was extracted",)
    return Extracted(unicodedata.normalize("NFC", text), warnings=empty)
