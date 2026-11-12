"""Build conformance/store/vectors.json, the store contract vectors.

The vectors are written by hand in ``groundgate.store.contract.vectors``. This script gives that
function its own key and JCS functions from the standard library, so the keys and the log heads
in the JSON do not come from the store code. Run it after you edit a vector, and commit the
output:

    uv run python conformance/store/build.py

``tests/test_store_contract.py`` fails if the committed JSON differs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from groundgate.store import contract

HERE = Path(__file__).parent


def key_of(kind: str, data: bytes) -> str:
    """docs/design/store.md §4: SHA-256 of the prefix, the kind, a NUL byte and the data."""
    digest = hashlib.sha256(b"groundgate-object/1:" + kind.encode() + b"\0" + data)
    return "sha256:" + digest.hexdigest()


def jcs_of(value: Any) -> str:
    """RFC 8785 for the values of the vectors: objects, ASCII strings, small integers and null.
    Sorted members with no spaces give the same text for these values."""

    def plain(v: Any) -> None:
        if isinstance(v, dict):
            for m, x in v.items():
                plain(m)
                plain(x)
        elif isinstance(v, str):
            if not v.isascii():
                raise ValueError(f"{v!r} is not ASCII")
        elif not (v is None or (type(v) is int and abs(v) < 2**53)):
            raise ValueError(f"{v!r} is not a value that this JCS takes")

    plain(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> None:
    text = contract.dump(contract.vectors(key_of, jcs_of))
    (HERE / "vectors.json").write_text(text, encoding="ascii")


if __name__ == "__main__":
    main()
