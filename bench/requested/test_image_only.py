from __future__ import annotations

import re
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from requested.image_only import page_sizes, read_png, write_pdf


def _png(width: int, height: int, color: int = 2, depth: int = 8, interlace: int = 0) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + body))
        return struct.pack(">I", len(body)) + kind + body + crc

    pixel = b"\x80\x40\x20" if color == 2 else b"\x80"
    rows = b"".join(b"\x00" + pixel * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_read_png_returns_the_header_and_the_zlib_data() -> None:
    width, height, space, components, data = read_png(_png(3, 2))
    assert (width, height, space, components) == (3, 2, "DeviceRGB", 3)
    assert zlib.decompress(data) == (b"\x00" + b"\x80\x40\x20" * 3) * 2
    assert read_png(_png(1, 1, color=0))[2:4] == ("DeviceGray", 1)


@pytest.mark.parametrize(("color", "depth", "interlace"), [(6, 8, 0), (2, 16, 0), (2, 8, 1)])
def test_read_png_refuses_an_unsupported_png(color: int, depth: int, interlace: int) -> None:
    with pytest.raises(ValueError, match="unsupported PNG"):
        read_png(_png(1, 1, color=color, depth=depth, interlace=interlace))


def test_read_png_refuses_another_file() -> None:
    with pytest.raises(ValueError, match="not a PNG"):
        read_png(b"%PDF-1.5")


def test_write_pdf_has_one_image_per_page_and_a_valid_xref() -> None:
    raw = write_pdf([(576.0, 436.0, _png(4, 3)), (537.0, 431.0, _png(2, 2, color=0))])
    assert b"/Count 2" in raw
    assert b"/MediaBox [0 0 576.0000 436.0000]" in raw
    assert raw.count(b"/Subtype /Image") == 2
    assert b"/Font" not in raw and b"BT" not in raw  # no text layer
    xref = int(re.search(rb"startxref\n(\d+)", raw).group(1))  # type: ignore[union-attr]
    assert raw[xref:].startswith(b"xref\n0 9\n")
    offsets = [int(o) for o in re.findall(rb"(\d{10}) 00000 n", raw[xref:])]
    for number, offset in enumerate(offsets, start=1):
        assert raw[offset:].startswith(b"%d 0 obj\n" % number)


def test_page_sizes_swaps_a_turned_page() -> None:
    info = (
        "Page    1 size: 576 x 436 pts\nPage    1 rot:  0\n"
        "Page    2 size: 612 x 792 pts\nPage    2 rot:  90\n"
    )
    assert page_sizes(info) == [(576.0, 436.0), (792.0, 612.0)]
