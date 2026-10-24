"""Write tiny text PDFs for tests, so no binary fixtures live in the repo."""

from __future__ import annotations

Line = tuple[float, float, str] | tuple[float, float, str, float]  # x, y, text[, size]


def _string(text: str) -> bytes:
    raw = text.encode("cp1252")  # WinAnsiEncoding, close enough for tests
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def make_pdf(
    pages: list[list[Line]],
    size: float = 12,
    *,
    page_size: tuple[float, float] = (612, 792),
    crop_box: tuple[float, float, float, float] | None = None,
    rotation: int = 0,
    drawings: list[bytes] | None = None,
) -> bytes:
    """Draw in displayed page coordinates, including when the page has a rotation.

    ``drawings`` holds raw content-stream operators for each page, such as rules of a table.
    """
    width, height = page_size
    media = (height, width) if rotation in (90, 270) else (width, height)
    transforms = {
        0: b"",
        90: b"0 1 -1 0 %g 0 cm\n" % height,
        180: b"-1 0 0 -1 %g %g cm\n" % (width, height),
        270: b"0 -1 1 0 0 %g cm\n" % width,
    }
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # pages, filled in below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    kids = []
    for page, lines in enumerate(pages):
        stream = (drawings[page] if drawings else b"") + b"".join(
            b"BT /F1 %g Tf %g %g Td " % (line[3] if len(line) > 3 else size, line[0], line[1])
            + _string(line[2])
            + b" Tj ET\n"
            for line in lines
        )
        stream = transforms[rotation] + stream
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream")
        content = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g] " % media
            + (b"/CropBox [%g %g %g %g] " % crop_box if crop_box else b"")
            + (b"/Rotate %d " % rotation if rotation else b"")
            + b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content
        )
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def make_scan(
    images: list[tuple[int, int, bytes] | None], dpi: float = 300, kids: list[int] | None = None
) -> bytes:
    """A PDF of scanned pages: each page draws one gray image (width, height, 8-bit pixels, one
    byte for each pixel) and has no text layer. ``None`` gives a blank page with no image.
    ``kids`` gives the page tree: the 0-based pages in the ``/Kids`` array, and a page can be
    there two times. The default is each page one time."""
    import zlib

    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    pages = []
    for image in images:
        resources, stream = b"", b""
        if image is not None:
            w, h, pixels = image
            data = zlib.compress(pixels)
            objects.append(
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
                b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n"
                % (w, h, len(data))
                + data
                + b"\nendstream"
            )
            resources = b"/Resources << /XObject << /Im1 %d 0 R >> >> " % len(objects)
            stream = b"q %g 0 0 %g 0 0 cm /Im1 Do Q\n" % (w * 72 / dpi, h * 72 / dpi)
            size = (w * 72 / dpi, h * 72 / dpi)
        else:
            size = (612, 792)
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream")
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g] " % size
            + resources
            + b"/Contents %d 0 R >>" % len(objects)
        )
        pages.append(len(objects))
    tree = [pages[k] for k in kids] if kids is not None else pages
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in tree),
        len(tree),
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)
