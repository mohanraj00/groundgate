"""Run LangExtract over every benchmark document and cache the raw result.

    uv run --group langextract python bench/propose.py --provider agy \
        --model "Gemini 3.6 Flash (Medium)" [--buffer 4000]

Each document is extracted with its own field list and descriptions from bench/gold/<id>.json.
The prompt never sees the gold facts. Results go to bench/runs/<model>/<buffer>/<id>.json; an
existing file is skipped, so an interrupted run resumes where it stopped.

Providers:
  gemini      LangExtract's native Gemini provider (GEMINI_API_KEY)
  agy         the Antigravity CLI in print mode, plan mode, sandboxed, with a no-tools preamble
  claude-cli  the Claude Code CLI in print mode with every tool disabled
The CLI providers run a logged-in agent harness rather than a raw API call, so the harness's
own system prompt wraps ours. The benchmark reports which provider produced each run.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import langextract as lx
from langextract import data_lib
from langextract.core import base_model
from langextract.core import types as lx_types

HERE = Path(__file__).parent
HOME = str(Path.home())

KIND = {
    "fda": "the dosage sections of an FDA drug label",
    "ntsb": "an NTSB aviation accident report",
    "irs": "two pages of an IRS publication",
}

PROMPT = """Extract the fields listed below from {kind}.
Only extract a field when the text itself states its value. Do not compute, infer, or use
outside knowledge. If the text does not state a field, do not extract it.
extraction_class must be one of the field names below, exactly.
extraction_text must be copied verbatim from the text: the number as written, with its unit or
$ sign when they are adjacent.
attributes: "value" is the plain number without $, commas or units; "unit" is the unit code
given for the field.

Fields (name [unit code]: meaning):
{fields}
"""

EXAMPLES = {
    "fda": [
        lx.data.ExampleData(
            text=(
                "2 DOSAGE AND ADMINISTRATION\n\nHypertension: The recommended starting dose is "
                "20 mg once daily. The maximum recommended dose is 80 mg once daily.\n\n"
                "3 DOSAGE FORMS AND STRENGTHS\n\nTablets: 20 mg and 80 mg"
            ),
            extractions=[
                lx.data.Extraction(
                    "adult_starting_dose", "20 mg", attributes={"value": "20", "unit": "mg"}
                ),
                lx.data.Extraction(
                    "adult_max_daily_dose", "80 mg", attributes={"value": "80", "unit": "mg"}
                ),
                lx.data.Extraction(
                    "tablet_strengths", "20 mg", attributes={"value": "20", "unit": "mg"}
                ),
                lx.data.Extraction(
                    "tablet_strengths", "80 mg", attributes={"value": "80", "unit": "mg"}
                ),
            ],
        )
    ],
    "ntsb": [
        lx.data.ExampleData(
            text=(
                "Flight Time:\n\n1500 hours (Total, all aircraft), 200 hours (Total, this make "
                "and model)\n\nWind Speed/Gusts:\n\n9 knots / None"
            ),
            extractions=[
                lx.data.Extraction(
                    "pilot_total_hours", "1500 hours", attributes={"value": "1500", "unit": "hours"}
                ),
                lx.data.Extraction(
                    "pilot_make_model_hours",
                    "200 hours",
                    attributes={"value": "200", "unit": "hours"},
                ),
                lx.data.Extraction(
                    "wind_speed", "9 knots", attributes={"value": "9", "unit": "knots"}
                ),
            ],
        )
    ],
    "irs": [
        lx.data.ExampleData(
            text=(
                "For 2019, the annual filing fee is $4,500 ($5,200 for firms with more than 50 "
                "employees). The late fee applies if payment is more than $300 but less than $900."
            ),
            extractions=[
                lx.data.Extraction(
                    "filing_fee_2019", "$4,500", attributes={"value": "4500", "unit": "USD"}
                ),
                lx.data.Extraction(
                    "filing_fee_large_firm_2019",
                    "$5,200",
                    attributes={"value": "5200", "unit": "USD"},
                ),
                lx.data.Extraction(
                    "late_fee_threshold_start", "$300", attributes={"value": "300", "unit": "USD"}
                ),
                lx.data.Extraction(
                    "late_fee_threshold_end", "$900", attributes={"value": "900", "unit": "USD"}
                ),
            ],
        )
    ],
}

AGY_PREFIX = (
    "Answer directly from the text below. Do not use any tools, do not run commands, "
    "and do not read or write files. Output only the JSON requested.\n\n"
)


def _strip_fence(out: str) -> str:
    out = out.strip()
    if out.startswith("```"):
        out = out.partition("\n")[2].rsplit("```", 1)[0]
    return out


class CLIModel(base_model.BaseLanguageModel):
    """A LangExtract provider that shells out to a logged-in model CLI with tools disabled."""

    def __init__(self, provider: str, model: str, workers: int) -> None:
        super().__init__()
        self.provider, self.model, self.workers = provider, model, workers
        self.raw: list[dict[str, str]] = []  # every response, in chunk order

    def _one(self, prompt: str) -> str:
        if self.provider == "agy":
            cmd = ["agy", "--model", self.model, "--mode", "plan", "--sandbox",
                   "--print-timeout", "300s", "-p", AGY_PREFIX + prompt]  # fmt: skip
            stdin = None
        else:
            cmd = ["claude", "-p", "--model", self.model, "--tools", "",
                   "--no-session-persistence", "--output-format", "json"]  # fmt: skip
            stdin = prompt
        for attempt in range(3):
            proc = subprocess.run(
                cmd, input=stdin, capture_output=True, text=True, timeout=600, check=False
            )
            out = proc.stdout
            if proc.returncode == 0 and self.provider == "claude-cli":
                res = json.loads(out)
                out = "" if res.get("is_error") else res["result"]
            if proc.returncode == 0 and out.strip():
                return _strip_fence(out)
            time.sleep(10 * (attempt + 1))
        raise RuntimeError(f"{self.provider} failed 3 times: {proc.stderr[-300:]}")

    def infer(
        self, batch_prompts: Sequence[str], **kwargs: Any
    ) -> Iterator[Sequence[lx_types.ScoredOutput]]:
        with ThreadPoolExecutor(self.workers) as pool:
            for prompt, out in zip(batch_prompts, pool.map(self._one, batch_prompts), strict=True):
                digest = hashlib.sha256(prompt.encode()).hexdigest()
                # agents sometimes answer with a link to a file they wrote; keep home paths out
                self.raw.append({"prompt_sha256": digest, "output": out.replace(HOME, "~")})
                print(".", end="", flush=True)
                yield [lx_types.ScoredOutput(score=1.0, output=out)]


def prompt_for(gold: dict[str, Any]) -> str:
    lines = [
        f"- {name} [{spec['schema']['unit'] or 'none'}]: {spec['description']}"
        for name, spec in gold["fields"].items()
    ]
    return PROMPT.format(kind=KIND[gold["kind"]], fields="\n".join(lines))


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "agy", "claude-cli"], required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--buffer", type=int, default=1000, help="LangExtract max_char_buffer")
    ap.add_argument("--workers", type=int, default=3, help="parallel CLI calls")
    ap.add_argument("--only", nargs="*", help="document ids")
    args = ap.parse_args()

    out_dir = HERE / "runs" / safe(args.model) / str(args.buffer)
    out_dir.mkdir(parents=True, exist_ok=True)
    kw: dict[str, Any] = {}
    if args.provider == "gemini":
        kw["model_id"] = args.model
    else:
        kw["model"] = CLIModel(args.provider, args.model, args.workers)
    for path in sorted((HERE / "gold").glob("*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        doc_id = gold["doc"]
        target = out_dir / f"{doc_id}.json"
        if target.exists() or (args.only and doc_id not in args.only):
            continue
        text = (HERE / "docs" / f"{doc_id}.txt").read_text(encoding="utf-8")
        print(f"{doc_id} ", end="", flush=True)
        t0 = time.time()
        if isinstance(kw.get("model"), CLIModel):
            kw["model"].raw = []
        try:
            result = lx.extract(
                text_or_documents=text,
                prompt_description=prompt_for(gold),
                examples=EXAMPLES[gold["kind"]],
                max_char_buffer=args.buffer,
                fence_output=False,
                use_schema_constraints=False,
                temperature=0.0,
                show_progress=False,
                **kw,
            )
        except Exception as e:  # keep going; a rerun retries the failed document
            print(f" FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        result.document_id = doc_id
        record = {
            "provider": args.provider,
            "model": args.model,
            "langextract": importlib.metadata.version("langextract"),
            "max_char_buffer": args.buffer,
            "seconds": round(time.time() - t0),
            "document": data_lib.annotated_document_to_dict(result),
        }
        if isinstance(kw.get("model"), CLIModel):
            record["raw_outputs"] = kw["model"].raw
        target.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f" {len(result.extractions or [])} extractions, {record['seconds']}s")


if __name__ == "__main__":
    main()
