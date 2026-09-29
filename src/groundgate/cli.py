"""Command line: ``groundgate admit`` and ``groundgate verify``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .admit import admit, verify
from .model import PacketError


def _json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="groundgate", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    a = sub.add_parser("admit", help="decide candidates and write a receipt")
    a.add_argument("document", help="UTF-8 NFC text file")
    a.add_argument("schema", help="schema JSON")
    a.add_argument("candidates", help="JSON array of candidates")
    a.add_argument("--policy", help="policy JSON")
    a.add_argument("--document-id")
    a.add_argument("-o", "--output", help="write the receipt here instead of stdout")

    v = sub.add_parser("verify", help="re-derive a receipt and compare")
    v.add_argument("receipt")
    v.add_argument("document")
    v.add_argument("schema")
    v.add_argument("candidates")
    v.add_argument("--policy", help="policy JSON")

    args = ap.parse_args(argv)
    try:
        policy = _json(args.policy) if args.policy else None
        if args.command == "admit":
            receipt = admit(
                _text(args.document),
                _json(args.schema),
                _json(args.candidates),
                policy,
                document_id=args.document_id,
            )
            out = json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False) + "\n"
            if args.output:
                Path(args.output).write_text(out, encoding="utf-8")
            else:
                sys.stdout.write(out)
            return 0
        result = verify(
            _json(args.receipt),
            _text(args.document),
            _json(args.schema),
            _json(args.candidates),
            policy,
        )
    except (PacketError, OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"groundgate: {e}", file=sys.stderr)
        return 2
    if result.ok:
        print("receipt verified")
        return 0
    for problem in result.problems:
        print(f"mismatch: {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
