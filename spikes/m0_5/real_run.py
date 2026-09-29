"""M0.5 spike, real-model check: run lx.extract with a local model on the chunks that hold the
gold facts, then score what LangExtract accepts against what groundgate admits.

Each gold chunk is its own LangExtract document, so the model sees exactly the chunk
`lx.extract` would have sent. The prompt lists the typed fields (the schema). Raw annotated
output is cached in runs/<model>.json; pass --score-only to re-score from the cache.

Providers:
  --provider gemini     LangExtract's native Gemini provider (needs GEMINI_API_KEY)
  --provider claude-cli your logged-in `claude` CLI, tools disabled (uses your Claude plan)
  --provider agy        the Antigravity CLI in print mode, plan mode, sandboxed; --model takes
                        its display name, e.g. "Gemini 3.6 Flash (Medium)". It is an agent
                        harness, not a raw API call, so its system prompt wraps ours.
  --provider ollama     a local Ollama model (needs RAM for the model)

Run: .venv-spike/bin/python spikes/m0_5/real_run.py --provider claude-cli --model claude-haiku-4-5
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections.abc import Iterator, Sequence
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

import langextract as lx
from langextract import factory
from langextract.core import base_model, data
from langextract.core import types as lx_types

import spike
from spike import Fact, groundgate

HERE = Path(__file__).parent
RUNS = HERE / "runs"

PROMPT = """Extract numeric facts from the text for the fields listed below.
Only extract a field when the text itself states its value. Do not guess or compute values.
extraction_class must be one of the listed field names, exactly.
extraction_text must be copied verbatim from the text: the number as written, with its $ sign
or unit when they are adjacent (for example "$4,500" or "250 mg").
attributes: "value" is the plain number without commas or symbols; "unit" is one of:
USD, mg, mL/min/1.73m2, hours, mmol/L, mcg/mL, years, %, mg/kg/day, times, count, weeks.

Fields:
{fields}
"""

EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "The annual filing fee is $4,500 for small firms. Adults may take 250 mg twice daily, "
            "not to exceed 1,000 mg per day."
        ),
        extractions=[
            lx.data.Extraction("annual_filing_fee_small_firm", "$4,500", attributes={"value": "4500", "unit": "USD"}),
            lx.data.Extraction("adult_dose", "250 mg", attributes={"value": "250", "unit": "mg"}),
            lx.data.Extraction("max_daily_dose", "1,000 mg", attributes={"value": "1000", "unit": "mg"}),
        ],
    )
]


class ClaudeCLIModel(base_model.BaseLanguageModel):
    """LangExtract provider that calls the `claude` CLI in print mode with every tool disabled."""

    def __init__(self, model_id: str, **kwargs: object) -> None:
        super().__init__()
        self.model_id = model_id
        self.cost_usd = 0.0

    def infer(self, batch_prompts: Sequence[str], **kwargs: object) -> Iterator[Sequence[lx_types.ScoredOutput]]:
        for prompt in batch_prompts:
            proc = subprocess.run(
                ["claude", "-p", "--model", self.model_id, "--tools", "", "--no-session-persistence",
                 "--output-format", "json"],
                input=prompt, capture_output=True, text=True, timeout=600, check=False,
            )
            res = json.loads(proc.stdout)
            if res.get("is_error"):
                raise RuntimeError(f"claude CLI error: {res.get('result')}")
            self.cost_usd += float(res.get("total_cost_usd") or 0)
            out = res["result"].strip()
            if out.startswith("```"):  # LangExtract runs with fence_output=False
                out = out.split("\n", 1)[1].rsplit("```", 1)[0]
            yield [lx_types.ScoredOutput(score=1.0, output=out)]


AGY_PREFIX = (
    "Answer directly from the text below. Do not use any tools, do not run commands, "
    "and do not read or write files. Output only the JSON requested.\n\n"
)


class AgyModel(base_model.BaseLanguageModel):
    """LangExtract provider that calls the Antigravity CLI (`agy -p`) in plan mode, sandboxed."""

    def __init__(self, model_id: str, **kwargs: object) -> None:
        super().__init__()
        self.model_id = model_id
        self.cost_usd = 0.0  # not reported by agy

    def infer(self, batch_prompts: Sequence[str], **kwargs: object) -> Iterator[Sequence[lx_types.ScoredOutput]]:
        for prompt in batch_prompts:
            proc = subprocess.run(
                ["agy", "-p", AGY_PREFIX + prompt, "--model", self.model_id, "--mode", "plan", "--sandbox",
                 "--print-timeout", "300s"],
                capture_output=True, text=True, timeout=360, check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"agy error {proc.returncode}: {proc.stderr[-500:]}")
            out = proc.stdout.strip()
            if out.startswith("```"):
                out = out.split("\n", 1)[1].rsplit("```", 1)[0]
            print(".", end="", flush=True)
            yield [lx_types.ScoredOutput(score=1.0, output=out)]


def gold_chunks(facts: list[Fact]) -> list[tuple[str, int, int, int]]:
    seen: dict[tuple[str, int], tuple[str, int, int, int]] = {}
    for f in facts:
        seen[(f.doc, f.chunk_start)] = (f.doc, f.chunk_start, f.chunk_end, f.chunk_token_start)
    return sorted(seen.values())


def extract(provider: str, model: str, texts: dict[str, str], facts: list[Fact]) -> list[dict]:
    fields = "\n".join(sorted({f"- {f.field} ({f.unit})" for f in facts}))
    docs = [
        lx.data.Document(text=texts[d][s:e], document_id=f"{d}@{s}")
        for d, s, e, _ in gold_chunks(facts)
    ]
    kw: dict[str, object] = {}
    cli = None
    if provider == "claude-cli":
        cli = ClaudeCLIModel(model)
        kw["model"] = cli
    elif provider == "agy":
        cli = AgyModel(model)
        kw["model"] = cli
    elif provider == "ollama":
        kw["config"] = factory.ModelConfig(
            model_id=model, provider="OllamaLanguageModel",
            provider_kwargs={"model_url": "http://localhost:11434", "timeout": 600},
        )
    else:
        kw["model_id"] = model
    t0 = time.time()
    results = lx.extract(
        text_or_documents=docs,
        prompt_description=PROMPT.format(fields=fields),
        examples=EXAMPLES,
        **kw,
        max_char_buffer=spike.MAX_CHAR_BUFFER,
        fence_output=False,
        use_schema_constraints=False,
        temperature=0.0,
        show_progress=False,
    )
    out = []
    for r in results:
        for x in r.extractions or []:
            ci = x.char_interval
            out.append({
                "document_id": r.document_id,
                "class": x.extraction_class,
                "text": x.extraction_text,
                "attributes": x.attributes,
                "char_interval": [ci.start_pos, ci.end_pos] if ci else None,
                "status": x.alignment_status.value if x.alignment_status else None,
            })
    cost = f", ${cli.cost_usd:.4f}" if cli else ""
    print(f"extracted {len(out)} in {time.time() - t0:.0f}s{cost}")
    return out


CFGS = ["lx-all", "lx-aligned", "lx-exact", "gg-strict", "gg-v2"]


def safe(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("_")


def _dec(v: object) -> Decimal | None:
    try:
        return Decimal(str(v).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def score(model: str, raw: list[dict], texts: dict[str, str], facts: list[Fact]) -> str:
    by_field = {f.field: f for f in facts}
    chunk_of = {f"{d}@{s}": (d, s, e, t) for d, s, e, t in gold_chunks(facts)}
    rows = []
    for x in raw:
        d, cs, ce, ct = chunk_of[x["document_id"]]
        doc = texts[d]
        g = by_field.get(x["class"])
        attrs = x["attributes"] or {}
        if g is None:
            label = "unknown_field"
        else:
            ok = _dec(attrs.get("value")) == g.value and attrs.get("unit") == g.unit
            label = "correct" if ok else "wrong"
        ci = None
        if x["char_interval"] and x["char_interval"][0] is not None:
            ci = data.CharInterval(start_pos=cs + x["char_interval"][0], end_pos=cs + x["char_interval"][1])
        ext = data.Extraction(x["class"], x["text"], char_interval=ci, attributes=attrs)
        if g is None:
            gg = v2 = ("rejected", ["FIELD_UNKNOWN"])
        else:
            local = Fact(d, g.id, g.field, g.value, g.unit, g.qualifier, g.start, g.end, cs, ce, ct)
            gg = groundgate(ext, local, doc, flags=False)
            v2 = groundgate(ext, local, doc, flags=True, verbatim=False, multi=False)
        rows.append({**x, "label": label, "gg": gg[0], "gg_codes": gg[1], "v2": v2[0], "v2_codes": v2[1],
                     "gold_value": str(g.value) if g else None, "gold_unit": g.unit if g else None})

    found = {(r["class"]) for r in rows if r["label"] == "correct"}
    lines = [f"model: {model}   extractions: {len(rows)}   gold facts: {len(facts)}   "
             f"gold fields recovered correctly (any config): {len(found & set(by_field))}/{len(facts)}\n"]
    labels = Counter(r["label"] for r in rows)
    lines.append("labels: " + ", ".join(f"{k}={v}" for k, v in labels.most_common()))

    def acc(r: dict, c: str) -> bool:
        return {"lx-all": True, "lx-aligned": r["char_interval"] is not None and r["char_interval"][0] is not None,
                "lx-exact": r["status"] == "match_exact", "gg-strict": r["gg"] == "admitted",
                "gg-v2": r["v2"] == "admitted"}[c]

    lines.append(f"\n{'':<16}" + "".join(f"{c:>12}" for c in CFGS))
    for lab in ["correct", "wrong", "unknown_field"]:
        rs = [r for r in rows if r["label"] == lab]
        if rs:
            lines.append(f"{lab + ' accepted':<16}" + "".join(
                f"{sum(acc(r, c) for r in rs):>6}/{len(rs):<5}" for c in CFGS))
            if lab == "correct":
                rev = sum(r["v2"] == "needs_verification" for r in rs)
                rej = sum(r["v2"] == "rejected" for r in rs)
                lines.append(f"{'':<16}gg-v2 on correct facts: {rev} sent to review, {rej} rejected")
    lines.append("\nwrong extractions (what each got wrong, and what groundgate said):")
    for r in rows:
        if r["label"] == "wrong":
            lines.append(f"  {r['class']}: text={r['text']!r} value={r['attributes']} gold={r['gold_value']} {r['gold_unit']}"
                         f"  lx={r['status']}  gg={r['gg']} {r['gg_codes']}")
    lines.append("\ncorrect extractions groundgate rejected:")
    for r in rows:
        if r["label"] == "correct" and r["gg"] != "admitted":
            lines.append(f"  {r['class']}: text={r['text']!r} lx={r['status']} gg={r['gg_codes']} v2={r['v2']} {r['v2_codes']}")
    (RUNS / f"{safe(model)}.scored.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "claude-cli", "agy", "ollama"], default="claude-cli")
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--score-only", action="store_true")
    a = ap.parse_args()
    texts, facts = spike.load()
    RUNS.mkdir(exist_ok=True)
    cache = RUNS / f"{safe(a.model)}.json"
    if a.score_only:
        raw = json.loads(cache.read_text())
    else:
        raw = extract(a.provider, a.model, texts, facts)
        cache.write_text(json.dumps(raw, indent=1, ensure_ascii=False))
    report = score(a.model, raw, texts, facts)
    (RUNS / f"{cache.stem}.txt").write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
