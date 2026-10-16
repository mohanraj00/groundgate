"""Bounded isolated public-admission worker. No schema conversion or model capability."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_LIMIT = 16 * 1024 * 1024


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def main() -> None:
    raw = sys.stdin.buffer.read(_LIMIT + 1)
    if len(raw) > _LIMIT:
        raise ValueError("packet cap")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    request = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(request, dict) or set(request) != {"expected", "packet"}:
        raise ValueError("invalid worker envelope")
    import groundgate as gg
    from groundgate.canonical import SPEC_VERSION

    def encoded(value: Any) -> bytes:
        return gg.jcs(value).encode("utf-8")

    root = Path(gg.__file__).parent
    files = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".py", ".json"}:
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _LIMIT:
            raise ValueError("invalid package file")
        total += path.stat().st_size
        if total > 128 * 1024 * 1024 or len(files) >= 4096:
            raise ValueError("package cap")
        files[str(path.relative_to(root))] = _digest(path.read_bytes())
    code = _digest(encoded(files))
    expected, packet = request["expected"], request["packet"]
    if (gg.__version__, SPEC_VERSION, code) != (
        expected["package_version"],
        expected["spec_version"],
        expected["code_sha256"],
    ):
        raise ValueError("worker package fingerprint differs")
    if not isinstance(packet, dict) or set(packet) != {
        "text",
        "schema",
        "candidates",
        "policy",
        "document_id",
        "document_source",
        "references",
        "judgments",
    }:
        raise ValueError("invalid admission packet")
    # The supplied packet enters the public API unchanged; no key or offset adapter runs here.
    receipt = gg.admit(**packet).to_dict()
    output = {
        "package_version": gg.__version__,
        "spec_version": SPEC_VERSION,
        "code_sha256": code,
        "packet_sha256": _digest(encoded(packet)),
        "schema": gg.Schema.from_dict(packet["schema"]).to_dict(),
        "policy": gg.Policy.from_dict(packet["policy"]).to_dict(),
        "receipt": receipt,
    }
    body = encoded(output)
    if len(body) > _LIMIT:
        raise ValueError("receipt cap")
    sys.stdout.buffer.write(body)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never leak source, labels, package paths or exception text to coordinator logs.
        sys.stderr.write("diagnostic worker failed\n")
        raise SystemExit(1) from None
