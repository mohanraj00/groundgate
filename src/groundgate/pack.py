"""The base vocabulary pack ``en`` (SPEC §4.7): the words that the text rules read."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Any

from .canonical import jcs

BASE_ID = "en"
BASE_VERSION = "1.0.0"


def pack_digest(pack: dict[str, Any]) -> str:
    """The digest of a pack object (SPEC §4.7). The prefix names the pack format, not the spec
    version, so one pack has one digest under each spec version."""
    prefix = f"groundgate-pack/1:{pack['type']}\0".encode("ascii")
    payload = jcs(pack).encode("utf-8", "surrogatepass")
    return "sha256:" + hashlib.sha256(prefix + payload).hexdigest()


def _load_base() -> dict[str, Any]:
    path = resources.files("groundgate") / "packs" / BASE_ID / f"{BASE_VERSION}.json"
    pack: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return pack


BASE = _load_base()
