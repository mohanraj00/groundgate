"""The two runs on bench/afr (#229), as bench/sec3/run.py runs them: the same models, CLI flags,
isolation, default effort, prompt from docs/guide.md and records. Each CLI gets
gg.extractor_schema(schema) as it is, with no "$schema" member (#197).

    uv run python bench/afr/run.py --provider claude-cli --model claude-haiku-5-5
    uv run python bench/afr/run.py --provider codex --model gpt-6-luna

Replies go to runs/<model>/<id>.json. An existing file is skipped, so a stopped run resumes.
With --tabs, the runs read tabs/docs, the text since #230, and go to tabs/runs/<model>/ (#230).
With --tabs and --old-text, they read docs/, the 0.7 text, and go to tabs/runs-0.7-text/<model>/:
a model with no run of #229 gets both texts. With --effort, the CLI gets that reasoning effort,
and the folder is <model>-<effort>.

    uv run python bench/afr/run.py --tabs --provider claude-cli --model claude-sonnet-5-5 \
        --effort high [--old-text]
    uv run python bench/afr/run.py --tabs --provider codex --model gpt-6.1-sol \
        --effort high [--old-text]
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

    def __init__(
        self, provider: str, model: str, schema: dict[str, Any], effort: str = "default"
    ) -> None:
        super().__init__(provider, model, schema, effort)
        self.schema = schema
        self.schema_file.write_text(json.dumps(schema), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", choices=["claude-cli", "codex"], required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tabs", action="store_true", help="read tabs/docs, write tabs/runs (#230)")
    ap.add_argument("--old-text", action="store_true", help="with --tabs: read docs/ (#230)")
    ap.add_argument("--effort", default="default", choices=["default", "high"])
    args = ap.parse_args()
    if args.old_text and not args.tabs:
        ap.error("--old-text needs --tabs")
    schema = gg.extractor_schema(json.loads((HERE / "schema.json").read_text()))
    runner = Runner(args.provider, args.model, schema, args.effort)
    root = HERE / "tabs" if args.tabs else HERE
    name = args.model if args.effort == "default" else f"{args.model}-{args.effort}"
    folder = root / ("runs-0.7-text" if args.old_text else "runs") / name
    folder.mkdir(parents=True, exist_ok=True)
    docs = HERE / "docs" if args.old_text else root / "docs"
    todo = [d for d in sorted(docs.glob("*.txt")) if not (folder / f"{d.stem}.json").exists()]
    with ThreadPoolExecutor(args.workers) as pool:
        for line in pool.map(lambda d: runner.one(d, folder / f"{d.stem}.json"), todo):
            print(line, flush=True)


if __name__ == "__main__":
    main()
