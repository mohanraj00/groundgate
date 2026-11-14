"""The completeness of a reading (SPEC §4.16, #615).

A reader says if its text is all of the source, or which pages gave no text. The gate checks
the form of the statement, keeps it in the receipt, and gives a quote of the document that does
not occur the code ``SOURCE_NOT_READ`` when the reading is not complete. A passage of such a
reading gets the flag ``PASSAGE_NOT_READ`` when a page that was not read can be in its section
(SPEC §4.17, #672).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .model import PacketError
from .text import normalize_ws

STATUSES = ("complete", "partial", "no_text")
REASONS = ("ocr_off", "ocr_no_text", "no_text_layer")
MAX_PAGE = 1_000_000


def status_of(text: str, missing: Sequence[object]) -> str:
    """The status that the document and the missing pages give (SPEC §4.16, rules 1 to 3)."""
    if not normalize_ws(text):
        return "no_text"
    return "partial" if missing else "complete"


def completeness_of(text: str, missing: Iterable[tuple[int, str]] = ()) -> dict[str, Any]:
    """The completeness of a reading with ``text``, from (page, reason) pairs."""
    pages = [{"page": p, "reason": r} for p, r in sorted(dict(missing).items())]
    return {"status": status_of(text, pages), "missing": pages}


def check_completeness(raw: object, text: str) -> dict[str, Any]:
    """The completeness of the packet (SPEC §4.16), or ``PacketError``."""
    if not isinstance(raw, Mapping) or set(raw) != {"status", "missing"}:
        raise PacketError("completeness must be an object with status and missing")
    status, missing = raw["status"], raw["missing"]
    if not isinstance(status, str) or status not in STATUSES:
        raise PacketError(f"completeness status must be one of {', '.join(STATUSES)}")
    if isinstance(missing, (str, bytes)) or not isinstance(missing, Sequence):
        raise PacketError("completeness missing must be a list")
    if len(missing) > MAX_PAGE:
        raise PacketError(f"completeness missing has more than {MAX_PAGE} entries")
    out: list[dict[str, Any]] = []
    last = 0
    for n, entry in enumerate(missing):
        where = f"completeness missing {n}"
        if not isinstance(entry, Mapping) or set(entry) != {"page", "reason"}:
            raise PacketError(f"{where} must be an object with page and reason")
        page, reason = entry["page"], entry["reason"]
        if type(page) is not int or not last < page <= MAX_PAGE:
            raise PacketError(
                f"{where} must have a page from 1 to {MAX_PAGE}, higher than the page before it"
            )
        if not isinstance(reason, str) or reason not in REASONS:
            raise PacketError(f"{where} must have a reason that is one of {', '.join(REASONS)}")
        last = page
        out.append({"page": page, "reason": reason})
    want = status_of(text, out)
    if status != want:
        raise PacketError(
            f"completeness status is {status}, and the document and the missing pages give {want}"
        )
    return {"status": status, "missing": out}
