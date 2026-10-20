"""The groundgate-calibrate command: it tells the user to change, then runs groundgate calibrate."""

from __future__ import annotations

import sys

from groundgate.cli import main as groundgate

MOVED = (
    "groundgate-calibrate: this tool is now `groundgate calibrate` in groundgate 0.11; "
    "use that command and uninstall groundgate-calibrate"
)


def main(argv: list[str] | None = None) -> int:
    print(MOVED, file=sys.stderr)
    return groundgate(["calibrate", *(sys.argv[1:] if argv is None else argv)])
