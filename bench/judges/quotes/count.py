"""How often spec 0.3 flags NON_VERBATIM_EVIDENCE in the recorded extraction runs of the v0.1
set and set 2, and how each flagged quote differs from its span. This decides whether the quote
question of #67 has enough natural flags to label and ask a model.

    uv run --group langextract python bench/judges/quotes/count.py           # counts.json
    uv run --group langextract python bench/judges/quotes/count.py --check

It prints no document text and asks no model.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
BENCH = HERE.parent.parent
sys.path.insert(0, str(BENCH))

import score  # noqa: E402  (bench/score.py)

import groundgate as gg  # noqa: E402
from groundgate.text import normalize_ws, verbatim_equal  # noqa: E402

SETS = {"v0.1": BENCH, "set 2": BENCH / "set2"}


def difference(quote: str, span: str) -> str:
    """How the quote differs from the span text, after the §4.4 normalisation."""
    q, s = normalize_ws(quote), normalize_ws(span)
    if q.lower() == s.lower():
        return "case only"
    if s in q:
        return "the quote adds text"
    if q in s:
        return "the quote drops text"
    return "the quote changes text"


def count(path: Path) -> dict[str, Any]:
    score.SET = path
    golds = score.load_gold(False)
    score.SET2 = any(g.groups for g in golds.values())
    runs, _ = score.load_runs(golds)
    candidates, flags = 0, 0
    pairs: dict[tuple[str, int, int, str], str] = {}
    kinds: Counter[str] = Counter()
    for docs in runs.values():
        for doc, cands in docs.items():
            g = golds[doc]
            if g.control:
                continue
            by = {d.candidate_sha256: d for d in gg.admit(g.text, g.schema, cands).decisions}
            raw = g.text.encode()
            for c in cands:
                candidates += 1
                d = by[gg.digest("candidate", c)]
                if "NON_VERBATIM_EVIDENCE" not in d.codes or d.evidence is None:
                    continue
                flags += 1
                kinds[g.kind] += 1
                a, b = d.evidence
                span = raw[a:b].decode()
                quote = c["evidence"]["text"]
                assert not verbatim_equal(quote, span)
                pairs[(doc, a, b, quote)] = difference(quote, span)
    return {
        "candidates": candidates,
        "flags": flags,
        "flags_by_kind": dict(sorted(kinds.items())),
        "pairs": len(pairs),
        "pairs_by_difference": dict(sorted(Counter(pairs.values()).items())),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if counts.json differs")
    args = ap.parse_args()
    out = json.dumps({name: count(path) for name, path in SETS.items()}, indent=2) + "\n"
    target = HERE / "counts.json"
    if args.check:
        if target.read_text() != out:
            raise SystemExit("counts.json differs; run count.py")
        print("counts.json matches")
        return
    target.write_text(out)
    print(out, end="")


if __name__ == "__main__":
    main()
