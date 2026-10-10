"""The two runs on bench/sec3 (#170). Each document goes to a model CLI with
gg.extractor_schema(schema) as its structured output and the instructions from docs/guide.md,
unchanged. This is the path that the docs recommend since 0.5.1.

    uv run python bench/sec3/run.py --provider claude-cli --model claude-haiku-5-5
    uv run python bench/sec3/run.py --provider codex --model gpt-6-luna

Each run uses the CLI's default reasoning effort. The Claude CLI got the schema without its
"$schema" member, because its --json-schema check does not load draft 2020-12 (#197). Since
#197, gg.extractor_schema has no "$schema" member, and the codex runs get it back as they had it.

The CLIs run as in bench/propose.py: in an empty directory, with no tools, settings, rules, MCP
servers or saved session. A reply from another model, with a tool call or a denied tool call is
discarded and asked again, up to 3 times. Replies go to runs/<model>/<id>.json, with the CLI
version and the hashes of the prompt and the output schema. An existing file is skipped, so a
stopped run resumes. The replies quote the filings, so runs/ stays out of git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import groundgate as gg

HERE = Path(__file__).parent
GUIDE = HERE.parent.parent / "docs" / "guide.md"
# the same harness text as bench/propose.py
CLAUDE_SYSTEM = "You extract facts from documents. Answer only from the text you are given."
CODEX_PREFIX = (
    "Answer directly from the text below. Do not use any tools, do not run commands, "
    "and do not read or write files. Output only the JSON requested.\n\n"
)


def instructions() -> str:
    """The text block after "These instructions tell the model what to put in it:" in the
    guide, so that a change to the guide shows in the prompt hash."""
    guide = GUIDE.read_text(encoding="utf-8")
    m = re.search(
        r"These instructions tell the model what to put in it:\n\n```text\n(.*?)```", guide, re.S
    )
    if m is None:
        raise SystemExit("docs/guide.md has no instructions block")
    return m.group(1).strip()


def harness(provider: str) -> str:
    """The text that the provider's CLI gets with every prompt: a system prompt or a prefix."""
    return CLAUDE_SYSTEM if provider == "claude-cli" else CODEX_PREFIX


def prompt_for(text: str) -> str:
    return f"{instructions()}\n\nThe text:\n\n{text}"


def sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def output_schema(provider: str, schema: dict[str, Any]) -> dict[str, Any]:
    """The output schema that the provider's CLI got in the recorded runs. Since #197,
    gg.extractor_schema has no "$schema" member. The codex runs got the schema with it."""
    if provider == "codex":
        return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
    return schema


class Runner:
    def __init__(
        self, provider: str, model: str, schema: dict[str, Any], effort: str = "default"
    ) -> None:
        schema = output_schema(provider, schema)
        self.provider, self.model, self.schema = provider, model, schema
        self.effort = effort  # "default" adds no flag, as in the recorded runs
        self.empty = tempfile.mkdtemp(prefix="groundgate-sec3-")
        self.schema_file = Path(self.empty) / "output.schema.json"
        self.schema_file.write_text(json.dumps(schema), encoding="utf-8")

    def version(self) -> str:
        cmd = ["claude" if self.provider == "claude-cli" else "codex", "--version"]
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()

    def claude(self, prompt: str) -> tuple[dict[str, Any] | None, str | None]:
        """(reply, why it was discarded)."""
        cmd = [
            "claude", "-p", "--model", self.model, "--tools", "", "--strict-mcp-config",
            "--disable-slash-commands", "--setting-sources", "", "--no-session-persistence",
            "--system-prompt", CLAUDE_SYSTEM, "--output-format", "json",
            "--json-schema", json.dumps(self.schema),
        ]  # fmt: skip
        if self.effort != "default":
            cmd += ["--effort", self.effort]
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=900, cwd=self.empty
        )
        if proc.returncode != 0 or not proc.stdout.startswith("{"):
            return None, f"exit {proc.returncode}: {proc.stderr[-200:]}"
        res = json.loads(proc.stdout)
        if res.get("stop_reason") == "refusal":
            return None, "refusal"
        if set(res.get("modelUsage", {})) != {self.model} or res.get("permission_denials"):
            return None, "harness: another model or a denied tool call"
        out = res.get("structured_output")
        return (
            (out, None)
            if isinstance(out, dict) and not res.get("is_error")
            else (None, "no output")
        )

    def codex(self, prompt: str) -> tuple[dict[str, Any] | None, str | None]:
        cmd = [
            "codex", "exec", "-m", self.model, "--json", "--ephemeral", "--ignore-user-config",
            "--ignore-rules", "--skip-git-repo-check", "-s", "read-only", "-C", self.empty,
            "-c", "project_doc_max_bytes=0", "--output-schema", str(self.schema_file), "-",
        ]  # fmt: skip
        if self.effort != "default":
            cmd[-1:-1] = ["-c", f'model_reasoning_effort="{self.effort}"']
        proc = subprocess.run(
            cmd, input=CODEX_PREFIX + prompt, capture_output=True, text=True, timeout=900
        )
        if proc.returncode != 0:
            return None, f"exit {proc.returncode}: {proc.stderr[-200:]}"
        reply, tools = "", 0
        for line in proc.stdout.splitlines():
            event = json.loads(line) if line.startswith("{") else {}
            item = event.get("item") or {}
            if event.get("type") != "item.completed":
                continue
            if item.get("type") == "agent_message":
                reply = item.get("text", "")
            elif item.get("type") not in ("reasoning", "error"):
                tools += 1
        if tools:
            return None, "harness: a tool call"
        try:
            out = json.loads(reply)
        except json.JSONDecodeError:
            return None, "no output"
        return (out, None) if isinstance(out, dict) else (None, "no output")

    def one(self, doc: Path, out: Path, prompt: str | None = None) -> str:
        """Ask for one document. The prompt is that of prompt_for, unless one is given."""
        if prompt is None:
            prompt = prompt_for(doc.read_text(encoding="utf-8"))
        discarded: list[str] = []
        for attempt in range(3):
            ask = self.claude if self.provider == "claude-cli" else self.codex
            try:
                reply, why = ask(prompt)
            except subprocess.TimeoutExpired:
                reply, why = None, "timeout"
            if reply is not None:
                break
            assert why is not None
            discarded.append(why)
            if why == "refusal":
                break
            time.sleep(10 * (attempt + 1))
        record = {
            "doc": doc.stem,
            "provider": self.provider,
            "model": self.model,
            "effort": self.effort,
            "cli": self.version(),
            "prompt_sha256": sha(prompt),
            "harness_sha256": sha(harness(self.provider)),
            "output_schema_sha256": sha(json.dumps(self.schema, sort_keys=True)),
            "output_schema_without": [] if "$schema" in self.schema else ["$schema"],
            "reply": reply,
            "discarded": discarded,
        }
        out.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return f"{doc.stem}: {'ok' if reply is not None else 'no reply'}"


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
