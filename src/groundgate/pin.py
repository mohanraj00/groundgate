"""Source pins (SPEC §4.14, #616).

A pin records where the bytes of a document came from: the URL, the digest of the bytes, the
day of the retrieval, an edition marker and the origin. A pin changes no decision. The receipt
of a packet with a pin holds the pin and its digest.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from typing import Any

from .canonical import jcs
from .model import PacketError

FORMAT = 1
PREFIX = "groundgate-pin/1:"  # names the pin format, not the spec version
ORIGINS = ("fetched", "supplied")
MAX_URL = 2048  # characters of the url
MAX_TEXT = 200  # characters of the edition and of the label
MEMBERS = frozenset(
    {"groundgate_pin", "source_sha256", "url", "retrieved", "edition", "origin", "label"}
)
_REQUIRED = frozenset({"groundgate_pin", "source_sha256", "retrieved", "origin"})
_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


def _fail(msg: str) -> PacketError:
    return PacketError(f"pin: {msg}")


def _text(value: object, limit: int, what: str, check: str) -> str | None:
    """Null, or a string with a character that is not white space and at most ``limit``
    characters."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _fail(f"{what} must be null or a non-blank text of at most {limit} characters "
                    f"({check})")  # fmt: skip
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _fail(f"{what} is not valid Unicode text ({check})") from None
    return value


def check_pin(pin: object) -> dict[str, Any]:
    """Run the checks S1 to S5 on one pin (SPEC §4.14), and return the pin after defaults.
    Raises ``PacketError``."""
    if not isinstance(pin, dict):
        raise _fail("a pin must be a JSON object (S1)")
    unknown = set(pin) - MEMBERS
    if unknown:
        raise _fail(f"members that the format does not list: {sorted(map(repr, unknown))} (S1)")
    missing = _REQUIRED - set(pin)
    if missing:
        raise _fail(f"a pin must give {', '.join(sorted(missing))} (S1)")
    fmt = pin["groundgate_pin"]
    if isinstance(fmt, bool) or fmt != FORMAT or type(fmt) is not int:
        raise _fail(f"groundgate_pin must be {FORMAT} (S1)")
    source = pin["source_sha256"]
    if not isinstance(source, str) or not _SHA.match(source):
        raise _fail("source_sha256 must be sha256: and 64 lowercase hex digits (S2)")
    date = pin["retrieved"]
    try:
        ok = isinstance(date, str) and bool(_DATE.match(date))
        ok = ok and datetime.date.fromisoformat(date).isoformat() == date
    except ValueError:
        ok = False
    if not ok:
        raise _fail("retrieved must be a real day as YYYY-MM-DD (S3)")
    origin = pin["origin"]
    if not isinstance(origin, str) or origin not in ORIGINS:
        raise _fail(f"origin must be one of {', '.join(ORIGINS)} (S4)")
    url = _text(pin.get("url"), MAX_URL, "url", "S5")
    edition = _text(pin.get("edition"), MAX_TEXT, "edition", "S5")
    label = _text(pin.get("label"), MAX_TEXT, "label", "S5")
    if origin == "fetched" and url is None:
        raise _fail("a fetched pin must give the url (S5)")
    if origin == "fetched" and label is not None:
        raise _fail("only a supplied pin has a label (S5)")
    return {
        "groundgate_pin": FORMAT,
        "source_sha256": source,
        "url": url,
        "retrieved": date,
        "edition": edition,
        "origin": origin,
        "label": label,
    }


def pin_digest(pin: object) -> str:
    """The digest of a pin (SPEC §4.14). Raises ``PacketError`` for an invalid pin."""
    body = check_pin(pin)
    return "sha256:" + hashlib.sha256((PREFIX + jcs(body)).encode("utf-8")).hexdigest()


def pin_entry(pin: object, document_source: str | None = None) -> dict[str, Any]:
    """The ``pin`` member of the receipt (SPEC §5): the pin after defaults, without the format
    member, and its digest. With a document source, the pin ``url`` must be equal to it (S6)."""
    body = check_pin(pin)
    if document_source is not None and body["url"] != document_source:
        raise _fail("the url must be equal to the document source of the packet (S6)")
    out = {k: v for k, v in body.items() if k != "groundgate_pin"}
    out["sha256"] = "sha256:" + hashlib.sha256((PREFIX + jcs(body)).encode("utf-8")).hexdigest()
    return out


def source_digest(data: bytes) -> str:
    """The ``source_sha256`` of the bytes of a source file."""
    return "sha256:" + hashlib.sha256(data).hexdigest()
