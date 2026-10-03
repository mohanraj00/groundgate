"""Decide candidates with the installed groundgate, one packet per line. score.py runs it on the
released 0.1.0 wheel to score set 2 under spec 0.1, next to the 0.2 core that score.py imports:

    uv run --isolated --no-project --python 3.12 --with groundgate==0.1.0 python bench/decide.py

Each stdin line is {"text": ..., "schema": ..., "candidates": [...]}, and each stdout line is
[[outcome, [codes]], ...] in candidate order. The schema comes in as spec 0.2 writes it. Spec
0.1 has no keyed fields, so a keyed field loses `keys` and becomes `multiple`, the way a 0.1 user
would declare a field with one value per condition. The candidates are the same as for 0.2, `key`
included: spec 0.1 ignores keys it does not know.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import groundgate as gg


def as_01(schema: dict[str, Any]) -> dict[str, Any]:
    fields = {}
    for name, spec in schema["fields"].items():
        spec = dict(spec)
        if spec.pop("keys", None):
            spec["multiple"] = True
        fields[name] = spec
    return {**schema, "fields": fields}


def main() -> None:
    for line in sys.stdin:
        packet = json.loads(line)
        cands = packet["candidates"]
        receipt = gg.admit(packet["text"], as_01(packet["schema"]), cands)
        by_sha = {d.candidate_sha256: d for d in receipt.decisions}
        out = [by_sha[gg.digest("candidate", c)] for c in cands]
        print(json.dumps([[d.outcome, list(d.codes)] for d in out]), flush=True)


if __name__ == "__main__":
    main()
