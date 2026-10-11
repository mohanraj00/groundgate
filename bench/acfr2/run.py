"""The two runs on bench/acfr2 (#249, #250), as bench/afr/run.py runs them: the same models, CLI
flags, isolation, default effort, prompt from docs/guide.md and records. Each CLI gets
gg.extractor_schema(schema) as it is, with no "$schema" member (#197).

    uv run python bench/acfr2/run.py --provider claude-cli --model claude-haiku-5-5
    uv run python bench/acfr2/run.py --provider codex --model gpt-6-luna

Replies go to runs/<model>/<id>.json. An existing file is skipped, so a stopped run resumes.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import groundgate as gg

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "sec3"))
import run as sec3_run  # noqa: E402  (bench/sec3/run.py)


class Runner(sec3_run.Runner):
    """The runner of bench/sec3, with the output schema as gg.extractor_schema gives it."""

    def __init__(self, provider: str, model: str, schema: dict[str, Any]) -> None:
        super().__init__(provider, model, schema)
        self.schema = schema
        self.schema_file.write_text(json.dumps(schema), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", choices=["claude-cli", "codex"], required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    schema = gg.extractor_schema(json.loads((HERE / "schema.json").read_text()))
    runner = Runner(args.provider, args.model, schema)
    folder = HERE / "runs" / args.model
    folder.mkdir(parents=True, exist_ok=True)
    todo = [
        d for d in sorted((HERE / "docs").glob("*.txt")) if not (folder / f"{d.stem}.json").exists()
    ]
    with ThreadPoolExecutor(args.workers) as pool:
        for line in pool.map(lambda d: runner.one(d, folder / f"{d.stem}.json"), todo):
            print(line, flush=True)


if __name__ == "__main__":
    main()
