"""OCR of a scanned PDF page with the Tesseract program (#7). Needs ``groundgate[ocr]``.

OCR is opt-in: ``read(path, ocr=True)`` or ``groundgate read --ocr``. An OCR word can be wrong,
and ``admit`` does not read ``doubt``, so OCR is off by default.

A page with no text layer and an image is a scan. pypdfium2 (Apache-2.0 or BSD-3-Clause) renders
the page in gray at 300 dpi, and the ``tesseract`` program reads the image and gives a TSV table
of words with boxes and a confidence. groundgate starts the program with a list of arguments, no
shell and a timeout, and gives the image on its standard input. Threads read stdout and stderr
with a limit while the program runs. pytesseract is not used.

The program is the first executable ``tesseract`` in an absolute PATH entry: the current folder
is never searched. One read sends at most ``MAX_PAGES`` (200) pages to OCR. Before the first
page, the reader compares the page count of pdfminer and of pypdfium2. If they are different,
OCR cannot match a page to its number, and the read stops.

The text of the engine is untrusted input. In each word, the ligatures are written out, a
control, format or space character is removed, and then the word becomes NFC. The parser
refuses a table that it does not know. The same image and the same tesseract version give the
same words: the program runs with one thread (``OMP_THREAD_LIMIT=1``), the language is ``eng``
and the dpi is fixed. The reader then records the tesseract version (``read.reader``), so a new
version is a new reading.

This is the only module of groundgate that starts a process.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import re
import subprocess
import sys
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .layout import Box

DPI = 300
SCALE = DPI / 72  # pixels for each PDF point
MAX_PIXELS = 2**26  # a larger page renders at a lower dpi, so one page cannot fill the memory
MAX_PAGES = 200  # the most pages that one read sends to OCR
LANGUAGE = "eng"
TIMEOUT = 120.0  # seconds for one page
VERSION_TIMEOUT = 10.0
MAX_OUTPUT = 2**24  # bytes of TSV for one page
MAX_ERROR = 2**16  # bytes of stderr for one call
MAX_VERSION = 2**16  # bytes of stdout for ``tesseract --version``
INSTALL = (
    "install the tesseract program (for example `brew install tesseract` or "
    "`apt install tesseract-ocr`), or OCR the PDF first (for example with ocrmypdf)"
)
_COLUMNS = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
)
_VERSION = re.compile(r"tesseract v?([0-9][0-9A-Za-z.+-]{0,63})")

OcrLine = list[tuple[str, Box, float]]  # the words of one engine line, with their confidence


@dataclass
class Scan:
    """What OCR did in one read. ``version`` is the tesseract version, or None when no page had
    OCR. ``pages`` are the page numbers that OCR read. ``doubt`` holds the ``document@1`` doubt
    entries: the UTF-8 byte span of each OCR word, and its confidence from 0 to 1."""

    version: str | None = None
    pages: list[int] = field(default_factory=list)
    doubt: list[dict[str, Any]] = field(default_factory=list)
    _program: str | None = None
    _pdf: Any = None

    def close(self) -> None:
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None


def _env() -> dict[str, str]:
    return {**os.environ, "OMP_THREAD_LIMIT": "1"}


class _Over(Exception):
    """A stream of the program went above its limit."""


def _run(argv: list[str], data: bytes, timeout: float, limit: int) -> tuple[int, bytes, bytes]:
    """Run ``argv`` with ``data`` on stdin, with no shell. Give the exit code, stdout and
    stderr. Threads read stdout (at most ``limit`` bytes) and stderr (at most ``MAX_ERROR``
    bytes) while the program runs. If a stream goes above its limit, the program is killed and
    ``_Over`` is raised. After ``timeout`` seconds, the program is killed and
    ``subprocess.TimeoutExpired`` is raised."""
    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env()
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    streams = {"stdout": (proc.stdout, limit), "stderr": (proc.stderr, MAX_ERROR)}
    got: dict[str, list[bytes]] = {name: [] for name in streams}
    over: list[str] = []

    def drain(name: str) -> None:
        stream, most = streams[name]
        size = 0
        while block := os.read(stream.fileno(), 65536):
            size += len(block)
            if size > most:
                over.append(f"tesseract wrote more than {most} bytes to {name}")
                proc.kill()
                return
            got[name].append(block)

    def feed() -> None:
        assert proc.stdin is not None
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except OSError:  # the program stopped before it read all of the image
            pass

    threads = [threading.Thread(target=drain, args=(name,), daemon=True) for name in streams]
    threads.append(threading.Thread(target=feed, daemon=True))
    for t in threads:
        t.start()
    try:
        code = proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        for t in threads:
            t.join(1.0)  # a child of the program can keep a pipe open: do not wait for it
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            with contextlib.suppress(OSError):
                stream.close()
    if over:
        raise _Over(over[0])
    return code, b"".join(got["stdout"]), b"".join(got["stderr"])


def find_program(name: str) -> str | None:
    """The first executable file ``name`` in the PATH entries, or None. An empty or relative
    entry is skipped, so the current folder is never searched (``shutil.which`` can search it
    first on Windows). On Windows, the names of PATHEXT are tried (default ``.EXE``)."""
    suffixes = [""]
    if sys.platform == "win32":
        suffixes = [s for s in os.environ.get("PATHEXT", ".EXE").split(os.pathsep) if s]
        suffixes = suffixes or [".EXE"]
    for entry in os.environ.get("PATH", os.defpath).split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue
        for suffix in suffixes:
            candidate = os.path.join(entry, name + suffix)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def start(scan: Scan, number: int, data: bytes, pages: int) -> None:
    """Find the program and its version, and open the PDF ``data`` for rendering. ``pages`` is
    the number of pages that pdfminer gives. Raises ``ReadError`` or ``ImportError`` with the
    fix when a part is not installed, and ``ReadError`` when pypdfium2 gives a different number
    of pages, because then OCR cannot match a page to its number."""
    from . import ReadError

    if scan._program is not None:
        return
    program = find_program("tesseract")
    if program is None:
        raise ReadError(f"page {number} has no text layer, and OCR needs tesseract: {INSTALL}")
    try:  # pypdfium2 has no type marker, so mypy does not read it
        pypdfium2: Any = importlib.import_module("pypdfium2")
    except ImportError as e:
        raise ImportError(
            f"page {number} has no text layer, and OCR needs pypdfium2: "
            "pip install 'groundgate[ocr]'"
        ) from e
    try:
        code, stdout, stderr = _run([program, "--version"], b"", VERSION_TIMEOUT, MAX_VERSION)
    except (OSError, _Over, subprocess.TimeoutExpired) as e:
        raise ReadError(f"tesseract --version failed ({e}): {INSTALL}") from e
    # Tesseract 3 wrote the version to stderr, later versions write it to stdout.
    out = (stdout or stderr).decode("utf-8", "replace")
    found = _VERSION.match(out.strip())
    if code != 0 or found is None:
        raise ReadError(f"tesseract --version gave no version: {INSTALL}")
    try:
        scan._pdf = pypdfium2.PdfDocument(data)
    except pypdfium2.PdfiumError as e:
        raise ReadError(f"pypdfium2 cannot open the PDF to render page {number} ({e})") from e
    rendered = len(scan._pdf)
    if rendered != pages:
        scan.close()
        raise ReadError(
            f"the PDF has {pages} pages for pdfminer and {rendered} pages for pypdfium2, "
            "so OCR cannot match the pages"
        )
    scan._program, scan.version = program, found.group(1)


def render(scan: Scan, index: int) -> tuple[bytes, float]:
    """Page ``index`` (0-based) as a binary PGM image in gray, and its pixels for each point.
    pypdfium2 renders the CropBox with the page rotation, as pdfminer gives the page."""
    from . import ReadError

    pdfium: Any = importlib.import_module("pypdfium2")
    try:
        page = scan._pdf[index]
        try:
            width, height = page.get_size()
            scale = SCALE
            if width * height * scale * scale > MAX_PIXELS:
                scale = (MAX_PIXELS / (width * height)) ** 0.5
            bitmap = page.render(scale=scale, grayscale=True, may_draw_forms=False)
            try:
                w, h, stride = bitmap.width, bitmap.height, bitmap.stride
                gray = bitmap.n_channels == 1 and min(w, h) >= 1
                buf = bytes(bitmap.buffer) if gray else b""
            finally:
                bitmap.close()
        finally:
            page.close()
    except (pdfium.PdfiumError, ValueError, IndexError) as e:
        raise ReadError(f"page {index + 1}: pypdfium2 cannot render the page ({e})") from e
    if not gray:  # pragma: no cover - pdfium gives gray when asked
        raise ReadError(f"page {index + 1}: pypdfium2 gave no gray image")
    rows = b"".join(buf[y * stride : y * stride + w] for y in range(h))
    return b"P5\n%d %d\n255\n" % (w, h) + rows, scale


def recognize(scan: Scan, number: int, image: bytes, scale: float) -> list[list[OcrLine]]:
    """The blocks of page ``number``: each engine paragraph, as lines of words."""
    from . import ReadError

    assert scan._program is not None
    argv = [scan._program, "stdin", "stdout", "--dpi", str(round(scale * 72)),
            "-l", LANGUAGE, "--psm", "3", "tsv"]  # fmt: skip
    try:
        code, stdout, stderr = _run(argv, image, TIMEOUT, MAX_OUTPUT)
    except subprocess.TimeoutExpired as e:
        raise ReadError(f"page {number}: tesseract took more than {TIMEOUT:g} seconds") from e
    except _Over as e:
        raise ReadError(f"page {number}: {e}") from e
    except OSError as e:
        raise ReadError(f"page {number}: tesseract did not start ({e}): {INSTALL}") from e
    if code != 0:
        message = stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no error"]
        raise ReadError(f"page {number}: tesseract failed ({message[0][:200]})")
    return parse_tsv(stdout, number, scale)


def _clean(text: str) -> str:
    from .pdf import LIGATURES

    # Remove the characters first, then normalize: a format character between a letter and a
    # combining mark keeps them apart, so NFC before the filter can give a word that is not NFC.
    text = "".join(c for c in text.translate(LIGATURES) if unicodedata.category(c)[0] not in "CZ")
    return unicodedata.normalize("NFC", text)


def parse_tsv(raw: bytes, number: int, scale: float) -> list[list[OcrLine]]:
    """The words of a tesseract TSV table, grouped in paragraphs and lines, in the order of the
    table. A box is in PDF points from the top-left of the visible page. The table is untrusted:
    a row that does not fit the format raises ``ReadError``."""
    from . import ReadError

    try:
        lines = raw.decode("utf-8").split("\n")
    except UnicodeDecodeError as e:
        raise ReadError(f"page {number}: the tesseract output is not UTF-8") from e
    if lines[0].rstrip("\r") != _COLUMNS:
        raise ReadError(f"page {number}: the tesseract output has unknown columns")
    blocks: dict[tuple[int, int], dict[int, OcrLine]] = {}
    for i, row in enumerate(lines[1:], 2):
        row = row.rstrip("\r")
        if not row:
            continue
        cols = row.split("\t", 11)
        try:
            if len(cols) != 12:
                raise ValueError("not 12 columns")
            level, _, block, par, line, _, left, top, width, height = map(int, cols[:10])
            conf = float(cols[10])
        except ValueError as e:
            raise ReadError(f"page {number}: tesseract output line {i} is not valid ({e})") from e
        if level != 5:
            continue
        text = _clean(cols[11])
        if not text:
            continue
        if min(left, top, width, height) < 0 or not 0 <= conf <= 100:
            raise ReadError(f"page {number}: tesseract output line {i} has a bad box or conf")
        box = Box(number, round(left / scale, 2), round(top / scale, 2),
                  round((left + width) / scale, 2), round((top + height) / scale, 2))  # fmt: skip
        words = blocks.setdefault((block, par), {}).setdefault(line, [])
        words.append((text, box, round(conf / 100, 4)))
    return [list(paragraph.values()) for paragraph in blocks.values()]
