"""Time work in tests with little noise from a shared CI runner (#467).

A ratio of two wall times is noisy on a shared runner: a pause of the runner or a garbage
collection in one run can make the ratio two times too large. These helpers stop the garbage
collector, keep the best of some runs, run the two sizes one after the other, and try again
before they fail. Quadratic work at four times the size takes about 16 times as long, so it
fails each try against a bound of 8.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

REPEATS = 3
ATTEMPTS = 3


@contextmanager
def _no_gc() -> Iterator[None]:
    was = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        yield
    finally:
        if was:
            gc.enable()


def _seconds(run: Callable[[], object]) -> float:
    began = time.perf_counter()
    run()
    return time.perf_counter() - began


def best_seconds(run: Callable[[], object]) -> float:
    """The best time of REPEATS runs, with no garbage collection."""
    with _no_gc():
        return min(_seconds(run) for _ in range(REPEATS))


def assert_linear(
    prepare: Callable[[int], Callable[[], object]], small: int, large: int, bound: float = 8
) -> None:
    """Assert that the run for ``large`` takes less than ``bound`` times the run for ``small``.

    ``prepare(n)`` makes the input of size ``n`` and gives the run to time. The two runs
    alternate, so a slow period of the runner touches both. If one try fails, the next try
    measures again. The assertion fails only when all ATTEMPTS tries fail.
    """
    runs = prepare(small), prepare(large)
    ratios = []
    for _ in range(ATTEMPTS):
        best = [float("inf"), float("inf")]
        with _no_gc():
            for _ in range(REPEATS):
                for k, run in enumerate(runs):
                    best[k] = min(best[k], _seconds(run))
        if best[1] < bound * best[0]:
            return
        ratios.append(round(best[1] / best[0], 1))
    raise AssertionError(f"size {large} took {ratios} times the time of size {small}")
