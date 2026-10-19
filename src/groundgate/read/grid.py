"""The cells of a ruled table, from the rules that the page draws (#332).

A PDF draws the grid of a table as thin lines or thin filled rectangles. This module finds the
cells of such a grid. It uses only the page geometry, never the words, so a "?" at the end of a
cell does not change a row. Coordinates are PDF points with the origin at the top-left of the
page, as in ``layout``.

If the grid is irregular or more than the limits below, the module gives no cells for it. Then
the reader writes the text as it did before, because a wrong row is worse than no row.
"""

from __future__ import annotations

import bisect
import itertools
from dataclasses import dataclass

from .layout import Box

Rule = tuple[float, float, float, float]  # x0, top, x1, bottom of a line or a thin rectangle
Segment = tuple[float, float, float]  # the position across the rule, then its start and end

RULE_WIDTH = 3.0  # a rectangle this thin or thinner, and longer than wide, is a rule
JOIN = 3.0  # two rule pieces this close are one rule; a wall reaches a corner within this
SAME = 1.0  # two rules this close across their length are at one position
INSIDE = 1.0  # a word can go this far past the wall of its cell, as a glyph's side bearing can
PAGE_RULES = 4000  # a page with more rules than this, such as a chart, gives no ruled table
TABLE_WALLS = 200  # a table with more walls than this in one direction gives no cells
PAGE_TABLES = 50  # a page with more ruled tables than this, such as a form of boxes, gives none
PAIRS = 250_000  # more pairs of a horizontal and a vertical rule than this give no ruled table


@dataclass(frozen=True)
class Cell:
    """A cell of a ruled table. ``row`` counts the rows of its table from the top."""

    x0: float
    top: float
    x1: float
    bottom: float
    row: int


@dataclass(frozen=True)
class Grid:
    """The cells of one ruled table, and a lookup from a point to its cell."""

    box: tuple[float, float, float, float]
    cells: tuple[Cell, ...]
    bands: tuple[tuple[float, float], ...]  # the space between two levels, top to bottom
    walls: tuple[tuple[float, ...], ...]  # for each band, its vertical walls
    index: dict[tuple[int, int], int]  # (band, slot between two walls) to the cell
    starts: tuple[int, ...]  # for each row, the band where it starts

    def slots(self, row: int) -> list[int]:
        """The cells of a row left to right, also a tall cell from a row above."""
        band = self.starts[row]
        return [self.index[(band, slot)] for slot in range(len(self.walls[band]) - 1)]

    def cell_of(self, box: Box) -> int | None:
        """The cell that holds the box, or None. A box across a wall is in no cell."""
        y = (box.top + box.bottom) / 2
        band = bisect.bisect_right(self.bands, (y, float("inf"))) - 1
        if not 0 <= band < len(self.bands) or y > self.bands[band][1]:
            return None  # on a rule, or outside the table
        walls = self.walls[band]
        slot = bisect.bisect_right(walls, (box.x0 + box.x1) / 2) - 1
        if not 0 <= slot < len(walls) - 1:
            return None
        if box.x0 < walls[slot] - INSIDE or box.x1 > walls[slot + 1] + INSIDE:
            return None
        return self.index.get((band, slot))


def grids(rules: list[Rule]) -> list[Grid]:
    """The ruled tables of a page: each has two or more rows with two or more cells."""
    if len(rules) > PAGE_RULES:
        return []
    horizontal, vertical = _segments(rules)
    if len(horizontal) * len(vertical) > PAIRS:
        return []
    out = []
    for hs, vs in _components(horizontal, vertical):
        grid = _grid(hs, vs)
        if grid is not None and sum(len(grid.slots(r)) > 1 for r in range(len(grid.starts))) > 1:
            out.append(grid)
    return out if len(out) <= PAGE_TABLES else []


def _segments(rules: list[Rule]) -> tuple[list[Segment], list[Segment]]:
    """The horizontal and the vertical rules, with the pieces of one rule joined."""
    horizontal: list[Segment] = []
    vertical: list[Segment] = []
    for x0, top, x1, bottom in rules:
        width, height = x1 - x0, bottom - top
        if height <= RULE_WIDTH and width > height:
            horizontal.append(((top + bottom) / 2, x0, x1))
        elif width <= RULE_WIDTH and height > width:
            vertical.append(((x0 + x1) / 2, top, bottom))
    return _join(horizontal), _join(vertical)


def _join(segments: list[Segment]) -> list[Segment]:
    """Rules at one position (within SAME) whose pieces overlap or are JOIN apart become one."""
    out: list[Segment] = []
    segments = sorted(segments)
    start = 0
    for end in range(1, len(segments) + 1):
        if end < len(segments) and segments[end][0] - segments[end - 1][0] <= SAME:
            continue
        group = segments[start:end]
        position = group[0][0]
        pieces = sorted((lo, hi) for _, lo, hi in group)
        lo, hi = pieces[0]
        for a, b in pieces[1:]:
            if a <= hi + JOIN:
                hi = max(hi, b)
            else:
                out.append((position, lo, hi))
                lo, hi = a, b
        out.append((position, lo, hi))
        start = end
    return out


def _touch(h: Segment, v: Segment) -> bool:
    return h[1] - JOIN <= v[0] <= h[2] + JOIN and v[1] - JOIN <= h[0] <= v[2] + JOIN


def _components(
    horizontal: list[Segment], vertical: list[Segment]
) -> list[tuple[list[Segment], list[Segment]]]:
    """The groups of rules that touch each other, such as the rules of one table."""
    parent = list(range(len(horizontal) + len(vertical)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for (i, h), (j, v) in itertools.product(enumerate(horizontal), enumerate(vertical)):
        if _touch(h, v):
            parent[root(i)] = root(len(horizontal) + j)
    groups: dict[int, tuple[list[Segment], list[Segment]]] = {}
    for i, h in enumerate(horizontal):
        groups.setdefault(root(i), ([], []))[0].append(h)
    for j, v in enumerate(vertical):
        groups.setdefault(root(len(horizontal) + j), ([], []))[1].append(v)
    return [group for group in groups.values() if len(group[0]) >= 2 and len(group[1]) >= 2]


def _clusters(positions: list[float]) -> list[tuple[float, float]]:
    """The runs of positions where each is at most JOIN from the one before, as (first, last).

    The pieces of one thick rule, or two rules drawn close together, are one wall: no cell is
    so thin that it holds a line of text.
    """
    out: list[tuple[float, float]] = []
    for p in sorted(positions):
        if out and p - out[-1][1] <= JOIN:
            out[-1] = (out[-1][0], p)
        else:
            out.append((p, p))
    return out


def _spans(pieces: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The pieces of one wall joined where they overlap or are at most JOIN apart."""
    out: list[tuple[float, float]] = []
    for a, b in sorted(pieces):
        if out and a <= out[-1][1] + JOIN:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _ends(vertical: list[Segment]) -> list[Segment]:
    """A rule where the walls start or stop at one level, from the first wall to the last.

    Some tables draw no rule at the top or the bottom, such as under a shaded heading. If the
    first and the last wall of the table start or stop there, the table ends there too.
    """
    left = min(x for x, _, _ in vertical)
    right = max(x for x, _, _ in vertical)
    out: list[Segment] = []
    for ends in ([(a, x) for x, a, _ in vertical], [(b, x) for x, _, b in vertical]):
        for lo, hi in _clusters([y for y, _ in ends]):
            xs = [x for y, x in ends if lo <= y <= hi]
            if min(xs) <= left + JOIN and max(xs) >= right - JOIN:
                out.append(((lo + hi) / 2, min(xs), max(xs)))
    return out


def _covered(spans: list[tuple[float, float]], lo: float, hi: float) -> bool:
    return any(a <= lo + JOIN and b >= hi - JOIN for a, b in spans)


def _same_slot(above: list[tuple[float, float, int]], x0: float, x1: float) -> int:
    """The cell of the slot above with the same walls (within JOIN), or -1.

    The slots are in order from left to right, so a bisect finds the first candidate.
    """
    i = bisect.bisect_left(above, (x0 - JOIN,))
    while i < len(above) and above[i][0] <= x0 + JOIN:
        if abs(above[i][1] - x1) <= JOIN:
            return above[i][2]
        i += 1
    return -1


def _grid(horizontal: list[Segment], vertical: list[Segment]) -> Grid | None:
    """The cells of one group of rules, or None when the grid is irregular.

    The horizontal rules give the levels, and between two levels is a band. The vertical rules
    that run through the whole band are its walls. Two walls side by side make a slot. A slot
    starts a cell when a rule at the top level runs across it. Else it continues the cell of the
    same slot in the band above, as a tall cell does. A slot with no rule at the top and no cell
    above, or a cell with no rule at the bottom, makes the grid irregular. A band with fewer than
    two walls has no cells.
    """
    horizontal = horizontal + _ends(vertical)
    levels = _clusters([p for p, _, _ in horizontal])
    if len(levels) > TABLE_WALLS or len(_clusters([p for p, _, _ in vertical])) > TABLE_WALLS:
        return None
    rules = [_spans([(a, b) for p, a, b in horizontal if lo <= p <= hi]) for lo, hi in levels]
    cells: list[list[float]] = []  # x0, top, x1, bottom
    index: dict[tuple[int, int], int] = {}
    walls: list[tuple[float, ...]] = []
    above: list[tuple[float, float, int]] = []  # the slots of the band above, and their cells
    for band, ((_, top), (bottom, _)) in enumerate(itertools.pairwise(levels)):
        xs = [
            (lo + hi) / 2
            for lo, hi in _clusters(
                [x for x, a, b in vertical if a <= top + JOIN and b >= bottom - JOIN]
            )
        ]
        walls.append(tuple(xs))
        here: list[tuple[float, float, int]] = []
        for slot, (x0, x1) in enumerate(itertools.pairwise(xs)):
            if _covered(rules[band], x0, x1):
                cells.append([x0, top, x1, bottom])
                n = len(cells) - 1
            else:
                n = _same_slot(above, x0, x1)
                if n < 0:
                    return None
                cells[n][3] = bottom
            index[(band, slot)] = n
            here.append((x0, x1, n))
        going = {n for _, _, n in here}
        if any(n not in going and not _covered(rules[band], a, b) for a, b, n in above):
            return None  # a cell that does not go on must be closed at the bottom
        above = here
    if not cells or any(not _covered(rules[-1], a, b) for a, b, _ in above):
        return None
    tops = sorted({c[1] for c in cells})
    made = tuple(Cell(c[0], c[1], c[2], c[3], tops.index(c[1])) for c in cells)
    box = (
        min(c.x0 for c in made),
        min(c.top for c in made),
        max(c.x1 for c in made),
        max(c.bottom for c in made),
    )
    bands = tuple((top, bottom) for (_, top), (bottom, _) in itertools.pairwise(levels))
    starts = tuple(next(b for b, (t, _) in enumerate(bands) if t == top) for top in tops)
    return Grid(box, made, bands, tuple(walls), index, starts)
