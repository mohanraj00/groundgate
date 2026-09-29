# Spike M0.5: does value-level admission catch errors LangExtract accepts?

**Decision: go, with a sharper headline and a harder benchmark.**

- **The gap is real.** LangExtract verifies the *text*; groundgate verifies the *value*. On planted errors, a large, measurable gap sits at that boundary.
- **On clean text, real models made no value errors.** Across 84 real-model extractions from Claude Haiku 4.5 and Gemini 3.6 Flash, there were zero value or unit errors. groundgate had nothing to catch.
- **The review cost is low and the flags are legitimate.** 7 of 84 (8%) went to review, 0 were rejected, and every flag marked a real range or an "approximately".

So the claim "fewer wrong facts get through" is **not yet supported on real output**. Track B has to measure it where models actually fail. Until then, the supported claim is: groundgate proves each fact at a known review cost, and catches the error classes LangExtract cannot see when they occur.

## Setup

**Sources.** Two public-domain US government documents, fetched and hash-pinned by `fetch.py`:

- IRS Publication 590-A (2025), pages 1–12, via pdfminer.six;
- an FDA label for metformin extended-release tablets (DailyMed SPL, version 5).

**Gold.** 51 numeric facts, each a typed field with a value, a unit, and a declared comparator ("more than", "up to", and so on). Each span is located by a pattern that must match exactly once. The spike author labelled them from the source text. They are not the person-checked benchmark gold.

**Proposals.** For each fact we build the extraction a LangExtract model would emit: a verbatim `extraction_text` plus `value` and `unit` attributes. We then apply one controlled corruption at a time.

**Alignment.** Every proposal is aligned by LangExtract 1.7.0's own `Resolver.align`. Alignment runs inside the same 1,000-character chunk `lx.extract` would have sent to the model (`ChunkIterator`, default `max_char_buffer`). No model is called, so the run is deterministic: a re-run reproduces `results.txt` byte for byte.

**Configurations.**

| Name | Rule |
|---|---|
| `lx-all` | accept everything LangExtract returns |
| `lx-aligned` | accept anything with a `char_interval` (LangExtract's default notion of grounded) |
| `lx-exact` | accept only `MATCH_EXACT` |
| `gg-strict` | LangExtract output checked by a throwaway groundgate: null literal, type, schema unit, span bounds, span text equals `extraction_text`, collision-safe value-in-span, unit-at-value, and re-anchoring when exactly one other verbatim occurrence in the chunk passes |
| `gg-flags` | `gg-strict` plus review flags: undeclared qualifier, other same-unit values in the sentence, scale words |
| `gg-v2` | the design carried into M1. Value and unit must verify at the aligned location. Non-verbatim evidence is *flagged*, not rejected. Qualifier and scale flags stay; the blunt multi-value flag is dropped |

## Results

Share of **wrong** facts accepted silently (lower is better). For `gg-flags`, the cell shows accepted / sent to review.

| Corruption | n | lx-all | lx-aligned | lx-exact | gg-strict | gg-flags | gg-v2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| value attribute ×10, text untouched | 51 | 100% | 100% | **100%** | **0%** | 0% / 0% | 0% / 0% |
| text and value ×10 | 51 | 100% | 31% | 0% | 0% | 0% / 0% | 0% / 0% |
| near-miss digit (7,000 → 7,200) | 51 | 100% | 61% | 10% | 8% | 0% / 8% | 4% / 4% |
| adjacent value: real text, wrong field | 42 | 100% | 100% | **100%** | **100%** | 19% / 81% | 69% / 31% |
| unit swapped (mg → mcg) | 22 | 100% | 100% | **100%** | **0%** | 0% / 0% | 0% / 0% |
| string "null" | 51 | 100% | 0% | 0% | 0% | 0% / 0% | 0% / 0% |

**Correct** facts: accepted / sent to review / rejected.

| Kind | n | lx-exact | gg-strict | gg-flags | gg-v2 |
|---|---:|---:|---:|---:|---:|
| clean | 51 | 100 / 0 / 0 | **100 / 0 / 0** | 35 / **65** / 0 | 94 / 6 / 0 |
| correct value, paraphrased evidence | 51 | 12 / 0 / 88 | 12 / 0 / 88 | 8 / 4 / 88 | 10 / 33 / 57 |

Per-class rates are the result. The "all wrong" totals in `results.txt` depend on the corruption mix the spike chose, so don't quote them.

## What we learned

1. **LangExtract's alignment never looks at attributes.** When the typed value or unit disagrees with a verbatim `extraction_text`, even `MATCH_EXACT` accepts 100% of them. Value-in-span and unit-at-value checks caught all of them, with no false rejections on the 51 correct facts. This is the core gap groundgate fills.
2. **LangExtract's default acceptance is lenient.** `MATCH_LESSER` and `MATCH_FUZZY` alignments let through 31% of numbers inflated tenfold and 61% of near-miss digits. An exact-only filter fixes that, but it also rejects 88% of correct facts whose evidence was paraphrased. groundgate strict behaves the same on those, since both fail closed.
3. **Evidence location is sometimes wrong even when the value is right.** On 5 of 51 correct facts, LangExtract's `char_interval` pointed somewhere other than the gold location. For a short `extraction_text` like `5`, it anchors to the first matching token in the chunk, such as a section reference "(5.1)". groundgate re-anchored 2 of these to the unique occurrence that carries the right unit. The other 3 pointed to another occurrence with the same value and unit.
4. **"Real text, wrong field" is not solved by span checks.** When the model reports another value that really appears in the same sentence (the $8,000 age-50 limit instead of the $7,000 base limit), every strict configuration accepts it. A blunt "other values in this sentence" flag catches 81%, but sends 65% of correct facts to review. That review load is unusable, so this flag will not ship as a default.
5. **Collision-safe number reading surfaces real source defects.** The IRS publication prints "$252,0000". It is never read as 252,000.

## Consequences for the plan

- **Headline:** "LangExtract verifies the text; groundgate verifies the value." It is scoped to what was measured.
- **M1 spec:** re-anchoring (`EVIDENCE_REANCHORED`) becomes a defined step with a uniqueness rule, not a heuristic.
- **Adopt `gg-v2` as the M1 policy.** Enforce value and unit at the evidence location; flag non-verbatim evidence, never reject it for formatting alone.
- **Replace the multi-value flag.**
  - What replaces it: a `CONFLICTING_CANDIDATES` check that compares two independent proposals, plus optional per-field context cues declared in the schema.
  - Acceptance bar: at most 15% of correct facts sent to review on Track B, with the catch rate on adjacent-value errors reported next to it.
- **Track B must measure how often real models produce each error class, under hard conditions.** The first real runs found none on clean text. If errors stay rare, the headline becomes "per-fact proof with receipts at an 8% review cost", not "fewer wrong facts". The write-up must say which one the data supports.

## Real-model check

**Setup.**

- `real_run.py` runs `lx.extract` on the 16 chunks that hold the gold facts, with the field list given in the prompt and one invented few-shot example.
- Claude Haiku 4.5 ran through the `claude` CLI with tools disabled. Gemini 3.6 Flash (Medium) ran through the Antigravity CLI in plan mode, sandboxed, with a no-tools preamble. Both are agent harnesses rather than raw API calls, so their system prompts wrap ours.
- Raw outputs are cached in `runs/`. `--score-only` re-scores them without any model.

**Results.**

| Model | Extractions | Correct | Wrong | Fields recalled | lx-exact accepts | gg-v2 admitted / review / rejected |
|---|---:|---:|---:|---:|---:|---:|
| Claude Haiku 4.5 | 30 | 30 | **0** | 30 / 51 | 26 / 30 | 26 / 4 / 0 |
| Gemini 3.6 Flash (Medium) | 54 | 54 | **0** | 51 / 51 | 52 / 54 | 51 / 3 / 0 |

**Why facts went to review.** Every flag was legitimate:

- a range reported as its low end ("7 to 8 hours" → 7; "24 to 48 hours" → 24);
- an "approximately";
- evidence the model had normalized ("30 mL/min/1.73m2" for "30 and 60 mL/minute/1.73 m2").

Strict verbatim checking had rejected those normalized facts outright. That is why `gg-v2` flags them instead.

**What it means.** On clean, well-structured government text with the schema given, both models were accurate, and LangExtract's accept-all would have been perfect. A planted-error spike shows where the gap *is*; it can't show how often real models fall into it. The benchmark therefore has to include the conditions where extraction actually fails:

- long chunks (users raise `max_char_buffer`);
- tables and worksheets;
- OCR'd scans;
- fields absent from the text, as hallucination bait;
- near-duplicate values across sections and years;
- smaller or cheaper model settings.

It must report the real error rate next to the catch rate.

## Reproduce

```bash
uv venv --python 3.12 .venv-spike && uv pip install --python .venv-spike langextract==1.7.0 pdfminer.six
```

```bash
.venv-spike/bin/python spikes/m0_5/fetch.py
```

```bash
.venv-spike/bin/python spikes/m0_5/spike.py
```
