"""Hand-written PDF table regressions for the approved 0.9 extraction rules."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.read import read
from groundgate.read.layout import Box
from groundgate.read.pdf import HEADER_BAND, _fill_empty_cells, _number_columns, _plan

from pdfgen import make_pdf

CASES = json.loads((Path(__file__).parent / "fixtures/pdf_table_cases.json").read_text())["cases"]


def _line(text: str, x0: float, x1: float, top: float = 100) -> list[tuple[str, Box]]:
    return [(text, Box(1, x0, top, x1, top + 10))]


@pytest.mark.parametrize("case", [case for case in CASES if "page" in case], ids=lambda c: c["id"])
def test_hand_written_pdf_rows_and_word_offsets(tmp_path: Path, case: dict[str, Any]) -> None:
    path = tmp_path / "case.pdf"
    path.write_bytes(make_pdf([[tuple(line) for line in case["page"]]]))
    doc = read(path)
    lines = doc.text.split("\n")
    for key in ("expected_table_rows", "expected_second_table_rows"):
        rows = ["\t".join(row) for row in case.get(key, [])]
        assert any(lines[i : i + len(rows)] == rows for i in range(len(lines))), key
    for text in case.get("absent_text", []):
        assert text not in doc.text
    assert doc.text == read(path).text
    assert doc.layout is not None
    raw = doc.text.encode()
    words = [raw[word.start : word.end].decode() for word in doc.layout.words]
    assert words == doc.text.split()
    assert Counter(words) == Counter(word for line in case["page"] for word in line[2].split())
    for word in doc.layout.words:
        assert word.box.page == 1
        assert 0 <= word.box.x0 < word.box.x1 <= 612
        assert 0 <= word.box.top < word.box.bottom <= 792
    if "expected_prose_words" in case:
        head = [raw[w.start : w.end].decode() for w in doc.layout.words if w.box.top < HEADER_BAND]
        assert head == case["expected_prose_words"]


@pytest.mark.parametrize("top,included", [(35.99, False), (36.0, True), (36.01, True)])
def test_header_band_uses_physical_points_and_row_top(top: float, included: bool) -> None:
    # The first word starts outside the band; the second word's top determines the row's top.
    blocks = [
        [_line("Title", 72, 110, top + 0.2)],
        [_line("Units", 400, 430, top)],
        [_line("Cash", 72, 100, 300), _line("Land", 72, 100, 315)],
        [_line("1", 300, 308, 300), _line("2", 300, 308, 315)],
    ]
    _, _, plan = _plan(blocks)
    assert HEADER_BAND == 36
    assert plan[0][0] == (0 if included else 1)


def test_sparse_row_preserves_utf8_offsets_and_numeric_source_box(tmp_path: Path) -> None:
    path = tmp_path / "unicode.pdf"
    path.write_bytes(
        make_pdf(
            [
                [
                    (300, 720, "2025"),
                    (400, 720, "2024"),
                    (72, 700, "Café"),
                    (400, 700, "100"),
                    (72, 685, "Land"),
                    (300, 685, "20"),
                    (400, 685, "30"),
                    (72, 670, "Debt"),
                    (300, 670, "40"),
                    (400, 670, "50"),
                ]
            ]
        )
    )
    doc = read(path)
    assert "Café\t\t100" in doc.text
    assert doc.layout is not None
    raw = doc.text.encode()
    start = raw.index(b"100")
    assert start == doc.text.index("100") + 1  # the accent takes a second UTF-8 byte
    (box,) = doc.layout.locate(start, start + 3)
    assert box.x0 == 400
    assert box.top == pytest.approx(82.48, abs=0.01)
    assert box.page == 1
    assert [raw[w.start : w.end].decode() for w in doc.layout.words] == doc.text.split()


def test_sparse_rows_fill_consecutive_and_trailing_empty_columns() -> None:
    columns = [(200.0, 220.0), (300.0, 320.0), (400.0, 420.0), (500.0, 520.0)]
    row = [_line("Cash", 72, 100), _line("100", 501, 518)]
    assert _fill_empty_cells(row, columns) == [row[0], [], [], [], row[1]]
    row = [_line("Cash", 72, 100), _line("100", 201, 218)]
    assert _fill_empty_cells(row, columns) == [row[0], row[1], [], [], []]


@pytest.mark.parametrize("number", [(150, 170), (215, 305)])
def test_unmapped_or_ambiguous_cell_removes_every_tab(number: tuple[int, int]) -> None:
    row = [_line("Cash", 72, 100), _line("100", *number)]
    assert _fill_empty_cells(row, [(200, 220), (300, 320)]) == [[*row[0], *row[1]]]


def test_duplicate_columns_and_number_in_label_are_ambiguous() -> None:
    row = [_line("Cash", 72, 100), _line("1", 201, 205), _line("2", 210, 215)]
    assert len(_fill_empty_cells(row, [(200, 220), (300, 320)])) == 1
    row = [_line("Cash", 72, 100), _line("1", 110, 115), _line("2", 301, 315)]
    assert len(_fill_empty_cells(row, [(200, 220), (300, 320)])) == 1


def test_widest_rows_must_share_a_disjoint_grid() -> None:
    rows = [
        [_line("100", 200, 220), _line("200", 300, 320)],
        [_line("10", 205, 220), _line("20", 305, 320)],
    ]
    assert _number_columns(rows) == [(200, 220), (300, 320)]
    rows.append([_line("1", 500, 510), _line("2", 600, 610)])
    assert _number_columns(rows) == []
    assert _number_columns([[_line("1", 200, 310), _line("2", 300, 320)]]) == []


@pytest.mark.parametrize("sign", ["$", "(", "-", "\u2013"])
def test_number_cell_parts_keep_their_words_and_boxes(sign: str) -> None:
    words = [(sign, Box(1, 300, 100, 304, 110)), ("100", Box(1, 305, 100, 320, 110))]
    row = [_line("Cash", 72, 100), words]
    assert _fill_empty_cells(row, [(200, 220), (300, 320)]) == [row[0], [], words]


@pytest.mark.parametrize("case", [case for case in CASES if "text" in case], ids=lambda c: c["id"])
def test_sparse_text_never_admits_a_wrong_key(case: dict[str, Any]) -> None:
    (decision,) = gg.admit(case["text"], case["schema"], [case["candidate"]]).decisions
    assert decision.outcome in case["required_outcomes"]
    if "supported_candidate" in case:
        (supported,) = gg.admit(
            case["text"], case["schema"], [case["supported_candidate"]]
        ).decisions
        assert supported.outcome == case["desired_supported_outcome"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("page_size", [(612, 792), (595, 842)])
def test_header_policy_uses_displayed_page_after_rotation(
    tmp_path: Path, rotation: int, page_size: tuple[float, float]
) -> None:
    path = tmp_path / "rotated.pdf"
    height = page_size[1]
    page = [
        (72, height - 26, "Report"),
        (500, height - 26, "Page 1"),
        (72, height - 276, "Cash"),
        (300, height - 276, "1"),
        (72, height - 291, "Land"),
        (300, height - 291, "2"),
    ]
    path.write_bytes(make_pdf([page], page_size=page_size, rotation=rotation))
    doc = read(path)
    assert "Cash\t1\nLand\t2" in doc.text
    assert "Report\tPage 1" not in doc.text
    assert doc.layout is not None
    assert (doc.layout.pages[0].width, doc.layout.pages[0].height) == page_size
    raw = doc.text.encode()
    (head,) = [w for w in doc.layout.words if raw[w.start : w.end] == b"Report"]
    assert head.box.x0 == 72
    assert head.box.top == pytest.approx(16.48, abs=0.01)
    assert [raw[w.start : w.end].decode() for w in doc.layout.words] == doc.text.split()


def test_header_policy_uses_cropbox_top(tmp_path: Path) -> None:
    path = tmp_path / "crop.pdf"
    page = [
        (72, 716, "Report"),
        (500, 716, "Page 1"),
        (72, 466, "Cash"),
        (300, 466, "1"),
        (72, 451, "Land"),
        (300, 451, "2"),
    ]
    path.write_bytes(make_pdf([page], crop_box=(20, 30, 592, 742)))
    doc = read(path)
    assert "Cash\t1\nLand\t2" in doc.text
    assert "Report\tPage 1" not in doc.text
    assert doc.layout is not None
    assert (doc.layout.pages[0].width, doc.layout.pages[0].height) == (572, 712)
    raw = doc.text.encode()
    (head,) = [w for w in doc.layout.words if raw[w.start : w.end] == b"Report"]
    assert head.box.x0 == 52
    assert head.box.top == pytest.approx(16.48, abs=0.01)


@pytest.mark.parametrize(
    "value_x,key,outcome",
    [
        (400, "2025", "needs_verification"),
        (400, "2024", "admitted"),
        (350, "2025", "needs_verification"),
    ],
)
def test_pdf_columns_reach_the_decision_safely(
    tmp_path: Path, value_x: int, key: str, outcome: str
) -> None:
    path = tmp_path / "decision.pdf"
    path.write_bytes(
        make_pdf(
            [
                [
                    (300, 720, "2025"),
                    (400, 720, "2024"),
                    (72, 700, "Cash"),
                    (value_x, 700, "100"),
                    (72, 685, "Land"),
                    (300, 685, "20"),
                    (400, 685, "30"),
                    (72, 670, "Debt"),
                    (300, 670, "40"),
                    (400, 670, "50"),
                ]
            ]
        )
    )
    text = read(path).text
    assert ("Cash\t\t100" if value_x == 400 else "Cash 100") in text
    schema = {"fields": {"cash": {"aliases": ["Cash"], "keys": ["2025", "2024"]}}}
    candidate = {
        "field": "cash",
        "value": "100",
        "key": key,
        "evidence": [
            {"text": "100"},
            {"role": "field", "text": "Cash"},
            {"role": "key", "text": key},
        ],
    }
    (decision,) = gg.admit(text, schema, [candidate]).decisions
    assert decision.outcome == outcome


def test_numeric_only_sparse_row_has_an_explicit_empty_label_slot() -> None:
    row = [_line("100", 301, 318)]
    assert _fill_empty_cells(row, [(200, 220), (300, 320)]) == [[], [], row[0]]


@pytest.mark.parametrize("key", ["2025", "2024"])
def test_ambiguous_numeric_only_row_cannot_reuse_a_prior_field_or_header(
    tmp_path: Path, key: str
) -> None:
    path = tmp_path / "unlabeled.pdf"
    page = [
        (300, 720, "2025"),
        (400, 720, "2024"),
        (72, 700, "Cash"),
        (350, 685, "100"),
        (72, 670, "Land"),
        (300, 670, "20"),
        (400, 670, "30"),
        (72, 655, "Debt"),
        (300, 655, "40"),
        (400, 655, "50"),
    ]
    path.write_bytes(make_pdf([page]))
    text = read(path).text
    assert "\n\n\n100\n\n\n" in text
    schema = {"fields": {"cash": {"aliases": ["Cash"], "keys": ["2025", "2024"]}}}
    candidate = {
        "field": "cash",
        "value": "100",
        "key": key,
        "evidence": [
            {"text": "100"},
            {"role": "field", "text": "Cash"},
            {"role": "key", "text": key},
        ],
    }
    (decision,) = gg.admit(text, schema, [candidate]).decisions
    assert decision.outcome == "needs_verification"


def test_full_width_numeric_row_off_the_grid_is_isolated(tmp_path: Path) -> None:
    path = tmp_path / "offgrid.pdf"
    page = [
        (300, 720, "2025"),
        (400, 720, "2024"),
        (72, 705, "Land"),
        (300, 705, "10"),
        (400, 705, "20"),
        (72, 690, "Cash"),
        (350, 675, "100"),
        (450, 675, "200"),
        (72, 660, "Debt"),
        (300, 660, "30"),
        (400, 660, "40"),
    ]
    path.write_bytes(make_pdf([page]))
    text = read(path).text
    assert "\t2025\t2024\nLand\t10\t20" in text
    assert "\n\n\n100 200\n\n\n" in text
    schema = {"fields": {"cash": {"aliases": ["Cash"], "keys": ["2025", "2024"]}}}
    candidate = {
        "field": "cash",
        "value": "100",
        "key": "2025",
        "evidence": [
            {"text": "100"},
            {"role": "field", "text": "Cash"},
            {"role": "key", "text": "2025"},
        ],
    }
    (decision,) = gg.admit(text, schema, [candidate]).decisions
    assert decision.outcome == "needs_verification"


@pytest.mark.parametrize(
    "x,expected",
    [(402, "Cash\t\tn/a"), (300, "Cash\tn/a"), (420, "Cash n/a")],
    ids=["inside-second-column", "inside-first-column", "across-the-column-edge"],
)
def test_text_only_row_in_a_table_keeps_its_column(tmp_path: Path, x: int, expected: str) -> None:
    path = tmp_path / "text-cell.pdf"
    page = [
        (72, 705, "Land"),
        (300, 705, "1,000"),
        (400, 705, "2,000"),
        (72, 690, "Cash"),
        (x, 690, "n/a"),
        (72, 675, "Debt"),
        (300, 675, "3,000"),
        (400, 675, "4,000"),
    ]
    path.write_bytes(make_pdf([page]))
    lines = read(path).text.split("\n")
    assert expected in lines


def test_numeric_row_label_is_not_a_number_column(tmp_path: Path) -> None:
    path = tmp_path / "year-label.pdf"
    page = [
        (300, 720, "Q1"),
        (400, 720, "Q2"),
        (72, 705, "Cash"),
        (300, 705, "10"),
        (400, 705, "20"),
        (72, 690, "Debt"),
        (300, 690, "50"),
        (400, 690, "60"),
        (72, 675, "2024"),
        (300, 675, "30"),
        (400, 675, "40"),
        (72, 660, "2023"),
        (400, 660, "70"),
    ]
    path.write_bytes(make_pdf([page]))
    lines = read(path).text.split("\n")
    for row in ("Cash\t10\t20", "Debt\t50\t60", "2024\t30\t40", "2023\t\t70"):
        assert row in lines
    assert not any(line.startswith("\tCash") for line in lines)
