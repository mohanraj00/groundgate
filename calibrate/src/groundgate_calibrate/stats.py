"""The statistics of hybrid design §9: a one-sided 95% upper bound, and the threshold that it
picks for a ceiling."""

from __future__ import annotations

from collections.abc import Callable, Iterable

CEILINGS = (0.05, 0.1, 0.2)


def upper_95(k: int, n: int) -> float:
    """The one-sided 95% upper bound of a binomial rate, k of n (Clopper-Pearson), by bisection
    on the binomial CDF. With nothing to count, the bound is 1."""
    if n == 0 or k >= n:
        return 1.0

    def cdf(p: float) -> float:
        total, term = 0.0, (1 - p) ** n
        for i in range(k + 1):
            total += term
            term *= (n - i) / (i + 1) * p / (1 - p) if p < 1 else 0
        return total

    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > 0.05 else (lo, mid)
    return round(hi, 4)


def needed(ceiling: float) -> int:
    """The fewest items with no failure whose upper bound is below the ceiling."""
    n = 1
    while upper_95(0, n) >= ceiling:
        n += 1
    return n


def pick(
    thresholds: Iterable[float], bound: Callable[[float], float], ceiling: float, best: str
) -> float | None:
    """The threshold whose bound is below the ceiling, the lowest or the highest of them by
    best, or None when there is no such threshold."""
    ok = [t for t in thresholds if bound(t) < ceiling]
    if not ok:
        return None
    return min(ok) if best == "lowest" else max(ok)
