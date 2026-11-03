"""The OCR crop of the review page (docs/design/review.md §7, §8, §9 rule 9, #537).

A fake tesseract program (a shell script) reads a small scanned PDF, so the tests need a POSIX
shell, pdfminer and pypdfium2, but not the real program.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

import pytest
from test_review_serve import CLOCK, EVERY, answer, running

from groundgate.read import crop
from groundgate.review import measures, serve
from groundgate.review.serve import NO_OCR, SCAN_GONE, Refused, Review
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore
from groundgate.store.packets import admit_packet, put_reading

pytest.importorskip("pdfminer")
pytest.importorskip("pypdfium2")
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the fake program is a shell script"
)

HERE = Path(__file__).parent
HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
    "\tleft\ttop\twidth\theight\tconf\ttext\n"
)
# 300 dpi pixels: "Rent:" at 72 pt and "$2,450" at 112 pt from the left, 72 pt from the top
TSV = HEADER + "".join(
    f"5\t1\t1\t1\t1\t{n}\t{left}\t300\t150\t50\t95\t{word}\n"
    for n, (left, word) in enumerate([(300, "Rent:"), (466, "$2,450")], 1)
)


def _pdfgen() -> Any:
    spec = importlib.util.spec_from_file_location("pdfgen", HERE.parent / "pdfgen.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scan_pdf() -> bytes:
    """One scanned page of 612 x 792 points: a gray image of 255 x 330 pixels at 30 dpi."""
    pixels = bytes((x * 7 + y * 3) % 256 for y in range(330) for x in range(255))
    return bytes(_pdfgen().make_scan([(255, 330, pixels)], dpi=30))


def fetch(port: int, path: str) -> tuple[int, dict[str, str], bytes]:
    """A GET with the right Host and no token, and the body as bytes."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


def size(image: bytes) -> tuple[int, int]:
    assert image.startswith(b"\x89PNG\r\n\x1a\n") and image[12:16] == b"IHDR"
    width, height, depth, color = struct.unpack(">IIBB", image[16:26])
    assert (depth, color) == (8, 0)  # 8-bit gray
    return width, height


@pytest.fixture
def ocr_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[FolderStore, str, str]:
    """A store with one OCR reading of the scan, a packet for the rent and its task. Give the
    store, the task key and the source key."""
    (tmp_path / "out.tsv").write_text(TSV, encoding="utf-8")
    program = tmp_path / "tesseract"
    program.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then printf "tesseract 5.3.0\\n"; exit 0; fi\n'
        f'cat > /dev/null; cat "{tmp_path / "out.tsv"}"\n',
        encoding="utf-8",
    )
    program.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    path = tmp_path / "lease.pdf"
    path.write_bytes(scan_pdf())
    store = FolderStore(tmp_path / "store")
    reading, doc = put_reading(store, path, ocr=True)
    assert doc.ocr == "5.3.0"
    at = doc.text.encode().index(b"2,450")
    cand = [{"id": "c1", "field": "rent", "value": "2450", "unit": "USD",
             "evidence": {"start": at, "end": at + 5}}]  # fmt: skip
    schema = {"fields": {"rent": {"type": "integer", "unit": "USD"}}}
    k, _ = admit_packet(store, doc.text, schema, cand, None, "lease", reading=reading)
    (tk,) = [t for t, _ in write_tasks(store, k, EVERY).tasks]
    source = json.loads(store.get("reading@2", reading))["source"]
    return store, tk, source


def test_a_crop_is_the_box_with_24_points_on_each_side_cut_at_the_page_edge() -> None:
    pdf = scan_pdf()
    image = crop.crop(pdf, 1, (100, 100, 200, 120))
    assert size(image) == (616, 284)  # 148 x 68 points at 300 dpi, as pdfium rounds them
    # the rows are gray pixels, one filter byte before each row
    rows = zlib.decompress(image[41 : 41 + struct.unpack(">I", image[33:37])[0]])
    assert len(rows) == (616 + 1) * 284
    # a box at the corner gives only the page: 12 + 24 points on each axis
    assert size(crop.crop(pdf, 1, (600, 780, 700, 900))) == (150, 151)
    with pytest.raises(crop.CropError, match="not on the page"):
        crop.crop(pdf, 1, (700, 800, 710, 810))
    with pytest.raises(crop.CropError, match="no page 2"):
        crop.crop(pdf, 2, (100, 100, 200, 120))
    with pytest.raises(crop.CropError, match="cannot open"):
        crop.crop(b"%PDF-1.4 not a pdf", 1, (100, 100, 200, 120))


def test_a_larger_box_renders_at_a_lower_dpi() -> None:
    pdf = scan_pdf()
    # the page at 300 dpi is 2550 x 3300 pixels, more than 2^22
    width, height = size(crop.crop(pdf, 1, (0, 0, 612, 792)))
    assert width * height <= crop.MAX_PIXELS and width * height > 0.99 * crop.MAX_PIXELS
    assert abs(width / height - 612 / 792) < 0.01
    width, height = size(crop.crop(pdf, 1, (0, 0, 612, 792), max_pixels=10_000))
    assert width * height <= 10_000


def test_the_child_process_renders_the_crop() -> None:
    pdf = scan_pdf()
    assert crop.run(pdf, 1, (100, 100, 200, 120)) == crop.crop(pdf, 1, (100, 100, 200, 120))
    with pytest.raises(crop.CropError, match="no page 3"):
        crop.run(pdf, 3, (100, 100, 200, 120))


def test_the_child_process_stops_at_the_time_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crop, "TIMEOUT", 0.5)
    monkeypatch.setattr(crop, "_argv", lambda: [sys.executable, "-I", "-c",
                                                "import time; time.sleep(30)"])  # fmt: skip
    with pytest.raises(crop.CropError, match=r"more than 0\.5 seconds"):
        crop.run(scan_pdf(), 1, (100, 100, 200, 120))


def test_a_response_above_the_byte_limit_gives_no_crop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crop, "MAX_BYTES", 100)
    with pytest.raises(crop.CropError, match="more than 100 bytes"):
        crop.run(scan_pdf(), 1, (100, 100, 200, 120))


def test_the_page_shows_a_crop_of_each_place_with_a_one_time_ticket(
    ocr_store: tuple[FolderStore, str, str],
) -> None:
    store, tk, _ = ocr_store
    with store, running(Review(store, "ana")) as (call, _, port):
        view = json.loads(call("GET", f"/api/task/{tk}")[2])["view"]
        assert view["kind"] == "pdf" and "note" not in view
        (page,) = view["pages"]
        (url,) = page["crops"]
        assert url.startswith("/crop/")
        # an img element cannot send the header, so the crop needs no token
        status, headers, image = fetch(port, url)
        assert status == 200 and size(image) == (349, 251)  # 84 x 60 points at 300 dpi
        assert headers["Content-Type"] == "image/png"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Content-Security-Policy"] == "default-src 'none'"
        # the ticket works one time, and a crop request still needs the right Host
        assert call("GET", url, token=None)[0] == 404
        again = json.loads(call("GET", f"/api/task/{tk}")[2])["view"]["pages"][0]["crops"][0]
        assert call("GET", again, host="evil.example")[0] == 421
        assert call("GET", "/crop/" + "A" * 22, token=None)[0] == 404


def test_the_crop_is_the_png_of_the_place(ocr_store: tuple[FolderStore, str, str]) -> None:
    store, tk, source = ocr_store
    review = Review(store, "ana")
    url = review.view(tk)["view"]["pages"][0]["crops"][0]
    data, page, box = review.crop_source(url.removeprefix("/crop/"))
    assert data == store.get("source@1", source) and page == 1
    assert box == pytest.approx((111.84, 72.0, 147.84, 84.0))  # the word box of the place
    with pytest.raises(Refused) as e:
        review.crop_source(url.removeprefix("/crop/"))
    assert e.value.code == 404


def test_a_time_out_gives_an_error_and_the_page_shows_the_text_only(
    ocr_store: tuple[FolderStore, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, tk, _ = ocr_store
    monkeypatch.setattr(crop, "TIMEOUT", 0.5)
    monkeypatch.setattr(crop, "_argv", lambda: [sys.executable, "-I", "-c",
                                                "import time; time.sleep(30)"])  # fmt: skip
    with store, running(Review(store, "ana")) as (call, _, _):
        url = json.loads(call("GET", f"/api/task/{tk}")[2])["view"]["pages"][0]["crops"][0]
        status, headers, body = call("GET", url, token=None)
        assert status == 502 and json.loads(body) == {"error": "the scan cannot be shown"}
        assert headers["Content-Type"].startswith("application/json")
        # the server still answers: the lock is not held during the crop
        assert call("GET", "/api/queue")[0] == 200


def test_after_forget_of_the_source_the_page_says_that_the_scan_is_gone(
    ocr_store: tuple[FolderStore, str, str],
) -> None:
    store, tk, source = ocr_store
    review = Review(store, "ana")
    url = review.view(tk)["view"]["pages"][0]["crops"][0]
    store.forget(source, "the client asked")
    with pytest.raises(Refused) as e:  # a ticket from before the forget
        review.crop_source(url.removeprefix("/crop/"))
    assert e.value.code == 410
    view = review.view(tk)["view"]
    assert view["note"] == SCAN_GONE and view["pages"][0]["crops"] == []
    assert view["pages"][0]["words"]  # the text is still there
    view = Review(store, "ana").view(tk)["view"]  # also for a new server
    assert view["note"] == SCAN_GONE and view["pages"][0]["crops"] == []


def test_without_the_ocr_extra_the_page_says_which_extra_shows_the_scan(
    ocr_store: tuple[FolderStore, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, tk, _ = ocr_store
    find_spec = importlib.util.find_spec

    def without(name: str, *more: Any) -> Any:
        return None if name == "pypdfium2" else find_spec(name, *more)

    monkeypatch.setattr(serve.importlib.util, "find_spec", without)
    view = Review(store, "ana").view(tk)["view"]
    assert view["note"] == NO_OCR == "Install groundgate[ocr] to see the scan"
    assert view["pages"][0]["crops"] == []


def test_a_pdf_with_a_text_layer_and_no_ocr_gets_no_crop(tmp_path: Path) -> None:
    path = tmp_path / "lease.pdf"
    path.write_bytes(_pdfgen().make_pdf([[(72, 100, "The monthly rent is $2,450.")]]))
    store = FolderStore(tmp_path / "store")
    with store:
        reading, doc = put_reading(store, path)
        at = doc.text.encode().index(b"2,450")
        cand = [{"id": "c1", "field": "rent", "value": "2450", "unit": "USD",
                 "evidence": {"start": at, "end": at + 5}}]  # fmt: skip
        schema = {"fields": {"rent": {"type": "integer", "unit": "USD"}}}
        k, _ = admit_packet(store, doc.text, schema, cand, None, "lease", reading=reading)
        (tk,) = [t for t, _ in write_tasks(store, k, EVERY).tasks]
        view = Review(store, "ana").view(tk)["view"]
    assert "note" not in view and view["pages"][0]["crops"] == []


def test_review_measures_gives_the_ocr_crop_row(ocr_store: tuple[FolderStore, str, str]) -> None:
    store, tk, _ = ocr_store
    Review(store, "ana", clock=lambda: CLOCK).answer(answer(tk, "confirm"))
    found = measures.measures(store).kinds["number"]
    none = {"answers": 0, "ms_median": None, "corrected": [0, 0]}
    other = {"answers": 1, "ms_median": 900, "corrected": [0, 1]}
    assert found["ocr_crop"] == {"doubt": none, "other": other}
    assert found["fields"]["rent"]["ocr_crop"] == found["ocr_crop"]
    line = measures.lines(measures.measures(store))[1]
    assert line.endswith(
        "ocr doubt answers 0, median time none, corrected 0 of 0, "
        "ocr other answers 1, median time 900 ms, corrected 0 of 1"
    )


def test_a_view_makes_at_most_max_crops_tickets_and_each_one_works(
    ocr_store: tuple[FolderStore, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, tk, _ = ocr_store
    review = Review(store, "ana")
    first = review.view(tk)["view"]["pages"][0]["crops"][0].removeprefix("/crop/")
    second = review.view(tk)["view"]["pages"][0]["crops"][0].removeprefix("/crop/")
    assert list(review.crops) == [second]  # a new view ends the tickets of the last one
    with pytest.raises(Refused):
        review.crop_source(first)
    assert review.crop_source(second)[1] == 1
    # a place after the limit gets no ticket, so no ticket of the view goes out of the dict
    monkeypatch.setattr(serve, "MAX_CROPS", 0)
    view = review.view(tk)["view"]
    assert view["pages"][0]["crops"] == [] and review.crops == {}
    assert view["note"] == "The page shows the scan of the first 0 places only."
