"""The published release that verifies a receipt of an earlier spec version (SPEC §8.6, #710).

``verify`` checks a receipt only with the decisions of its own spec version. For a receipt of
another spec version it names the release here, and the user runs that release.
"""

from __future__ import annotations

# The last release on PyPI of each earlier spec version. The tags v0.12.0 and v0.13.0 also
# implement spec 0.11, and they are not on PyPI.
SPEC_RELEASES: dict[str, str] = {
    "0.1": "0.1.0",
    "0.2": "0.2.0",
    "0.3": "0.3.0",
    "0.4": "0.4.0",
    "0.5": "0.5.2",
    "0.6": "0.6.1",
    "0.7": "0.7.0",
    "0.8": "0.8.0",
    "0.9": "0.9.0",
    "0.10": "0.10.0",
    "0.11": "0.11.0",
    "0.12": "0.17.0",
}


def release_of(version: object) -> str | None:
    """The last published release that implements the spec version ``version``, or None when
    this release knows none. ``version`` is the ``groundgate`` member of a receipt, so it can
    be any JSON value."""
    return SPEC_RELEASES.get(version) if isinstance(version, str) else None
