"""List the sentences of the targeted IRS and Federal Register documents that match their groups.

    uv run python bench/set2/gold/matches.py [doc_id ...]

SELECTION.md: a targeted document gets one field for every amount in a matched sentence (for
"from X to Y", both X and Y). This prints each matched sentence with its group, so a draft can
cover every amount in it. The patterns are pick.py's, and sentences end where groundgate's do.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
SET = HERE.parent
sys.path.insert(0, str(SET.parent))

from pick import PATTERNS  # noqa: E402

from groundgate.text import sentence  # noqa: E402

TARGETED = set(PATTERNS)


def matched_sentences(text: str, groups: list[str]) -> list[tuple[int, int, list[str]]]:
    """(start, end, groups) of every sentence holding a match of one of ``groups``."""
    found: dict[tuple[int, int], list[str]] = {}
    for group in groups:
        for m in PATTERNS[group].finditer(text):
            span = sentence(text, m.start())
            if group not in found.setdefault(span, []):
                found[span].append(group)
    return [(a, b, g) for (a, b), g in sorted(found.items())]


def main() -> None:
    sources = json.loads((SET / "sources.json").read_text(encoding="utf-8"))["sources"]
    wanted = set(sys.argv[1:])
    for src in sources:
        groups = [g for g in src["groups"] if g in TARGETED]
        if not groups or (wanted and src["id"] not in wanted):
            continue
        text = (SET / "docs" / f"{src['id']}.txt").read_text(encoding="utf-8")
        print(f"== {src['id']} ({', '.join(groups)})")
        for a, b, g in matched_sentences(text, groups):
            print(f"[{', '.join(g)}] " + " ".join(text[a:b].split()))
        print()


if __name__ == "__main__":
    main()
