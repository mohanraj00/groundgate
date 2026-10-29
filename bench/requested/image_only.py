"""Make an image-only copy of a scanned PDF, with no text layer (#548).

A scan from an archive often has page images and an OCR text layer. ``groundgate read --ocr``
reads OCR only on a page with no text layer, so the archive's layer would hide the OCR path.
This script renders each page with pdftoppm and writes a new PDF that holds only the page
images, as lossless PNG data, on the page sizes of the source:

    PYTHONPATH=bench uv run python -m requested.image_only --dpi 350 SOURCE.pdf OUT.pdf

The OCR layer of a scan is invisible, so the render shows the page as it was scanned. The
script prints one JSON record: ``source_sha256``, ``image_only_sha256``, ``method``
(``image-only-render/1``), ``resolution_dpi``, ``pages`` and ``renderer``. It needs pdfinfo
and pdftoppm (poppler). It makes no model call and reads no label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

METHOD = "image-only-render/1"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_COLOR_TYPES = {0: ("DeviceGray", 1), 2: ("DeviceRGB", 3)}
_PAGE_SIZE = re.compile(r"^Page\s+(\d+) size:\s+([\d.]+) x ([\d.]+) pts", re.M)
_PAGE_ROT = re.compile(r"^Page\s+(\d+) rot:\s+(\d+)", re.M)


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def read_png(raw: bytes) -> tuple[int, int, str, int, bytes]:
    """Return width, height, color space, components and the zlib data of an 8-bit PNG."""
    if not raw.startswith(_PNG_SIGNATURE):
        raise ValueError("not a PNG file")
    pos, header, data = len(_PNG_SIGNATURE), None, bytearray()
    while pos < len(raw):
        (length,) = struct.unpack(">I", raw[pos : pos + 4])
        kind, body = raw[pos + 4 : pos + 8], raw[pos + 8 : pos + 8 + length]
        if len(body) != length:
            raise ValueError("truncated PNG chunk")
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            data += body
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError("PNG has no IHDR chunk")
    width, height, depth, color, _, _, interlace = header
    if depth != 8 or color not in _COLOR_TYPES or interlace != 0:
        raise ValueError(f"unsupported PNG: depth {depth}, color {color}, interlace {interlace}")
    space, components = _COLOR_TYPES[color]
    return width, height, space, components, bytes(data)


def write_pdf(pages: list[tuple[float, float, bytes]]) -> bytes:
    """Write a PDF with one full-page PNG image on each page of the given size in points."""
    objects: list[bytes] = [b"", b""]  # 1 catalog, 2 pages; filled in below
    kids = []
    for width_pt, height_pt, png in pages:
        width, height, space, components, data = read_png(png)
        image = len(objects) + 1
        objects.append(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /%s"
            b" /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15"
            b" /Colors %d /BitsPerComponent 8 /Columns %d >> /Length %d >>\nstream\n"
            % (width, height, space.encode(), components, width, len(data))
            + data
            + b"\nendstream"
        )
        draw = b"q %.4f 0 0 %.4f 0 0 cm /Im0 Do Q" % (width_pt, height_pt)
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(draw), draw))
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.4f %.4f]"
            b" /Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
            % (width_pt, height_pt, image, image + 1)
        )
        kids.append(b"%d 0 R" % (image + 2))
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(kids), len(kids))
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def page_sizes(info: str) -> list[tuple[float, float]]:
    """Read the page sizes of ``pdfinfo -f 1 -l N`` output, swapped for a page turned 90."""
    turned = {int(n) for n, rot in _PAGE_ROT.findall(info) if int(rot) % 180}
    sizes = []
    for number, width, height in _PAGE_SIZE.findall(info):
        w, h = float(width), float(height)
        sizes.append((h, w) if int(number) in turned else (w, h))
    return sizes


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def make_copy(source: Path, out: Path, dpi: int) -> dict[str, object]:
    count = int(re.search(r"^Pages:\s+(\d+)", _run("pdfinfo", str(source)), re.M).group(1))  # type: ignore[union-attr]
    sizes = page_sizes(_run("pdfinfo", "-f", "1", "-l", str(count), str(source)))
    if len(sizes) != count:
        raise ValueError(f"pdfinfo gave {len(sizes)} page sizes for {count} pages")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", str(source), str(Path(tmp) / "p")],
            check=True,
            capture_output=True,
        )
        pngs = sorted(Path(tmp).glob("p-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        if len(pngs) != count:
            raise ValueError(f"pdftoppm wrote {len(pngs)} pages for {count} pages")
        raw = write_pdf([(w, h, png.read_bytes()) for (w, h), png in zip(sizes, pngs, strict=True)])
    out.write_bytes(raw)
    version = subprocess.run(["pdftoppm", "-v"], capture_output=True, text=True).stderr
    return {
        "source_sha256": _digest(source.read_bytes()),
        "image_only_sha256": _digest(raw),
        "method": METHOD,
        "resolution_dpi": dpi,
        "pages": count,
        "renderer": version.splitlines()[0].strip() if version else "pdftoppm",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dpi", type=int, required=True, help="render resolution of the scan")
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"{args.out} exists; this script does not overwrite a file")
    json.dump(make_copy(args.source, args.out, args.dpi), sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
