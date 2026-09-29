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
  codex       the Codex CLI: `codex exec` in an empty directory, read-only sandbox, user config,
              rules and AGENTS.md ignored, no session saved; a reply that used any tool is
              discarded and retried
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
import tempfile
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
outside knowledge. If the text does not state a field, leave it out.
Answer in exactly the JSON layout the examples use. Each extraction is keyed by one of the field
names below, and its text is copied verbatim from the source: the number as written, with its
unit or $ sign when they are adjacent. The matching "<field name>_attributes" object holds
"value", the plain number without $, commas or units, and "unit", the unit code given for the
field. Leave "unit" out for a field that has no unit code.

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
                "Age:\n\n38,Female\n\nFlight Time:\n\n1500 hours (Total, all aircraft), 200 "
                "hours (Total, this make and model)\n\nWind Speed/Gusts:\n\n9 knots / None"
            ),
            extractions=[
                lx.data.Extraction("pilot_age", "38", attributes={"value": "38"}),
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

    def __init__(self, provider: str, model: str, workers: int, effort: str | None) -> None:
        super().__init__()
        self.provider, self.model, self.workers, self.effort = provider, model, workers, effort
        self.raw: list[dict[str, Any]] = []  # every response, in chunk order
        self.empty = tempfile.mkdtemp(prefix="groundgate-bench-")  # codex's working root

    def command(self) -> list[str]:
        """The codex command line; the prompt goes on stdin."""
        cmd = [
            "codex",
            "exec",
            "-m",
            self.model,
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "-s",
            "read-only",
            "-C",
            self.empty,
            "-c",
            "project_doc_max_bytes=0",
        ]
        if self.effort:
            cmd += ["-c", f'model_reasoning_effort="{self.effort}"']
        return [*cmd, "-"]

    def _codex(self, prompt: str) -> tuple[str, int]:
        """(reply, tool items seen). Raises on a failed call."""
        proc = subprocess.run(
            self.command(),
            input=AGY_PREFIX + prompt,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        reply, tools, error = "", 0, proc.stderr[-300:]
        for line in proc.stdout.splitlines():
            event = json.loads(line) if line.startswith("{") else {}
            item = event.get("item") or {}
            if event.get("type") == "turn.failed":
                error = str(event.get("error", {}).get("message", ""))[-300:]
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                reply = item.get("text", "")
            elif event.get("type") == "item.completed" and item.get("type") != "reasoning":
                tools += 1
        if proc.returncode != 0:
            raise RuntimeError(error)
        return reply, tools

    def _one(self, prompt: str) -> tuple[str, dict[str, Any]]:
        notes: dict[str, Any] = {}
        if self.provider == "codex":
            for attempt in range(3):
                try:
                    out, tools = self._codex(prompt)
                except (RuntimeError, subprocess.TimeoutExpired) as e:
                    notes.setdefault("failed_calls", []).append(str(e)[-200:])
                    time.sleep(10 * (attempt + 1))
                    continue
                if tools:  # the answer may lean on something other than the prompt
                    notes["discarded_for_tool_use"] = notes.get("discarded_for_tool_use", 0) + 1
                    continue
                if out.strip():
                    return _strip_fence(out), notes
            raise RuntimeError(f"codex failed 3 times: {notes}")
        if self.provider == "agy":
            cmd = [
                "agy",
                "--model",
                self.model,
                "--mode",
                "plan",
                "--sandbox",
                "--print-timeout",
                "300s",
                "-p",
                AGY_PREFIX + prompt,
            ]
            stdin = None
        else:
            cmd = [
                "claude",
                "-p",
                "--model",
                self.model,
                "--tools",
                "",
                "--no-session-persistence",
                "--output-format",
                "json",
            ]
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
                return _strip_fence(out), notes
            time.sleep(10 * (attempt + 1))
        raise RuntimeError(f"{self.provider} failed 3 times: {proc.stderr[-300:]}")

    def infer(
        self, batch_prompts: Sequence[str], **kwargs: Any
    ) -> Iterator[Sequence[lx_types.ScoredOutput]]:
        with ThreadPoolExecutor(self.workers) as pool:
            results = pool.map(self._one, batch_prompts)
            for prompt, (out, notes) in zip(batch_prompts, results, strict=True):
                digest = hashlib.sha256(prompt.encode()).hexdigest()
                # agents sometimes answer with a link to a file they wrote; keep home paths out
                entry = {"prompt_sha256": digest, "output": out.replace(HOME, "~")}
                self.raw.append(entry | ({"harness": notes} if notes else {}))
                print(".", end="", flush=True)
                yield [lx_types.ScoredOutput(score=1.0, output=out)]


def prompt_for(gold: dict[str, Any]) -> str:
    lines = [
        f"- {name} [{unit}]: {spec['description']}"
        if (unit := spec["schema"]["unit"])
        else f"- {name}: {spec['description']}"
        for name, spec in gold["fields"].items()
    ]
    return PROMPT.format(kind=KIND[gold["kind"]], fields="\n".join(lines))


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "agy", "claude-cli", "codex"], required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--buffer", type=int, default=1000, help="LangExtract max_char_buffer")
    ap.add_argument("--workers", type=int, default=3, help="parallel CLI calls")
    ap.add_argument("--only", nargs="*", help="document ids")
    ap.add_argument("--effort", help="codex reasoning effort (low, medium, high)")
    ap.add_argument("--label", help='name in the results, e.g. "GPT-6 Luna (Medium)"')
    args = ap.parse_args()
    label = args.label or args.model

    out_dir = HERE / "runs" / safe(label) / str(args.buffer)
    out_dir.mkdir(parents=True, exist_ok=True)
    kw: dict[str, Any] = {}
    if args.provider == "gemini":
        kw["model_id"] = args.model
    else:
        kw["model"] = CLIModel(args.provider, args.model, args.workers, args.effort)
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
            if "not supported" in str(e):
                raise SystemExit(4) from None  # this account cannot use the model
            if any(w in str(e) for w in ("RESOURCE_EXHAUSTED", "quota", "usage limit", "429")):
                raise SystemExit(3) from None  # out of quota: stop, a later pass resumes
            continue
        result.document_id = doc_id
        record = {
            "provider": args.provider,
            "model": label,
            "model_id": args.model,
            "effort": args.effort,
            "langextract": importlib.metadata.version("langextract"),
            "max_char_buffer": args.buffer,
            "seconds": round(time.time() - t0),
            "document": data_lib.annotated_document_to_dict(result),
        }
        if isinstance(kw.get("model"), CLIModel):
            if args.provider == "codex":
                cmd = kw["model"].command()
                record["harness"] = ["<empty dir>" if a.startswith("/") else a for a in cmd]
            record["raw_outputs"] = kw["model"].raw
        target.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f" {len(result.extractions or [])} extractions, {record['seconds']}s")


if __name__ == "__main__":
    main()
