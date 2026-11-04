"""The OCR crop of the review page (docs/design/review.md §7, §9 rule 9). Needs ``groundgate[ocr]``.

``crop`` renders a box of a PDF page with ``MARGIN`` (24) points of the page on each side, cut at
the page edge. pypdfium2 renders it in gray at 300 dpi. A box of more than ``MAX_PIXELS`` (2^22)
pixels renders at a lower dpi. The PNG writer uses ``zlib`` of the standard library.

The PDF is untrusted, and a thread cannot stop pdfium. So the review server calls ``run``, which
renders the crop in a child process (``python -I -m groundgate.read.crop``) with a time limit of
``TIMEOUT`` (10) seconds and a response of at most ``MAX_BYTES`` (4 MiB). The child reads one JSON
line and the PDF bytes on stdin, and writes the PNG on stdout. The core never imports this module.
"""

from __future__ import annotations

import importlib
import json
import struct
import subprocess
import sys
import zlib
from collections.abc import Sequence
from typing import Any

DPI = 300
MARGIN = 24.0  # points of the page on each side of the box
MAX_PIXELS = 2**22
MAX_BYTES = 4 * 2**20
TIMEOUT = 10.0  # seconds for one crop
MAX_ERROR = 2**12  # bytes of stderr that the error message keeps


class CropError(Exception):
    """The crop cannot be made. The page then shows the text only."""


def _scale(width: float, height: float, max_pixels: int) -> float:
    """The pixels for each point: 300 dpi, or less, so that ``ceil(width * s) * ceil(height * s)``
    is at most ``max_pixels``. The bound adds one pixel on each axis for the rounding."""
    scale = DPI / 72
    if (width * scale + 1) * (height * scale + 1) <= max_pixels:
        return scale
    a, b, c = width * height, width + height, 1 - max_pixels
    return float((-b + (b * b - 4 * a * c) ** 0.5) / (2 * a))


def png(width: int, height: int, rows: bytes) -> bytes:
    """A PNG image of 8-bit gray pixels. ``rows`` holds ``height`` rows of ``width`` bytes."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    raw = b"".join(b"\0" + rows[y * width : (y + 1) * width] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def crop(source: bytes, page: int, box: Sequence[float], max_pixels: int = MAX_PIXELS) -> bytes:
    """The PNG crop of ``box`` (x0, top, x1, bottom in points from the top-left of the visible
    page) on page ``page`` (1-based) of the PDF ``source``. Raise ``CropError`` when the PDF,
    the page or the box is not valid, and ``ImportError`` without pypdfium2."""
    pdfium: Any = importlib.import_module("pypdfium2")
    x0, top, x1, bottom = (float(v) for v in box)
    try:
        pdf = pdfium.PdfDocument(source)
    except pdfium.PdfiumError as e:
        raise CropError(f"pypdfium2 cannot open the PDF ({e})") from e
    try:
        if not 1 <= page <= len(pdf):
            raise CropError(f"the PDF has no page {page}")
        pg = pdf[page - 1]
        try:
            width, height = pg.get_size()
            left, up = max(0.0, x0 - MARGIN), max(0.0, top - MARGIN)
            right, down = min(width, x1 + MARGIN), min(height, bottom + MARGIN)
            if not (right > left and down > up):
                raise CropError("the box is not on the page")
            scale = _scale(right - left, down - up, max_pixels)
            bitmap = pg.render(scale=scale, crop=(left, height - down, width - right, up),
                               grayscale=True, may_draw_forms=False)  # fmt: skip
            try:
                w, h, stride = bitmap.width, bitmap.height, bitmap.stride
                gray = bitmap.n_channels == 1 and min(w, h) >= 1
                buf = bytes(bitmap.buffer) if gray else b""
            finally:
                bitmap.close()
        finally:
            pg.close()
    except (pdfium.PdfiumError, ValueError) as e:
        raise CropError(f"pypdfium2 cannot render page {page} ({e})") from e
    finally:
        pdf.close()
    if not gray:  # pragma: no cover - pdfium gives gray when asked
        raise CropError("pypdfium2 gave no gray image")
    if w * h > max_pixels:  # pragma: no cover - the scale keeps the crop below the limit
        raise CropError(f"the crop has more than {max_pixels} pixels")
    return png(w, h, b"".join(buf[y * stride : y * stride + w] for y in range(h)))


def _argv() -> list[str]:
    return [sys.executable, "-I", "-m", __name__]


def run(source: bytes, page: int, box: Sequence[float]) -> bytes:
    """The PNG crop of ``crop``, made in a child process with the limits of review.md §9 rule 9.
    Raise ``CropError`` on a time-out, an error of the child or a response that is too big."""
    request = json.dumps({"page": page, "box": [float(v) for v in box],
                          "max_pixels": MAX_PIXELS}).encode() + b"\n"  # fmt: skip
    try:
        proc = subprocess.Popen(_argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)  # fmt: skip
    except OSError as e:
        raise CropError(f"the crop process did not start ({e})") from e
    try:
        out, err = proc.communicate(request + source, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as e:
        proc.kill()
        proc.communicate()
        raise CropError(f"the crop took more than {TIMEOUT:g} seconds") from e
    if proc.returncode != 0:
        message = err[-MAX_ERROR:].decode("utf-8", "replace").strip().splitlines()[-1:]
        raise CropError(f"the crop failed ({(message or ['no error'])[0][:200]})")
    if len(out) > MAX_BYTES:
        raise CropError(f"the crop is more than {MAX_BYTES} bytes")
    if not out.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CropError("the crop process gave no PNG")
    return out


def _main() -> int:
    data = sys.stdin.buffer.read()
    line, _, source = data.partition(b"\n")
    try:
        request = json.loads(line)
        page, box, most = request["page"], request["box"], request["max_pixels"]
        if type(page) is not int or type(most) is not int or len(box) != 4:
            raise ValueError("the request is not valid")
        image = crop(source, page, box, most)
    except (CropError, ImportError, KeyError, TypeError, ValueError) as e:
        sys.stderr.write(f"{e}\n")
        return 1
    if len(image) > MAX_BYTES:
        sys.stderr.write(f"the crop is more than {MAX_BYTES} bytes\n")
        return 1
    sys.stdout.buffer.write(image)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
