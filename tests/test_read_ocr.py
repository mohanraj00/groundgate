"""OCR of scanned PDF pages with the tesseract program (#7).

The tests with ``tesseract`` in their name need the real program and skip without it. A fake
program (a shell script) covers the process code on each machine with a POSIX shell.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import unicodedata
from pathlib import Path

import pytest

from groundgate.cli import main
from groundgate.read import ReadError, read, reader
from groundgate.read import ocr as ocr_module
from groundgate.read.document import read_document
from groundgate.read.ocr import parse_tsv

from pdfgen import make_pdf, make_scan

HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
    "\tleft\ttop\twidth\theight\tconf\ttext\n"
)
NEEDS_TESSERACT = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="the tesseract program is not installed"
)
POSIX = pytest.mark.skipif(sys.platform == "win32", reason="the fake program is a shell script")


def _row(
    level: int, block: int, par: int, line: int, word: int, box: str, conf: str, t: str
) -> str:
    return f"{level}\t1\t{block}\t{par}\t{line}\t{word}\t{box}\t{conf}\t{t}\n"


TSV = (
    HEADER
    + _row(1, 0, 0, 0, 0, "0\t0\t2550\t3300", "-1", "")
    + _row(4, 1, 1, 1, 0, "300\t300\t600\t50", "-1", "")
    + _row(5, 1, 1, 1, 1, "300\t300\t150\t50", "96.5", "Fee:")
    + _row(5, 1, 1, 1, 2, "475\t300\t150\t50", "100", "$500")
    + _row(5, 1, 1, 2, 1, "300\t375\t150\t50", "80.25", "per​year")
    + _row(5, 1, 1, 2, 2, "475\t375\t150\t50", "50", " ")
    + _row(5, 2, 1, 1, 1, "300\t600\t300\t50", "12", "oﬃce")
)


def test_parse_tsv_groups_paragraphs_and_lines_and_cleans_words() -> None:
    blocks = parse_tsv(TSV.encode(), 3, 300 / 72)
    texts = [[[t for t, _, _ in line] for line in b] for b in blocks]
    assert texts == [[["Fee:", "$500"], ["peryear"]], [["office"]]]
    _, box, conf = blocks[0][0][0]
    assert (box.page, box.x0, box.top, box.x1, box.bottom) == (3, 72.0, 72.0, 108.0, 84.0)
    assert conf == 0.965 and blocks[0][0][1][2] == 1.0


def test_parse_tsv_gives_nfc_after_it_removes_format_characters() -> None:
    # A zero width space between "e" and a combining acute accent: NFC before the filter
    # keeps the accent apart, and the word is not NFC.
    raw = HEADER + _row(5, 1, 1, 1, 1, "0\t0\t1\t1", "90", "Cafe\u200b\u0301 \ufb01")
    ((line,),) = parse_tsv(raw.encode(), 1, 1.0)
    assert [t for t, _, _ in line] == ["Caf\u00e9fi"]
    assert unicodedata.is_normalized("NFC", line[0][0])


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"level\tpage\n",
        (HEADER + "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\n").encode(),  # 11 columns
        (HEADER + _row(5, 1, 1, 1, 1, "a\t0\t1\t1", "90", "x")).encode(),
        (HEADER + _row(5, 1, 1, 1, 1, "-1\t0\t1\t1", "90", "x")).encode(),
        (HEADER + _row(5, 1, 1, 1, 1, "0\t0\t1\t1", "101", "x")).encode(),
        (HEADER + _row(5, 1, 1, 1, 1, "0\t0\t1\t1", "nan", "x")).encode(),
        HEADER.encode() + b"5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\t\xff\n",
    ],
)
def test_parse_tsv_refuses_output_it_does_not_know(raw: bytes) -> None:
    with pytest.raises(ReadError, match="page 2"):
        parse_tsv(raw, 2, 1.0)


def _scan(tmp_path: Path, *pages: tuple[int, int, bytes] | None) -> Path:
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_scan(list(pages)))
    return path


def _gray(width: int = 40, height: int = 20) -> tuple[int, int, bytes]:
    return width, height, b"\xff" * (width * height)


def test_a_blank_page_with_no_image_keeps_the_warning(tmp_path: Path) -> None:
    doc = read(_scan(tmp_path, None), ocr=True)
    assert doc.warnings == (
        "page 1 has no text layer; OCR the PDF first (for example with ocrmypdf)",
    )
    assert doc.ocr is None


OFF = (
    "page 1 has no text layer; OCR the PDF first (for example with ocrmypdf), or read it with --ocr"
)


def test_ocr_is_off_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_ocr(*args: object) -> None:
        raise AssertionError("OCR ran with the option off")

    monkeypatch.setattr(ocr_module, "start", no_ocr)
    path = _scan(tmp_path, _gray())
    for doc in (read(path), read_document(path)[0]):
        assert doc.text == "" and doc.warnings == (OFF,) and doc.ocr is None
    _, document = read_document(path)
    assert document.doubt == [] and document.reader == reader()


def test_the_cli_reads_a_scan_with_no_ocr_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ocr_module.shutil, "which", lambda name: None)
    path = _scan(tmp_path, _gray())
    assert main(["read", str(path)]) == 0
    assert OFF in capsys.readouterr().err
    assert main(["read", "--ocr", str(path)]) == 2  # with the option, OCR runs: no tesseract
    assert "OCR needs tesseract" in capsys.readouterr().err


def test_no_tesseract_gives_an_error_with_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr_module.shutil, "which", lambda name: None)
    with pytest.raises(ReadError, match=r"page 1 has no text layer, and OCR needs tesseract.*brew"):
        read(_scan(tmp_path, _gray()), ocr=True)


def test_no_pypdfium2_gives_an_error_with_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr_module.shutil, "which", lambda name: "/bin/true")
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    with pytest.raises(ImportError, match=r"groundgate\[ocr\]"):
        read(_scan(tmp_path, _gray()), ocr=True)


def _fake(tmp_path: Path, version: str, tsv: str, code: int = 0) -> None:
    """A fake tesseract program in ``tmp_path``: it prints ``version`` for ``--version`` and
    ``tsv`` for a page, and exits with ``code``."""
    (tmp_path / "out.tsv").write_text(tsv, encoding="utf-8")
    program = tmp_path / "tesseract"
    program.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then printf "{version}\\n"; exit 0; fi\n'
        f'cat > /dev/null; cat "{tmp_path / "out.tsv"}"; echo "the error line" >&2; exit {code}\n',
        encoding="utf-8",
    )
    program.chmod(program.stat().st_mode | stat.S_IXUSR)


@POSIX
def test_a_fake_program_gives_words_boxes_reader_and_doubt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pypdfium2")
    _fake(tmp_path, "tesseract 5.3.0", TSV)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    path = _scan(tmp_path, None, _gray())
    extracted, doc = read_document(path, [2], ocr=True)
    assert extracted.text == "Fee: $500\nperyear\n\noffice"
    assert extracted.warnings == () and extracted.ocr == "5.3.0"
    assert (
        doc.reader
        == reader("5.3.0")
        == {
            "name": "groundgate.read+tesseract",
            "version": f"{reader()['version']}+tesseract.5.3.0",
        }
    )
    assert [n.kind for n in doc.nodes] == ["paragraph", "paragraph"]
    assert {n.basis for n in doc.nodes} == {"layout"}
    # "$500" has confidence 1, so it is no doubt
    assert doc.doubt == [
        {"start": 0, "end": 4, "confidence": 0.965},
        {"start": 10, "end": 17, "confidence": 0.8025},
        {"start": 19, "end": 25, "confidence": 0.12},
    ]
    assert extracted.layout is not None
    assert [w.box.page for w in extracted.layout.words] == [2, 2, 2, 2]


@POSIX
@pytest.mark.parametrize(
    ("version", "tsv", "code", "message"),
    [
        ("no version here", TSV, 0, "gave no version"),
        ("tesseract 5.3.0", TSV, 1, r"tesseract failed \(the error line\)"),
        ("tesseract 5.3.0", "wrong header\n", 0, "unknown columns"),
    ],
)
def test_a_fake_program_that_fails_gives_a_read_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, tsv: str, code: int, message: str
) -> None:
    pytest.importorskip("pypdfium2")
    _fake(tmp_path, version, tsv, code)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(ReadError, match=message):
        read(_scan(tmp_path, _gray()), ocr=True)


@POSIX
@pytest.mark.parametrize(
    ("limit", "message"),
    [
        ("MAX_OUTPUT", "page 1: tesseract wrote more than 100 bytes to stdout"),
        ("MAX_ERROR", "page 1: tesseract wrote more than 10 bytes to stderr"),
    ],
)
def test_a_fake_program_that_writes_too_much_is_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str, message: str
) -> None:
    pytest.importorskip("pypdfium2")
    _fake(tmp_path, "tesseract 5.3.0", TSV)  # TSV is more than 100 bytes; stderr is 15 bytes
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(ocr_module, limit, 100 if limit == "MAX_OUTPUT" else 10)
    with pytest.raises(ReadError, match=message):
        read(_scan(tmp_path, _gray()), ocr=True)


def _rendered(lines: list[tuple[float, float, str]], dpi: int = 200) -> tuple[int, int, bytes]:
    """A text page rendered to gray pixels, as a scanner gives it."""
    pdfium = pytest.importorskip("pypdfium2")
    pdf = pdfium.PdfDocument(make_pdf([lines], page_size=(400, 300)))
    bitmap = pdf[0].render(scale=dpi / 72, grayscale=True)
    w, h, stride, buf = bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer)
    pdf.close()
    return w, h, b"".join(buf[y * stride : y * stride + w] for y in range(h))


@NEEDS_TESSERACT
def test_tesseract_reads_a_scanned_page(tmp_path: Path) -> None:
    lines = [(72, 250, "Fee: $500 per year."), (72, 230, "Dosage is 2,000 mg per day.")]
    path = tmp_path / "mixed.pdf"
    path.write_bytes(make_scan([None, _rendered(lines, 200)], dpi=200))
    extracted, doc = read_document(path, ocr=True)
    assert "Fee: $500 per year.\nDosage is 2,000 mg per day." in extracted.text
    assert extracted.warnings == (
        "page 1 has no text layer; OCR the PDF first (for example with ocrmypdf)",
    )
    assert doc.reader["name"] == "groundgate.read+tesseract"
    assert extracted.layout is not None
    raw = extracted.text.encode()
    start = raw.index(b"$500")
    (box,) = extracted.layout.locate(start, start + 4)
    assert box.page == 2 and 90 < box.x0 < box.x1 < 140 and 40 < box.top < box.bottom < 60
    assert doc.doubt and all(0 <= d["confidence"] < 1 for d in doc.doubt)
    _, again = read_document(path, ocr=True)
    assert again.to_json() == doc.to_json()  # the same tesseract gives the same bytes
    assert read(path, ocr=True).text == extracted.text


@NEEDS_TESSERACT
def test_tesseract_on_a_white_page_warns_that_ocr_found_no_text(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    doc = read(_scan(tmp_path, _gray(400, 400)), ocr=True)
    assert doc.warnings == ("page 1: OCR found no text on the scanned page",)
    assert doc.ocr is not None


@NEEDS_TESSERACT
def test_tesseract_reading_in_the_store_names_the_engine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from groundgate.store import FolderStore

    path = tmp_path / "a.pdf"
    path.write_bytes(make_scan([_rendered([(72, 250, "Fee: $500 per year.")], 200)], dpi=200))
    root = tmp_path / "s"
    assert main(["read", "--store", str(root), "--ocr", str(path)]) == 0
    k = capsys.readouterr().out.strip()
    with FolderStore(root) as store:
        reading = json.loads(store.get("reading@1", k))
    assert reading["reader"]["name"] == "groundgate.read+tesseract"
