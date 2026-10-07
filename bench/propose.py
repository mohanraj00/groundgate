"""Run LangExtract over every benchmark document and cache the raw result.

    uv run --group langextract python bench/propose.py --provider agy \
        --model "Gemini 3.6 Flash (Medium)" [--buffer 4000]

Each document is extracted with its own field list and descriptions from bench/gold/<id>.json.
The prompt never sees the gold facts. A keyed field (set 2) lists its keys, and the prompt asks for
the key of each value; documents without keyed fields get the v0.1 prompt byte for byte. With
--key-span (#130), a keyed prompt also asks for "key_text", the words before the value that name
its key, and the keyed examples carry it; without the flag the prompt is unchanged. Results
go to bench/runs/<model>/<buffer>/<id>.json; an existing file is skipped, so an interrupted run
resumes where it stopped.

Providers:
  gemini      LangExtract's native Gemini provider (GEMINI_API_KEY)
  agy         the Antigravity CLI in print mode, plan mode, sandboxed, with a no-tools preamble
  claude-cli  the Claude Code CLI in print mode, run in an empty directory with no tools, MCP
              servers, skills or setting sources (so no CLAUDE.md, hooks or memory), no saved
              session, and a one-line system prompt in place of the default; a reply from
              another model, or with more than one turn, is discarded and retried
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
SET = HERE  # the benchmark set: gold, docs and runs (--set)
KEY_SPAN = False  # ask a keyed prompt for the key span (--key-span)
HOME = str(Path.home())

KIND = {
    "fda": "the dosage sections of an FDA drug label",
    "ntsb": "an NTSB aviation accident report",
    "irs": "two pages of an IRS publication",
    "fr": "a page of a Federal Register final rule",
    "sec": "Item 7 (Management's Discussion and Analysis) of a 10-K annual report",
}
IRS_PAGES = {1: "one page of an IRS publication", 3: "three pages of an IRS publication"}

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
KEYS_NOTE = """
A field marked "one per key" can have one value for each key it lists. Give each of its
extractions a "key" in the attributes: the key of the condition the value belongs to, copied
exactly from the field's list.
"""
KEY_SPAN_NOTE = """
When words before the value name its key, such as a heading, a table row or column label, or a
bullet, also give "key_text" in the attributes: those words copied verbatim from the text, the
nearest ones before the value. Leave "key_text" out when no words before the value name its key.
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

_SET2_FDA_TEXT = (
    "2 DOSAGE AND ADMINISTRATION\n\n2.1 Gout\nThe recommended starting dose is 20 mg once "
    "daily. The maximum recommended dose is 80 mg once daily.\n\n2.2 Psoriasis\nStart at 10 mg "
    "once daily.\n\n3 DOSAGE FORMS AND STRENGTHS\n\nTablets: 10 mg, 20 mg and 80 mg"
)


def _mg(field: str, value: str, key: str | None = None) -> lx.data.Extraction:
    attrs = {"value": value, "unit": "mg"} | ({"key": key} if key else {})
    return lx.data.Extraction(field, f"{value} mg", attributes=attrs)


_STRENGTHS = [_mg("strengths", v) for v in ("10", "20", "80")]
SET2_EXAMPLES = {  # set 2 renames the FDA fields and adds keys and the Federal Register
    "fda": [
        lx.data.ExampleData(
            text=_SET2_FDA_TEXT,
            extractions=[_mg("starting_dose", "20"), _mg("max_daily_dose", "80"), *_STRENGTHS],
        )
    ],
    "fda keyed": [
        lx.data.ExampleData(
            text=_SET2_FDA_TEXT,
            extractions=[
                _mg("starting_dose", "20", "Gout"),
                _mg("max_daily_dose", "80", "Gout"),
                _mg("starting_dose", "10", "Psoriasis"),
                *_STRENGTHS,
            ],
        )
    ],
    "fr": [
        lx.data.ExampleData(
            text=(
                "This final rule raises the small business size standard from $7.5 million to "
                "$9 million in average annual receipts. About 1,200 firms will qualify."
            ),
            extractions=[
                lx.data.Extraction(
                    "size_standard_old",
                    "$7.5 million",
                    attributes={"value": "7500000", "unit": "USD"},
                ),
                lx.data.Extraction(
                    "size_standard_new",
                    "$9 million",
                    attributes={"value": "9000000", "unit": "USD"},
                ),
                lx.data.Extraction("firms_qualifying", "1,200", attributes={"value": "1200"}),
            ],
        )
    ],
    "sec": [  # the 10-K demo of the calibration tool (#112); the text is made up
        lx.data.ExampleData(
            text=(
                "Net sales were $4.2 billion in fiscal 2025, up from $3.9 billion in fiscal "
                "2024. Operating income was $512 million in 2025.\n\n"
                "(in millions)\t2025\t2024\nCash and cash equivalents\t$\t860\t$\t745\n"
            ),
            extractions=[
                lx.data.Extraction(
                    "revenue",
                    "$4.2 billion",
                    attributes={"value": "4200000000", "unit": "USD", "key": "2025"},
                ),
                lx.data.Extraction(
                    "revenue",
                    "$3.9 billion",
                    attributes={"value": "3900000000", "unit": "USD", "key": "2024"},
                ),
                lx.data.Extraction(
                    "operating_income",
                    "$512 million",
                    attributes={"value": "512000000", "unit": "USD", "key": "2025"},
                ),
                lx.data.Extraction(
                    "cash_and_equivalents",
                    "860",
                    attributes={"value": "860", "unit": "USD", "key": "2025"},
                ),
                lx.data.Extraction(
                    "cash_and_equivalents",
                    "745",
                    attributes={"value": "745", "unit": "USD", "key": "2024"},
                ),
            ],
        )
    ],
}

# the key span of each keyed example extraction, by example and extraction text (--key-span)
KEY_TEXTS = {
    "fda keyed": {
        ("20 mg", "Gout"): "Gout",
        ("80 mg", "Gout"): "Gout",
        ("10 mg", "Psoriasis"): "Psoriasis",
    },
    "sec": {("860", "2025"): "2025", ("745", "2024"): "2024"},  # the others name it after the value
}


def with_key_text(name: str, examples: list[lx.data.ExampleData]) -> list[lx.data.ExampleData]:
    """A copy of the examples with "key_text" on each keyed extraction that has a key span."""
    spans = KEY_TEXTS.get(name, {})
    out = []
    for ex in examples:
        xs = []
        for x in ex.extractions:
            attrs = dict(x.attributes or {})
            if (span := spans.get((x.extraction_text, attrs.get("key")))) is not None:
                attrs["key_text"] = span
            xs.append(lx.data.Extraction(x.extraction_class, x.extraction_text, attributes=attrs))
        out.append(lx.data.ExampleData(text=ex.text, extractions=xs))
    return out


CLAUDE_SYSTEM = "You extract facts from documents. Answer only from the text you are given."
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
        """The codex or claude command line; the prompt goes on stdin."""
        if self.provider == "claude-cli":
            cmd = [
                "claude",
                "-p",
                "--model",
                self.model,
                "--tools",
                "",
                "--strict-mcp-config",
                "--disable-slash-commands",
                "--setting-sources",
                "",
                "--no-session-persistence",
                "--system-prompt",
                CLAUDE_SYSTEM,
                "--output-format",
                "json",
            ]
            return [*cmd, "--effort", self.effort] if self.effort else cmd
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

    def _codex(self, prompt: str) -> tuple[str, int, list[str]]:
        """(reply, tool items seen, harness messages). Raises on a failed call."""
        proc = subprocess.run(
            self.command(),
            input=AGY_PREFIX + prompt,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        reply, tools, error = "", 0, proc.stderr[-300:]
        messages: list[str] = []
        for line in proc.stdout.splitlines():
            event = json.loads(line) if line.startswith("{") else {}
            item = event.get("item") or {}
            if event.get("type") == "turn.failed":
                error = str(event.get("error", {}).get("message", ""))[-300:]
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                reply = item.get("text", "")
            elif event.get("type") == "item.completed" and item.get("type") == "error":
                # a notice from the harness itself, such as "Skill descriptions were shortened"
                messages.append(str(item.get("message", ""))[:200])
            elif event.get("type") == "item.completed" and item.get("type") != "reasoning":
                tools += 1
        if proc.returncode != 0:
            raise RuntimeError(error)
        return reply, tools, messages

    def _one(self, prompt: str) -> tuple[str, dict[str, Any]]:
        notes: dict[str, Any] = {}
        if self.provider == "codex":
            for attempt in range(3):
                try:
                    out, tools, messages = self._codex(prompt)
                except (RuntimeError, subprocess.TimeoutExpired) as e:
                    notes.setdefault("failed_calls", []).append(str(e)[-200:])
                    time.sleep(10 * (attempt + 1))
                    continue
                for m in messages:
                    if m not in notes.setdefault("harness_messages", []):
                        notes["harness_messages"].append(m)
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
            cmd, stdin = self.command(), prompt
        for attempt in range(3):
            proc = subprocess.run(
                cmd,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
                cwd=self.empty,
            )
            out = proc.stdout
            if (
                self.provider == "claude-cli"
                and out.startswith("{")
                and json.loads(out).get("stop_reason") == "refusal"
            ):
                # the API's safety classifier refused the chunk; it refuses every retry,
                # so record it and give LangExtract nothing, which skips the chunk
                notes["refused"] = 1
                return "", notes
            if proc.returncode == 0 and self.provider == "claude-cli":
                res = json.loads(out)
                clean = (
                    set(res.get("modelUsage", {})) == {self.model}
                    and res.get("num_turns") == 1
                    and not res.get("permission_denials")
                )
                if not clean:  # a fallback model, a tool turn or a denied tool call
                    notes["discarded_for_harness"] = notes.get("discarded_for_harness", 0) + 1
                out = "" if res.get("is_error") or not clean else res["result"]
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


def keyed(gold: dict[str, Any]) -> bool:
    return any(spec["schema"].get("keys") for spec in gold["fields"].values())


def kind_text(gold: dict[str, Any]) -> str:
    """What the text is. Set-2 IRS documents can have one or three pages, not two."""
    if gold["kind"] == "irs":
        sources = json.loads((SET / "sources.json").read_text(encoding="utf-8"))["sources"]
        pages = next(s["select"]["pages"] for s in sources if s["id"] == gold["doc"])
        return IRS_PAGES.get(len(pages), KIND["irs"])
    return KIND[gold["kind"]]


def field_line(name: str, spec: dict[str, Any]) -> str:
    unit = spec["schema"]["unit"]
    head = f"- {name} [{unit}]" if unit else f"- {name}"
    if keys := spec["schema"].get("keys"):
        head += " (one per key; keys: " + "; ".join(f'"{k}"' for k in keys) + ")"
    return f"{head}: {spec['description']}"


def prompt_for(gold: dict[str, Any]) -> str:
    lines = [field_line(name, spec) for name, spec in gold["fields"].items()]
    prompt = PROMPT.format(kind=kind_text(gold), fields="\n".join(lines))
    if not keyed(gold):
        return prompt
    return prompt + KEYS_NOTE + (KEY_SPAN_NOTE if KEY_SPAN else "")


def examples_for(gold: dict[str, Any]) -> list[lx.data.ExampleData]:
    name = None
    if gold["kind"] in ("fr", "sec"):
        name = gold["kind"]
    elif gold["kind"] == "fda" and "starting_dose" in gold["fields"]:  # set 2's FDA field names
        name = "fda keyed" if keyed(gold) else "fda"
    if name is None:
        return EXAMPLES[gold["kind"]]
    if KEY_SPAN and keyed(gold):
        return with_key_text(name, SET2_EXAMPLES[name])
    return SET2_EXAMPLES[name]


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
    ap.add_argument("--set", type=Path, default=HERE, help="benchmark set directory")
    ap.add_argument("--key-span", action="store_true", help='ask for "key_text" (#130)')
    args = ap.parse_args()
    global SET, KEY_SPAN
    SET = args.set.resolve()
    KEY_SPAN = args.key_span
    label = args.label or args.model

    out_dir = SET / "runs" / safe(label) / str(args.buffer)
    out_dir.mkdir(parents=True, exist_ok=True)
    kw: dict[str, Any] = {}
    if args.provider == "gemini":
        kw["model_id"] = args.model
    else:
        kw["model"] = CLIModel(args.provider, args.model, args.workers, args.effort)
    cli = {"agy": "agy", "codex": "codex", "claude-cli": "claude"}.get(args.provider)
    cli_version = (
        subprocess.run([cli, "--version"], capture_output=True, text=True).stdout.strip()
        if cli
        else None
    )
    for path in sorted((SET / "gold").glob("*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        doc_id = gold["doc"]
        target = out_dir / f"{doc_id}.json"
        if target.exists() or (args.only and doc_id not in args.only):
            continue
        text = (SET / "docs" / f"{doc_id}.txt").read_text(encoding="utf-8")
        print(f"{doc_id} ", end="", flush=True)
        t0 = time.time()
        if isinstance(kw.get("model"), CLIModel):
            kw["model"].raw = []
        try:
            result = lx.extract(
                text_or_documents=text,
                prompt_description=prompt_for(gold),
                examples=examples_for(gold),
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
            **({"key_span": True} if args.key_span else {}),
            "langextract": importlib.metadata.version("langextract"),
            "max_char_buffer": args.buffer,
            "seconds": round(time.time() - t0),
            "document": data_lib.annotated_document_to_dict(result),
        }
        if isinstance(kw.get("model"), CLIModel):
            record["cli_version"] = cli_version
            if args.provider in ("codex", "claude-cli"):
                cmd = kw["model"].command()
                record["harness"] = ["<empty dir>" if a.startswith("/") else a for a in cmd]
            record["raw_outputs"] = kw["model"].raw
        target.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f" {len(result.extractions or [])} extractions, {record['seconds']}s")


if __name__ == "__main__":
    main()
