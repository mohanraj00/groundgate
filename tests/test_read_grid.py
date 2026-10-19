"""Hand-written ruled tables of text cells in a PDF (#332)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from groundgate.read import read
from groundgate.read.grid import PAGE_RULES, PAGE_TABLES, Grid, grids
from groundgate.read.layout import Box

from pdfgen import make_pdf

Text = tuple[float, float, str]

QUESTIONS: list[Text] = [
    (76, 705, "Important Questions"),
    (254, 705, "Answers"),
    (76, 685, "What is the overall"),
    (76, 671, "deductible?"),
    (254, 685, "$500 individual /"),
    (254, 671, "$1,000 family"),
    (76, 645, "Are there other deductibles?"),
    (254, 645, "No."),
    (76, 605, "What is the out-of-pocket limit?"),
    (254, 605, "$2,000 individual"),
]


def _rules(xs: list[float], ys: list[float], width: float = 0.5) -> bytes:
    """A full grid of thin filled rectangles: a rule at each x and at each y."""
    half = width / 2
    out = [b"%g %g %g %g re f\n" % (xs[0], y - half, xs[-1] - xs[0], width) for y in ys]
    out += [b"%g %g %g %g re f\n" % (x - half, ys[-1], width, ys[0] - ys[-1]) for x in xs]
    return b"".join(out)


def _read(tmp_path: Path, lines: list[Text], drawing: bytes) -> str:
    path = tmp_path / "grid.pdf"
    path.write_bytes(make_pdf([lines], drawings=[drawing]))
    doc = read(path)
    assert doc.layout is not None
    raw = doc.text.encode()
    assert [raw[w.start : w.end].decode() for w in doc.layout.words] == doc.text.split()
    assert doc.text == read(path).text
    return doc.text


def test_question_beside_its_answer_is_one_line(tmp_path: Path) -> None:
    text = _read(tmp_path, QUESTIONS, _rules([72, 250, 540], [720, 700, 660, 620, 580]))
    assert text.split("\n") == [
        "Important Questions\tAnswers",
        "What is the overall deductible?\t$500 individual / $1,000 family",
        "Are there other deductibles?\tNo.",
        "What is the out-of-pocket limit?\t$2,000 individual",
    ]


def test_without_rules_the_text_stays_as_before(tmp_path: Path) -> None:
    text = _read(tmp_path, QUESTIONS, b"")
    assert "\t" not in text
    assert "What is the overall\ndeductible?" in text


def test_a_word_keeps_its_box_in_a_joined_cell(tmp_path: Path) -> None:
    path = tmp_path / "grid.pdf"
    path.write_bytes(
        make_pdf([QUESTIONS], drawings=[_rules([72, 250, 540], [720, 700, 660, 620, 580])])
    )
    doc = read(path)
    assert doc.layout is not None
    start = doc.text.encode().index(b"deductible?")
    (box,) = doc.layout.locate(start, start + len(b"deductible?"))
    assert box.x0 == 76
    assert box.top == pytest.approx(792 - 671 - 12 * 0.718, abs=1)


def test_stroked_lines_and_rectangles_are_rules(tmp_path: Path) -> None:
    lines = b"".join(b"72 %g m 540 %g l S\n" % (y, y) for y in (720, 700, 660, 620))
    lines += b"72 580 468 40 re S\n"  # the last row is a stroked rectangle
    lines += b"".join(b"%g 580 m %g 720 l S\n" % (x, x) for x in (72, 250, 540))
    text = _read(tmp_path, QUESTIONS, lines)
    assert "What is the overall deductible?\t$500 individual / $1,000 family" in text
    assert "What is the out-of-pocket limit?\t$2,000 individual" in text


def test_tall_cell_leaves_an_empty_slot_in_the_rows_below(tmp_path: Path) -> None:
    lines: list[Text] = [
        (76, 705, "Event"),
        (204, 705, "Service"),
        (354, 705, "You pay"),
        (76, 665, "If you visit"),
        (76, 651, "a doctor"),
        (204, 685, "Primary care"),
        (354, 685, "$20 copay"),
        (204, 645, "Specialist visit"),
        (354, 645, "$50 copay"),
    ]
    rules = b"".join(b"72 %g 468 0.5 re f\n" % y for y in (720, 700, 630))
    rules += b"200 660 340 0.5 re f\n"  # no rule across the first column: its cell is tall
    rules += b"".join(b"%g 630 0.5 90 re f\n" % x for x in (72, 200, 350, 540))
    text = _read(tmp_path, lines, rules)
    assert text.split("\n") == [
        "Event\tService\tYou pay",
        "If you visit a doctor\tPrimary care\t$20 copay",
        "\tSpecialist visit\t$50 copay",
    ]


def test_wall_ends_close_a_table_with_no_top_rule(tmp_path: Path) -> None:
    rules = b"".join(b"72 %g 468 0.5 re f\n" % y for y in (660, 620, 580))  # none at 700
    rules += b"".join(b"%g 580 0.5 120 re f\n" % x for x in (72, 250, 540))
    text = _read(tmp_path, QUESTIONS[2:], rules)
    assert text.split("\n") == [
        "What is the overall deductible?\t$500 individual / $1,000 family",
        "Are there other deductibles?\tNo.",
        "What is the out-of-pocket limit?\t$2,000 individual",
    ]


def test_lists_side_by_side_keep_the_text_as_before(tmp_path: Path) -> None:
    lines: list[Text] = [
        (76, 705, "Member"),
        (254, 705, "Meetings"),
        (76, 685, "Ann Lee (Chair)"),
        (76, 671, "Bo Chen"),
        (76, 657, "Cy Diaz"),
        (254, 685, "1/1"),
        (254, 671, "4/4"),
        (254, 657, "5/5"),
    ]
    rules = _rules([72, 250, 540], [720, 700, 640])  # no rule between the members
    assert _read(tmp_path, lines, rules) == _read(tmp_path, lines, b"")
    wrapped: list[Text] = [
        (76, 705, "Question"),
        (164, 705, "Answer"),
        (76, 685, "What is the"),
        (76, 671, "out-of-pocket"),
        (76, 657, "limit?"),
        (164, 685, "$2,000 for one person and"),
        (164, 671, "$4,000 for a family, and the"),
        (164, 657, "deductible counts."),
    ]
    rules = _rules([72, 160, 410], [720, 700, 640])  # the question wraps: its next word is too wide
    assert "What is the out-of-pocket limit?\t$2,000 for one person" in _read(
        tmp_path, wrapped, rules
    )


def test_pieces_of_a_thick_rule_are_one_wall(tmp_path: Path) -> None:
    rules = _rules([72, 250, 540], [720, 700, 620, 580])
    rules += b"72 658.5 468 1.2 re f\n72 659.9 468 1.4 re f\n"  # two pieces, 2.6 points tall
    text = _read(tmp_path, QUESTIONS, rules)
    assert text.split("\n")[1:] == [
        "What is the overall deductible?\t$500 individual / $1,000 family",
        "Are there other deductibles?\tNo.",
        "What is the out-of-pocket limit?\t$2,000 individual",
    ]


def test_an_underline_in_a_cell_does_not_split_it(tmp_path: Path) -> None:
    rules = _rules([72, 250, 540], [720, 700, 660, 620, 580])
    rules += b"76 669 60 0.9 re f\n"  # under "deductible?"
    text = _read(tmp_path, QUESTIONS, rules)
    assert "What is the overall deductible?\t$500 individual / $1,000 family" in text


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(b"72 640 178 0.5 re f\n400 620 0.5 20 re f\n", id="an-irregular-grid"),
        pytest.param(b"", id="a-word-across-a-wall"),
    ],
)
def test_an_ambiguous_grid_keeps_the_text_as_before(tmp_path: Path, extra: bytes) -> None:
    lines = list(QUESTIONS)
    if not extra:
        lines[6] = (230, 645, "Deductibles?")  # one word from 230 to 297, across the wall at 250
    rules = _rules([72, 250, 540], [720, 700, 660, 620, 580]) + extra
    assert _read(tmp_path, lines, rules) == _read(tmp_path, lines, b"")


def test_a_framed_note_keeps_its_lines(tmp_path: Path) -> None:
    lines: list[Text] = [(76, 700, "This is only a summary."), (76, 686, "Read the plan.")]
    rules = _rules([72, 540], [720, 670])
    assert _read(tmp_path, lines, rules) == _read(tmp_path, lines, b"")


def test_a_table_with_numbers_keeps_its_rows(tmp_path: Path) -> None:
    lines: list[Text] = [
        (76, 705, "Cash"),
        (300, 705, "100"),
        (400, 705, "200"),
        (76, 685, "Land"),
        (300, 685, "300"),
        (400, 685, "400"),
        (76, 665, "Debt"),
        (300, 665, "500"),
        (400, 665, "600"),
    ]
    rules = _rules([72, 290, 390, 540], [720, 700, 680, 660])
    assert _read(tmp_path, lines, rules) == _read(tmp_path, lines, b"")


def _grid(rules: list[tuple[float, float, float, float]]) -> list[Grid]:
    return grids(rules)


def test_grid_cells_and_lookup() -> None:
    rules = [(0.0, y, 300.0, y + 0.5) for y in (0, 20, 40)]
    rules += [(x, 0.0, x + 0.5, 40.0) for x in (0, 100, 300)]
    (grid,) = _grid(rules)
    assert len(grid.cells) == 4
    assert [grid.slots(r) for r in range(2)] == [[0, 1], [2, 3]]
    assert grid.cell_of(Box(1, 5, 25, 50, 35)) == 2
    assert grid.cell_of(Box(1, 90, 25, 110, 35)) is None  # across the wall at 100
    assert grid.cell_of(Box(1, 400, 25, 410, 35)) is None  # outside the table


def test_grid_needs_a_closed_cell() -> None:
    rules = [(0.0, y, 300.0, y + 0.5) for y in (0, 20)]
    rules += [(0.0, 40.0, 100.0, 40.5)]  # the bottom rule is under the first column only
    rules += [(0.0, 0.0, 0.5, 40.0), (100.0, 0.0, 100.5, 60.0), (300.0, 0.0, 300.5, 60.0)]
    assert _grid(rules) == []
    rules[-1] = (300.0, 0.0, 300.5, 40.0)  # the walls end at one level, so that level closes it
    rules[-2] = (100.0, 0.0, 100.5, 40.0)
    assert len(_grid(rules)) == 1


def test_too_many_rules_give_no_grid_quickly() -> None:
    rules = [(0.0, float(y), 300.0, y + 0.5) for y in range(PAGE_RULES + 1)]
    started = time.perf_counter()
    assert _grid(rules) == []
    many = [(0.0, float(y), 300.0, y + 0.5) for y in range(0, 2000, 2)]
    many += [(float(x), 0.0, x + 0.5, 2000.0) for x in range(0, 2000, 2)]
    assert _grid(many) == []  # a mesh of 1000 by 1000 rules, such as a chart
    assert time.perf_counter() - started < 2


def test_a_page_of_many_small_tables_gives_none() -> None:
    def table(left: float) -> list[tuple[float, float, float, float]]:
        out = [(left, y, left + 8.0, y + 0.5) for y in (0.0, 4.0, 8.0)]
        return out + [(x, 0.0, x + 0.5, 8.0) for x in (left, left + 4.0, left + 8.0)]

    assert len(_grid(table(0.0))) == 1
    many = [rule for n in range(PAGE_TABLES + 1) for rule in table(20.0 * n)]
    assert _grid(many) == []
