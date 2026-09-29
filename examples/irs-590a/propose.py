"""Run LangExtract over document.txt and cache the result in runs/<model>.json.

This is the only step that calls a model. Everything after it (admit, verify, report) reads the
cache, so the example reproduces without API keys.

    pip install langextract
    python propose.py --provider gemini --model gemini-2.5-flash      # needs GEMINI_API_KEY
    python propose.py --provider agy --model "Gemini 3.6 Flash (Medium)"
    python propose.py --provider claude-cli --model claude-haiku-4-5

`agy` (Antigravity) and `claude-cli` run the model through a locally logged-in CLI with tools
disabled, for people without an API key. They wrap the prompt in their own system prompt, so
treat those runs as close to, not identical to, a raw API call.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import subprocess
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import langextract as lx
from langextract import data_lib
from langextract.core import base_model
from langextract.core import types as lx_types

HERE = Path(__file__).parent

PROMPT = """Extract the IRA dollar amounts listed below from this IRS publication.
Only extract a field when the text states its value. Do not compute or infer values.
extraction_class must be one of the field names below, exactly.
extraction_text must be copied verbatim from the text: the amount as written, with its $ sign.
attributes: "value" is the plain number without $ or commas; "unit" is "USD".

Fields ("start" is where a phase-out begins, "end" is where it is complete):
{fields}
"""

DESCRIBE = {
    "ira_limit": "IRA contribution limit",
    "ira_limit_age_50": "IRA contribution limit for individuals age 50 or older",
    "traditional_phaseout_joint": "traditional IRA deduction phase-out, married filing jointly, "
    "when covered by a retirement plan at work",
    "traditional_phaseout_single": "traditional IRA deduction phase-out, single or head of "
    "household, when covered by a retirement plan at work",
    "spousal_phaseout": "deduction phase-out when your spouse is covered by a plan at work and "
    "you are not",
    "roth_phaseout_joint": "Roth IRA contribution phase-out, married filing jointly",
    "roth_phaseout_single": "Roth IRA contribution phase-out, single or head of household",
    "trump_account_pilot_contribution": "Trump account pilot program contribution",
}

EXAMPLES = [
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
                "filing_fee_large_firm_2019", "$5,200", attributes={"value": "5200", "unit": "USD"}
            ),
            lx.data.Extraction(
                "late_fee_threshold_start", "$300", attributes={"value": "300", "unit": "USD"}
            ),
            lx.data.Extraction(
                "late_fee_threshold_end", "$900", attributes={"value": "900", "unit": "USD"}
            ),
        ],
    )
]


def describe(field: str) -> str:
    m = re.fullmatch(r"(.+?)_(\d{4})(?:_(start|end))?", field)
    if not m:
        return DESCRIBE[field]
    base, year, edge = m.groups()
    return f"{DESCRIBE[base]}, {year}" + (f", {edge}" if edge else "")


def _strip_fence(out: str) -> str:
    out = out.strip()
    if out.startswith("```"):
        out = out.partition("\n")[2].rsplit("```", 1)[0]
    return out


class CLIModel(base_model.BaseLanguageModel):
    """A LangExtract provider that shells out to a logged-in model CLI with tools disabled."""

    def __init__(self, command: list[str], prompt_prefix: str = "") -> None:
        super().__init__()
        self.command = command
        self.prefix = prompt_prefix

    def infer(
        self, batch_prompts: Sequence[str], **kwargs: Any
    ) -> Iterator[Sequence[lx_types.ScoredOutput]]:
        for prompt in batch_prompts:
            proc = subprocess.run(
                [*self.command, self.prefix + prompt] if self.prefix else self.command,
                input=None if self.prefix else prompt,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"{self.command[0]} failed: {proc.stderr[-500:]}")
            out = proc.stdout
            if self.command[0] == "claude":
                res = json.loads(out)
                if res.get("is_error"):
                    raise RuntimeError(f"claude error: {res.get('result')}")
                out = res["result"]
            print(".", end="", flush=True)
            yield [lx_types.ScoredOutput(score=1.0, output=_strip_fence(out))]


AGY_PREFIX = (
    "Answer directly from the text below. Do not use any tools, do not run commands, "
    "and do not read or write files. Output only the JSON requested.\n\n"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "agy", "claude-cli"], required=True)
    ap.add_argument("--model", required=True)
    args = ap.parse_args()

    fields = json.loads((HERE / "schema.json").read_text())["fields"]
    prompt = PROMPT.format(fields="\n".join(f"- {f}: {describe(f)}" for f in fields))
    kw: dict[str, Any] = {}
    if args.provider == "agy":
        cmd = ["agy", "--model", args.model, "--mode", "plan", "--sandbox"]
        kw["model"] = CLIModel([*cmd, "--print-timeout", "300s", "-p"], AGY_PREFIX)
    elif args.provider == "claude-cli":
        cmd = ["claude", "-p", "--model", args.model, "--tools", "", "--no-session-persistence"]
        kw["model"] = CLIModel([*cmd, "--output-format", "json"])
    else:
        kw["model_id"] = args.model

    text = (HERE / "document.txt").read_text(encoding="utf-8")
    result = lx.extract(
        text_or_documents=text,
        prompt_description=prompt,
        examples=EXAMPLES,
        fence_output=False,
        use_schema_constraints=False,
        temperature=0.0,
        show_progress=False,
        **kw,
    )
    result.document_id = "irs-p590a-2025-pages-1-2"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", args.model).strip("_")
    out = HERE / "runs" / f"{name}.json"
    out.parent.mkdir(exist_ok=True)
    version = importlib.metadata.version("langextract")
    record = {"provider": args.provider, "model": args.model, "langextract": version}
    record["document"] = data_lib.annotated_document_to_dict(result)
    out.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{len(result.extractions or [])} extractions -> {out.relative_to(HERE)}")


if __name__ == "__main__":
    main()
