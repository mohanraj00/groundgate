from __future__ import annotations

import json
from pathlib import Path

import pytest

import groundgate as gg
from groundgate.extract import ExtractError, Layout, extract
from groundgate.extract.markup import html_text, xml_text
from groundgate.extract.pdf import LIGATURES

from pdfgen import make_pdf


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "label.pdf"
    path.write_bytes(
        make_pdf(
            [
                [
                    (72, 720, "Dosage"),
                    (72, 690, "Start at 500 mg once daily."),
                    (72, 675, "Do not exceed 2,000 mg per day."),
                ],
                [(72, 720, "Café staff: up to 3 filings.")],
                [],
            ]
        )
    )
    return path


def test_pdf_text_pages_and_words(pdf: Path) -> None:
    doc = extract(pdf)
    assert doc.text == (
        "Dosage\n\nStart at 500 mg once daily.\nDo not exceed 2,000 mg per day."
        "\n\fCafé staff: up to 3 filings.\n\f"
    )
    assert doc.layout is not None
    assert [p.number for p in doc.layout.pages] == [1, 2, 3]
    assert doc.warnings == (
        "page 3 has no text layer; OCR the PDF first (for example with ocrmypdf)",
    )
    raw = doc.text.encode()
    for w in doc.layout.words:
        assert raw[w.start : w.end].decode().strip() == raw[w.start : w.end].decode()
    assert doc.layout.document_sha256 == gg.digest("document", {"text": doc.text})


def test_pdf_locate_maps_a_span_to_page_boxes(pdf: Path) -> None:
    doc = extract(pdf)
    assert doc.layout is not None
    start = doc.text.encode().index(b"2,000 mg")
    boxes = doc.layout.locate(start, start + len(b"2,000 mg"))
    assert len(boxes) == 1
    box = boxes[0]
    assert box.page == 1
    assert 792 - 675 - 12 <= box.top < box.bottom <= 792 - 675 + 4
    two_lines = doc.layout.locate(0, doc.layout.pages[0].end)
    assert len(two_lines) == 3
    assert doc.layout.page_at(start) == 1
    cafe = doc.text.encode().index("Café".encode())
    assert doc.layout.page_at(cafe) == 2
    assert doc.layout.page_at(len(doc.text.encode()) + 5) is None


def test_ligatures_are_expanded() -> None:
    assert "\ufb01nal \ufb02ow".translate(LIGATURES) == "final flow"


def test_pdf_page_selection(pdf: Path) -> None:
    doc = extract(pdf, pages=[2, 9])
    assert doc.text == "Café staff: up to 3 filings."
    assert doc.layout is not None
    assert [p.number for p in doc.layout.pages] == [2]
    assert doc.warnings == ("the PDF has fewer pages than requested (1 extracted)",)


def test_layout_round_trip(pdf: Path) -> None:
    layout = extract(pdf).layout
    assert layout is not None
    assert Layout.from_dict(json.loads(json.dumps(layout.to_dict()))) == layout
    with pytest.raises(gg.PacketError):
        Layout.from_dict({"groundgate_layout": "9"})
    with pytest.raises(gg.PacketError):
        Layout.from_dict({**layout.to_dict(), "words": [[1, 2]]})
    raw = layout.to_dict()
    with pytest.raises(gg.PacketError, match="text order"):
        Layout.from_dict({**raw, "words": raw["words"][::-1]})
    with pytest.raises(gg.PacketError, match="text order"):
        Layout.from_dict({**raw, "pages": raw["pages"][::-1]})


def test_a_pdf_decision_admits_against_extracted_text(pdf: Path) -> None:
    doc = extract(pdf)
    start = doc.text.encode().index(b"2,000 mg")
    cand = {
        "field": "max_daily_dose",
        "value": "2000",
        "unit": "mg",
        "evidence": {"start": start, "end": start + 8, "text": "2,000 mg"},
    }
    schema = {"fields": {"max_daily_dose": {"type": "integer", "unit": "mg", "comparator": "le"}}}
    (d,) = gg.admit(doc.text, schema, [cand]).decisions
    assert (d.outcome, d.codes) == ("admitted", ())


def test_pdf_superscripts_never_fuse_with_the_number(tmp_path: Path) -> None:
    # "count 10" then a raised, smaller "9", then "/L": x per Helvetica advance widths
    x = 72 + 12 * (0.5 * 5 + 0.278 + 0.556 * 2)
    path = tmp_path / "sup.pdf"
    path.write_bytes(
        make_pdf([[(72, 700, "count 10"), (x, 705, "9", 7), (x + 7 * 0.556, 700, "/L")]])
    )
    assert extract(path).text == "count 10^9/L"


def test_pdf_drops_text_outside_the_visible_page(tmp_path: Path) -> None:
    path = tmp_path / "proof.pdf"
    path.write_bytes(make_pdf([[(72, 800, "Draft proof 99"), (72, 700, "Fee: $5.")]]))
    doc = extract(path)
    assert doc.text == "Fee: $5."
    assert doc.warnings == ("page 1: dropped 3 words drawn outside the visible page",)


def test_pdf_errors(tmp_path: Path, pdf: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 not really")
    with pytest.raises(ExtractError, match="not a readable PDF"):
        extract(bad)
    for pages in ([0], []):
        with pytest.raises(ExtractError, match="1-based"):
            extract(pdf, pages=pages)
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(make_pdf([]))
    assert extract(empty).warnings == ("no pages were extracted",)


@pytest.mark.parametrize(
    ("html", "text"),
    [
        ("<p>One</p><p>Two  <b>bold</b>\n words</p>", "One\n\nTwo bold words"),
        ("<ul><li>a</li><li>b</li></ul>", "a\nb"),
        ("<table><tr><td>Dose</td> <td>500 mg</td></tr><tr><td>Max</td></tr></table>",
         "Dose\t500 mg\nMax"),
        ("<head><title>x</title><style>p{}</style></head><script>1</script><p>A &amp; B</p>",
         "A & B"),
        ("<html><head><title>T</title><body><p>Hi there</p></body></html>", "Hi there"),
        ("<head><meta charset=utf-8><p>No body tag</p>", "No body tag"),
        ("line<br>break<br/>again", "line\nbreak\nagain"),
        ("<pre>  keep\n  this</pre><p>x</p>", "  keep\n  this\n\nx"),
        ("10<sup>9</sup>/L, CO<sub>2</sub>, 500 mg<sup>1</sup> 2", "10^9/L, CO_2, 500 mg^1 2"),
        ("10<sup>9</sup>5", "10^9 5"),
        ("<p>Fee <span hidden>$9,000</span>$500</p>", "Fee $500"),
        ('<div style="display: none"><p>$9,000</p><br></div><p style="color:red">$500</p>',
         "$500"),
        ("<div hidden><div>x</div>y</div>z<input hidden>w", "zw"),
    ],
)  # fmt: skip
def test_html(html: str, text: str) -> None:
    assert html_text(html) == text


@pytest.mark.parametrize(
    ("xml", "text"),
    [
        ('<?xml version="1.0" encoding="UTF-8"?><document xmlns="urn:hl7-org:v3"><section>'
         "<title>Dosage <content>500 mg</content></title><text><paragraph>Take "
         "<sup>1</sup>it.</paragraph><paragraph>Again</paragraph></text></section></document>",
         "Dosage 500 mg\n\nTake ^1it.\n\nAgain"),
        ('<r xmlns:h="urn:x"><h:paragraph>a</h:paragraph><h:paragraph>b</h:paragraph></r>',
         "a\n\nb"),
        ("<r>A<![CDATA[ 5 mg ]]>B<script>x</script></r>", "A 5 mg B"),
    ],
)  # fmt: skip
def test_xml(xml: str, text: str) -> None:
    assert xml_text(xml.encode()) == text


def test_html_xml_and_text_files(tmp_path: Path) -> None:
    (tmp_path / "a.html").write_text("<p>Cafe\u0301</p>", encoding="utf-8")
    assert extract(tmp_path / "a.html").text == "Café"
    assert extract(tmp_path / "a.html").layout is None
    (tmp_path / "e.html").write_text("<script>x</script>", encoding="utf-8")
    assert extract(tmp_path / "e.html").warnings == ("e.html: no text was extracted",)
    (tmp_path / "b.txt").write_bytes("\ufeffline one\r\nline two".encode())
    assert extract(tmp_path / "b.txt").text == "line one\nline two"
    (tmp_path / "c.txt").write_bytes(b"\xff\xfe")
    with pytest.raises(ExtractError):
        extract(tmp_path / "c.txt")
    (tmp_path / "d.docx").write_bytes(b"")
    with pytest.raises(ExtractError):
        extract(tmp_path / "d.docx")
    (tmp_path / "f.xml").write_bytes(
        "<r>Caf\u00e9</r>".encode("latin-1").replace(
            b"<r>", b'<?xml version="1.0" encoding="latin-1"?><r>'
        )
    )
    assert extract(tmp_path / "f.xml").text == "Café"
    (tmp_path / "g.xml").write_bytes(b"<r>unclosed")
    with pytest.raises(ExtractError, match="well-formed"):
        extract(tmp_path / "g.xml")
