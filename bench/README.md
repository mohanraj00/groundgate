# Benchmark

The IRS example shows groundgate on one document. This benchmark asks the same question at a
larger scale: when an extractor running through LangExtract gets a value wrong, how often does
the wrong value reach you without anyone looking at it, and how much work does groundgate add
to stop it?

The numbers are in [RESULTS.md](RESULTS.md). This page covers how they were made and where the
method is weak.

## Documents

30 public-domain US government documents in three kinds. I picked each set with a fixed rule
before running any model, so the set was not chosen for what groundgate catches.

| Kind | Documents | Text used | How they were picked |
|---|---|---|---|
| FDA drug labels (DailyMed SPL) | 10 | sections 2 and 3: dosage, dosage forms and strengths | for each of ten common generic drugs, the first tablet label DailyMed search returns |
| NTSB aviation accident reports | 10 | the whole report | the first ten report ids from 192700 up that are final reports of 8 pages or fewer |
| IRS publications | 10 | pages 1 and 2 | the first ten from a list of common publications with at least 8 dollar amounts on those pages |

Metformin and IRS Publication 590-A are excluded because I used them while building groundgate.

`sources.json` pins each download by URL and SHA-256. `fetch.py` downloads them, checks the
hashes, and writes the text to `docs/` with groundgate's own extractor. The text is committed,
so the benchmark scores offline after a publisher revises a document.

## Gold

Each document has its own fields (5 per FDA label, 12 per NTSB report, 9 to 14 per IRS
publication), with a description and a unit. Every IRS document also has one field that it
does not state, so hallucinated values have a place to show up.

A model (Claude) drafted the gold with `gold/prelabels.py`. A person then checked every draft
fact and absence in the labeling app ([label/README.md](label/README.md)), which never shows what
the benchmarked models extracted. Only checked facts count. The gold files record who checked
each document, when, and how long it took.

The check took 2.4 hours and kept nearly all of the draft. It rejected one draft value and
excluded that field as ambiguous, excluded one more field, found one field the draft had called
absent (levothyroxine is dosed from birth, so the youngest pediatric age is 0), and added two
places as evidence.

An extraction is **correct** when its value is a gold value for its field and its unit is the
field's unit. It is **wrong** when the value differs, the field is absent from the document, the
unit differs, or the value is not a number. Off-schema field names are counted but not scored.
Separately, a correct extraction *cites the right place* when its span overlaps one of the gold
evidence spans.

## Track A: planted errors

No model is called. For every gold fact, `score.py` builds the extraction a model would emit if
it read the right place: the gold text as `extraction_text`, the value and unit as attributes.
It then plants one error at a time:

| Planted | What changes |
|---|---|
| value attribute x10, text right | the value attribute only |
| value and text x10 | both, consistently |
| one digit changed | both; the second digit moves by 2 |
| decimal point dropped | the value attribute: 0.4 hours read as 4 |
| comma read as a decimal point | the value attribute: $184,500 read as 184.5 |
| wrong unit | the unit attribute (mg to mcg, USD to cents, and so on) |
| "null" as the value | the text and value become the literal `null` |
| a nearby number with the same unit | both become another real number from the same chunk |

Two more classes leave the extraction alone and change the document instead, so the value is
no longer what the text means:

| Planted | What changes |
|---|---|
| "more than" written before the value | the document; skipped for fields whose comparator is already "more than" |
| "million" written after the value | the document; dollar and unitless fields only |

Two controls stay correct: the clean extraction, and one whose text is paraphrased ("10
milligrams" for "10 mg"). Plantings that happen to land on another gold value for the field
are skipped.

Each extraction is aligned by LangExtract's own `Resolver.align`, inside the same 1,000-character
chunk `lx.extract` would have sent to the model, then passed through the real groundgate adapter
and `admit`. So Track A measures the two systems' checks against each other with nothing else
varying.

## Track B: real models

`propose.py` runs `lx.extract` over every document with each model, at LangExtract's default
chunk size (`max_char_buffer=1000`) and at 4,000. The prompt gives field names, units and
descriptions, plus one invented example per kind. It never sees the gold. Every run is cached
in `runs/` with the raw model output for each chunk, so scoring never calls a model.

Each extraction is scored under four rules:

- **LangExtract, all**: accept everything `lx.extract` returns.
- **LangExtract, aligned**: accept anything with a character interval.
- **LangExtract, MATCH_EXACT**: accept only exact alignments. This is the strictest setting
  LangExtract offers, and the fair comparison.
- **groundgate**: accept what it admits, send what it flags to review, drop what it rejects.

Groups of models also go through one `admit` call together (every pair, and all models), so
a disagreement on a single-valued field is flagged `CONFLICTING_CANDIDATES`. Each group is
compared with the same candidates admitted one model at a time.

| Model | Through | Setting |
|---|---|---|
| Gemini 3.6 Flash | Antigravity CLI | Medium |
| Gemini 3.8 Flash | Antigravity CLI | Low, the cheapest setting of the newest Flash |
| GPT-5.6 Luna | Codex CLI | medium reasoning effort |
| GPT-5.6 Terra | Codex CLI | medium reasoning effort |
| Claude Sonnet 5.5 | Claude Code CLI | default |
| Claude Haiku 4.5 | Claude Code CLI | default |
| Claude Sonnet 4.6 | Claude Code CLI | default; an older model, kept as a baseline |

`RESULTS.md` also reports, per run: which reason code stopped each wrong extraction, how often
a correct value was admitted or rejected while citing a place the gold does not list, results
by source, and harness health (chunks, replies LangExtract could not parse, replies discarded
for tool use, seconds per document).

The metrics:

- **escaped**: wrong extractions accepted without review, as a share of wrong extractions;
- **false rejects**: correct extractions that cite the right place and are rejected;
- **review load**: extractions groundgate sends to a person, as a share of all scored ones;
- **recall**: gold facts with at least one correct extraction admitted (or admitted or sent to
  review).

Rates carry 95% Wilson intervals. With a few dozen wrong extractions per run, they are wide.

## What groundgate cannot catch

groundgate checks that the value is in the cited text with the right unit and no qualifier the
field doesn't allow. It cannot tell whether that text is the right place. When a model cites a
real "20 mg" as the tablet strength and the label only sells 10 mg tablets, every check passes.
Track A's "nearby number with the same unit" row measures this directly, and the Track B
appendix lists every real case.

In the real runs, this was six of the eight escapes. Each took a value stated for another
condition: five models took metoprolol's heart failure maximum as the hypertension maximum, and
one took lisinopril's renal impairment dose. The FDA fields name one condition ("the first
indication in section 2") because a v0.1 field holds one value per document. A field whose value
depends on a condition, checked against the condition's words near the evidence, is a candidate
for the next spec version.

The other two read levothyroxine's "1.6 mcg/kg/day" as a flat 1.6 mcg. The unit rule finds `mcg`
right after the number and does not look further.

## Caveats

- **The spec is frozen for this benchmark.** Scoring uses SPEC 0.1 as of commit `9245852`. While
  building the scorer I saw three known weaknesses in the draft numbers: "increased from $70,000
  to $72,000" reads as a range and is flagged; "must not be more than" is flagged even when the
  field is the limit itself; and "$1 million" is rejected for the value 1000000 because scale
  words only flag. I did not fix them here, because fixing them against this set would tune the
  rules on the test data. Fixes go into a later spec version and get measured on new documents.
- **One fix to the code, none to the spec.** At 4,000 characters, LangExtract's chunker cut
  "Altimeter Setting: 29.97" after "29.", and three models answered 29 from that chunk. The spec
  says a span never reads a prefix of a longer number, but the code only checked for that when the
  span ended right on a digit, so it admitted 29. I fixed the code to match the spec and added a
  conformance vector. The results are from the fixed code; before the fix, these three also
  escaped (11 of 117, not 8).
- **Who drafted the gold.** Claude drafted it, and three Claude models (Sonnet 4.6, Sonnet 5.5,
  Haiku 4.5) are among the benchmarked ones. A person checked every fact without seeing model
  output, but drafts anchor judgment. The check changed little, and from here I can't tell a good
  draft from an anchored checker.
- **How the models were called.** Every model ran through a logged-in agent CLI, not a raw API.
  Antigravity runs in its sandboxed plan mode with a no-tools preamble. Codex runs `codex exec`
  in an empty directory with a read-only sandbox, my user config, rules and AGENTS.md ignored,
  and no saved session; its event stream shows every tool call, and a reply that used one is
  discarded and retried. Claude Code runs `claude -p` in an empty directory with no tools, MCP
  servers, skills or setting sources, so no CLAUDE.md, hooks or memory load, and a one-line
  system prompt replaces the default; a reply from a fallback model or with more than one turn
  is discarded. Antigravity and Codex add their own system prompt, and temperature is not
  under my control in any of them, so a rerun gives different extractions. The cached runs are
  what was scored. `propose.py` also supports LangExtract's native Gemini provider.
- **The prompt changed once, before the full runs.** The first prompt described the output
  with the words `extraction_class` and `extraction_text`, and GPT-5.6 answered in that shape
  instead of the one LangExtract parses, so its chunks were dropped. The final prompt describes
  the layout the examples use and says to leave `unit` out for unitless fields. I discarded
  every run made with the first prompt, about 30 documents, and reran all models on the same
  final prompt.
- **Dropped chunks.** When a model's reply for a chunk isn't valid JSON, LangExtract logs a
  warning and skips the chunk. In an early trial GPT-OSS 120B in plan mode wrote a plan file and
  replied with a link to it instead of JSON. Haiku 4.5 and Sonnet 4.6 answered some IRS chunks,
  mostly tables of contents, with a note that they saw no document, or with prose before the
  JSON, instead of an empty list. Those facts count against recall for every rule equally. The
  raw replies are in the run files, with home directory paths replaced by `~`.
- **"Cited the right place" is only as good as the gold evidence.** A label often states the
  same value in several places. A citation counts as right only when the checker listed that
  place, so this rate is a lower bound.
- **Not every model I tried was available.** GPT-6 Luna is not offered to a ChatGPT account in
  Codex, so GPT-5.6 Terra took its place.
- **Small n.** 30 documents and seven models is enough to show where the failure classes are,
  not to rank models.

## Reproduce

```bash
uv sync --group langextract
uv run python bench/fetch.py                                   # optional: re-download and verify
uv run --group langextract python bench/score.py               # rescore from the cached runs
uv run --group langextract python bench/propose.py --provider gemini --model <model id>  # new runs
```

CI runs `score.py --check`, which fails if `RESULTS.md`, `results.json` or the charts differ
from what the cached runs and gold produce.
