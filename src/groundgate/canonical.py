"""Canonical JSON (RFC 8785), digests, and UTF-8 byte offsets (SPEC §2.2, §6)."""

from __future__ import annotations

import hashlib
import math
import unicodedata
from decimal import Decimal
from typing import Any

SPEC_VERSION = "0.4"
_SAFE_INT = 2**53 - 1
_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def is_nfc(text: str) -> bool:
    return unicodedata.is_normalized("NFC", text)


def _number(x: float) -> str:
    """ECMAScript Number.prototype.toString for a finite float."""
    if not math.isfinite(x):
        raise ValueError("NaN and infinities are not permitted in canonical JSON")
    if x == 0:
        return "0"
    if x < 0:
        return "-" + _number(-x)
    _, digits, exp = Decimal(repr(x)).as_tuple()
    assert isinstance(exp, int)
    ds = "".join(map(str, digits)).rstrip("0")
    exp += len(digits) - len(ds)
    k = len(ds)
    n = exp + k
    if k <= n <= 21:
        return ds + "0" * (n - k)
    if 0 < n <= 21:
        return ds[:n] + "." + ds[n:]
    if -6 < n <= 0:
        return "0." + "0" * -n + ds
    e = n - 1
    mantissa = ds if k == 1 else ds[0] + "." + ds[1:]
    return f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"


def _string(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif o < 0x20 or 0xD800 <= o <= 0xDFFF:
            out.append(f"\\u{o:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def jcs(obj: Any) -> str:
    """Serialise ``obj`` as RFC 8785 canonical JSON."""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, int):
        if abs(obj) > _SAFE_INT:
            raise ValueError(f"integer {obj} is outside the exactly representable range")
        return str(obj)
    if isinstance(obj, float):
        return _number(obj)
    if isinstance(obj, str):
        return _string(obj)
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(jcs(v) for v in obj) + "]"
    if isinstance(obj, dict):
        for k in obj:
            if not isinstance(k, str):
                raise TypeError("object keys must be strings")
        keys = sorted(obj, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(_string(k) + ":" + jcs(obj[k]) for k in keys) + "}"
    raise TypeError(f"{type(obj).__name__} is not JSON-serialisable")


def digest(kind: str, obj: Any) -> str:
    """Domain-separated SHA-256 of ``obj``'s canonical JSON (SPEC §6)."""
    prefix = f"groundgate/{SPEC_VERSION}:{kind}\0".encode("ascii")
    payload = jcs(obj).encode("utf-8", "surrogatepass")
    return "sha256:" + hashlib.sha256(prefix + payload).hexdigest()


class Offsets:
    """Converts between UTF-8 byte offsets and code-point offsets in one text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._byte_at: list[int] = [0]
        for ch in text:
            self._byte_at.append(self._byte_at[-1] + len(ch.encode("utf-8", "surrogatepass")))
        self._char_at = {b: i for i, b in enumerate(self._byte_at)}

    @property
    def byte_length(self) -> int:
        return self._byte_at[-1]

    def to_bytes(self, char_offset: int) -> int:
        return self._byte_at[char_offset]

    def to_char(self, byte_offset: int) -> int | None:
        """Code-point offset for a byte offset, or None if it is not on a character boundary."""
        return self._char_at.get(byte_offset)
